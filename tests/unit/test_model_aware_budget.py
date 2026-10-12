"""M54 模型窗口感知主动压缩测试（founder 2026-08-11 指令, k3-256k 事故治本）.

核心: 压缩预算从全局静态值 → min(全局, 模型真实输入窗口预算, provider 显式预算)。
窗口预算只预留可证明的安全边距/输出容量，不再固定砍半；最终载荷仍有发送前硬校验。

全部 Mock, 零真实网络。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from llm_loop.core.message import Message, MessageSource, ToolCall, ToolResultStatus
from llm_loop.core.prompt_build.stages.history_pipeline import _anchor_for_current_contract

from .test_model_attribution import (  # noqa: F401
    _FakeLLMClient,
    _make_engine,
    _make_pool,
    _settings,
)

# 256K 窗口 provider（对齐 kimi/k3-256k 规格）
_K256_JSON = json.dumps(
    {
        "kimi": {
            "base_url": "https://api.kimi.com/coding/v1",
            "api_key_env": "KIMI_API_KEY",
            "models": {
                "k3-256k": {"context": 262144, "thinking": True, "cost_tier": "mid"},
                "k3": {"context": 1000000, "thinking": True, "cost_tier": "mid"},
            },
            "default_model": "k3-256k",
        },
    }
)


def _stuff_history(engine, sid, total_chars: int) -> None:
    """向会话填充指定总量的历史消息（模拟长期对话）."""
    sess = engine.session.load(sid)
    from llm_loop.core.message import Message, MessageSource

    per_msg = 5000
    # 每轮追加 user+assistant 两条，各约 per_msg；旧 helper 按 total/per_msg
    # 循环导致实际载荷约为声明的 2 倍，使大窗口测试错误触发 compact。
    for i in range(total_chars // (per_msg * 2)):
        sess.messages.append(
            Message(role="user", content=f"历史消息{i} " + "x" * (per_msg - 20), source=MessageSource.USER)
        )
        sess.messages.append(
            Message(role="assistant", content=f"历史回答{i} " + "y" * (per_msg - 20), source=MessageSource.USER)
        )
    engine.session.save(sess)


def _received_history_chars(fake) -> int:
    """fake 收到的 messages 总字符数（含 system + 历史）."""
    return sum(len(json.dumps(m, ensure_ascii=False)) for m in fake.calls[-1]["messages"])


def test_legacy_history_anchor_is_reopened_for_current_contract() -> None:
    sess = SimpleNamespace(
        history_anchors={"minimax": 42},
        history_anchor_scopes={},
    )
    assert _anchor_for_current_contract(
        sess,
        provider_id="minimax",
        resolved_label="minimax/MiniMax-M3",
        sess_anchor=42,
        effective_budget=540_000,
    ) == 0
    assert sess.history_anchors["minimax"] == 0


def test_versioned_history_anchor_survives_only_same_or_stricter_contract() -> None:
    def _sess():
        return SimpleNamespace(
            history_anchors={"glm": 37},
            history_anchor_scopes={
                "glm": {
                    "version": 1,
                    "model": "glm/glm-5.3",
                    "effective_budget": 300_000,
                }
            },
        )

    same = _sess()
    assert _anchor_for_current_contract(
        same,
        provider_id="glm",
        resolved_label="glm/glm-5.3",
        sess_anchor=37,
        effective_budget=300_000,
    ) == 37

    stricter = _sess()
    assert _anchor_for_current_contract(
        stricter,
        provider_id="glm",
        resolved_label="glm/glm-5.3",
        sess_anchor=37,
        effective_budget=200_000,
    ) == 37

    expanded = _sess()
    assert _anchor_for_current_contract(
        expanded,
        provider_id="glm",
        resolved_label="glm/glm-5.3",
        sess_anchor=37,
        effective_budget=500_000,
    ) == 0

    switched = _sess()
    assert _anchor_for_current_contract(
        switched,
        provider_id="glm",
        resolved_label="glm/glm-5.3-flash",
        sess_anchor=37,
        effective_budget=300_000,
    ) == 0


def test_engine_clears_legacy_marker_once_on_actual_session_messages(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Compaction-contract migration must mutate durable Session messages, not a copy."""
    monkeypatch.setenv("KIMI_API_KEY", "k")
    settings = _settings(
        tmp_path,
        model_providers_raw=_K256_JSON,
        llm_model="k3-256k",
        history_max_chars=1_000_000,
    )
    fake = _FakeLLMClient("k3")
    pool = _make_pool(settings, fake, cached={"kimi": fake})
    engine = _make_engine(tmp_path, pool, settings)
    sid = engine.session.create()
    sess = engine.session.load(sid)
    sess.model_override = "kimi/k3"
    sess.messages.append(
        Message(
            role="assistant",
            content="legacy-hidden-but-now-fits",
            source=MessageSource.USER,
            metadata={"cache_compacted_for": ["kimi"]},
        )
    )
    engine.session.save(sess)

    registry = pool.registry_snapshot()
    engine._build_llm_messages(  # noqa: SLF001 — regression targets real build state migration
        sess,
        [],
        max_chars=540_000,
        planned_label="kimi/k3",
        registry_snapshot=registry,
    )
    epoch_after_first = engine._run_state().cache_prefix_epoch  # noqa: SLF001
    assert "cache_compacted_for" not in sess.messages[0].metadata
    engine.session.save(sess)
    reloaded = engine.session.load(sid)
    assert "cache_compacted_for" not in reloaded.messages[0].metadata

    engine._build_llm_messages(  # noqa: SLF001
        reloaded,
        [],
        max_chars=540_000,
        planned_label="kimi/k3",
        registry_snapshot=registry,
    )
    assert engine._run_state().cache_prefix_epoch == epoch_after_first  # noqa: SLF001


def test_engine_clears_stale_marker_from_live_tool_when_provider_view_uses_receipt(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Compaction reset must clear canonical tool state even when ingress uses a copy."""
    monkeypatch.setenv("KIMI_API_KEY", "k")
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_RECEIPTS", "1")
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_BATCH_CHARS", "4096")
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_GRACE_GROUPS", "0")
    settings = _settings(
        tmp_path,
        model_providers_raw=_K256_JSON,
        llm_model="k3-256k",
        history_max_chars=1_000_000,
    )
    fake = _FakeLLMClient("k3")
    pool = _make_pool(settings, fake, cached={"kimi": fake})
    engine = _make_engine(tmp_path, pool, settings)
    sid = engine.session.create()
    sess = engine.session.load(sid)
    sess.model_override = "kimi/k3"
    sess.messages.extend(
        [
            Message(role="user", content="task", source=MessageSource.USER),
            Message(
                role="assistant",
                content="inspect",
                source=MessageSource.USER,
                tool_calls=[
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "{}"},
                    }
                ],
                metadata={"answer_origin": "model"},
            ),
            Message(
                role="tool",
                content="X" * 5000,
                source=MessageSource.TOOL,
                tool_call_id="c1",
                status=ToolResultStatus.SUCCESS,
                tool_name="read_file",
                metadata={
                    "cache_compacted_for": ["kimi"],
                    "recoverability_status": "recorded",
                    "evidence_ref": "evidence://v1/stale-copy",
                    "evidence_representation": "full",
                    "evidence_projection_complete": True,
                },
            ),
            Message(
                role="assistant",
                content="continue",
                source=MessageSource.USER,
                metadata={"answer_origin": "model"},
            ),
        ]
    )
    engine.session.save(sess)

    registry = pool.registry_snapshot()
    engine._build_llm_messages(  # noqa: SLF001
        sess,
        [],
        max_chars=540_000,
        planned_label="kimi/k3",
        registry_snapshot=registry,
    )
    epoch_after_first = engine._run_state().cache_prefix_epoch  # noqa: SLF001
    assert "cache_compacted_for" not in sess.messages[2].metadata

    engine._build_llm_messages(  # noqa: SLF001
        sess,
        [],
        max_chars=540_000,
        planned_label="kimi/k3",
        registry_snapshot=registry,
    )
    assert engine._run_state().cache_prefix_epoch == epoch_after_first  # noqa: SLF001


def test_small_window_model_compresses_proactively(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """256K 窗模型: 30万字符历史超过物理输入预算 → 主动压缩（M54 核心）."""
    monkeypatch.setenv("KIMI_API_KEY", "k")
    settings = _settings(tmp_path, model_providers_raw=_K256_JSON, llm_model="k3-256k", history_max_chars=1_000_000)  # EVO-20260814: 显式 1M 模拟生产环境
    fake = _FakeLLMClient("k3-256k")
    pool = _make_pool(settings, fake)
    engine = _make_engine(tmp_path, pool, settings)

    sid = engine.session.create()
    _stuff_history(engine, sid, 300000)  # 30万字符 > ~14.2万模型历史预算, < 全局 1M

    result = engine.run(sid, "新问题")
    assert result.final_answer.startswith("默认回答")  # 方案B尾行适配（EVO-20260819-2254e3b4，展示层不参与断言）
    # 全局 1M 预算不会压缩 30万；256K 模型窗口预算约 14.2万字符，应压缩。
    received = _received_history_chars(fake)
    assert received < 290000, f"应压缩到预算内, 实际 {received}"


def test_large_window_model_calibrated_budget(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """1M 窗模型 (kimi/k3): 30万字符历史不应被旧 50% 启发式提前压缩。

    当前 model_budget = 1M×0.9×0.6 = 540K 字符（无额外 provider 输出预算），
    30万字符仍有明确物理 headroom，应保持 append-only 稳定前缀而不是 compact。
    本测试只验证物理模型预算校准；不存在独立的 K-fold 语义策略。
    """
    monkeypatch.setenv("KIMI_API_KEY", "k")
    settings = _settings(
        tmp_path,
        model_providers_raw=_K256_JSON,
        llm_model="k3-256k",
        history_max_chars=1_000_000,  # T2(2026-08-14): 显式 1M 全局预算，保持"窗口公式生效"测试意图
    )
    fake = _FakeLLMClient("k3-256k")
    pool = _make_pool(settings, fake, cached={"kimi": fake})
    engine = _make_engine(tmp_path, pool, settings)

    sid = engine.session.create()
    # 会话 override 到 1M 窗模型
    sess = engine.session.load(sid)
    sess.model_override = "kimi/k3"
    engine.session.save(sess)
    _stuff_history(engine, sid, 300000)

    result = engine.run(sid, "新问题")
    assert result.final_answer.startswith("默认回答")  # 方案B尾行适配
    received = _received_history_chars(fake)
    assert received > 290000, f"1M 窗仍有 headroom 时不应提前压缩 30万字符, 实际 {received}"


def test_effective_budget_math(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """预算计算: min(全局, context×0.9×chars_per_token)，再预留显式输出容量。"""
    monkeypatch.setenv("KIMI_API_KEY", "k")
    settings = _settings(
        tmp_path,
        model_providers_raw=_K256_JSON,
        llm_model="k3-256k",
        history_max_chars=1_000_000,  # T2(2026-08-14): 显式 1M 全局预算，保持 min(全局, 窗口) 公式语义
    )
    fake = _FakeLLMClient("k3-256k")
    pool = _make_pool(settings, fake)
    engine = _make_engine(tmp_path, pool, settings)

    # 256K 窗: 262144 × 0.9 × 0.6 = 141557
    assert engine._effective_history_budget("kimi/k3-256k") == 141557
    # 1M 窗: min(1M全局, 1000000×0.9×0.6=540000) = 540000
    assert engine._effective_history_budget("kimi/k3") == 540_000
    # 未知模型（有 pool 且 "/"）→ 8K 保守兜底（M53: 防 4K/8K/32K 小窗口模型超限硬拒绝）
    assert engine._effective_history_budget("ghost/x") == 8000


def test_no_pool_zero_regression(build_test_engine) -> None:
    """无 pool → 全局预算（零回归）."""
    engine, fake = build_test_engine([{"content": "你好"}])
    fake.model = "fake-model"
    engine.llm_pool = None
    assert engine._effective_history_budget("") == engine._runtime_history_budget()


# ── provider 级预算收紧（本地慢模型接入, prefill 随上下文线性涨）──

_LOCAL_JSON = json.dumps(
    {
        "local": {
            "base_url": "http://localhost:1234/v1",
            "api_key_env": "",
            "history_budget_chars": 12000,
            "models": {
                "qwen3.6-27b": {"context": 131072, "thinking": True, "cost_tier": "free"},
                "qwen9b": {"context": 1048576, "thinking": False, "cost_tier": "free"},
            },
            "default_model": "qwen3.6-27b",
        },
        "kimi": {
            "base_url": "https://api.kimi.com/coding/v1",
            "api_key_env": "KIMI_API_KEY",
            "models": {"k3-256k": {"context": 262144, "thinking": True, "cost_tier": "mid"}},
            "default_model": "k3-256k",
        },
    }
)


def test_provider_history_budget_caps_global(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """provider history_budget_chars 优先于全局预算（本地慢模型核心修复）.

    local 配 12000 → 即使模型窗口 1M（qwen9b）也按 12000 收紧;
    未配置的 provider（kimi）保持 min(全局, 窗口) 语义（零回归）。
    """
    monkeypatch.setenv("KIMI_API_KEY", "k")
    settings = _settings(
        tmp_path,
        model_providers_raw=_LOCAL_JSON,
        llm_model="qwen3.6-27b",
        history_max_chars=1_000_000,
    )
    fake = _FakeLLMClient("qwen3.6-27b")
    pool = _make_pool(settings, fake)
    engine = _make_engine(tmp_path, pool, settings)

    # local 27B: provider 显式 12000 仍优先于更大的模型窗口预算
    assert engine._effective_history_budget("local/qwen3.6-27b") == 12000
    # local 9B（1M 窗）: provider 预算仍压到 12000（窗口大 ≠ prefill 快）
    assert engine._effective_history_budget("local/qwen9b") == 12000
    # 未配置 provider cap: 只受模型物理窗口预算约束
    assert engine._effective_history_budget("kimi/k3-256k") == 141557


def test_local_tool_round_has_no_hidden_budget_clamp(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A prior tool call must not silently turn a 12K explicit/provider cap into 8K/4K."""
    monkeypatch.setenv("KIMI_API_KEY", "k")
    settings = _settings(
        tmp_path,
        model_providers_raw=_LOCAL_JSON,
        llm_model="qwen3.6-27b",
        history_max_chars=1_000_000,
    )
    fake = _FakeLLMClient("qwen3.6-27b")
    pool = _make_pool(settings, fake)
    engine = _make_engine(tmp_path, pool, settings)
    sid = engine.session.create()
    sess = engine.session.load(sid)
    sess.messages.append(
        Message(
            role="assistant",
            content="",
            source=MessageSource.USER,
            tool_calls=[ToolCall(id="t1", name="read_file", arguments={"path": "x"})],
        )
    )

    plan = engine._attempt_executor.plan(None, sess, pool.registry_snapshot())

    assert plan.planned_label == "local/qwen3.6-27b"
    assert plan.effective_budget == 12_000
    assert set(vars(plan)) == {"planned_label", "effective_budget"}


def test_model_output_budget_reserve_overrides_provider_output_default(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """物理输入预算必须预留实际路由模型的输出上限，而不是 provider 兄弟模型默认值。"""
    providers = json.dumps(
        {
            "glm": {
                "base_url": "https://x.invalid/v1",
                "api_key_env": "",
                "max_tokens": 65536,
                "models": {
                    "glm-5.3": {"context": 1_000_000, "max_tokens": 131072},
                    "glm-5.3-flash": {"context": 1_000_000},
                },
                "default_model": "glm-5.3",
            }
        }
    )
    settings = _settings(
        tmp_path,
        model_providers_raw=providers,
        llm_model="glm-5.3",
        history_max_chars=1_000_000,
    )
    fake = _FakeLLMClient("glm-5.3")
    pool = _make_pool(settings, fake)
    engine = _make_engine(tmp_path, pool, settings)

    # 5.3: (1,000,000 - 131,072) * 0.6 = 521,356 chars.
    # Flash inherits provider 65,536; 90% safety margin (900K) is tighter => 540K chars.
    assert engine._effective_history_budget("glm/glm-5.3") == 521356
    assert engine._effective_history_budget("glm/glm-5.3-flash") == 540000


def test_provider_history_budget_compresses_sent_context(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """端到端: local provider 下 30万字符历史 → 实际发送被压到 12000 预算附近."""
    monkeypatch.setenv("KIMI_API_KEY", "k")
    settings = _settings(
        tmp_path,
        model_providers_raw=_LOCAL_JSON,
        llm_model="qwen3.6-27b",
        history_max_chars=1_000_000,
    )
    fake = _FakeLLMClient("qwen3.6-27b")
    pool = _make_pool(settings, fake)
    engine = _make_engine(tmp_path, pool, settings)

    sid = engine.session.create()
    _stuff_history(engine, sid, 300000)

    result = engine.run(sid, "新问题")
    assert result.final_answer.startswith("默认回答")  # 方案B尾行适配
    received = _received_history_chars(fake)
    # 发送载荷压到 ~12K 预算量级（含 system prompt）, 远小于全局 1M
    assert received < 40000, f"应压到 provider 预算内, 实际 {received}"
