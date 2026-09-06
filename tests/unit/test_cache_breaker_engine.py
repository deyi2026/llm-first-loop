"""P0 压缩风暴熔断 engine 级集成测试（2026-08-25 规格）.

真实 LoopEngine 全链路: build → 风暴检测 → breaker 冻结 → context_pressure →
逃生轮受控压缩 → 恢复退出。零真实网络（FakeLLM 大输出驱动上下文膨胀）。
"""

from __future__ import annotations

import json
import os
from contextlib import suppress

from .test_model_attribution import (
    _FakeLLMClient,
    _make_engine,
    _make_pool,
    _settings,
)

_DEEPSEEK_JSON = json.dumps(
    {
        "deepseek": {
            "base_url": "https://api.deepseek.com/v1",
            "api_key_env": "DEEPSEEK_API_KEY",
            "models": {
                "deepseek-v4-flash": {"context": 1000000, "thinking": True, "cost_tier": "low"},
            },
            "default_model": "deepseek-v4-flash",
        },
    }
)

_BIG_ANSWER = "y" * 40_000  # 每轮 40K 字符回答 → 上下文快速膨胀


def _mk_engine(
    tmp_path,
    monkeypatch,
    *,
    budget: int = 60_000,
    head_keep_ratio: str = "0",
    audit_file: str = "/tmp/cb_engine_test.jsonl",
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    # 风暴复现: 关 head_keep（build 时读 env）——生产风暴走 downgrade 路径
    # （超预算数倍时 head 放弃保留 → 锚点每轮前移），此处直接对齐该形态。
    monkeypatch.setenv("HEAD_KEEP_RATIO", head_keep_ratio)
    monkeypatch.setenv("HEAD_KEEP_FORCE_RATIO", "0")
    settings = _settings(
        tmp_path,
        model_providers_raw=_DEEPSEEK_JSON,
        llm_model="deepseek/deepseek-v4-flash",
        history_max_chars=budget,
    )
    fake = _FakeLLMClient("deepseek/deepseek-v4-flash")
    pool = _make_pool(settings, fake, cached={"deepseek": fake})
    engine = _make_engine(tmp_path, pool, settings)
    # breaker 参数直接注入 monitor（BREAKER_* 模块常量 import 时冻结，env 无效）
    mon = engine._cache_monitor  # noqa: SLF001
    mon._breaker_trigger_runs = 3
    mon._breaker_cooldown_rounds = 4
    mon._breaker_exit_stable_runs = 2
    mon._breaker_pressure_escape_max = 2
    mon._breaker_audit_file = audit_file  # noqa: SLF001
    with suppress(OSError):
        os.unlink(audit_file)
    return engine, fake


def _read_audit(path: str) -> list[dict]:
    rows = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def _arm_breaker(mon, sid: str, *, budget: int = 60_000) -> None:
    """用真实 monitor API 构造已确认的历史风暴，供 engine 集成层验证冻结/逃生。"""
    model = "deepseek/deepseek-v4-flash"
    # build 通知天然早于当轮 usage record；先放两条历史低命中样本满足共信号。
    mon.record(20_000, 1_000, model_ref=model, session_id=sid)
    mon.record(20_000, 1_000, model_ref=model, session_id=sid)
    for _ in range(3):
        mon.note_build_result(
            compacted=True,
            anchor_moved=True,
            chars_total=int(budget * 0.93),
            budget=budget,
            session_id=sid,
            model_ref=model,
        )
        mon.record(20_000, 1_000, model_ref=model, session_id=sid)
    assert mon.breaker_active_for(sid) is True


def test_breaker_full_chain_storm_to_recovery(tmp_path, monkeypatch):
    """显式 legacy 回滚：风暴 → context_pressure → 逃生压缩 → 恢复退出."""
    # 504641c 后默认行为已收窄为“不因性能水位终止 run”；本测试验证的是
    # 显式兼容回滚路径，因此必须 opt-in 旧阻断语义，不能把旧默认偷带回来。
    monkeypatch.setenv("LFL_BREAKER_PRESSURE_NARROW", "0")
    audit = str(tmp_path / "breaker.jsonl")
    engine, fake = _mk_engine(tmp_path, monkeypatch, audit_file=audit)
    sid = engine.session.create()
    mon = engine._cache_monitor  # noqa: SLF001
    # 新中段压缩正常会在单轮内回落，不应人为制造风暴；这里用 monitor 的真实输入
    # API 重放“历史已确认风暴”，再验证 engine 对 active breaker 的完整接线。
    _arm_breaker(mon, sid)
    events = [e["event"] for e in _read_audit(audit)]
    assert "breaker_enter" in events

    # 阶段2: 冻结期超安全水位 → context_pressure（不提交）
    calls_before = len(fake.calls)
    r = engine.run(sid, "P" * 60_000)
    assert "[上下文压力]" in r.final_answer, "冻结期超水位应被 context_pressure 拦截"
    assert len(fake.calls) == calls_before
    assert mon.breaker_freeze_compression(sid) is True

    # 阶段3: 逃生轮（pressure 达上限）→ 放行一次受控压缩 → 上下文回落
    for i in range(3):
        fake.queue([__import__("llm_loop.llm.client", fromlist=["LLMResponse"]).LLMResponse(
            content="短回答", tool_calls=[], provider="fake",
            prompt_tokens=20000, prompt_cache_hit_tokens=19000,  # 高命中
        )])
        engine.run(sid, f"逃生轮{i}")
    events = [e["event"] for e in _read_audit(audit)]
    assert "escape_armed" in events, "连续 pressure 应武装逃生轮"

    # 阶段4: 受控压缩后上下文低于水位 + 连续稳定 → breaker 退出
    for i in range(6):
        fake.queue([__import__("llm_loop.llm.client", fromlist=["LLMResponse"]).LLMResponse(
            content="短回答", tool_calls=[], provider="fake",
            prompt_tokens=20000, prompt_cache_hit_tokens=19000,
        )])
        engine.run(sid, f"恢复轮{i}")
    events = [e["event"] for e in _read_audit(audit)]
    assert "breaker_exit" in events, "水位达标 + 连续稳定后应退出 breaker"
    assert mon.breaker_active_for(sid) is False


def test_breaker_freeze_prevents_compression(tmp_path, monkeypatch):
    """显式 legacy 回滚下冻结期 build 禁止压缩并由 pressure 阻断."""
    from llm_loop.llm.client import LLMResponse

    monkeypatch.setenv("LFL_BREAKER_PRESSURE_NARROW", "0")

    audit = str(tmp_path / "breaker2.jsonl")
    engine, fake = _mk_engine(tmp_path, monkeypatch, audit_file=audit)
    sid = engine.session.create()
    mon = engine._cache_monitor  # noqa: SLF001
    _arm_breaker(mon, sid)
    assert mon.breaker_freeze_compression(sid) is True, "冻结期应禁止程序压缩"
    # 冻结期超安全水位 → context_pressure 拦截（不调用 LLM——不制造不可恢复前缀）
    calls_before = len(fake.calls)
    fake.queue([LLMResponse(content="ok", tool_calls=[], provider="fake",
                           prompt_tokens=20000, prompt_cache_hit_tokens=1000)])
    r = engine.run(sid, "P" * 60_000)
    assert "[上下文压力]" in r.final_answer
    assert len(fake.calls) == calls_before, "冻结期超水位不应提交 LLM 请求"


def test_no_false_breaker_when_hit_healthy(tmp_path, monkeypatch):
    """结构信号满足但命中率高（渐进折叠/健康态）→ 不误触发 breaker."""
    from llm_loop.llm.client import LLMResponse

    audit = str(tmp_path / "breaker3.jsonl")
    engine, fake = _mk_engine(
        tmp_path, monkeypatch, audit_file=audit, head_keep_ratio="0.15"
    )
    sid = engine.session.create()
    for i in range(8):
        # 每轮 40K 增长（折叠 3 组跟不上）+ 高命中共信号 → 不触发
        fake.queue([LLMResponse(content=_BIG_ANSWER, tool_calls=[], provider="fake",
                               prompt_tokens=20000, prompt_cache_hit_tokens=19000)])
        engine.run(sid, f"第{i}轮")
    mon = engine._cache_monitor  # noqa: SLF001
    assert mon.breaker_active_for(sid) is False, "高命中时不误触发 breaker"
    assert _read_audit(audit) == [], "无 breaker 审计事件"


def test_mid_compaction_marker_survives_event_replay(tmp_path, monkeypatch):
    """真实engine中段折叠后，JSON与event-log replay都保留provider级隐藏状态。"""
    from llm_loop.event_log.replay import replay_session
    from llm_loop.event_log.store import EventStore
    from llm_loop.llm.client import LLMResponse

    audit = str(tmp_path / "breaker-mid.jsonl")
    engine, fake = _mk_engine(
        tmp_path, monkeypatch, audit_file=audit, head_keep_ratio="0.15"
    )
    engine._event_store = EventStore(tmp_path / "event_logs")  # noqa: SLF001
    sid = engine.session.create()
    for i in range(3):
        fake.queue(
            [
                LLMResponse(
                    content=_BIG_ANSWER,
                    tool_calls=[],
                    provider="fake",
                    prompt_tokens=20_000,
                    prompt_cache_hit_tokens=18_000,
                )
            ]
        )
        engine.run(sid, f"中段稳定轮{i}")

    saved = engine.session.load(sid)
    marked_saved = [
        i
        for i, m in enumerate(saved.messages)
        if "deepseek" in ((m.metadata or {}).get("cache_compacted_for") or [])
    ]
    assert marked_saved, "应至少有一条中段消息写入provider折叠标记"

    events = engine._event_store.read(sid)  # noqa: SLF001
    assert any(e.type == "message.cache_compacted" for e in events)
    replayed = replay_session(events)
    marked_replayed = [
        i
        for i, m in enumerate(replayed["messages"])
        if "deepseek" in ((m.get("metadata") or {}).get("cache_compacted_for") or [])
    ]
    assert marked_replayed == marked_saved


def test_telemetry_content_transport_separation(tmp_path, monkeypatch):
    """P1 遥测分层: 正文纯回答 + metadata.cache_health + 返回装饰 + 伪造行剥离."""
    from llm_loop.llm.client import LLMResponse

    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    monkeypatch.setenv("CACHE_HIT_SHOW_IN_ANSWER", "true")
    settings = _settings(
        tmp_path,
        model_providers_raw=_DEEPSEEK_JSON,
        llm_model="deepseek/deepseek-v4-flash",
        history_max_chars=60_000,
        cache_hit_show_in_answer=True,
    )
    fake = _FakeLLMClient("deepseek/deepseek-v4-flash")
    pool = _make_pool(settings, fake, cached={"deepseek": fake})
    engine = _make_engine(tmp_path, pool, settings)
    sid = engine.session.create()
    # 模型回答含伪造遥测行（模仿 8/25 msg[128] 形态）
    forged = (
        "这是回答正文。\n\n"
        "⚡ 缓存命中率 93.6%（近 1 轮，724,096/773,371 tokens；"
        "本模型(deepseek-v4-flash)累计 1 轮 93.6% 724,096/773,371 tokens）"
    )
    fake.queue([LLMResponse(content=forged, tool_calls=[], provider="fake",
                           prompt_tokens=20000, prompt_cache_hit_tokens=19000)])
    r = engine.run(sid, "第一问")
    # 返回（transport 层）: 装饰后含 canonical 遥测，且只含一条 ⚡
    assert r.final_answer.count("⚡ 缓存命中率") == 1, "返回只应有一条 canonical 遥测"
    assert "93.6" not in r.final_answer, "伪造行应被剥离（分母 773,371 为模型编造）"
    # 会话存储: 正文纯回答、无 ⚡ 行、无 93.6
    sess = engine.session.load(sid)
    last = [m for m in sess.messages if m.role == "assistant"][-1]
    assert "缓存命中率" not in (last.content or ""), "正文不应含遥测（纯回答）"
    assert "这是回答正文" in (last.content or "")
    health = (last.metadata or {}).get("cache_health")
    assert isinstance(health, dict) and health.get("note"), "权威遥测应在 metadata.cache_health"
    assert "⚡ 缓存命中率" in health["note"] and "93.6" not in health["note"]


def test_telemetry_metadata_only_change_is_persisted(tmp_path, monkeypatch):
    """正文本来就纯净时，新增 cache_health metadata 也必须单独落盘。"""
    from llm_loop.llm.client import LLMResponse

    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    monkeypatch.setenv("CACHE_HIT_SHOW_IN_ANSWER", "true")
    settings = _settings(
        tmp_path,
        model_providers_raw=_DEEPSEEK_JSON,
        llm_model="deepseek/deepseek-v4-flash",
        history_max_chars=60_000,
        cache_hit_show_in_answer=True,
    )
    fake = _FakeLLMClient("deepseek/deepseek-v4-flash")
    pool = _make_pool(settings, fake, cached={"deepseek": fake})
    engine = _make_engine(tmp_path, pool, settings)
    sid = engine.session.create()
    fake.queue([
        LLMResponse(
            content="这是纯回答正文。",
            tool_calls=[],
            provider="fake",
            prompt_tokens=20_000,
            prompt_cache_hit_tokens=19_000,
        )
    ])

    result = engine.run(sid, "第一问")
    assert result.final_answer.count("⚡ 缓存命中率") == 1

    reloaded = engine.session.load(sid)
    last = [m for m in reloaded.messages if m.role == "assistant"][-1]
    assert last.content == "这是纯回答正文。"
    health = (last.metadata or {}).get("cache_health")
    assert isinstance(health, dict) and "⚡ 缓存命中率" in str(health.get("note", ""))
