# FR-05 desktop_perceive wait：工具层接线与门控（DESIGN-20261104 §6.5）
"""只断言机制：谓词是否成立、超时是否仍为成功、门控是否照旧。

本机 ax_trusted=false，无法读真实 AX 树；因此这里全部走离线 fake backend，
不产生真实等待以外的任何系统副作用（超时用例最长 ~200ms）。
"""

from __future__ import annotations

import json
from typing import Any

from llm_loop.desktop.models import (
    AX_ERROR_API_DISABLED,
    AxNode,
    AxView,
    PermissionSnapshot,
    PlatformInfo,
    Pt,
    SessionSnapshot,
    Size,
    WindowInfo,
)
from llm_loop.tools.builtin.desktop_perceive import DesktopPerceiveTool


class FakeBackend:
    supported = True

    def __init__(self, *, window: WindowInfo, frames: list[AxView]) -> None:
        self._window = window
        self._frames = frames
        self.calls = 0
        self._perms = PermissionSnapshot(
            ax_trusted=True, screen_capture_granted=True, ax_error=None
        )
        self._session = SessionSnapshot(
            gui_available=True, console_user="tester", screen_locked=False
        )

    def platform_info(self) -> PlatformInfo:
        return PlatformInfo(os="darwin", version="15.0")

    def session_snapshot(self) -> SessionSnapshot:
        return self._session

    def permission_snapshot(self) -> PermissionSnapshot:
        return self._perms

    def capability_snapshot(self) -> dict[str, bool]:
        return {"can_list_windows": True, "can_read_ax": True, "can_capture": True}

    def list_displays(self):
        return []

    def process_info(self):
        return {"pid": 1, "executable": "/usr/bin/python", "python": "3.13"}

    def list_apps(self):
        return []

    def list_windows(self, include_offscreen: bool = False):
        return [self._window]

    def get_window(self, window_id: int):
        return self._window if window_id == self._window.window_id else None

    def ax_snapshot(self, window, depth, node_limit):
        index = min(self.calls, len(self._frames) - 1)
        self.calls += 1
        return self._frames[index]

    def capture_window(self, window):
        return None


def _window(window_id: int = 101, bundle: str = "com.apple.Notes") -> WindowInfo:
    return WindowInfo(
        window_id=window_id,
        pid=4242,
        app="Notes",
        bundle_id=bundle,
        title="笔记",
        title_available=True,
        title_redacted=False,
        bounds_pt=(0.0, 38.0, 1200.0, 800.0),
        layer=0,
        on_screen=True,
        is_foreground=True,
    )


def _node(
    ax_ref: str = "0.1",
    *,
    focused: bool = False,
    enabled: bool | None = True,
    value: str | None = None,
) -> AxNode:
    return AxNode(
        ax_ref=ax_ref,
        role="AXTextField",
        subrole=None,
        title="输入框",
        value=value,
        focused=focused,
        pos_pt=Pt(x=0.0, y=0.0),
        size_pt=Size(w=10.0, h=10.0),
        enabled=enabled,
    )


def _view(*nodes: AxNode) -> AxView:
    return AxView(available=True, root_role="AXWindow", nodes=nodes)


def _tool(backend: FakeBackend) -> DesktopPerceiveTool:
    return DesktopPerceiveTool(backend=backend, session_id_getter=lambda: "sess-wait-test")


def _payload(result) -> dict[str, Any]:
    return json.loads(result.content)


def test_wait_focused_satisfied_on_first_poll():
    """肯定型谓词命中即返回：不要为了"稳定"多等一轮。"""
    backend = FakeBackend(window=_window(), frames=[_view(_node(focused=True))])
    payload = _payload(
        _tool(backend).execute(action="wait", window_id=101, ax_ref="0.1", kind="focused")
    )
    assert payload["ok"] is True
    assert payload["wait"]["satisfied"] is True
    assert payload["wait"]["state"] == "satisfied"
    assert payload["wait"]["polls"] == 1
    assert payload["wait"]["observed"]["focused"] is True


def test_wait_exists_appears_later():
    backend = FakeBackend(
        window=_window(),
        frames=[_view(), _view(), _view(_node())],
    )
    payload = _payload(
        _tool(backend).execute(
            action="wait", window_id=101, ax_ref="0.1", kind="exists", within_ms=2000
        )
    )
    assert payload["wait"]["satisfied"] is True
    assert payload["wait"]["polls"] >= 3


def test_wait_timeout_is_success_not_failure():
    """超时≠对象不存在：必须 ok=True + satisfied=false + 明确引导，否则
    调用方会把"还没加载完"当成"元素不存在"而改走错误分支。"""
    backend = FakeBackend(window=_window(), frames=[_view()])
    payload = _payload(
        _tool(backend).execute(
            action="wait", window_id=101, ax_ref="0.1", kind="exists", within_ms=200
        )
    )
    assert payload["ok"] is True
    assert payload["wait"]["satisfied"] is False
    assert payload["wait"]["state"] == "timeout"
    assert "超时≠对象不存在" in payload["guidance"]


def test_wait_absent_needs_settle():
    backend = FakeBackend(
        window=_window(),
        frames=[_view(_node()), _view(_node()), _view(), _view(), _view(), _view()],
    )
    payload = _payload(
        _tool(backend).execute(
            action="wait",
            window_id=101,
            ax_ref="0.1",
            kind="absent",
            settle_ms=100,
            within_ms=2000,
        )
    )
    assert payload["wait"]["satisfied"] is True
    assert payload["wait"]["settle_ms"] == 100


def test_wait_value_contains():
    backend = FakeBackend(window=_window(), frames=[_view(_node(value="同步完成 3/3"))])
    payload = _payload(
        _tool(backend).execute(
            action="wait",
            window_id=101,
            ax_ref="0.1",
            kind="value_contains",
            value="3/3",
        )
    )
    assert payload["wait"]["satisfied"] is True


def test_wait_rejects_missing_ax_ref():
    backend = FakeBackend(window=_window(), frames=[_view()])
    content = _tool(backend).execute(action="wait", window_id=101, kind="exists").content
    assert "ax_ref 必填" in content
    assert backend.calls == 0


def test_wait_rejects_unknown_kind_and_lists_supported():
    backend = FakeBackend(window=_window(), frames=[_view()])
    content = _tool(backend).execute(
        action="wait", window_id=101, ax_ref="0.1", kind="checked"
    ).content
    assert "checked/selected 暂不支持" in content
    assert backend.calls == 0


def test_wait_rejects_value_on_boolean_kind():
    backend = FakeBackend(window=_window(), frames=[_view()])
    content = _tool(backend).execute(
        action="wait", window_id=101, ax_ref="0.1", kind="focused", value="x"
    ).content
    assert "fields_mismatch" in content


def test_wait_rejects_absent_with_negative_expected():
    backend = FakeBackend(window=_window(), frames=[_view()])
    content = _tool(backend).execute(
        action="wait", window_id=101, ax_ref="0.1", kind="absent", expected=False
    ).content
    assert "kind=absent 不接受 expected=false" in content


def test_wait_clamps_within_ms_to_max():
    backend = FakeBackend(window=_window(), frames=[_view(_node(focused=True))])
    payload = _payload(
        _tool(backend).execute(
            action="wait", window_id=101, ax_ref="0.1", kind="focused", within_ms=999999
        )
    )
    assert payload["wait"]["within_ms"] == 60000


def test_wait_respects_privacy_core_list():
    """wait 每轮都读 AX，必须和 snapshot 走同一道 D8 门，否则是感知侧信道。"""
    backend = FakeBackend(window=_window(bundle="com.1password.1password"), frames=[_view()])
    payload = _payload(
        _tool(backend).execute(action="wait", window_id=101, ax_ref="0.1", kind="exists")
    )
    assert payload["ok"] is False
    assert payload["error_code"] == "privacy_blocked"
    assert backend.calls == 0


def test_wait_reports_ax_unavailable_as_degraded():
    backend = FakeBackend(
        window=_window(),
        frames=[
            AxView(available=False, failure="ax_unavailable", ax_error=AX_ERROR_API_DISABLED)
        ],
    )
    payload = _payload(
        _tool(backend).execute(
            action="wait", window_id=101, ax_ref="0.1", kind="exists", within_ms=100
        )
    )
    assert payload["ok"] is True
    assert payload["wait"]["satisfied"] is False
    assert "ax_unavailable" in payload["degraded"]


def test_wait_unknown_window_is_window_not_found():
    backend = FakeBackend(window=_window(), frames=[_view()])
    payload = _payload(
        _tool(backend).execute(action="wait", window_id=999, ax_ref="0.1", kind="exists")
    )
    assert payload["ok"] is False
    assert payload["error_code"] == "window_not_found"



def test_wait_all_unavailable_is_unavailable_state_with_scope_v11():
    """D-01：全程 AX 不可用 → state=unavailable（不是 timeout）；否定谓词回执
    携带 scope.coverage=unknown；引导语明确"不可解释为否定"。"""
    backend = FakeBackend(
        window=_window(),
        frames=[
            AxView(available=False, failure="ax_unavailable", ax_error=AX_ERROR_API_DISABLED)
        ],
    )
    payload = _payload(
        _tool(backend).execute(
            action="wait", window_id=101, ax_ref="0.1", kind="absent", within_ms=100
        )
    )
    assert payload["ok"] is True
    assert payload["wait"]["satisfied"] is False
    assert payload["wait"]["state"] == "unavailable"
    assert payload["wait"]["scope"]["coverage"] == "unknown"
    assert "不可解释为否定" in payload["guidance"]


def test_wait_absent_scope_full_when_view_complete_v11():
    """D-01：可用且未截断的视图=全覆盖；absent 满足时 scope.coverage=full。"""
    backend = FakeBackend(window=_window(), frames=[_view()])
    payload = _payload(
        _tool(backend).execute(
            action="wait", window_id=101, ax_ref="0.1", kind="absent", settle_ms=50
        )
    )
    assert payload["wait"]["satisfied"] is True
    assert payload["wait"]["scope"]["coverage"] == "full"
