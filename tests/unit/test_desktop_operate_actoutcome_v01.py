# D-02 投递/影响/验证三段拆分（M1 TASK-15377274-004，DESIGN v1.1 §5.3/§8 T-04/T-05）
"""红→绿契约：基线 7ae768519 上逐条失败；修复后全绿。

- 回读不一致（写入已发生但未确认）：dispatch_state=dispatched +
  verification=failed(readback_mismatch)；applied 不得再一刀切 False（None=不可判定）。
- post 观测异常不得把已投递动作改写成"从未发生"（T-05）：applied=True +
  effect_state=unknown。
- not_dispatched（解析失败/拒绝投递）：applied=False 语义保留。
- §5.8：unknown/不可判定在任何序列化边界不折叠为 false（applied=null）。
"""

from __future__ import annotations

import itertools
import json

from llm_loop.core.message import ToolCall
from llm_loop.desktop import macos_actuate
from llm_loop.desktop.backend_macos import MacOSDesktopBackend
from llm_loop.desktop.models import (
    ActOutcome,
    AxNode,
    AxView,
    BoundsPt,
    DesktopErrorCode,
    PermissionSnapshot,
    PlatformInfo,
    SessionSnapshot,
    WindowInfo,
)
from llm_loop.tools.builtin.desktop_operate import DesktopOperateTool
from llm_loop.tools.registry import ToolRegistry


def _node(ax_ref: str, role: str = "AXButton", title: str | None = None,
          value: str | None = None) -> AxNode:
    return AxNode(ax_ref=ax_ref, role=role, subrole=None, title=title, value=value,
                  focused=False, pos_pt=None, size_pt=None, enabled=True)


def _view(*nodes: AxNode) -> AxView:
    return AxView(available=True, root_role="AXWindow", nodes=nodes, binding="title_exact")


DEFAULT_VIEW = _view(
    _node("0", "AXWindow", "某文档"),
    _node("0.0", "AXButton", "新建"),
    _node("0.1", "AXTextArea", "正文", value=""),
)


def _window(window_id=101, pid=96579, app="Google Chrome", bundle_id="com.google.Chrome",
            title="某文档 - Google Chrome") -> WindowInfo:
    return WindowInfo(
        window_id=window_id, pid=pid, app=app, bundle_id=bundle_id,
        title=title, title_available=True, title_redacted=False,
        bounds_pt=BoundsPt(0.0, 38.0, 1512.0, 877.0), layer=0, on_screen=True,
        is_foreground=True,
    )


class FakeOutcomeBackend:
    """离线替身：act_set_value 返回可配置结果；ax_snapshot 可在指定次数后抛异常。"""

    supported = True

    def __init__(self, *, set_value_outcome: ActOutcome, post_snapshot_raises_at=None):
        self.windows = [_window()]
        self._view = DEFAULT_VIEW
        self.set_value_outcome = set_value_outcome
        self.act_calls: list[dict] = []
        self.snapshot_calls = 0
        self._raise_at = post_snapshot_raises_at

    def platform_info(self) -> PlatformInfo:
        return PlatformInfo(os="darwin", version="15.0")

    def session_snapshot(self) -> SessionSnapshot:
        return SessionSnapshot(gui_available=True, console_user="tester", screen_locked=False)

    def permission_snapshot(self) -> PermissionSnapshot:
        return PermissionSnapshot(ax_trusted=True, screen_capture_granted=True, ax_error=None)

    def list_windows(self, include_offscreen: bool = False):
        return [w for w in self.windows if include_offscreen or w.on_screen]

    def get_window(self, window_id: int):
        return next((w for w in self.windows if w.window_id == int(window_id)), None)

    def ax_snapshot(self, window, depth, node_limit):
        self.snapshot_calls += 1
        if self._raise_at is not None and self.snapshot_calls >= self._raise_at:
            raise RuntimeError("post-observation-boom")
        return self._view

    def hid_idle_ms(self):
        return 120_000

    def frontmost_app_bundle(self):
        return "com.google.Chrome"

    def ax_probe(self, pid: int):
        return 0

    def act_set_value(self, window, ax_ref, text):
        self.act_calls.append({"do": "type", "ax_ref": ax_ref, "text": text})
        return self.set_value_outcome

    def act_press(self, window, ax_ref):
        self.act_calls.append({"do": "click", "ax_ref": ax_ref})
        return ActOutcome(ok=True)

    def act_scroll(self, window, signed_lines):
        self.act_calls.append({"do": "scroll", "signed_lines": signed_lines})
        return ActOutcome(ok=True)

    def act_key(self, keycode, flags):
        self.act_calls.append({"do": "press_key", "keycode": keycode, "flags": flags})
        return ActOutcome(ok=True)

    def act_click_point(self, x_pt, y_pt):
        self.act_calls.append({"do": "click_point", "x": x_pt, "y": y_pt})
        return ActOutcome(ok=True)

    def act_scroll_into_view(self, window, ax_ref):
        self.act_calls.append({"do": "scroll_into_view", "ax_ref": ax_ref})
        return ActOutcome(ok=True)


_IDS = itertools.count()


def _runner(backend, audit_rows=None):
    """同一工具实例上的真实派发（dry 令牌与 apply 必须共享同一令牌库）。"""
    tool = DesktopOperateTool(
        backend=backend,
        session_id_getter=lambda: "sess-d02-test",
        writes_enabled=True,
        audit_sink=(audit_rows.append if audit_rows is not None else None),
    )
    reg = ToolRegistry()
    reg.register(tool)

    def run(**kwargs) -> dict:
        result = reg.execute(
            ToolCall(id=f"d02-{next(_IDS)}", name="desktop_operate", arguments=kwargs)
        )
        return json.loads(result.content)

    return run, reg


def _type_kwargs(text: str, **extra):
    return {"do": "type", "window_id": 101, "target": {"ax_ref": "0.1"},
            "text": text, **extra}


# ── backend 层：回读不一致的三段语义 ─────────────────────────────────

def test_t04_backend_readback_mismatch_is_dispatched_unverified(monkeypatch):
    class _FakeEl:
        def release(self) -> None:
            return None

    monkeypatch.setattr(macos_actuate, "resolve_element_by_axref",
                        lambda window, ax_ref: (_FakeEl(), None))
    monkeypatch.setattr(macos_actuate, "ax_set_value", lambda el, text: 0)
    monkeypatch.setattr(macos_actuate, "ax_read_value_string",
                        lambda el: "DIFFERENT-READBACK")
    outcome = MacOSDesktopBackend().act_set_value(_window(), "0.1", "SECRET-TEXT")
    assert outcome.ok is False and outcome.verified is False
    assert outcome.dispatch_state == "dispatched"  # AX 写入已发生
    assert outcome.effect_state == "unknown"
    assert outcome.verification_state == "failed"
    assert outcome.verification_reason == "readback_mismatch"


def test_t04_backend_readback_match_is_confirmed(monkeypatch):
    class _FakeEl:
        def release(self) -> None:
            return None

    monkeypatch.setattr(macos_actuate, "resolve_element_by_axref",
                        lambda window, ax_ref: (_FakeEl(), None))
    monkeypatch.setattr(macos_actuate, "ax_set_value", lambda el, text: 0)
    monkeypatch.setattr(macos_actuate, "ax_read_value_string", lambda el: "SAME")
    outcome = MacOSDesktopBackend().act_set_value(_window(), "0.1", "SAME")
    assert outcome.ok is True and outcome.verified is True
    assert outcome.dispatch_state == "dispatched"
    assert outcome.effect_state == "confirmed"
    assert outcome.verification_state == "passed"


# ── 工具层：T-04 回执不得把"已投递未确认"写成 applied=false ───────────

def _mismatch_outcome() -> ActOutcome:
    return ActOutcome(
        ok=False,
        error=DesktopErrorCode.BACKEND_ERROR,
        detail="AX 写入后回读不一致（写入已发生但结果未确认）",
        ax_error=None,
        verified=False,
        dispatch_state="dispatched",
        effect_state="unknown",
        verification_state="failed",
        verification_reason="readback_mismatch",
    )


def test_t04_tool_mismatch_receipt_dispatched_applied_null():
    backend = FakeOutcomeBackend(set_value_outcome=_mismatch_outcome())
    rows: list[dict] = []
    run, _reg = _runner(backend, rows)
    dry = run(**_type_kwargs("你好", dry_run=True))
    payload = run(**_type_kwargs("你好", dry_run=False, confirm_token=dry["confirm_token"]))
    assert payload["ok"] is False
    assert payload["applied"] is None  # 不可判定，不再一刀切 False（§5.3/§5.8）
    assert payload["dispatch_state"] == "dispatched"
    assert payload["effect_state"] == "unknown"
    assert payload["verification"]["state"] == "failed"
    assert payload["verification"]["reason"] == "readback_mismatch"
    assert payload["recovery"]["action"] == "observe_target"
    assert backend.act_calls and backend.act_calls[0]["text"] == "你好"
    row = rows[-1]
    assert row["applied"] is None and row["dispatch_state"] == "dispatched"
    assert row["verification_state"] == "failed"


def test_t04_tool_not_dispatched_keeps_applied_false():
    """解析失败（ax_ref 死引用）：根本没投 → applied=False 语义保留。"""
    outcome = ActOutcome(
        ok=False, error=DesktopErrorCode.AX_REF_NOT_FOUND,
        detail="ax_ref 在当前 AX 树中不存在（目标已变化）", ax_error=None,
        verified=False, dispatch_state="not_dispatched",
    )
    backend = FakeOutcomeBackend(set_value_outcome=outcome)
    run, _reg = _runner(backend)
    dry = run(**_type_kwargs("x", dry_run=True))
    payload = run(**_type_kwargs("x", dry_run=False, confirm_token=dry["confirm_token"]))
    assert payload["applied"] is False
    assert payload["dispatch_state"] == "not_dispatched"
    assert payload["verification"]["state"] == "not_requested"


# ── 工具层：T-05 post 观测异常不得改写已投递动作 ─────────────────────

def test_t05_post_observation_failure_preserves_delivery_evidence():
    """投递成功后 post snapshot 抛异常：applied=True、effect_state=unknown、
    post_sha256 缺席（不可观察），不再是 backend_error"从未发生"。"""
    backend = FakeOutcomeBackend(
        set_value_outcome=ActOutcome(
            ok=True, error=None, detail=None, ax_error=None, verified=True,
            dispatch_state="dispatched", effect_state="confirmed",
            verification_state="passed",
        ),
        post_snapshot_raises_at=4,  # dry 扫描/world 重绑/目标重解析各 1 次，post=4 抛
    )
    rows: list[dict] = []
    run, _reg = _runner(backend, rows)
    dry = run(**_type_kwargs("hi", dry_run=True))
    payload = run(**_type_kwargs("hi", dry_run=False, confirm_token=dry["confirm_token"]))
    assert payload["ok"] is True
    assert payload["applied"] is True
    assert payload["dispatch_state"] == "dispatched"
    assert payload["effect_state"] == "unknown"
    assert payload.get("post_sha256") is None
    assert backend.act_calls and backend.act_calls[0]["text"] == "hi"
    row = rows[-1]
    assert row["applied"] is True and row["effect_state"] == "unknown"


# ── 成功路径三段字段 + §5.8 序列化 ───────────────────────────────────

def test_success_receipt_carries_three_stage_fields():
    backend = FakeOutcomeBackend(
        set_value_outcome=ActOutcome(
            ok=True, error=None, detail=None, ax_error=None, verified=True,
            dispatch_state="dispatched", effect_state="confirmed",
            verification_state="passed",
        ),
    )
    run, _reg = _runner(backend)
    dry = run(**_type_kwargs("ok", dry_run=True))
    payload = run(**_type_kwargs("ok", dry_run=False, confirm_token=dry["confirm_token"]))
    assert payload["applied"] is True
    assert payload["dispatch_state"] == "dispatched"
    assert payload["effect_state"] == "confirmed"
    assert payload["verification"]["state"] == "passed"
    assert payload["verified"] is True  # 旧字段保留


def test_mismatch_receipt_serializes_null_not_false():
    """§5.8：不可判定序列化为 null，不得折叠为 false。"""
    backend = FakeOutcomeBackend(set_value_outcome=_mismatch_outcome())
    run, reg = _runner(backend)
    dry = run(**_type_kwargs("s", dry_run=True))
    raw = reg.execute(ToolCall(
        id="d02-raw", name="desktop_operate",
        arguments=_type_kwargs("s", dry_run=False, confirm_token=dry["confirm_token"]),
    )).content
    assert '"applied": null' in raw
    assert '"applied": false' not in raw
