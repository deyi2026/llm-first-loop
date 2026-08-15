"""M49 Fallback 降级链测试（design §5.4 / behavioral rule table）.

覆盖设计 §5.4 行为规则表全部条目:
- 默认模型 429 → 自动降级下一个 → 反馈含 [模型降级: 标注 + 审计记录
- 默认模型 timeout → 降级链走通
- 会话 override 模型失败 → 严格模式不降级, 直接如实反馈
- 链全失败 → 汇总各候选原因
- 4xx (如 400) 不降级
- MODEL_FALLBACKS 空 → 零回归（现状行为: 失败直接反馈）
- 非法 fallback 条目跳过不影响链

设计原则:
- 全部 Mock/FakeLLM, 零网络
- 不修改 conftest.py 已提供的 FakeLLM（不污染其他测试）

测试路径:
- 单测层: pool.fallback_candidates() 解析（4 个用例, fast）
- 集成层: LoopEngine.run() 触发降级（6 个用例, 验证 messages 注入 + 审计 + status）
"""

from __future__ import annotations

import json
import tempfile
from typing import Any

import pytest

from llm_loop.config import Settings
from llm_loop.introspection.corrections import CorrectionContext, CorrectionToolRegistry
from llm_loop.llm.client import LLMResponse
from llm_loop.llm.errors import (
    LLMHTTPError,
    LLMNetworkError,
    LLMTimeoutError,
)
from llm_loop.llm.pool import ModelClientPool
from llm_loop.llm.providers import ProviderRegistry

# ── Settings / 注册表构造辅助 ──


def _settings(**overrides) -> Settings:
    """构造最小 Settings（含 M49 model_fallbacks_raw）.

    隔离治理: data_dir 默认指向独立临时目录（tempfile.mkdtemp），杜绝测试写真实 data/；
    调用 engine.run 的测试显式传 data_dir=str(tmp_path / "data")，由 pytest 自动清理。
    """
    base: dict[str, Any] = {
        "llm_api_key": "test-key",
        "llm_base_url": "https://api.deepseek.com/v1",
        "llm_model": "deepseek-v4-flash",
        "data_dir": tempfile.mkdtemp(prefix="llm-fallback-test-"),
        "model_providers_raw": "",
        "model_fallbacks_raw": "",
    }
    base.update(overrides)
    return Settings(**base)


_THREE_PROVIDER_JSON = json.dumps(
    {
        "deepseek": {
            "base_url": "https://api.deepseek.com/v1",
            "api_key_env": "DEEPSEEK_API_KEY",
            "models": {
                "deepseek-v4-flash": {"context": 1000000, "thinking": True, "cost_tier": "low"},
                "deepseek-v4-pro": {"context": 1000000, "thinking": True, "cost_tier": "high"},
            },
            "default_model": "deepseek-v4-flash",
        },
        "minimax": {
            "base_url": "https://api.minimax.chat/v1",
            "api_key_env": "MINIMAX_API_KEY",
            "models": {
                "MiniMax-M3": {"context": 1000000, "thinking": False, "cost_tier": "mid"},
            },
            "default_model": "MiniMax-M3",
        },
        "local": {
            "base_url": "http://localhost:1234/v1",
            "api_key_env": "",
            "models": {
                "qwen3.6-27b": {"context": 131072, "thinking": True, "cost_tier": "free"},
            },
            "default_model": "qwen3.6-27b",
        },
    }
)


# ── 单测: pool.fallback_candidates() 解析 ──


def test_fallback_candidates_empty_returns_empty_list() -> None:
    """MODEL_FALLBACKS 未设置 → 返回空 list（零回归, 不启用降级）."""
    pool = ModelClientPool(
        registry=ProviderRegistry(providers={}),
        default_client=_FakeLLMClient("deepseek-v4-flash"),
        model_fallbacks_raw="",
    )
    assert pool.fallback_candidates() == []


def test_fallback_candidates_resolves_valid_entries(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """合法条目 → 全限定 provider/model 列表返回."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "real-key")
    monkeypatch.setenv("MINIMAX_API_KEY", "real-key")
    settings = _settings(
        model_providers_raw=_THREE_PROVIDER_JSON,
        model_fallbacks_raw="deepseek/deepseek-v4-flash,local/qwen3.6-27b,minimax/MiniMax-M3",
    data_dir=str(tmp_path / "data"),
    )
    from llm_loop.llm.providers import load_registry

    pool = ModelClientPool(
        registry=load_registry(settings),
        default_client=_FakeLLMClient("deepseek-v4-flash"),
        model_fallbacks_raw=settings.model_fallbacks_raw,
    )
    candidates = pool.fallback_candidates()
    assert candidates == [
        "deepseek/deepseek-v4-flash",
        "local/qwen3.6-27b",
        "minimax/MiniMax-M3",
    ]


def test_fallback_candidates_skips_invalid_entries(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """非法条目（未知 provider / 裸名歧义 / key 缺失）→ 跳过 + warning 日志, 不影响链上其他候选."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "real-key")
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    # 链中混入: 1)合法 deepseek-v4-flash; 2)未知 provider; 3)key 缺失的 minimax; 4)合法 local
    settings = _settings(
        model_providers_raw=_THREE_PROVIDER_JSON,
        model_fallbacks_raw=(
            "deepseek/deepseek-v4-flash,"
            "ghost/nonexistent,"
            "minimax/MiniMax-M3,"  # MINIMAX_API_KEY 未设 → 跳过
            "local/qwen3.6-27b"
        ),
        data_dir=str(tmp_path / "data"),
    )
    from llm_loop.llm.providers import load_registry

    pool = ModelClientPool(
        registry=load_registry(settings),
        default_client=_FakeLLMClient("deepseek-v4-flash"),
        model_fallbacks_raw=settings.model_fallbacks_raw,
    )
    with caplog.at_level("WARNING"):
        candidates = pool.fallback_candidates()
    assert candidates == ["deepseek/deepseek-v4-flash", "local/qwen3.6-27b"]
    # 至少两条 warning（ghost provider + MINIMAX_API_KEY 缺失）
    warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
    assert any("ghost/nonexistent" in m for m in warnings)
    assert any("MINIMAX_API_KEY" in m for m in warnings)


def test_fallback_candidates_bare_ambiguous_skipped(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """裸名跨 provider 歧义 → 跳过 + warning, 不阻断链上其他合法条目."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "real-key")
    # 两个 provider 都包含 "shared" → 裸名跨 provider 歧义 → 跳过
    raw = json.dumps(
        {
            "a": {
                "base_url": "http://a",
                "api_key_env": "",
                "models": {"shared": {}},
            },
            "b": {
                "base_url": "http://b",
                "api_key_env": "",
                "models": {"shared": {}},
            },
        }
    )
    settings = _settings(
        model_providers_raw=raw,
        model_fallbacks_raw="shared,local/qwen3.6-27b",  # "shared" 歧义; local 不存在 → 双跳过
    data_dir=str(tmp_path / "data"),
    )
    from llm_loop.llm.providers import load_registry

    pool = ModelClientPool(
        registry=load_registry(settings),
        default_client=_FakeLLMClient("deepseek-v4-flash"),
        model_fallbacks_raw=settings.model_fallbacks_raw,
    )
    with caplog.at_level("WARNING"):
        candidates = pool.fallback_candidates()
    # shared 跨 a/b 歧义 → 跳过 + warning
    # local/qwen3.6-27b 不在 {a, b} 注册表中 → resolve 失败 → 跳过 + warning
    assert candidates == []
    warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
    assert any("shared" in m for m in warnings)
    assert any("local" in m for m in warnings)


# ── FakeLLMClient: 可编程触发不同异常 + 多 client 独立响应序列 ──


class _FakeLLMClient:
    """可编程 LLMClient 桩: 每次 chat 按 responses 列表弹出 LLMResponse 或抛异常.

    与 tests/conftest.py FakeLLM 不同: 这里直接实现 LLMClient 协议（duck typing,
    具备 model/timeout_s/thinking_mode/reasoning_effort/thinking_supported 属性, 不实际发请求）。

    行为契约:
    - responses: list of (LLMResponse | Exception | callable(history) -> LLMResponse | Exception)
    - 默认 model / thinking 参数继承 default_client 设置（与 ModelClientPool 期望一致）
    """

    def __init__(self, model: str) -> None:
        self.model = model
        self.timeout_s = 120.0
        self.thinking_mode = True
        self.reasoning_effort = "high"
        self.thinking_supported = True
        self.max_tokens: int | None = None
        self.wire_protocol: str = "openai"  # P3-5 对齐 LLMClient 新字段  # 2026-08-15 对齐 LLMClient 新装配字段
        self._responses: list[Any] = []
        self.calls: list[dict[str, Any]] = []

    def queue(self, responses: list[Any]) -> None:
        """注入本次 chat 的响应序列（每个元素可为 LLMResponse 或 Exception）."""
        self._responses = list(responses)

    def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        timeout_s: float | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        self.calls.append({"messages": messages, "model": model})
        if not self._responses:
            raise AssertionError(
                f"_FakeLLMClient({self.model}): no more responses queued"
            )
        item = self._responses.pop(0)
        result = item(self.calls) if callable(item) else item
        if isinstance(result, Exception):
            raise result
        assert isinstance(result, LLMResponse), f"unexpected queued item: {type(result).__name__}"
        return result


def _build_fallback_pool(
    settings: Settings,
    *,
    provider_clients: dict[str, _FakeLLMClient] | None = None,
) -> ModelClientPool:
    """构造带默认 + 降级候选的 ModelClientPool（注入预制 _FakeLLMClient）.

    provider_clients: provider_id -> _FakeLLMClient, ModelClientPool.get_client(provider/model)
    将按 provider_id 在此字典中查找; 找不到则临时构造一个返回空响应的 _FakeLLMClient。
    """
    from llm_loop.llm.providers import load_registry

    registry = load_registry(settings)
    default_client = _FakeLLMClient(settings.llm_model)
    pool = ModelClientPool(
        registry=registry,
        default_client=default_client,
        model_fallbacks_raw=settings.model_fallbacks_raw,
    )
    # 注入预制候选 client（按 provider_id 缓存; 后续 get_client(ref) 命中缓存）
    if provider_clients:
        for provider_id, client in provider_clients.items():
            # 缓存键为 provider_id, ModelClientPool.get_client 内部按 provider_id 缓存
            # 这里直接操作 _provider_cache 以跳过预检 client_params（简化测试装配）
            pool._provider_cache[provider_id] = client  # noqa: SLF001
    return pool


# ── 集成: 降级逻辑 6 场景 ──


def test_default_model_429_triggers_fallback_to_next(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§5.4 表第 1 行: 默认模型 429 → 自动降级下一个 → 回执含 [模型降级: 标注 + 审计记录."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "real-key")
    settings = _settings(
        model_providers_raw=_THREE_PROVIDER_JSON,
        model_fallbacks_raw="deepseek/deepseek-v4-flash,local/qwen3.6-27b",
    data_dir=str(tmp_path / "data"),
    )

    # 主 client 第一次 chat 抛 429, 之后不再调用（fallback 接管）
    main_client = _FakeLLMClient("deepseek-v4-flash")
    main_client.queue(
        [
            LLMHTTPError(
                "HTTP 429: rate limit",
                status_code=429,
                body="rate limited",
                provider="deepseek",
            )
        ]
    )
    # 降级到 local 成功（注意: ModelClientPool 按 provider_id 缓存, 这里 local 命中我们注入的 client）
    fallback_client = _FakeLLMClient("qwen3.6-27b")
    fallback_client.queue(
        [LLMResponse(content="（降级后回答）", tool_calls=[], provider="local")]
    )

    pool = _build_fallback_pool(
        settings, provider_clients={"local": fallback_client}
    )
    # 把默认 client 替换为我们预制的（带 429 响应）
    pool.default_client = main_client  # type: ignore[assignment]

    # 装配 LoopEngine（用预制 pool）
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(exist_ok=True)
    status, ctx_corr, engine = _build_loop_engine_with_pool(
        settings, pool, audit_dir
    )
    ctx_corr.model_pool = pool

    sid = engine.session.create()
    result = engine.run(sid, "请回答我")

    # 验证 final_answer 取自降级响应
    assert result.final_answer == "（降级后回答）"
    # 验证消息流含 [模型降级: 标注（AI 可见, design 原则 2）
    sess = engine.session.load(sid)
    fallback_msgs = [m for m in sess.messages if "[模型降级:" in m.content]
    assert len(fallback_msgs) == 1
    assert "deepseek-v4-flash→local/qwen3.6-27b" in fallback_msgs[0].content
    assert "429 限流" in fallback_msgs[0].content

    # 验证审计落盘（self_correction_log.jsonl 含 model_fallback success 记录）
    log = audit_dir / "self_correction_log.jsonl"
    assert log.exists()
    lines = log.read_text(encoding="utf-8").strip().splitlines()
    fallback_records = [
        json.loads(ln)
        for ln in lines
        if json.loads(ln).get("tool_name") == "model_fallback"
    ]
    assert len(fallback_records) == 1
    rec = fallback_records[0]
    assert rec["result_status"] == "success"
    assert rec["arguments"]["from"] == "deepseek-v4-flash"
    assert rec["arguments"]["to"] == "local/qwen3.6-27b"
    assert rec["arguments"]["reason"] == "429 限流"

    # 验证 architecture_status 暴露降级态
    snap = status.snapshot()
    assert "model_fallback" in snap
    assert snap["model_fallback"]["active"] is True
    assert snap["model_fallback"]["from"] == "deepseek-v4-flash"
    assert snap["model_fallback"]["to"] == "local/qwen3.6-27b"
    assert snap["model_fallback"]["reason"] == "429 限流"


def test_default_model_timeout_triggers_fallback_chain(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§5.4 表第 2 行: 默认模型 timeout → 降级链走通."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "real-key")
    settings = _settings(
        model_providers_raw=_THREE_PROVIDER_JSON,
        model_fallbacks_raw="local/qwen3.6-27b,minimax/MiniMax-M3",
    data_dir=str(tmp_path / "data"),
    )
    monkeypatch.setenv("MINIMAX_API_KEY", "real-key")

    main_client = _FakeLLMClient("deepseek-v4-flash")
    main_client.queue([LLMTimeoutError("LLM 请求超时（120s）")])

    # local 第一个候选（按 model_fallbacks_raw 顺序）
    fallback_client_1 = _FakeLLMClient("qwen3.6-27b")
    fallback_client_1.queue([LLMResponse(content="（降级到 local 成功）", tool_calls=[], provider="local")])

    pool = _build_fallback_pool(
        settings, provider_clients={"local": fallback_client_1}
    )
    pool.default_client = main_client  # type: ignore[assignment]

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(exist_ok=True)
    status, ctx_corr, engine = _build_loop_engine_with_pool(
        settings, pool, audit_dir
    )
    ctx_corr.model_pool = pool

    sid = engine.session.create()
    result = engine.run(sid, "请回答我")

    assert result.final_answer == "（降级到 local 成功）"
    # 降级链走通: 命中第一个候选 local
    assert fallback_client_1.calls  # 确认 fallback_client_1 确实被调用
    # 审计记录
    log = audit_dir / "self_correction_log.jsonl"
    fallback_records = [
        json.loads(ln)
        for ln in log.read_text(encoding="utf-8").strip().splitlines()
        if json.loads(ln).get("tool_name") == "model_fallback"
    ]
    assert len(fallback_records) == 1
    assert fallback_records[0]["result_status"] == "success"
    assert fallback_records[0]["arguments"]["reason"] == "请求超时"
    assert fallback_records[0]["arguments"]["to"] == "local/qwen3.6-27b"
    # 状态上报
    assert status.snapshot()["model_fallback"]["active"] is True


def test_session_override_model_failure_no_fallback_strict_mode(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§5.4 表第 2 行: 会话 override 模型失败 → 严格模式不降级, 直接如实反馈.

    验证: sess.model_override 非空时（即使是合法 provider/model）, 失败不沿 fallback 链尝试,
    而直接如实反馈 LLMError; 既无降级提示消息, 也无 model_fallback 审计。
    """
    monkeypatch.setenv("DEEPSEEK_API_KEY", "real-key")
    settings = _settings(
        model_providers_raw=_THREE_PROVIDER_JSON,
        model_fallbacks_raw="local/qwen3.6-27b",
    data_dir=str(tmp_path / "data"),
    )

    # 默认 client 跑通（设置 override 前先完成设置, 因为 run() 内部读 sess.model_override）
    main_client = _FakeLLMClient("deepseek-v4-flash")
    main_client.queue([LLMResponse(content="从未执行", tool_calls=[], provider="deepseek")])

    pool = _build_fallback_pool(settings)
    pool.default_client = main_client  # type: ignore[assignment]

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(exist_ok=True)
    status, ctx_corr, engine = _build_loop_engine_with_pool(
        settings, pool, audit_dir
    )
    ctx_corr.model_pool = pool

    # 关键: 会话已设置 override（模拟用户/AI 经 switch_model 选择 minimax）
    sid = engine.session.create()
    sess = engine.session.load(sid)
    sess.model_override = "minimax/MiniMax-M3"
    engine.session.save(sess)

    # 重新装配: minimax client 抛 429（应严格模式不降级, 直接如实反馈）
    monkeypatch.setenv("MINIMAX_API_KEY", "real-key")
    minimax_client = _FakeLLMClient("MiniMax-M3")
    minimax_client.queue(
        [
            LLMHTTPError(
                "HTTP 429: rate limit",
                status_code=429,
                body="rate limited",
                provider="minimax",
            )
        ]
    )
    # 将 minimax 注入缓存以便 resolve("minimax/MiniMax-M3") 命中我们预制的 client
    pool._provider_cache["minimax"] = minimax_client  # noqa: SLF001

    result = engine.run(sid, "请回答我")

    # 严格模式: final_answer 是 llm_error_text 直接如实反馈, 不是降级提示
    assert "LLM 调用异常" in result.final_answer
    assert "HTTP 429" in result.final_answer
    # 既无 [模型降级: 提示消息, 也无 model_fallback 审计
    sess_loaded = engine.session.load(sid)
    assert not any("[模型降级:" in m.content for m in sess_loaded.messages if m.role == "system")
    log_path = audit_dir / "self_correction_log.jsonl"
    if log_path.exists():
        fallback_records = [
            json.loads(ln)
            for ln in log_path.read_text(encoding="utf-8").strip().splitlines()
            if json.loads(ln).get("tool_name") == "model_fallback"
        ]
        assert fallback_records == []
    # 状态: 未触发 record_fallback（严格模式）
    assert status.snapshot()["model_fallback"]["active"] is False


def test_all_fallbacks_fail_summarizes_reasons(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§5.4 表第 3 行: 链全失败 → 汇总各候选原因."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "real-key")
    monkeypatch.setenv("MINIMAX_API_KEY", "real-key")
    settings = _settings(
        model_providers_raw=_THREE_PROVIDER_JSON,
        model_fallbacks_raw="deepseek/deepseek-v4-flash,local/qwen3.6-27b,minimax/MiniMax-M3",
    data_dir=str(tmp_path / "data"),
    )

    # 主 client 抛 5xx
    main_client = _FakeLLMClient("deepseek-v4-flash")
    main_client.queue(
        [
            LLMHTTPError(
                "HTTP 503: service unavailable",
                status_code=503,
                body="upstream error",
                provider="deepseek",
            )
        ]
    )
    # 所有候选也失败
    fb1 = _FakeLLMClient("deepseek-v4-flash")
    fb1.queue([LLMNetworkError("LLM 网络不可达: timeout")])
    fb2 = _FakeLLMClient("qwen3.6-27b")
    fb2.queue([LLMTimeoutError("LLM 请求超时（120s）")])
    fb3 = _FakeLLMClient("MiniMax-M3")
    fb3.queue(
        [
            LLMHTTPError(
                "HTTP 429: rate limit",
                status_code=429,
                body="rate limited",
                provider="minimax",
            )
        ]
    )

    pool = _build_fallback_pool(
        settings,
        provider_clients={
            "deepseek": fb1,
            "local": fb2,
            "minimax": fb3,
        },
    )
    pool.default_client = main_client  # type: ignore[assignment]

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(exist_ok=True)
    status, ctx_corr, engine = _build_loop_engine_with_pool(
        settings, pool, audit_dir
    )
    ctx_corr.model_pool = pool

    sid = engine.session.create()
    result = engine.run(sid, "请回答我")

    # 链全失败 → final_answer 是 llm_error_text（如实反馈原始异常）
    assert "LLM 调用异常" in result.final_answer
    assert "503" in result.final_answer

    # 验证消息流注入汇总提示（含每个候选失败原因）
    sess_loaded = engine.session.load(sid)
    summary_msgs = [m for m in sess_loaded.messages if "[模型降级]" in m.content and "全部失败" in m.content]
    assert len(summary_msgs) == 1
    summary_content = summary_msgs[0].content
    assert "deepseek/deepseek-v4-flash" in summary_content  # 默认主模型
    assert "deepseek/deepseek-v4-flash" in summary_content  # 候选1
    assert "local/qwen3.6-27b" in summary_content  # 候选2
    assert "minimax/MiniMax-M3" in summary_content  # 候选3
    assert "网络不可达" in summary_content
    assert "请求超时" in summary_content
    assert "429" in summary_content

    # 审计记录 result_status="all_failed"
    log = audit_dir / "self_correction_log.jsonl"
    fallback_records = [
        json.loads(ln)
        for ln in log.read_text(encoding="utf-8").strip().splitlines()
        if json.loads(ln).get("tool_name") == "model_fallback"
    ]
    assert len(fallback_records) == 1
    rec = fallback_records[0]
    assert rec["result_status"] == "all_failed"
    assert rec["arguments"]["from"] == "deepseek-v4-flash"
    assert rec["arguments"]["to"] == "all_failed"
    assert rec["arguments"]["reason"] == "HTTP 503 上游错误"

    # 状态: 链全失败不算降级态（active=False）
    assert status.snapshot()["model_fallback"]["active"] is False


def test_http_4xx_no_fallback(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§5.4 表注: 4xx (如 400) 不降级 — 请求本身有问题, 换模型无用."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "real-key")
    settings = _settings(
        model_providers_raw=_THREE_PROVIDER_JSON,
        model_fallbacks_raw="local/qwen3.6-27b,minimax/MiniMax-M3",
    data_dir=str(tmp_path / "data"),
    )
    monkeypatch.setenv("MINIMAX_API_KEY", "real-key")

    main_client = _FakeLLMClient("deepseek-v4-flash")
    main_client.queue(
        [
            LLMHTTPError(
                "HTTP 400: bad request",
                status_code=400,
                body='{"error": "messages malformed"}',
                provider="deepseek",
            )
        ]
    )
    # 候选若被错误地调用, 会成功（但实际不应被调用）
    fb_local = _FakeLLMClient("qwen3.6-27b")
    fb_local.queue([LLMResponse(content="（不应被调用）", tool_calls=[], provider="local")])
    fb_minimax = _FakeLLMClient("MiniMax-M3")
    fb_minimax.queue([LLMResponse(content="（不应被调用）", tool_calls=[], provider="minimax")])

    pool = _build_fallback_pool(
        settings,
        provider_clients={"local": fb_local, "minimax": fb_minimax},
    )
    pool.default_client = main_client  # type: ignore[assignment]

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(exist_ok=True)
    status, ctx_corr, engine = _build_loop_engine_with_pool(
        settings, pool, audit_dir
    )
    ctx_corr.model_pool = pool

    sid = engine.session.create()
    result = engine.run(sid, "请回答我")

    # 4xx 非 429 → 不降级, 直接如实反馈原始 400 异常
    assert "LLM 调用异常" in result.final_answer
    assert "HTTP 400" in result.final_answer or "400" in result.final_answer
    # 无降级提示消息
    sess_loaded = engine.session.load(sid)
    assert not any("[模型降级:" in m.content for m in sess_loaded.messages if m.role == "system")
    # 无审计记录
    log = audit_dir / "self_correction_log.jsonl"
    if log.exists():
        fallback_records = [
            json.loads(ln)
            for ln in log.read_text(encoding="utf-8").strip().splitlines()
            if json.loads(ln).get("tool_name") == "model_fallback"
        ]
        assert fallback_records == []
    # 候选 client 不应被调用
    assert fb_local.calls == []
    assert fb_minimax.calls == []
    # 状态: 未降级
    assert status.snapshot()["model_fallback"]["active"] is False


def test_empty_fallbacks_zero_regression(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MODEL_FALLBACKS 空 → 零回归: 失败直接反馈, 无降级提示/审计/状态变化."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "real-key")
    settings = _settings(
        model_providers_raw=_THREE_PROVIDER_JSON,
        model_fallbacks_raw="",  # 空 = 不启用
    data_dir=str(tmp_path / "data"),
    )

    main_client = _FakeLLMClient("deepseek-v4-flash")
    main_client.queue(
        [
            LLMHTTPError(
                "HTTP 429: rate limit",
                status_code=429,
                body="rate limited",
                provider="deepseek",
            )
        ]
    )

    pool = _build_fallback_pool(settings)
    pool.default_client = main_client  # type: ignore[assignment]

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(exist_ok=True)
    status, ctx_corr, engine = _build_loop_engine_with_pool(
        settings, pool, audit_dir
    )
    ctx_corr.model_pool = pool

    sid = engine.session.create()
    result = engine.run(sid, "请回答我")

    # 失败直接如实反馈原始异常
    assert "LLM 调用异常" in result.final_answer
    assert "429" in result.final_answer
    # 无降级提示消息
    sess_loaded = engine.session.load(sid)
    assert not any("[模型降级:" in m.content for m in sess_loaded.messages if m.role == "system")
    # 无审计
    log_path = audit_dir / "self_correction_log.jsonl"
    if log_path.exists():
        fallback_records = [
            json.loads(ln)
            for ln in log_path.read_text(encoding="utf-8").strip().splitlines()
            if json.loads(ln).get("tool_name") == "model_fallback"
        ]
        assert fallback_records == []
    # 状态: 未降级
    assert status.snapshot()["model_fallback"]["active"] is False
    # pool.fallback_candidates() 验证: 空 list
    assert pool.fallback_candidates() == []


# ── 辅助: 用预制 pool 装配 LoopEngine（用于集成测试） ──


def _build_loop_engine_with_pool(
    settings: Settings,
    pool: ModelClientPool,
    audit_dir,
):
    """用预制 ModelClientPool 装配 LoopEngine（返回 status, ctx, engine 三元组）.

    测试专用: 不复用 conftest.build_test_engine（因它内部强制用 FakeLLM + 自己建 pool）.
    本函数装配最小 LoopEngine（status + correction_ctx + correction_registry）,
    沿用现有架构自省/审计通道, 但 pool 由调用方注入以控制候选 client.
    """
    from llm_loop.core.loop import LoopEngine
    from llm_loop.core.session import SessionStore
    from llm_loop.feedback.validator import DeclarationValidator
    from llm_loop.introspection.status import ArchitectureStatusProvider
    from llm_loop.memory.archive import ArchiveStore
    from llm_loop.memory.store import MemoryStore
    from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
    from llm_loop.tools.builtin.read_file import ReadFileTool
    from llm_loop.tools.registry import ToolRegistry

    memory = MemoryStore(settings.memory_dir)
    session = SessionStore(settings.sessions_dir)
    archive = ArchiveStore(settings.archive_dir) if settings.archive_enabled else None
    tool_registry = ToolRegistry(
        tool_timeout_s=settings.tool_timeout_s,
        max_output_chars=settings.tool_max_output_chars,
        archive_store=archive,
    )
    tool_registry.register(ReadFileTool())
    tool_registry.register(ExecuteCommandTool())

    status = ArchitectureStatusProvider(
        audit_dir=settings.audit_dir,
        enabled=settings.self_inspection_enabled,
        config_status=settings.to_status_dict,
    )
    ctx_corr = CorrectionContext()
    corrections = CorrectionToolRegistry(
        ctx_corr, audit_dir=audit_dir, status_provider=status, archive_store=archive
    )
    ctx_corr.model_pool = pool

    validator = DeclarationValidator(audit_dir=settings.audit_dir)
    engine = LoopEngine(
        llm_client=pool.default_client,  # type: ignore[arg-type] — _FakeLLMClient duck typing
        registry=tool_registry,
        memory=memory,
        session=session,
        settings=settings,
        validator=validator,
        status_provider=status,
        correction_registry=corrections,
        correction_ctx=ctx_corr,
        archive=archive,
        llm_pool=pool,  # M49 降级逻辑走 pool 路由
    )
    return status, ctx_corr, engine


# ── 密钥安全 ──


def test_no_api_key_leaked_in_fallback_audit(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """降级审计 / 提示消息 / status 永不回显 api_key 本体（DFX-SEC-02）."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "supersecret-xyz-789")
    settings = _settings(
        model_providers_raw=_THREE_PROVIDER_JSON,
        model_fallbacks_raw="local/qwen3.6-27b",
    data_dir=str(tmp_path / "data"),
    )

    main_client = _FakeLLMClient("deepseek-v4-flash")
    main_client.queue(
        [
            LLMHTTPError(
                "HTTP 429: rate limit",
                status_code=429,
                body="rate limited",
                provider="deepseek",
            )
        ]
    )
    fb_local = _FakeLLMClient("qwen3.6-27b")
    fb_local.queue([LLMResponse(content="（降级成功）", tool_calls=[], provider="local")])

    pool = _build_fallback_pool(settings, provider_clients={"local": fb_local})
    pool.default_client = main_client  # type: ignore[assignment]

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(exist_ok=True)
    status, ctx_corr, engine = _build_loop_engine_with_pool(
        settings, pool, audit_dir
    )
    ctx_corr.model_pool = pool

    sid = engine.session.create()
    engine.run(sid, "请回答我")

    # 审计 log 不含 key 本体
    log_text = (audit_dir / "self_correction_log.jsonl").read_text(encoding="utf-8")
    assert "supersecret-xyz-789" not in log_text

    # 注入提示消息不含 key 本体
    sess_loaded = engine.session.load(sid)
    all_text = "\n".join(m.content for m in sess_loaded.messages)
    assert "supersecret-xyz-789" not in all_text

    # status snapshot 不含 key 本体
    status_text = json.dumps(status.snapshot(), ensure_ascii=False)
    assert "supersecret-xyz-789" not in status_text
