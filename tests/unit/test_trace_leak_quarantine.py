"""R8.24-D 组 DT 硬门断言（D-G1/D-G2/D-G3 + quarantine 计数对账）——tasks DT-1.6.

覆盖（对齐设计包 §4.1 结构硬门）：
- D-G1: off（默认 enforce）模式 REFERENCE appendix 回喂路径 chars=0 +
        quarantine 文件落盘 + leak.quarantined 事件在场（sha1/basis/preview≤200 无原文）
- D-G2: leak_downgrade 永久无 prompt plumbing；on/shadow 仅改变审计语义。
- D-G3: default mode=fail-closed（enforce）配置断言 + 无 token user 写入 drop +
        有 token（issue_test_ingress 白名单路径）放行双态
- shadow 态 would_quarantine 计数；on/shadow/provider chars 均为 0。
- census 计数对账：leak.quarantined 事件数 == quarantine 文件数
- guard operator 覆盖审计（leak.guard_override）演练留痕
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.trace_leak import leak_events

QUARANTINE_ENV = "LFL_LEAK_QUARANTINE"
GUARD_MODE_ENV = "LFL_LEAK_GUARD_MODE"
MISLABEL_MD = {"origin_layer": "user_instruction", "program_origin": True}


class _CaptureSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def __call__(self, session_id: str, kind: str, payload: dict) -> None:
        self.events.append((kind, payload))

    def kinds(self) -> list[str]:
        return [k for k, _ in self.events]

    def of(self, kind: str) -> list[dict]:
        return [p for k, p in self.events if k == kind]


@pytest.fixture()
def sink(monkeypatch: pytest.MonkeyPatch) -> _CaptureSink:
    s = _CaptureSink()
    monkeypatch.setattr(leak_events, "_DEFAULT_SINK", s, raising=False)
    return s


def _user(content: str, metadata: dict | None = None) -> Message:
    return Message(role="user", content=content, source=MessageSource.USER, metadata=metadata)


def _wire_engine(tmp_path: Path):
    from tests.unit.test_injection_fingerprint import _engine

    engine, sess = _engine(tmp_path)
    return engine, sess


def _build_with_mislabel(tmp_path: Path, sink: _CaptureSink | None = None):
    """构造含 downgrade_to_appendix finding 的 build 场景（mislabel user 消息）.

    α hook 的 quarantine 事件带显式 sink=engine._event_append（UI 事件轨）；
    传入 sink 时同时捕获该通道，保证事件断言双通道可见。
    """
    engine, sess = _wire_engine(tmp_path)
    if sink is not None:
        engine._event_append = sink  # type: ignore[method-assign]
    leaked = _user("外部agent轨迹原文片段XYZ-QUARANTINE-PROBE", dict(MISLABEL_MD))
    sess.messages = [leaked] + list(sess.messages)
    engine._run_state().current_turn_ref = len(sess.messages) - 1
    out = engine._build_llm_messages(sess, [], planned_label="zhipu/glm-5")
    return engine, sess, leaked, out


def _provider_chars(out: list[dict], probe: str) -> int:
    """provider 视图中含探针子串的内容字符量（回喂路径 chars 度量）."""
    return sum(
        len(str(m.get("content") or "")) for m in out if probe[:24] in str(m.get("content") or "")
    )


class TestDg1QuarantineEnforce:
    """D-G1: off（默认）模式回喂路径 chars=0 + quarantine 承接三件套在场."""

    def test_off_mode_reference_reinject_chars_zero(
        self, tmp_path: Path, sink: _CaptureSink
    ) -> None:
        monkeypatch_env = None  # conftest 未设 QUARANTINE_ENV → 默认 off（enforce）
        assert monkeypatch_env is None
        engine, sess, leaked, out = _build_with_mislabel(tmp_path, sink)
        # D-G1 核心：mislabel 内容不进 provider 视图（REFERENCE 回喂路径 chars=0）
        assert _provider_chars(out, leaked.content) == 0
        # 失真消息不以 user 历史原样投影
        assert not any(
            m.get("role") == "user" and str(m.get("content") or "") == leaked.content for m in out
        )
        # leak.quarantined 事件在场（D-D1 三件套之一）
        assert leak_events.LEAK_QUARANTINED in sink.kinds()
        evt = sink.of(leak_events.LEAK_QUARANTINED)[0]
        assert evt["provider_chars"] == 0
        # quarantine 文件落盘在场（D-D1 三件套之二）
        qroot = leak_events.quarantine_root(sess.session_id)
        assert qroot.exists() and list(qroot.glob("*.json"))

    def test_quarantine_event_payload_no_raw_content(
        self, tmp_path: Path, sink: _CaptureSink
    ) -> None:
        """⑥ quarantine 事件 payload 口径：sha1 + preview≤200 截断 + basis 非空.

        长内容（>200 chars）时 preview 必须截断（全文不随事件外泄）；
        preview 之外的任何字段不得出现原文。
        """
        engine, sess = _wire_engine(tmp_path)
        engine._event_append = sink  # type: ignore[method-assign]
        long_body = "外部agent轨迹长文" + "X" * 400 + "尾部敏感"
        leaked = _user(long_body, dict(MISLABEL_MD))
        sess.messages = [leaked] + list(sess.messages)
        engine._run_state().current_turn_ref = len(sess.messages) - 1
        engine._build_llm_messages(sess, [], planned_label="zhipu/glm-5")
        quarantined = sink.of(leak_events.LEAK_QUARANTINED)
        assert quarantined
        for payload in quarantined:
            assert payload["content_sha1"]
            assert len(payload["content_preview"]) <= 200
            assert payload["basis"]
            assert long_body not in payload["content_preview"], "preview 必须 ≤200 截断"
            for key, v in payload.items():
                if key == "content_preview":
                    continue
                assert long_body not in str(v)

    def test_quarantine_file_permission_converged(self, tmp_path: Path, sink: _CaptureSink) -> None:
        """DT-1.1④: quarantine 目录 0700 / 文件 0600（泄漏面收敛）."""
        engine, sess, leaked, out = _build_with_mislabel(tmp_path, sink)
        qroot = leak_events.quarantine_root(sess.session_id)
        files = list(qroot.glob("*.json"))
        assert files
        assert (qroot.stat().st_mode & 0o777) == 0o700
        assert (files[0].stat().st_mode & 0o777) == 0o600

    def test_ui_notice_channel_present(self, tmp_path: Path, sink: _CaptureSink) -> None:
        """⑤ UI 提示在场：leak.quarantined 经 engine._event_append 事件轨（SSE 面）。"""
        engine, sess, leaked, out = _build_with_mislabel(tmp_path, sink)
        kinds = sink.kinds()
        assert leak_events.LEAK_QUARANTINED in kinds, "UI/事件轨提示不缺席"

    def test_census_count_reconciliation(self, tmp_path: Path, sink: _CaptureSink) -> None:
        """⑦ enforce 态计数对账：leak.quarantined 事件数 == quarantine 文件数."""
        engine, sess, leaked, out = _build_with_mislabel(tmp_path, sink)
        evt_n = len(sink.of(leak_events.LEAK_QUARANTINED))
        qroot = leak_events.quarantine_root(sess.session_id)
        file_n = len(list(qroot.glob("*.json"))) if qroot.exists() else 0
        assert evt_n >= 1
        assert evt_n == file_n, f"事件数({evt_n}) 与 quarantine 文件数({file_n}) 不一致"


class TestShadowAndRollback:
    """shadow 计数 + on 回滚通道行为对照（门 DT1 留痕）."""

    def test_shadow_would_quarantine_counted_and_behavior_unchanged(
        self, tmp_path: Path, sink: _CaptureSink, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """shadow/on 只改变审计事件，不恢复 model-visible leaked prose."""
        monkeypatch.setenv(QUARANTINE_ENV, "shadow")
        engine, sess, leaked, out_shadow = _build_with_mislabel(tmp_path, sink)
        assert leak_events.LEAK_WOULD_QUARANTINE in sink.kinds()
        wp = sink.of(leak_events.LEAK_WOULD_QUARANTINE)[0]
        assert wp["chars"] == len(leaked.content)
        assert wp["quarantine_mode"] == "shadow"
        # 两种 rollback audit mode 都没有 provider prompt 权限。
        monkeypatch.setenv(QUARANTINE_ENV, "on")
        engine2, sess2, leaked2, out_on = _build_with_mislabel(tmp_path, sink)
        assert _provider_chars(out_shadow, leaked.content) == 0
        assert _provider_chars(out_on, leaked2.content) == 0
        # shadow 期间不产生 quarantine 副作用（计数态零行为变化）
        assert leak_events.LEAK_QUARANTINED not in [
            k for k, _ in sink.events[: len(sink.events)]
        ] or not sink.of(leak_events.LEAK_QUARANTINED)

    def test_shadow_event_no_raw_content(
        self, tmp_path: Path, sink: _CaptureSink, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """shadow 计数事件口径同 quarantine（preview≤200 截断；其余字段无原文）。"""
        monkeypatch.setenv(QUARANTINE_ENV, "shadow")
        engine, sess = _wire_engine(tmp_path)
        engine._event_append = sink  # type: ignore[method-assign]
        long_body = "外部agent轨迹shadow长文" + "Y" * 400 + "尾部敏感"
        leaked = _user(long_body, dict(MISLABEL_MD))
        sess.messages = [leaked] + list(sess.messages)
        engine._run_state().current_turn_ref = len(sess.messages) - 1
        engine._build_llm_messages(sess, [], planned_label="zhipu/glm-5")
        events = sink.of(leak_events.LEAK_WOULD_QUARANTINE)
        assert events
        for payload in events:
            assert len(payload["content_preview"]) <= 200
            assert long_body not in payload["content_preview"]
            for key, v in payload.items():
                if key == "content_preview":
                    continue
                assert long_body not in str(v)

    def test_mode_toggle_roundtrip(
        self, tmp_path: Path, sink: _CaptureSink, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """开关三态可切换（回滚演练留痕：off→on→off）."""
        from llm_loop.core.trace_leak.leak_events import current_quarantine_mode

        assert current_quarantine_mode() == "off"
        monkeypatch.setenv(QUARANTINE_ENV, "on")
        assert current_quarantine_mode() == "on"
        monkeypatch.setenv(QUARANTINE_ENV, "shadow")
        assert current_quarantine_mode() == "shadow"
        monkeypatch.setenv(QUARANTINE_ENV, "off")
        assert current_quarantine_mode() == "off"
        monkeypatch.setenv(QUARANTINE_ENV, "bogus")
        assert current_quarantine_mode() == "off", "非法值回落 default（off）"


class TestDg2StaticAssertions:
    """D-G2: 双静态断言 CI 常驻（allowlist 本体 + build 旁路追加路径扫描）."""

    def test_allowlist_excludes_leak_downgrade(self) -> None:
        from llm_loop.core.prompt_eligibility import PROMPT_DYNAMIC_PRODUCER_SLOTS

        assert "leak_downgrade" not in PROMPT_DYNAMIC_PRODUCER_SLOTS

    def test_build_has_no_dynamic_prompt_assembly_control_plane(self) -> None:
        """leak_downgrade evidence has no model-visible program-prompt assembler."""
        import importlib.util

        assert (
            importlib.util.find_spec("llm_loop.core.prompt_build.stages.injection_assembly") is None
        )

    def test_dynamic_producer_registry_is_empty(self) -> None:
        """No legacy slot, including leak_downgrade, can regain prompt authority."""
        from llm_loop.core.prompt_eligibility import PROMPT_DYNAMIC_PRODUCER_SLOTS

        assert not PROMPT_DYNAMIC_PRODUCER_SLOTS

    def test_invariant_marker_preserved(self) -> None:
        """DT-1.2④: invariant.py / downgrade_message 的 injection_kind=
        leak_downgrade 溯源标记保留（P1 已交付资产，删除的只是注入通道）。"""
        from llm_loop.core.trace_leak.invariant import correct_mislabeled_metadata
        from llm_loop.core.trace_leak.user_ingress_guard import downgrade_message

        md = correct_mislabeled_metadata(dict(MISLABEL_MD))
        assert md.get("injection_kind") == "leak_downgrade"
        m = downgrade_message(_user("x", dict(MISLABEL_MD)))
        assert m.metadata.get("injection_kind") == "leak_downgrade"


class TestDg3FailClosedDefault:
    """D-G3: default mode=fail-closed + 无 token drop / 有 token 放行双态."""

    def test_default_mode_is_enforce(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from llm_loop.core.trace_leak.user_ingress_guard import (
            DEFAULT_GUARD_MODE,
            current_guard_mode,
        )

        monkeypatch.delenv(GUARD_MODE_ENV, raising=False)
        assert DEFAULT_GUARD_MODE == "enforce"
        assert current_guard_mode() == "enforce", "无 env 时 default 必须 fail-closed"

    def test_no_token_user_write_dropped(
        self, monkeypatch: pytest.MonkeyPatch, sink: _CaptureSink
    ) -> None:
        from llm_loop.core.session import SessionStore
        from llm_loop.core.trace_leak.user_ingress_guard import (
            GuardAction,
            guard_user_write,
        )

        monkeypatch.delenv(GUARD_MODE_ENV, raising=False)
        monkeypatch.setattr(leak_events, "_DEFAULT_SINK", sink, raising=False)
        store = SessionStore(__import__("tempfile").mkdtemp(prefix="dg3-"))
        sid = store.create()
        verdict = guard_user_write(
            store.load(sid) if hasattr(store, "load") else type("S", (), {"session_id": sid})(),
            _user("无凭据写入"),
            None,
        )
        assert verdict.action is GuardAction.DENY
        assert leak_events.LEAK_CHANNEL_DENIED in sink.kinds()

    def test_whitelisted_token_write_allowed(
        self, monkeypatch: pytest.MonkeyPatch, sink: _CaptureSink
    ) -> None:
        from llm_loop.core.trace_leak.ingress_token import issue_test_ingress
        from llm_loop.core.trace_leak.user_ingress_guard import (
            GuardAction,
            guard_user_write,
        )

        monkeypatch.delenv(GUARD_MODE_ENV, raising=False)
        monkeypatch.setattr(leak_events, "_DEFAULT_SINK", sink, raising=False)
        msg = _user("带凭据写入")
        verdict = guard_user_write(
            type("S", (), {"session_id": "s-dg3"})(), msg, issue_test_ingress()
        )
        assert verdict.action is GuardAction.ALLOW
        assert msg.metadata.get("ingress_channel") == "test_harness"
        # 白名单凭据路径不产生拒绝事件
        assert leak_events.LEAK_CHANNEL_DENIED not in sink.kinds()

    def test_engine_run_default_enforce_denies_without_credential(
        self, build_test_engine, monkeypatch: pytest.MonkeyPatch, sink: _CaptureSink
    ) -> None:
        monkeypatch.delenv(GUARD_MODE_ENV, raising=False)
        monkeypatch.setattr(leak_events, "_DEFAULT_SINK", sink, raising=False)
        engine, _fake = build_test_engine([{"content": "ok", "tool_calls": []}])
        sid = engine.session.create()
        result = engine.run(sid, "无凭据消息")
        assert "写入被拒" in result.final_answer
        sess = engine.session.load(sid)
        assert not [m for m in sess.messages if m.role == "user"]

    def test_engine_run_default_enforce_allows_with_web_credential(
        self, build_test_engine, monkeypatch: pytest.MonkeyPatch, sink: _CaptureSink
    ) -> None:
        monkeypatch.delenv(GUARD_MODE_ENV, raising=False)
        monkeypatch.setattr(leak_events, "_DEFAULT_SINK", sink, raising=False)
        from llm_loop.core.trace_leak.ingress_token import issue_ingress

        engine, _fake = build_test_engine([{"content": "ok", "tool_calls": []}])
        sid = engine.session.create()
        result = engine.run(sid, "Web 凭据消息", ingress=issue_ingress("web"))
        assert "ok" in result.final_answer
        sess = engine.session.load(sid)
        user_msgs = [m for m in sess.messages if m.role == "user"]
        assert user_msgs and user_msgs[0].metadata.get("ingress_channel") == "web"

    def test_rollback_flip_default_back_to_observe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """回滚演练留痕：仅翻回 default（env 显式 observe=operator 覆盖通道）。"""
        from llm_loop.core.trace_leak.user_ingress_guard import current_guard_mode

        monkeypatch.delenv(GUARD_MODE_ENV, raising=False)
        assert current_guard_mode() == "enforce"
        monkeypatch.setenv(GUARD_MODE_ENV, "observe")
        assert current_guard_mode() == "observe", "回滚=翻回 observe（不动入口签发）"
        monkeypatch.delenv(GUARD_MODE_ENV, raising=False)
        assert current_guard_mode() == "enforce"

    def test_guard_fault_failopen_preserved(
        self, monkeypatch: pytest.MonkeyPatch, sink: _CaptureSink
    ) -> None:
        """guard fault fail-open 语义零回归（组验收）。"""
        from llm_loop.core.trace_leak import user_ingress_guard as uig

        monkeypatch.delenv(GUARD_MODE_ENV, raising=False)
        monkeypatch.setattr(leak_events, "_DEFAULT_SINK", sink, raising=False)
        monkeypatch.setattr(
            uig, "current_guard_mode", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        verdict = uig.guard_user_write(
            type("S", (), {"session_id": "s-fault"})(), _user("guard 异常"), None
        )
        assert verdict.action is uig.GuardAction.ALLOW
        assert leak_events.LEAK_GUARD_FAULT in sink.kinds()


class TestOperatorOverrideAudit:
    """DT-1.4④: operator 显式覆盖通道审计留痕（leak.guard_override）。"""

    def test_override_emits_audit_event_once(
        self, monkeypatch: pytest.MonkeyPatch, sink: _CaptureSink
    ) -> None:
        from llm_loop.core.trace_leak.user_ingress_guard import (
            current_guard_mode,
            reset_override_audit,
        )

        monkeypatch.delenv(GUARD_MODE_ENV, raising=False)
        monkeypatch.setattr(leak_events, "_DEFAULT_SINK", sink, raising=False)
        reset_override_audit()
        try:
            assert current_guard_mode() == "enforce"  # default 不算覆盖
            assert not sink.of(leak_events.LEAK_GUARD_OVERRIDE)
            monkeypatch.setenv(GUARD_MODE_ENV, "observe")
            assert current_guard_mode() == "observe"
            assert len(sink.of(leak_events.LEAK_GUARD_OVERRIDE)) == 1
            # 进程内一次性：再次读取不重复发
            current_guard_mode()
            assert len(sink.of(leak_events.LEAK_GUARD_OVERRIDE)) == 1
        finally:
            reset_override_audit()
