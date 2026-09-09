"""Agency-first provider-wire fingerprint.

Historical memory/tip/hotcard/gate program slots are deliberately armable in tests, but
none has automatic prompt authority.  The stable invariant is stronger than the old
"append-only injection" fingerprint: arming, adding, removing, or changing legacy prompt
wrappers must leave the provider wire byte-identical to the naked baseline.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import llm_loop.core.loop.focus as focus_mod
from llm_loop.core.cache_health import GATE_NOTE_CONTENT
from llm_loop.core.loop.hotcard import hotcard_path, write_hotcard
from llm_loop.core.message import Message, MessageSource

_MEMORY_FIX = "记忆检索结果：" + "注" * 220
_TIP_FIX = "经验提示：" + "注" * 220


def _engine(tmp_path: Path):
    os.environ.setdefault("ZHIPU_API_KEY", "k")
    from tests.unit.test_model_attribution import (
        _FakeLLMClient,
        _make_engine,
        _make_pool,
        _settings,
    )

    providers = json.dumps(
        {
            "zhipu": {
                "base_url": "https://api.zhipu.local/v1",
                "api_key_env": "ZHIPU_API_KEY",
                "models": {"glm-5": {"context": 300000, "thinking": True, "cost_tier": "low"}},
                "default_model": "glm-5",
            },
        }
    )
    settings = _settings(
        tmp_path,
        model_providers_raw=providers,
        llm_model="zhipu/glm-5",
        history_max_chars=300_000,
    )
    fake = _FakeLLMClient("zhipu/glm-5")
    pool = _make_pool(settings, fake, cached={"zhipu": fake})
    engine = _make_engine(tmp_path, pool, settings)
    sid = engine.session.create()
    sess = engine.session.load(sid)
    sess.messages.append(
        Message(role="user", content="固定任务：继续当前工作。", source=MessageSource.USER)
    )
    return engine, sess


def _arm_all_slots(
    engine,
    sess,
    *,
    memory: bool = True,
    tip: bool = True,
    durable_hotcard: bool = True,
    tip_extra: int = 0,
    gate_note: bool = True,
):
    tips = []
    if tip:
        tips.append(Message(role="system", content=_TIP_FIX, source=MessageSource.SYSTEM))
        tips += [
            Message(role="system", content=_TIP_FIX + f"#{i}", source=MessageSource.SYSTEM)
            for i in range(tip_extra)
        ]
    engine._tip_tail_messages = tips or None
    if durable_hotcard:
        write_hotcard(
            origin_session="other-session",
            anchor="durable-only-hotcard",
            data_dir=engine.settings.data_dir,
        )
    if gate_note:
        engine._cache_monitor._get_bucket(sess.session_id).gate_note_pending = True
    return (
        [Message(role="system", content=_MEMORY_FIX, source=MessageSource.SYSTEM)] if memory else []
    )


def _build(engine, sess, memory_msgs) -> list[dict]:
    return engine._build_llm_messages(
        sess, memory_msgs, max_chars=200_000, planned_label="zhipu/glm-5"
    )


def _baseline(engine, sess) -> list[dict]:
    engine._tip_tail_messages = None
    return _build(engine, sess, [])


def _assert_prompt_neutral(engine, sess, **arm_kwargs) -> list[dict]:
    base = _baseline(engine, sess)
    memory_msgs = _arm_all_slots(engine, sess, **arm_kwargs)
    armed = _build(engine, sess, memory_msgs)
    assert armed == base
    assert not hasattr(engine._run_state(), "last_build_injections")
    return armed


class TestGoldenFingerprint:
    def test_golden_tail_morphology(self, tmp_path):
        """Golden morphology is naked exact history; old slots add zero provider messages."""
        engine, sess = _engine(tmp_path)
        out = _assert_prompt_neutral(engine, sess)
        assert out[-1]["role"] == "user"
        assert out[-1]["content"] == "固定任务：继续当前工作。"
        assert float(out[-1].get("_message_time_ts") or 0.0) > 0
        wire = "\n".join(str(m.get("content") or "") for m in out)
        for forbidden in ("记忆检索结果", "经验提示", "slot:", "[程序附录", GATE_NOTE_CONTENT):
            assert forbidden not in wire

    def test_registration_matches_tail(self, tmp_path):
        """No automatic provider injection means no InjectedEntry registration."""
        engine, sess = _engine(tmp_path)
        _assert_prompt_neutral(engine, sess)
        assert not hasattr(engine._run_state(), "last_build_injections")

    def test_live_tip_no_memory_tail(self, tmp_path):
        engine, sess = _engine(tmp_path)
        out = _assert_prompt_neutral(engine, sess, memory=False, tip=True)
        wire = "\n".join(str(m.get("content") or "") for m in out)
        assert "经验提示" not in wire and "记忆检索结果" not in wire

    def test_wire_prefix_invariant(self, tmp_path):
        """Armed legacy channels preserve the entire wire, not merely a prefix."""
        engine, sess = _engine(tmp_path)
        base = _baseline(engine, sess)
        memory_msgs = _arm_all_slots(engine, sess)
        full = _build(engine, sess, memory_msgs)
        assert full == base


class TestRedLightMutations:
    def test_slot_added(self, tmp_path):
        engine, sess = _engine(tmp_path)
        _assert_prompt_neutral(engine, sess, tip_extra=3)

    def test_live_slot_removed(self, tmp_path):
        engine, sess = _engine(tmp_path)
        _assert_prompt_neutral(engine, sess, tip=False, memory=False)

    def test_wrap_bypassed(self, tmp_path):
        """The retired prompt assembly stage must not expose wrap_injection at all."""
        assert (
            importlib.util.find_spec("llm_loop.core.prompt_build.stages.injection_cognitive")
            is None
        )
        engine, sess = _engine(tmp_path)
        _assert_prompt_neutral(engine, sess)

    def test_wrap_prefix_text_changed(self, tmp_path, monkeypatch):
        """Changing a legacy wrapper constant cannot change provider wire anymore."""
        engine, sess = _engine(tmp_path)
        base = _baseline(engine, sess)
        monkeypatch.setattr(focus_mod, "_INJECTION_PREFIX", "[legacy-wrapper-mutated]")
        memory_msgs = _arm_all_slots(engine, sess)
        assert _build(engine, sess, memory_msgs) == base

    def test_gate_note_marker_is_observability_only(self, tmp_path):
        engine, sess = _engine(tmp_path)
        out = _assert_prompt_neutral(engine, sess, gate_note=True)
        wire = "\n".join(str(m.get("content", "")) for m in out)
        assert GATE_NOTE_CONTENT not in wire
        assert engine._cache_monitor.take_gate_note(sess.session_id) is False

    def test_durable_hotcard_is_retrievable_only(self, tmp_path):
        engine, sess = _engine(tmp_path)
        out = _assert_prompt_neutral(engine, sess, durable_hotcard=True)
        wire = "\n".join(str(m.get("content", "")) for m in out)
        assert "slot:hotcard" not in wire and "[任务热卡]" not in wire
        card = json.loads(hotcard_path(engine.settings.data_dir).read_text(encoding="utf-8"))
        assert card["consumed"] is False and card["consumed_by"] == ""
