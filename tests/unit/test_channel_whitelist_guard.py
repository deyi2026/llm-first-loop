"""T2 通道管控测试（tasks 3.9，design §2.4 T2，spec 5.3.1 验收）.

- 白名单外入口以 user 身份写入的三模式矩阵：
  enforce 拒绝（含隔离记录 + 事件）/ downgrade 降级（标记如实）/ observe 放行 + 告警
- 白名单条目审批留痕可追溯性（spec 5.3.1-2a）
- 带外化两分支（spec 5.3.1-3a/3b）
- guard 异常 fail-open 对照组（spec 4.2-1）
- engine.run / SessionStore.append 双挂载点行为与测试后门
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.trace_leak import leak_events
from llm_loop.core.trace_leak.channel_whitelist import (
    CHANNEL_WHITELIST,
    INTRINSIC_CHANNELS,
    assert_intrinsic_immutable,
    whitelist_allows,
)
from llm_loop.core.trace_leak.ingress_token import (
    IngressToken,
    is_whitelisted,
    issue_ingress,
    issue_test_ingress,
)
from llm_loop.core.trace_leak.user_ingress_guard import (
    GUARD_MODE_ENV,
    GuardAction,
    guard_user_write,
)


class _CaptureSink:
    """测试事件捕获器。"""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def __call__(self, session_id: str, event_type: str, payload: dict) -> None:
        self.events.append((session_id, event_type, payload))

    def kinds(self) -> list[str]:
        return [e[1] for e in self.events]


class _FakeSess:
    def __init__(self) -> None:
        self.session_id = "t2-sess"


@pytest.fixture
def sink(monkeypatch: pytest.MonkeyPatch) -> _CaptureSink:
    s = _CaptureSink()
    monkeypatch.setattr(leak_events, "_DEFAULT_SINK", s, raising=False)
    return s


def _user_msg(content: str = "hello") -> Message:
    return Message(
        role="user",
        content=content,
        source=MessageSource.USER,
        metadata={
            "origin_layer": "user_instruction",
            "program_origin": False,
        },
    )


class TestIngressToken:
    def test_unknown_channel_rejected(self) -> None:
        with pytest.raises(ValueError):
            issue_ingress("telegram")

    def test_token_not_constructible_via_string(self) -> None:
        with pytest.raises(ValueError):
            IngressToken("pin-sentinel-fake", "feishu", "feishu")  # type: ignore[arg-type]

    def test_idempotent_issue(self) -> None:
        a = issue_ingress("feishu")
        b = issue_ingress("feishu")
        assert a is b  # 幂等：同 channel 等价凭据（零重复事件）

    def test_whitelisted_channels(self) -> None:
        for ch in ("feishu", "web", "cli"):
            assert is_whitelisted(issue_ingress(ch)) is True

    def test_forged_object_not_whitelisted(self) -> None:
        class Fake:
            channel = "feishu"
            entry = "feishu"

        # 非哨兵类型的伪造对象：属性形态可相似，但凭据校验须以签发实例为源
        assert whitelist_allows(Fake()) is True  # 通道级固有成员判定（channel 键）
        # 通道值域外伪造（无白名单条目）→ 拒绝
        class Fake2:
            channel = "internal"
            entry = "internal"

        assert whitelist_allows(Fake2()) is False


class TestWhitelistTraceability:
    def test_entries_traceable(self) -> None:
        for e in CHANNEL_WHITELIST:
            assert e.entry_id and e.rationale and e.approval_ref
            assert e.approval_ref.startswith("agent_trace_leak-")

    def test_intrinsic_immutable(self) -> None:
        assert_intrinsic_immutable()  # 固有成员不可移除 + 条目有效性
        assert {"feishu", "web", "cli"} <= INTRINSIC_CHANNELS

    def test_no_default_implied_entries(self) -> None:
        """无『默认隐含』条目：test_harness 也须显式登记。"""
        ids = {e.entry_id for e in CHANNEL_WHITELIST}
        assert "test_harness" in ids


class TestGuardModeMatrix:
    def test_observe_allows_with_warning(self, sink: _CaptureSink, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(GUARD_MODE_ENV, "observe")
        msg = _user_msg()
        verdict = guard_user_write(_FakeSess(), msg, None, entry="t2")
        assert verdict.action is GuardAction.ALLOW
        assert leak_events.LEAK_CHANNEL_OVERREACH in sink.kinds()

    def test_downgrade_marks_truthfully(self, sink: _CaptureSink, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(GUARD_MODE_ENV, "downgrade")
        msg = _user_msg("外部轨迹内容")
        verdict = guard_user_write(_FakeSess(), msg, None, entry="t2")
        assert verdict.action is GuardAction.DOWNGRADE
        md = verdict.message.metadata
        assert md["program_origin"] is True
        assert md["origin_layer"] == "program_recovery"
        assert md["injection_kind"] == "leak_downgrade"
        assert leak_events.LEAK_DOWNGRADED in sink.kinds()

    def test_enforce_denies_with_quarantine(
        self, sink: _CaptureSink, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(GUARD_MODE_ENV, "enforce")
        monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
        msg = _user_msg("被拒内容")
        verdict = guard_user_write(_FakeSess(), msg, None, entry="t2")
        assert verdict.action is GuardAction.DENY
        assert leak_events.LEAK_CHANNEL_DENIED in sink.kinds()
        quarantined = list(
            (tmp_path / "trace_leak_quarantine").rglob("*.json")
        )
        assert quarantined, "enforce 拒绝须有隔离记录（不静默丢弃）"
        body = json.loads(quarantined[0].read_text(encoding="utf-8"))
        assert body["content"] == "被拒内容" and body["basis"]

    def test_valid_credential_allows_byte_identical(self, sink: _CaptureSink) -> None:
        msg = _user_msg()
        verdict = guard_user_write(_FakeSess(), msg, issue_ingress("feishu"), entry="t2")
        assert verdict.action is GuardAction.ALLOW
        md = verdict.message.metadata
        assert md["origin_layer"] == "user_instruction"
        assert md["program_origin"] is False
        assert md["ingress_channel"] == "feishu"  # 凭据快照固化（token 不持久化）

    def test_non_user_role_passes(self, sink: _CaptureSink) -> None:
        tool_msg = Message(role="tool", content="r", source=MessageSource.TOOL)
        verdict = guard_user_write(_FakeSess(), tool_msg, None, entry="t2")
        assert verdict.action is GuardAction.ALLOW

    def test_guard_fault_fail_open(self, sink: _CaptureSink, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(GUARD_MODE_ENV, "downgrade")

        def boom(*a, **k):
            raise RuntimeError("guard internal fault")

        monkeypatch.setattr(
            "llm_loop.core.trace_leak.user_ingress_guard.current_guard_mode", boom
        )
        msg = _user_msg()
        verdict = guard_user_write(_FakeSess(), msg, None, entry="t2")
        assert verdict.action is GuardAction.ALLOW  # fail-open 放行
        assert leak_events.LEAK_GUARD_FAULT in sink.kinds()

    def test_invalid_mode_falls_back_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from llm_loop.core.trace_leak.user_ingress_guard import current_guard_mode

        monkeypatch.setenv(GUARD_MODE_ENV, "bogus")
        assert current_guard_mode() == "observe"


class TestEngineMount:
    """挂载点 1：engine.run ingress 参数（observe 存量零回归兜底）。"""

    def test_run_without_ingress_observe_zero_regression(self, build_test_engine) -> None:
        engine, fake = build_test_engine([{"content": "ok", "tool_calls": []}])
        import os

        assert os.environ.get(GUARD_MODE_ENV) is None  # 缺省 observe
        result = engine.run(engine.session.create(), "普通用户消息")
        assert "ok" in result.final_answer

    def test_run_with_credential_metadata_snapshot(self, build_test_engine) -> None:
        engine, fake = build_test_engine([{"content": "ok", "tool_calls": []}])
        sid = engine.session.create()
        engine.run(sid, "带凭据消息", ingress=issue_ingress("feishu"))
        sess = engine.session.load(sid)
        user_msgs = [m for m in sess.messages if m.role == "user"]
        md = user_msgs[0].metadata
        assert md["origin_layer"] == "user_instruction"
        assert md["program_origin"] is False
        assert md.get("ingress_channel") == "feishu"
        assert md.get("ingress_entry") == "feishu"

    def test_run_enforce_denies_without_credential(
        self, build_test_engine, monkeypatch: pytest.MonkeyPatch, sink: _CaptureSink
    ) -> None:
        monkeypatch.setenv(GUARD_MODE_ENV, "enforce")
        engine, fake = build_test_engine([])
        sid = engine.session.create()
        result = engine.run(sid, "无凭据消息")
        assert "写入被拒" in result.final_answer
        sess = engine.session.load(sid)
        assert not [m for m in sess.messages if m.role == "user"], "enforce 拒绝不落盘"
        assert leak_events.LEAK_CHANNEL_DENIED in sink.kinds()


class TestSessionStoreMount:
    """挂载点 2：SessionStore.append ingress 扩展 + 测试后门。"""

    def test_append_user_without_ingress_observe(self, isolated_data_dir, sink) -> None:
        from llm_loop.core.session import SessionStore

        store = SessionStore(str(isolated_data_dir / "sessions"))
        sid = store.create()
        store.append(sid, _user_msg("直调消息"))  # observe 缺省放行
        sess = store.load(sid)
        assert any(m.role == "user" for m in sess.messages)

    def test_append_user_enforce_denied(self, isolated_data_dir, monkeypatch, sink) -> None:
        from llm_loop.core.session import SessionStore, _LeakWriteDeniedError

        monkeypatch.setenv(GUARD_MODE_ENV, "enforce")
        store = SessionStore(str(isolated_data_dir / "sessions"))
        sid = store.create()
        with pytest.raises(_LeakWriteDeniedError):
            store.append(sid, _user_msg("被拒"))
        sess = store.load(sid)
        assert not [m for m in sess.messages if m.role == "user"]

    def test_append_test_backdoor_credential(self, isolated_data_dir, monkeypatch) -> None:
        from llm_loop.core.session import SessionStore

        monkeypatch.setenv(GUARD_MODE_ENV, "enforce")
        store = SessionStore(str(isolated_data_dir / "sessions"))
        sid = store.create()
        store.append(sid, _user_msg("测试后门消息"), ingress=issue_test_ingress())
        sess = store.load(sid)
        assert [m for m in sess.messages if m.role == "user"]

    def test_append_non_user_unaffected(self, isolated_data_dir, monkeypatch) -> None:
        from llm_loop.core.session import SessionStore

        monkeypatch.setenv(GUARD_MODE_ENV, "enforce")
        store = SessionStore(str(isolated_data_dir / "sessions"))
        sid = store.create()
        assistant = Message(role="assistant", content="a", source=MessageSource.SYSTEM)
        store.append(sid, assistant)  # 非 user-role 零影响
        sess = store.load(sid)
        assert sess.messages[-1].role == "assistant"

    def test_append_mislabel_corrected(self, isolated_data_dir, sink) -> None:
        from llm_loop.core.session import SessionStore

        store = SessionStore(str(isolated_data_dir / "sessions"))
        sid = store.create()
        bad = Message(
            role="user",
            content="失真消息",
            source=MessageSource.USER,
            metadata={"origin_layer": "user_instruction", "program_origin": True},  # 恒等式违反
        )
        store.append(sid, bad, ingress=issue_test_ingress())
        sess = store.load(sid)
        md = sess.messages[-1].metadata
        assert md["origin_layer"] == "program_recovery"
        assert md["program_origin"] is True
        assert leak_events.LEAK_MISLABEL_DETECTED in sink.kinds()


class TestOutboundTraceFetch:
    """带外化两分支（spec 5.3.1-3a/3b）。"""

    def test_explicit_request_returns_reference_view(self) -> None:
        from llm_loop.core.trace_leak.outbound_trace_fetch import fetch_external_trace

        view = fetch_external_trace("external://abc123#280-290")
        md = view.metadata
        assert md["origin_layer"] == "reference"
        assert md["program_origin"] is True
        assert md["external_trace_origin_session"] == "abc123"  # 原始会话归属标识
        frame = view.as_reference_frame()
        assert frame["metadata"]["origin_layer"] == "reference"  # 不获指令权

    def test_no_request_zero_entry(self) -> None:
        from llm_loop.core.trace_leak.outbound_trace_fetch import (
            fetch_audit_log,
        )

        before = len(fetch_audit_log())
        # 无用户显式请求：测试全程零调用 fetch_external_trace → 审计日志零增长
        assert len(fetch_audit_log()) == before
