"""T3: build 期泄漏检测（α/β 挂载 + 特征兜底 + fail-open）——tasks 4.5, spec 5.4.

覆盖:
- detect_leak_at_build 纯函数: 恒等式失真/通道越权/存量缺键放行/非 user 零影响
- α 挂载 wire: 失真 user 消息剔除 provider 视图 + 降级附录进聚合槽（会话存储零改动）
- 特征兜底 warn: 特征命中仅告警不改视图; 人类凭据豁免
- fail-open: 检测层异常放行（消息不丢 + detector_fault 事件）
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.trace_leak import leak_events
from llm_loop.core.trace_leak.leak_detector import detect_leak_at_build

SIGNATURE_ENV = "LFL_TRACE_SIGNATURE"


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


def _user(content: str, metadata: dict | None = None) -> Message:
    return Message(role="user", content=content, source=MessageSource.USER, metadata=metadata)


MISLABEL_MD = {"origin_layer": "user_instruction", "program_origin": True}


class TestDetectPureFunction:
    """纯 metadata 单遍判定（无 IO）."""

    def test_mislabel_finding_downgrades(self, sink: _CaptureSink) -> None:
        bad = _user("失真轨迹内容", dict(MISLABEL_MD))
        ok = _user("正常用户输入", {"origin_layer": "user_instruction", "program_origin": False})
        findings = detect_leak_at_build([ok, bad], session_id="s1")
        assert len(findings) == 1
        f = findings[0]
        assert f.kind == leak_events.LEAK_MISLABEL_DETECTED
        assert f.message_ref == 1
        assert f.action == "downgrade_to_appendix"
        assert leak_events.LEAK_MISLABEL_DETECTED in sink.kinds()

    def test_current_ingress_without_credential_observed(self, sink: _CaptureSink) -> None:
        cur = _user("当前轮无凭据", {"origin_layer": "user_instruction", "program_origin": False})
        findings = detect_leak_at_build([cur], session_id="s1", current_ingress=cur)
        assert [f.kind for f in findings] == [leak_events.LEAK_CHANNEL_OVERREACH]
        assert findings[0].action == "observe_event_only"
        assert leak_events.LEAK_CHANNEL_OVERREACH in sink.kinds()

    def test_current_ingress_with_credential_passes(self, sink: _CaptureSink) -> None:
        cur = _user(
            "带凭据的通道消息",
            {
                "origin_layer": "user_instruction",
                "program_origin": False,
                "ingress_channel": "feishu",
            },
        )
        assert detect_leak_at_build([cur], session_id="s1", current_ingress=cur) == []

    def test_legacy_missing_keys_fail_open(self, sink: _CaptureSink) -> None:
        legacy = _user("存量旧消息")
        assert detect_leak_at_build([legacy], session_id="s1") == []
        assert sink.kinds() == []

    def test_non_user_roles_skipped(self, sink: _CaptureSink) -> None:
        assistant = Message(role="assistant", content="回答", source=MessageSource.SYSTEM)
        tool = Message(role="tool", content="结果", source=MessageSource.SYSTEM, tool_call_id="t1")
        assert detect_leak_at_build([assistant, tool], session_id="s1") == []

    def test_detector_fault_fail_open(
        self, sink: _CaptureSink, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(messages, **_kw):
            raise RuntimeError("检测层内部故障")

        monkeypatch.setattr("llm_loop.core.trace_leak.leak_detector._detect_inner", _boom)
        bad = _user("失真", dict(MISLABEL_MD))
        assert detect_leak_at_build([bad], session_id="s1") == []
        assert leak_events.LEAK_DETECTOR_FAULT in sink.kinds()


def _wire_engine(tmp_path: Path):
    from tests.unit.test_injection_fingerprint import _engine

    engine, sess = _engine(tmp_path)
    return engine, sess


class TestBuildAlphaMount:
    """α 挂载: R4 过滤后、投影进 provider 视图前的剔除与降级（wire 层）."""

    def test_mislabel_message_excluded_and_downgraded(
        self, tmp_path: Path, sink: _CaptureSink, monkeypatch
    ) -> None:
        # Quarantine mode may change audit handling, never provider prompt authority.
        monkeypatch.setenv("LFL_LEAK_QUARANTINE", "on")
        engine, sess = _wire_engine(tmp_path)
        leaked = _user("外部agent轨迹原文片段XYZ", dict(MISLABEL_MD))
        sess.messages = [leaked] + list(sess.messages)
        engine._run_state().current_turn_ref = len(sess.messages) - 1

        out = engine._build_llm_messages(sess, [], planned_label="zhipu/glm-5")

        # 1) 失真消息不再以 user 历史原样投影
        assert not any(
            m.get("role") == "user" and str(m.get("content") or "") == leaked.content for m in out
        )
        # 2) Even explicit on rollback cannot turn leaked content into model context.
        downgraded = [
            str(m.get("content") or "")
            for m in out
            if leaked.content[:10] in str(m.get("content") or "")
        ]
        assert downgraded == []
        assert leak_events.LEAK_MISLABEL_DETECTED in sink.kinds()

    def test_session_storage_untouched(self, tmp_path: Path, sink: _CaptureSink) -> None:
        engine, sess = _wire_engine(tmp_path)
        leaked = _user("会话原文不可变", dict(MISLABEL_MD))
        before = len(sess.messages)
        sess.messages = [leaked] + list(sess.messages)
        engine._run_state().current_turn_ref = len(sess.messages) - 1

        engine._build_llm_messages(sess, [], planned_label="zhipu/glm-5")

        assert len(sess.messages) == before + 1
        stored = sess.messages[0]
        assert stored.content == "会话原文不可变"
        assert stored.metadata.get("origin_layer") == "user_instruction"
        assert stored.metadata.get("program_origin") is True  # 原文 metadata 零改动

    def test_detector_crash_fail_open_keeps_view(
        self, tmp_path: Path, sink: _CaptureSink, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine, sess = _wire_engine(tmp_path)
        leaked = _user("故障时也不丢消息", dict(MISLABEL_MD))
        sess.messages = [leaked] + list(sess.messages)
        engine._run_state().current_turn_ref = len(sess.messages) - 1

        def _boom(messages, **_kw):
            raise RuntimeError("挂载点异常")

        monkeypatch.setattr("llm_loop.core.trace_leak.leak_detector._detect_inner", _boom)
        out = engine._build_llm_messages(sess, [], planned_label="zhipu/glm-5")
        # Detector failure must not override the independent program-origin eligibility
        # boundary: explicit contradictory provenance remains provider-invisible.
        assert not any(
            m.get("role") == "user" and str(m.get("content") or "") == leaked.content for m in out
        )
        assert leak_events.LEAK_DETECTOR_FAULT in sink.kinds()


class TestSignatureWarn:
    """特征兜底（默认 off; warn 仅告警）."""

    TRACE_CONTENT = "思考过程\npython3 -c 'print(1)'\n自动 grep -r secret ."

    def test_off_by_default_no_scan(
        self, tmp_path: Path, sink: _CaptureSink, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(SIGNATURE_ENV, raising=False)
        engine, sess = _wire_engine(tmp_path)
        sig = _user(self.TRACE_CONTENT)
        sess.messages = [sig] + list(sess.messages)
        engine._run_state().current_turn_ref = len(sess.messages) - 1

        engine._build_llm_messages(sess, [], planned_label="zhipu/glm-5")
        assert leak_events.LEAK_SIGNATURE_WARNED not in sink.kinds()

    def test_warn_emits_event_keeps_view(
        self, tmp_path: Path, sink: _CaptureSink, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(SIGNATURE_ENV, "warn")
        engine, sess = _wire_engine(tmp_path)
        sig = _user(
            self.TRACE_CONTENT,
            {"origin_layer": "user_instruction", "program_origin": False},
        )
        sess.messages = [sig] + list(sess.messages)
        engine._run_state().current_turn_ref = len(sess.messages) - 1

        out = engine._build_llm_messages(sess, [], planned_label="zhipu/glm-5")

        assert leak_events.LEAK_SIGNATURE_WARNED in sink.kinds()
        # warn 仅告警: 视图不剔除
        assert any(
            m.get("role") == "user" and str(m.get("content") or "") == self.TRACE_CONTENT
            for m in out
        )

    def test_human_credential_exempt(
        self, tmp_path: Path, sink: _CaptureSink, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(SIGNATURE_ENV, "warn")
        engine, sess = _wire_engine(tmp_path)
        cred = _user(
            "思考过程\ngrep something",
            {
                "origin_layer": "user_instruction",
                "program_origin": False,
                "ingress_channel": "feishu",
            },
        )
        sess.messages = [cred] + list(sess.messages)
        engine._run_state().current_turn_ref = len(sess.messages) - 1

        engine._build_llm_messages(sess, [], planned_label="zhipu/glm-5")
        assert leak_events.LEAK_SIGNATURE_WARNED not in sink.kinds()
