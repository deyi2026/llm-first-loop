"""M48 模型工具测试（design §5.3 / model_catalog + switch_model + ModelClientPool）.

覆盖:
- model_catalog 回执含目录 + 当前模型 + degraded 标注
- switch_model 成功路径（override 落会话 + 审计记录 + 回执文案）
- switch_model 未知模型/歧义/key 缺失 三类失败如实回执且现状不变
- switch_model default 清除 override
- pool: 无 override 用默认 / 有 override 按 provider 缓存复用 / 零回归路径
- 会话持久化: override 写盘后重载仍在

全部 Mock/FakeLLM, 零真实网络。
"""

from __future__ import annotations

import json

import pytest

from llm_loop.config import Settings
from llm_loop.core.session import SessionStore
from llm_loop.introspection.corrections import CorrectionContext, CorrectionToolRegistry
from llm_loop.introspection.tools_model import (
    MODEL_CATALOG_TOOL_DEF,
    SWITCH_MODEL_TOOL_DEF,
    run_model_catalog,
    run_switch_model,
)
from llm_loop.llm.pool import ModelClientPool
from llm_loop.llm.providers import (
    ProviderRegistry,
    load_registry,
)

# ── 工具: 共享 fixture ──


def _settings(**overrides) -> Settings:
    """构造最小 Settings（M47 + M48 字段）."""
    base = {
        "llm_api_key": "test-key",
        "llm_base_url": "https://api.deepseek.com/v1",
        "llm_model": "deepseek-v4-flash",
        "data_dir": "./data",
        "model_providers_raw": "",
    }
    base.update(overrides)
    return Settings(**base)


_TWO_PROVIDER_JSON = json.dumps(
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


class _FakeLLM:
    """极简 FakeLLM（duck typing; ModelClientPool 仅作 default_client 容器, 不实际调 chat）.

    实现 LLMClient 同名属性（timeout_s / thinking_mode / reasoning_effort / thinking_supported）,
    使 ModelClientPool.get_client() 路径可读取 default_client 的运行参数继承到新建 client.
    """

    def __init__(self, model: str = "deepseek-v4-flash") -> None:
        self.model = model
        self.max_tokens: int | None = None
        self.wire_protocol: str = "openai"  # P3-5 对齐 LLMClient 新字段  # 2026-08-15: 对齐 LLMClient 新装配字段
        self.timeout_s = 120.0
        self.thinking_mode = True
        self.reasoning_effort = "high"
        self.thinking_supported = True

    def chat(self, *args, **kwargs):  # pragma: no cover — 不会被调用
        raise AssertionError("FakeLLM.chat should not be called in M48 unit tests")


def _build_pool(settings: Settings, *, providers: ProviderRegistry | None = None) -> ModelClientPool:
    """构造测试用 ModelClientPool（FakeLLM 作 default_client; providers 可外部注入）. """
    if providers is None:
        providers = load_registry(settings)
    return ModelClientPool(registry=providers, default_client=_FakeLLM(settings.llm_model))  # type: ignore[arg-type]


def _build_ctx(pool: ModelClientPool | None = None) -> CorrectionContext:
    """构造装配好的 CorrectionContext（含 model_pool）."""
    ctx = CorrectionContext()
    ctx.model_pool = pool
    return ctx


def _build_corrections(ctx: CorrectionContext, audit_dir) -> CorrectionToolRegistry:
    """构造带审计目录的 CorrectionToolRegistry.

    audit_dir: 测试传递的审计目录路径（由 caller 创建 + 确保存在）.
    """
    return CorrectionToolRegistry(ctx, audit_dir=audit_dir)


# ── 工具 schema 注册 ──


def test_model_catalog_tool_def_registered() -> None:
    """tool_defs() 含 model_catalog / switch_model schema（M48 工具注册可见）."""
    reg = _build_corrections(_build_ctx(), None if False else __import__("pathlib").Path("/tmp/m48-test-audit"))
    names = [td["name"] for td in reg.tool_defs()]
    assert "model_catalog" in names
    assert "switch_model" in names


def test_tool_def_schemas_match_spec() -> None:
    """schema 内容对齐 design §5.3."""
    assert MODEL_CATALOG_TOOL_DEF["name"] == "model_catalog"
    assert SWITCH_MODEL_TOOL_DEF["name"] == "switch_model"
    # model_catalog: 无必填参数
    assert SWITCH_MODEL_TOOL_DEF["parameters"]["required"] == ["model", "reason"]


# ── model_catalog: 回执含目录 + 当前模型 + degraded ──


def test_model_catalog_includes_directory_and_current() -> None:
    """catalog 回执含 provider/模型/能力 + 当前会话模型标注."""
    settings = _settings(model_providers_raw=_TWO_PROVIDER_JSON)
    pool = _build_pool(settings)
    ctx = _build_ctx(pool)
    ctx.session_model_override = None  # 默认装配
    result = run_model_catalog(ctx, pool, ctx.session_model_override)
    assert result.status.value == "success"
    content = result.content
    assert "deepseek" in content
    assert "deepseek-v4-flash" in content
    assert "deepseek-v4-pro" in content
    assert "local" in content
    assert "qwen3.6-27b" in content
    assert "当前会话模型" in content
    assert "默认装配" in content
    # thinking 标注存在
    assert "thinking=" in content
    # B6: 选型指引（成本/能力语义 + switch_model 引导）
    assert "选型指引" in content
    assert "cost=low/mid/high" in content
    assert "switch_model" in content


def test_model_catalog_marks_current_with_override() -> None:
    """override 设置后, 当前会话模型标注为 "会话覆盖" 且指向 override 模型."""
    settings = _settings(model_providers_raw=_TWO_PROVIDER_JSON)
    pool = _build_pool(settings)
    ctx = _build_ctx(pool)
    ctx.session_model_override = "local/qwen3.6-27b"
    result = run_model_catalog(ctx, pool, ctx.session_model_override)
    assert result.status.value == "success"
    assert "会话覆盖" in result.content
    assert "local/qwen3.6-27b" in result.content


def test_model_catalog_degraded_annotation() -> None:
    """注册表 degraded 时 catalog 回执如实标注."""
    settings = _settings(model_providers_raw="{not valid")
    pool = _build_pool(settings)
    # load_registry fail-soft → degraded=True
    assert pool.registry.degraded is True
    ctx = _build_ctx(pool)
    result = run_model_catalog(ctx, pool, ctx.session_model_override)
    assert result.status.value == "success"
    assert "[degraded]" in result.content


def test_model_catalog_zero_registry_singleton_provider(tmp_path) -> None:
    """零回归: 未配置 MODEL_PROVIDERS → catalog 如实返回单 provider 现状（不伪造多 provider）."""
    # data_dir 指向隔离目录，避免工作区 data/providers.json 影响（走 L0 合成）
    settings = _settings(data_dir=str(tmp_path / "data"))
    pool = _build_pool(settings)
    # L0 合成: 仅 deepseek 单 provider
    assert set(pool.registry.providers) == {"deepseek"}
    ctx = _build_ctx(pool)
    result = run_model_catalog(ctx, pool, ctx.session_model_override)
    assert result.status.value == "success"
    assert "[deepseek]" in result.content
    assert "deepseek-v4-flash" in result.content
    # 不应伪造多 provider
    assert "[local]" not in result.content


def test_model_catalog_pool_unavailable_truthful() -> None:
    """model_pool=None → 如实回执"工具不可用"（不崩）."""
    ctx = _build_ctx(pool=None)
    result = run_model_catalog(ctx, None, None)
    assert result.status.value == "failure"
    assert "[工具不可用]" in result.content


# ── switch_model: 成功路径 ──


def test_switch_model_success_writes_session_and_audit(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """成功路径: override 落会话 + 审计记录 + 回执文案含 from→to + 思考参数标注."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "real-key")
    settings = _settings(model_providers_raw=_TWO_PROVIDER_JSON)
    pool = _build_pool(settings)

    # 会话存储
    store = SessionStore(tmp_path / "sessions")
    sid = store.create()
    sess = store.load(sid)
    assert sess.model_override is None

    # 上下文 + set_override 回调
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(exist_ok=True)
    reg = _build_corrections(_build_ctx(pool), audit_dir)
    ctx = reg.ctx
    ctx.session_model_override = sess.model_override

    captured = {"value": None}

    def _set_override(value):
        captured["value"] = value
        sess.model_override = value

    ctx.session_set_override = _set_override

    # 执行: 切到 deepseek-v4-pro（同 provider, 走 resolve → 缓存复用）
    result = run_switch_model(
        ctx,
        pool,
        ctx.session_set_override,
        reg._audit,  # noqa: SLF001
        {"model": "deepseek-v4-pro", "reason": "需要更强推理"},
    )
    assert result.status.value == "success"
    # 回执文案对齐 design §5.3
    assert "[状态: 成功]" in result.content
    assert "deepseek-v4-flash → deepseek/deepseek-v4-pro" in result.content
    assert "需要更强推理" in result.content
    assert "思考参数" in result.content
    # B6: 成本/能力事实注入（目标模型 cost_tier + 能力语义, 判断归 AI）
    assert "成本档:" in result.content
    assert "能力:" in result.content
    # override 已写入会话
    assert captured["value"] == "deepseek/deepseek-v4-pro"
    assert sess.model_override == "deepseek/deepseek-v4-pro"
    # 审计落盘
    log = audit_dir / "self_correction_log.jsonl"
    assert log.exists()
    record = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert record["tool_name"] == "switch_model"
    assert record["result_status"] == "success"
    assert record["arguments"]["from"] == "deepseek-v4-flash"
    assert record["arguments"]["to"] == "deepseek/deepseek-v4-pro"
    assert record["arguments"]["reason"] == "需要更强推理"


def test_switch_model_cross_provider_thinking_note(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """跨 provider 切换 + thinking_supported 标注."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "real-key")
    settings = _settings(model_providers_raw=_TWO_PROVIDER_JSON)
    pool = _build_pool(settings)

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(exist_ok=True)
    reg = _build_corrections(_build_ctx(pool), audit_dir)
    ctx = reg.ctx

    def _set_override(value):
        pass

    ctx.session_set_override = _set_override
    # 切到 local/qwen3.6-27b（thinking=True, 但要测反向用例）
    result = run_switch_model(
        ctx,
        pool,
        ctx.session_set_override,
        reg._audit,  # noqa: SLF001
        {"model": "local/qwen3.6-27b", "reason": "本地兜底"},
    )
    assert result.status.value == "success"
    assert "local/qwen3.6-27b" in result.content
    assert "思考参数: 发送" in result.content


# ── switch_model: 失败路径 ──


def test_switch_model_unknown_model_truthful(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """未知模型 → 如实回执含候选列表 + 现状不变."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "real-key")
    settings = _settings(model_providers_raw=_TWO_PROVIDER_JSON)
    pool = _build_pool(settings)

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(exist_ok=True)
    reg = _build_corrections(_build_ctx(pool), audit_dir)
    ctx = reg.ctx

    sess_model_override_holder = {"value": "deepseek/deepseek-v4-pro"}
    ctx.session_model_override = sess_model_override_holder["value"]

    def _set_override(value):
        # 失败路径不应被调用
        sess_model_override_holder["value"] = value
        raise AssertionError("set_override should not be called on failure")

    ctx.session_set_override = _set_override

    result = run_switch_model(
        ctx,
        pool,
        ctx.session_set_override,
        reg._audit,  # noqa: SLF001
        {"model": "nonexistent-model", "reason": "测试未知"},
    )
    assert result.status.value == "failure"
    assert "[状态: 失败]" in result.content
    assert "不在注册表中" in result.content or "未知" in result.content
    # 候选列表
    assert "deepseek-v4-flash" in result.content or "候选" in result.content
    # 现状不变
    assert sess_model_override_holder["value"] == "deepseek/deepseek-v4-pro"


def test_switch_model_ambiguous_bare_name_truthful(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """裸名跨 provider 歧义 → 如实回执."""
    raw = json.dumps(
        {
            "a": {"base_url": "http://a", "api_key_env": "", "models": {"shared": {}}},
            "b": {"base_url": "http://b", "api_key_env": "", "models": {"shared": {}}},
        }
    )
    settings = _settings(model_providers_raw=raw)
    pool = _build_pool(settings)

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(exist_ok=True)
    reg = _build_corrections(_build_ctx(pool), audit_dir)
    ctx = reg.ctx
    ctx.session_model_override = None

    ctx.session_set_override = lambda v: pytest.fail("set_override should not be called")

    result = run_switch_model(
        ctx,
        pool,
        ctx.session_set_override,
        reg._audit,  # noqa: SLF001
        {"model": "shared", "reason": "歧义测试"},
    )
    assert result.status.value == "failure"
    assert "[状态: 失败]" in result.content
    assert "多个 provider" in result.content


def test_switch_model_missing_key_truthful(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """provider key 缺失 → 如实回执含 env var 名 + 现状不变."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    settings = _settings(model_providers_raw=_TWO_PROVIDER_JSON)
    pool = _build_pool(settings)

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(exist_ok=True)
    reg = _build_corrections(_build_ctx(pool), audit_dir)
    ctx = reg.ctx
    ctx.session_model_override = None

    override_calls = []

    def _set_override(value):
        override_calls.append(value)

    ctx.session_set_override = _set_override

    result = run_switch_model(
        ctx,
        pool,
        ctx.session_set_override,
        reg._audit,  # noqa: SLF001
        {"model": "deepseek-v4-pro", "reason": "缺 key 测试"},
    )
    assert result.status.value == "failure"
    assert "DEEPSEEK_API_KEY" in result.content
    assert "未设置" in result.content or "缺少" in result.content
    # 现状不变: set_override 不应被调用
    assert override_calls == []


def test_switch_model_missing_required_params(tmp_path) -> None:
    """缺必填参数 → 如实回执."""
    settings = _settings(model_providers_raw=_TWO_PROVIDER_JSON)
    pool = _build_pool(settings)
    reg = _build_corrections(_build_ctx(pool), tmp_path / "audit")
    ctx = reg.ctx

    # 缺 model
    result = run_switch_model(ctx, pool, None, None, {"reason": "test"})
    assert result.status.value == "failure"
    assert "缺少必填参数 'model'" in result.content

    # 缺 reason
    result = run_switch_model(ctx, pool, None, None, {"model": "deepseek-v4-pro"})
    assert result.status.value == "failure"
    assert "缺少必填参数 'reason'" in result.content


# ── switch_model: default 清除 override ──


def test_switch_model_default_clears_override(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """model='default' → 清除 override 回装配默认 + 审计落盘."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "real-key")
    settings = _settings(model_providers_raw=_TWO_PROVIDER_JSON)
    pool = _build_pool(settings)

    store = SessionStore(tmp_path / "sessions")
    sid = store.create()
    sess = store.load(sid)
    sess.model_override = "deepseek/deepseek-v4-pro"

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(exist_ok=True)
    reg = _build_corrections(_build_ctx(pool), audit_dir)
    ctx = reg.ctx
    ctx.session_model_override = sess.model_override

    def _set_override(value):
        sess.model_override = value

    ctx.session_set_override = _set_override

    result = run_switch_model(
        ctx,
        pool,
        ctx.session_set_override,
        reg._audit,  # noqa: SLF001
        {"model": "default", "reason": "回退默认"},
    )
    assert result.status.value == "success"
    assert "[状态: 成功]" in result.content
    assert "deepseek-v4-pro → default" in result.content or "→ default" in result.content
    assert "已清除会话覆盖" in result.content
    # 审计
    log = audit_dir / "self_correction_log.jsonl"
    record = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert record["arguments"]["to"] == "default"
    # override 已清除
    assert sess.model_override is None


def test_switch_model_default_case_insensitive(tmp_path) -> None:
    """model='DEFAULT'/'Default' 大小写不敏感视为清除."""
    settings = _settings(model_providers_raw=_TWO_PROVIDER_JSON)
    pool = _build_pool(settings)
    reg = _build_corrections(_build_ctx(pool), tmp_path / "audit")
    ctx = reg.ctx
    ctx.session_model_override = None

    override_calls = []

    def _set_override(value):
        override_calls.append(value)

    ctx.session_set_override = _set_override

    for variant in ("default", "DEFAULT", "Default"):
        result = run_switch_model(
            ctx,
            pool,
            ctx.session_set_override,
            reg._audit,  # noqa: SLF001
            {"model": variant, "reason": "case test"},
        )
        assert result.status.value == "success"
    assert override_calls == [None, None, None]


# ── ModelClientPool: 路由 / 缓存 / 零回归 ──


def test_pool_returns_default_when_no_override() -> None:
    """get_client(None) → 返回 default_client（不调用 resolve）."""
    settings = _settings(model_providers_raw=_TWO_PROVIDER_JSON)
    pool = _build_pool(settings)
    client = pool.get_client(None)
    assert client is pool.default_client


def test_pool_resolves_and_caches_by_provider() -> None:
    """get_client(override) → resolve → client_params → 缓存（同 provider 复用）."""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "real-key")
    try:
        settings = _settings(model_providers_raw=_TWO_PROVIDER_JSON)
        pool = _build_pool(settings)
        # 首次: 切到 deepseek-v4-pro
        client1 = pool.get_client("deepseek/deepseek-v4-pro")
        assert client1 is not pool.default_client
        assert client1.model == "deepseek-v4-pro"
        # 同 provider 再访问: 命中缓存
        client2 = pool.get_client("deepseek/deepseek-v4-flash")
        assert client2 is client1  # 缓存按 provider 复用
        # local provider: 独立缓存
        client3 = pool.get_client("local/qwen3.6-27b")
        assert client3 is not client1
        assert client3.model == "qwen3.6-27b"
        assert pool.cached_provider_ids() == ["deepseek", "local"]
    finally:
        monkeypatch.undo()


def test_pool_bare_name_unique_resolve() -> None:
    """裸名唯一匹配 → resolve → 缓存."""
    settings = _settings(model_providers_raw=_TWO_PROVIDER_JSON)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "real-key")
    try:
        pool = _build_pool(settings)
        client = pool.get_client("qwen3.6-27b")  # 裸名, 仅 local 命中
        assert client.model == "qwen3.6-27b"
        assert "local" in pool.cached_provider_ids()
    finally:
        monkeypatch.undo()


def test_pool_provider_timeout_wins_over_global() -> None:
    """provider 级 timeout_s 优先于全局默认（本地慢模型接入）.

    local 显式配置 timeout_s=600 → 构造 client 超时 600;
    deepseek 未配置 → 继承默认 client 的全局超时（零回归）.
    """
    raw = json.dumps(
        {
            "deepseek": {
                "base_url": "https://api.deepseek.com/v1",
                "api_key_env": "DEEPSEEK_API_KEY",
                "models": {"deepseek-v4-flash": {}},
            },
            "local": {
                "base_url": "http://localhost:1234/v1",
                "api_key_env": "",
                "timeout_s": 600,
                "models": {"qwen3.6-27b": {}},
            },
        }
    )
    settings = _settings(model_providers_raw=raw)
    pool = _build_pool(settings)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "real-key")
    try:
        local_client = pool.get_client("local/qwen3.6-27b")
        assert local_client.timeout_s == 600.0
        ds_client = pool.get_client("deepseek/deepseek-v4-flash")
        assert ds_client.timeout_s == pool.default_client.timeout_s  # 全局值继承
    finally:
        monkeypatch.undo()


def test_pool_bare_name_ambiguous_raises() -> None:
    """裸名歧义 → ValueError（如实反馈, 不静默 fallback）."""
    raw = json.dumps(
        {
            "a": {"base_url": "http://a", "api_key_env": "", "models": {"shared": {}}},
            "b": {"base_url": "http://b", "api_key_env": "", "models": {"shared": {}}},
        }
    )
    settings = _settings(model_providers_raw=raw)
    pool = _build_pool(settings)
    with pytest.raises(ValueError, match="多个 provider"):
        pool.get_client("shared")


def test_pool_zero_registry_only_default() -> None:
    """零回归: 未配置注册表 → pool 只有默认 client（同 L0 合成）."""
    settings = _settings()
    pool = _build_pool(settings)
    assert pool.cached_provider_ids() == []
    # get_client(None) → default
    assert pool.get_client(None) is pool.default_client
    # get_default_model
    assert pool.get_default_model() == "deepseek-v4-flash"


def test_pool_thinking_metadata_driven() -> None:
    """get_thinking 走 registry 元数据（衔接 M47 §5.5）."""
    settings = _settings(model_providers_raw=_TWO_PROVIDER_JSON)
    pool = _build_pool(settings)
    # default_client.thinking_supported 是 FakeLLM 默认 True, 但 get_thinking(None) 不依赖
    # 直接用 registry 查询
    assert pool.get_thinking("deepseek/deepseek-v4-flash") is True
    assert pool.get_thinking("deepseek/deepseek-v4-pro") is True
    assert pool.get_thinking("local/qwen3.6-27b") is True
    # 未知模型 → False
    assert pool.get_thinking("ghost/x") is False


def test_pool_clear_cache() -> None:
    """clear_cache 清空 provider 缓存（不影响 default_client）."""
    settings = _settings(model_providers_raw=_TWO_PROVIDER_JSON)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "real-key")
    try:
        pool = _build_pool(settings)
        pool.get_client("deepseek/deepseek-v4-pro")
        assert "deepseek" in pool.cached_provider_ids()
        pool.clear_cache()
        assert pool.cached_provider_ids() == []
        assert pool.default_client is not None
    finally:
        monkeypatch.undo()


# ── 会话持久化: override 写盘后重载仍在 ──


def test_session_model_override_persistence(tmp_path) -> None:
    """override 写入 SessionStore → 重载仍在."""
    store = SessionStore(tmp_path / "sessions")
    sid = store.create()
    sess = store.load(sid)
    assert sess.model_override is None
    # 写入
    sess.model_override = "deepseek/deepseek-v4-pro"
    store.save(sess)
    # 重载
    sess2 = store.load(sid)
    assert sess2.model_override == "deepseek/deepseek-v4-pro"


def test_session_old_file_missing_override_field_backward_compat(tmp_path) -> None:
    """旧 JSON 无 model_override 字段 → 重载时缺省 None（向后兼容）."""
    sid = "old-session"
    # 手工构造旧格式 JSON（无 model_override 字段）
    (tmp_path / "sessions").mkdir(exist_ok=True)
    (tmp_path / "sessions" / f"{sid}.json").write_text(
        json.dumps({"version": 3, "session_id": sid, "messages": []}),
        encoding="utf-8",
    )
    store = SessionStore(tmp_path / "sessions")
    sess = store.load(sid)
    assert sess.model_override is None  # 向后兼容


def test_session_to_dict_includes_override(tmp_path) -> None:
    """to_dict 含 model_override 字段（持久化生效）."""
    store = SessionStore(tmp_path / "sessions")
    sid = store.create()
    sess = store.load(sid)
    sess.model_override = "minimax/MiniMax-M3"
    d = sess.to_dict()
    assert d["model_override"] == "minimax/MiniMax-M3"


# ── 端到端: 注册表 + 工具 + 池 + 会话 (集成风格) ──


def test_end_to_end_catalog_then_switch_then_persist(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """端到端: catalog 查目录 → switch 切模型 → 会话持久化 → 重载仍在."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "real-key")
    settings = _settings(model_providers_raw=_TWO_PROVIDER_JSON)
    pool = _build_pool(settings)

    store = SessionStore(tmp_path / "sessions")
    sid = store.create()
    sess = store.load(sid)
    assert sess.model_override is None

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(exist_ok=True)
    reg = _build_corrections(_build_ctx(pool), audit_dir)
    ctx = reg.ctx

    # 1. model_catalog: 查目录
    catalog = run_model_catalog(ctx, pool, sess.model_override)
    assert catalog.status.value == "success"
    assert "deepseek-v4-pro" in catalog.content
    assert "默认装配" in catalog.content

    # 2. switch_model: 切到 deepseek-v4-pro（持久化到 sess）
    def _set_override(value):
        sess.model_override = value

    ctx.session_model_override = sess.model_override
    ctx.session_set_override = _set_override

    switch = run_switch_model(
        ctx,
        pool,
        ctx.session_set_override,
        reg._audit,  # noqa: SLF001
        {"model": "deepseek-v4-pro", "reason": "e2e 测试"},
    )
    assert switch.status.value == "success"
    # 持久化
    store.save(sess)

    # 3. 重载会话
    sess2 = store.load(sid)
    assert sess2.model_override == "deepseek/deepseek-v4-pro"

    # 4. pool 按 override 路由 → 取到对应 client
    client = pool.get_client(sess2.model_override)
    assert client.model == "deepseek-v4-pro"
    assert "deepseek" in pool.cached_provider_ids()

    # 5. 再 catalog: 应标注为 "会话覆盖"
    catalog2 = run_model_catalog(ctx, pool, sess2.model_override)
    assert catalog2.status.value == "success"
    assert "会话覆盖" in catalog2.content


# ── 密钥安全 ──


def test_no_api_key_leaked_in_tool_responses(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """工具回执/审计永不回显 api_key 本体."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "supersecret-xyz-789")
    settings = _settings(model_providers_raw=_TWO_PROVIDER_JSON)
    pool = _build_pool(settings)

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(exist_ok=True)
    reg = _build_corrections(_build_ctx(pool), audit_dir)
    ctx = reg.ctx

    def _set_override(value):
        pass

    ctx.session_set_override = _set_override

    # catalog
    cat = run_model_catalog(ctx, pool, None)
    assert "supersecret-xyz-789" not in cat.content

    # switch 成功
    sw = run_switch_model(
        ctx,
        pool,
        ctx.session_set_override,
        reg._audit,  # noqa: SLF001
        {"model": "deepseek-v4-pro", "reason": "key 安全测试"},
    )
    assert "supersecret-xyz-789" not in sw.content

    # 审计日志
    log_text = (audit_dir / "self_correction_log.jsonl").read_text(encoding="utf-8")
    assert "supersecret-xyz-789" not in log_text


# ── 集成: CorrectionToolRegistry 端到端 ──


def test_corrections_execute_dispatch_model_catalog(tmp_path) -> None:
    """CorrectionToolRegistry.execute('model_catalog', ...) 端到端通."""
    settings = _settings(model_providers_raw=_TWO_PROVIDER_JSON)
    pool = _build_pool(settings)
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(exist_ok=True)
    ctx = _build_ctx(pool)
    reg = _build_corrections(ctx, audit_dir)
    ctx.session_model_override = None

    result = reg.execute("model_catalog", {})
    assert result.status.value == "success"
    assert "deepseek" in result.content


def test_corrections_execute_dispatch_switch_model(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CorrectionToolRegistry.execute('switch_model', ...) 端到端通 + 审计."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "real-key")
    settings = _settings(model_providers_raw=_TWO_PROVIDER_JSON)
    pool = _build_pool(settings)

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(exist_ok=True)
    ctx = _build_ctx(pool)
    reg = _build_corrections(ctx, audit_dir)
    ctx.session_model_override = None
    ctx.session_set_override = lambda v: None

    result = reg.execute(
        "switch_model", {"model": "deepseek-v4-pro", "reason": "dispatch 测试"}
    )
    assert result.status.value == "success"
    # 审计
    log = audit_dir / "self_correction_log.jsonl"
    assert log.exists()
    record = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert record["tool_name"] == "switch_model"
    assert record["result_status"] == "success"


# ── R5: ModelSpec 能力字段 + model_catalog 展示 ──


def test_model_spec_capability_fields_default_false() -> None:
    """能力字段默认 False（未配置零回归）."""
    settings = _settings(model_providers_raw=_TWO_PROVIDER_JSON)
    pool = _build_pool(settings)
    spec = pool.registry.providers["deepseek"].models["deepseek-v4-flash"]
    assert spec.reasoning is False
    assert spec.long_context is False
    assert spec.multimodal is False


def test_model_catalog_shows_capabilities() -> None:
    """配置能力字段后 model_catalog 回执展示."""
    providers_json = json.dumps(
        {
            "deepseek": {
                "base_url": "https://api.deepseek.com/v1",
                "api_key_env": "DEEPSEEK_API_KEY",
                "models": {
                    "deepseek-v4-pro": {
                        "context": 1000000,
                        "thinking": True,
                        "cost_tier": "high",
                        "reasoning": True,
                        "long_context": True,
                    },
                    "deepseek-v4-flash": {
                        "context": 131072,
                        "thinking": True,
                        "cost_tier": "low",
                    },
                },
                "default_model": "deepseek-v4-flash",
            }
        }
    )
    settings = _settings(model_providers_raw=providers_json)
    pool = _build_pool(settings)
    spec = pool.registry.providers["deepseek"].models["deepseek-v4-pro"]
    assert spec.reasoning is True
    assert spec.long_context is True
    assert spec.multimodal is False

    ctx = _build_ctx(pool)
    ctx.session_model_override = None
    result = run_model_catalog(ctx, pool, ctx.session_model_override)
    assert result.status.value == "success"
    assert "reasoning/long_context" in result.content  # 能力标注
    assert "deepseek-v4-flash" in result.content  # 无能力字段模型不标注
