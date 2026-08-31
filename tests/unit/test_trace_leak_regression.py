"""T4: 轨迹泄漏回归防线（fixture 常驻四条件断言）——tasks 5.1, spec 5.4.2.

实证锚点（会话 004976ea msg #280/#290, 2026-08-31 取证）:
- #280/#290 同为 role=user、origin_layer=user_instruction、program_origin=False
- 内容逐字节一致（同一外部轨迹快照重复注入）→ sha1 回归锚点
- 特征命中: 思考过程标记 + 工具命令组合（trace_signature）

防线覆盖: 写入期 guard（enforce/observe/downgrade）+ build 期 detector
（特征兜底 warn + 恒等式失真剔除）双路径。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.trace_leak import leak_events
from llm_loop.core.trace_leak.trace_signature import (
    content_matches_signature,
    current_signature_mode,
)
from tests.unit.test_channel_whitelist_guard import GUARD_MODE_ENV

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "trace_leak"
EVIDENCE_SHA1 = "a0db25ab077af9ca07253d3f4bc0d3f0dde59f0c"


def _load_payload(name: str) -> dict:
    line = (FIXTURE_DIR / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()[0]
    return json.loads(line)["payload"]


def _evidence_message() -> Message:
    """实证 #280 消息还原（原 metadata 形态: 无凭据的 user_instruction）."""
    p = _load_payload("leak-280-msg")
    return Message(
        role="user",
        content=p["content"],
        source=MessageSource.USER,
        metadata=dict(p.get("metadata") or {}),
    )


class _CaptureSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def __call__(self, session_id: str, kind: str, payload: dict) -> None:
        self.events.append((kind, payload))

    def kinds(self) -> list[str]:
        return [k for k, _ in self.events]


@pytest.fixture()
def sink(monkeypatch: pytest.MonkeyPatch) -> _CaptureSink:
    s = _CaptureSink()
    monkeypatch.setattr(leak_events, "_DEFAULT_SINK", s, raising=False)
    return s


class TestFixtureAnchors:
    """fixture 完整性锚点（变更需同步根因报告）."""

    def test_280_290_byte_identical(self) -> None:
        p280, p290 = _load_payload("leak-280-msg"), _load_payload("leak-290-msg")
        assert p280["content"] == p290["content"]
        assert p280["role"] == p290["role"] == "user"
        assert p280["metadata"] == {
            "origin_layer": "user_instruction",
            "program_origin": False,
        }

    def test_content_sha1_stable(self) -> None:
        content = _load_payload("leak-280-msg")["content"]
        assert hashlib.sha1(content.encode()).hexdigest() == EVIDENCE_SHA1

    def test_evidence_hits_trace_signature(self) -> None:
        assert content_matches_signature(_load_payload("leak-280-msg")["content"])

    def test_replay_pair_fixture_loads(self) -> None:
        p = _load_payload("isomorphic-replay-pair")
        assert p["role"] == "assistant" and p.get("tool_calls")


class TestWritePathGuard:
    """写入期通道守卫（实证样本回放）."""

    def _sess(self) -> SimpleNamespace:
        return SimpleNamespace(session_id="s-regression", messages=[])

    def test_enforce_denies_evidence_write(self, sink: _CaptureSink, monkeypatch: pytest.MonkeyPatch) -> None:
        from llm_loop.core.trace_leak.user_ingress_guard import GuardAction, guard_user_write

        monkeypatch.setenv(GUARD_MODE_ENV, "enforce")
        verdict = guard_user_write(self._sess(), _evidence_message(), None)
        assert verdict.action is GuardAction.DENY
        assert leak_events.LEAK_CHANNEL_DENIED in sink.kinds()

    def test_observe_allows_with_overreach_event(self, sink: _CaptureSink, monkeypatch: pytest.MonkeyPatch) -> None:
        from llm_loop.core.trace_leak.user_ingress_guard import GuardAction, guard_user_write

        monkeypatch.setenv(GUARD_MODE_ENV, "observe")
        verdict = guard_user_write(self._sess(), _evidence_message(), None)
        assert verdict.action is GuardAction.ALLOW
        assert leak_events.LEAK_CHANNEL_OVERREACH in sink.kinds()

    def test_downgrade_relabels_truthfully(self, sink: _CaptureSink, monkeypatch: pytest.MonkeyPatch) -> None:
        from llm_loop.core.trace_leak.user_ingress_guard import GuardAction, guard_user_write

        monkeypatch.setenv(GUARD_MODE_ENV, "downgrade")
        verdict = guard_user_write(self._sess(), _evidence_message(), None)
        assert verdict.action is GuardAction.DOWNGRADE
        md = verdict.message.metadata
        assert md.get("origin_layer") == "program_recovery"
        assert md.get("program_origin") is True
        assert leak_events.LEAK_DOWNGRADED in sink.kinds()


class TestBuildPathDetector:
    """build 期检测（实证样本 + 恒等式失真）."""

    def test_signature_mode_default_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LFL_TRACE_SIGNATURE", raising=False)
        assert current_signature_mode() == "off"

    def test_evidence_detected_via_signature_scan(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from llm_loop.core.trace_leak.trace_signature import trace_signature_scan

        monkeypatch.setenv("LFL_TRACE_SIGNATURE", "warn")
        msg = _evidence_message()
        v = trace_signature_scan(
            msg.content, has_human_credential=bool(msg.metadata.get("ingress_channel"))
        )
        assert v.hit and v.mode == "warn"

    def test_human_credential_never_intercepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from llm_loop.core.trace_leak.trace_signature import trace_signature_scan

        monkeypatch.setenv("LFL_TRACE_SIGNATURE", "warn")
        v = trace_signature_scan(
            _evidence_message().content, has_human_credential=True
        )
        assert not v.hit

    def test_mislabel_variant_excluded_at_build(self, sink: _CaptureSink) -> None:
        from llm_loop.core.trace_leak.leak_detector import detect_leak_at_build

        content = _load_payload("leak-280-msg")["content"]
        bad = Message(
            role="user",
            content=content,
            source=MessageSource.USER,
            metadata={"origin_layer": "user_instruction", "program_origin": True},
        )
        findings = detect_leak_at_build([bad], session_id="s-regression")
        assert [f.action for f in findings] == ["downgrade_to_appendix"]
        assert leak_events.LEAK_MISLABEL_DETECTED in sink.kinds()
