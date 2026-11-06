# D-03 分页预算语义一致性 + subtree 定向续读
# (LFL_Computer_Browser_Audit_Requirements_Design_2026-11-06 §3.3 FR-03 / §405-410 M2 批次)
"""验收口径（对齐审计原话）：
- 「页宽不应改变同一源的可达性」：同一棵树不同 node_limit 累计可达节点数一致
- 「不能发出必定被拒绝的游标」：预算停止时 next_cursor=None + stop_reason/coverage
- 「提供明确可续的源或定向读取能力」：snapshot 支持 subtree=<ax_ref>，全局 ref 可寻址
- truncated 时 recovery 指向可调用恢复路径，不再暗示『加过滤总能恢复』
"""

from __future__ import annotations

import json
from typing import Any

from llm_loop.desktop.models import (
    AxNode,
    AxView,
    PermissionSnapshot,
    PlatformInfo,
    Pt,
    SessionSnapshot,
    Size,
    WindowInfo,
)
from llm_loop.desktop.paging import decode_cursor, encode_cursor, paginate, tree_fingerprint
from llm_loop.tools.builtin.desktop_perceive import DesktopPerceiveTool

WINDOW_ID = 101


class FakeBackend:
    supported = True

    def __init__(self, *, windows: list[WindowInfo] | None = None, ax_view: AxView | None = None,
                 subtree_view: AxView | None = None) -> None:
        self.windows = list(windows or [])
        self._ax_view = ax_view
        self._subtree_view = subtree_view
        self.ax_calls: list[dict[str, Any]] = []
        self._perms = PermissionSnapshot(ax_trusted=True, screen_capture_granted=True, ax_error=None)
        self._session = SessionSnapshot(gui_available=True, console_user="tester", screen_locked=False)

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
        return list(self.windows)

    def get_window(self, window_id: int):
        for window in self.windows:
            if window.window_id == window_id:
                return window
        return None

    def ax_snapshot(self, window, depth, node_limit, subtree=None):
        call: dict[str, Any] = {"window_id": window.window_id, "depth": depth,
                                "node_limit": node_limit}
        if subtree is not None:
            call["subtree"] = subtree
        self.ax_calls.append(call)
        if subtree is not None:
            if self._subtree_view is None:
                return AxView(available=False, failure="ax_ref_not_found")
            return self._subtree_view
        if self._ax_view is None:
            return AxView(available=False, failure="ax_window_unbound")
        return self._ax_view

    def capture_window(self, window):
        return None


def _window(window_id: int = WINDOW_ID) -> WindowInfo:
    return WindowInfo(
        window_id=window_id, pid=4242, app="Notes", bundle_id="com.apple.Notes",
        title="笔记", title_available=True, title_redacted=False,
        bounds_pt=(0.0, 38.0, 1200.0, 800.0), layer=0, on_screen=True, is_foreground=True,
    )


def _nodes(count: int, *, prefix: str = "0") -> tuple[AxNode, ...]:
    return tuple(
        AxNode(
            ax_ref=f"{prefix}.{index}", role="AXButton", subrole=None,
            title=f"节点{index}", value=None, focused=False,
            pos_pt=Pt(x=float(index), y=float(index)), size_pt=Size(w=10.0, h=10.0),
        )
        for index in range(count)
    )


def _tool(backend: FakeBackend) -> DesktopPerceiveTool:
    return DesktopPerceiveTool(backend=backend, session_id_getter=lambda: "sess-d03-test")


def _payload(result) -> dict[str, Any]:
    return json.loads(result.content)


# ── 纯分页层：total_cap 语义 ────────────────────────────────────────────
def _chain(nodes, page_limit: int, total_cap: int | None):
    cursor = None
    pages = []
    for _ in range(64):
        page = paginate(nodes, window_id=WINDOW_ID, depth=3, cursor=cursor,
                        page_limit=page_limit, total_cap=total_cap)
        pages.append(page)
        if page.next_cursor is None:
            return pages
        cursor = page.next_cursor
    raise AssertionError("64 页未收敛")


def test_pure_cap_width_invariance_and_no_dead_cursor():
    """800 节点、cap=600：页宽 200 与 500 累计都恰读到 600，末页 stop_reason=budget，
    链中发出的每个游标 decode 后 offset 均 < 600（不会发出必被拒的游标）。"""
    nodes = _nodes(800)
    for width in (200, 500):
        pages = _chain(nodes, width, 600)
        served = sum(len(p.nodes) for p in pages)
        assert served == 600, f"width={width} served={served}"
        last = pages[-1]
        assert last.next_cursor is None
        assert last.stop_reason == "budget"
        assert last.remaining > 0
        for page in pages[:-1]:
            decoded = decode_cursor(page.next_cursor)
            assert decoded.offset < 600


def test_pure_cap_partial_last_page():
    """页宽 500、cap 600：第二页只服务 100 个节点即预算停止（不是整页 500）。"""
    pages = _chain(_nodes(800), 500, 600)
    assert [len(p.nodes) for p in pages] == [500, 100]


def test_pure_cap_none_keeps_legacy_semantics():
    """默认 total_cap=None 保持旧行为：800 节点页宽 500 两页读全（回归护栏）。"""
    pages = _chain(_nodes(800), 500, None)
    assert sum(len(p.nodes) for p in pages) == 800
    assert pages[-1].stop_reason is None
    assert pages[-1].next_cursor is None


def test_pure_cap_smaller_than_page():
    """cap=4、页宽 3：先 3 后 1，预算停；树不足 cap 时正常 complete。"""
    pages = _chain(_nodes(10), 3, 4)
    assert [len(p.nodes) for p in pages] == [3, 1]
    assert pages[-1].stop_reason == "budget"
    done = _chain(_nodes(3), 3, 4)
    assert done[-1].stop_reason is None


# ── 工具层回执：预算停止不发死游标 ─────────────────────────────────────
def test_tool_budget_stop_receipt_no_dead_cursor():
    backend = FakeBackend(windows=[_window()], ax_view=AxView(
        available=True, root_role="AXWindow", nodes=_nodes(800)))
    tool = _tool(backend)
    cursor = None
    total_seen = 0
    for round_index in range(8):
        kwargs: dict[str, Any] = {"action": "snapshot", "window_id": WINDOW_ID, "node_limit": 200}
        if cursor is not None:
            kwargs["node_cursor"] = cursor
        payload = _payload(tool.execute(**kwargs))
        assert payload["ok"] is True, f"round {round_index} 被拒：{payload}"
        page = payload["ax"]["page"]
        total_seen += len(payload["ax"]["nodes"])
        if page["next_cursor"] is None:
            assert page["stop_reason"] == "budget"
            assert page["coverage"] == {"served": 600, "total": 800}
            assert "subtree" in page["stop_hint"]
            break
        cursor = page["next_cursor"]
    else:
        raise AssertionError("8 轮未终止（仍在发游标？）")
    assert total_seen == 600


def test_tool_width_invariance_at_receipt_level():
    """同一树 node_limit=500：500+100=600 停，与 200 宽一致（页宽不改可达性）。"""
    backend = FakeBackend(windows=[_window()], ax_view=AxView(
        available=True, root_role="AXWindow", nodes=_nodes(800)))
    tool = _tool(backend)
    first = _payload(tool.execute(action="snapshot", window_id=WINDOW_ID, node_limit=500))
    assert len(first["ax"]["nodes"]) == 500
    second = _payload(tool.execute(action="snapshot", window_id=WINDOW_ID, node_limit=500,
                                   node_cursor=first["ax"]["page"]["next_cursor"]))
    assert len(second["ax"]["nodes"]) == 100
    assert second["ax"]["page"]["next_cursor"] is None
    assert second["ax"]["page"]["stop_reason"] == "budget"


def test_tool_crafted_cursor_beyond_cap_still_rejected():
    """手造 offset=600 的游标（合法链路不再产生）：确定性 page_budget_exhausted。"""
    from llm_loop.desktop.paging import PageCursor

    backend = FakeBackend(windows=[_window()], ax_view=AxView(
        available=True, root_role="AXWindow", nodes=_nodes(800)))
    fp = tree_fingerprint(WINDOW_ID, 3, _nodes(800))
    cursor = encode_cursor(PageCursor(
        window_id=WINDOW_ID, depth=3, offset=600, total=800, tree_fp=fp))
    payload = _payload(_tool(backend).execute(
        action="snapshot", window_id=WINDOW_ID, node_limit=200, node_cursor=cursor))
    assert payload["ok"] is False
    assert payload["error_code"] == "page_budget_exhausted"


# ── subtree 定向续读 ───────────────────────────────────────────────────
def test_tool_subtree_read_global_refs_and_call_shape():
    subtree_nodes = _nodes(30, prefix="0.1")
    backend = FakeBackend(
        windows=[_window()],
        ax_view=AxView(available=True, root_role="AXWindow", nodes=_nodes(800), truncated=True),
        subtree_view=AxView(available=True, root_role="AXGroup", nodes=subtree_nodes),
    )
    tool = _tool(backend)
    payload = _payload(tool.execute(action="snapshot", window_id=WINDOW_ID, subtree="0.1"))
    assert payload["ok"] is True
    assert payload["ax"]["page"]["subtree_root"] == "0.1"
    assert payload["ax"]["nodes"][0]["ax_ref"] == "0.1.0"
    assert backend.ax_calls[-1].get("subtree") == "0.1"


def test_tool_subtree_invalid_ref_rejected():
    backend = FakeBackend(windows=[_window()], ax_view=AxView(
        available=True, root_role="AXWindow", nodes=_nodes(3)))
    result = _tool(backend).execute(action="snapshot", window_id=WINDOW_ID, subtree="abc")
    # invalid_args 走 _fail 纯文本回执（非 JSON envelope）
    assert "invalid_args" in str(result.content)


def test_tool_subtree_not_found_maps_ax_ref_not_found():
    backend = FakeBackend(windows=[_window()])  # subtree_view=None → ax_ref_not_found
    payload = _payload(_tool(backend).execute(action="snapshot", window_id=WINDOW_ID, subtree="0.9.9"))
    assert payload["ok"] is False
    assert payload["error_code"] == "ax_ref_not_found"


# ── truncated 恢复入口 ────────────────────────────────────────────────
def test_tool_truncated_recovery_hint():
    """traversal 截断时回执带可调用恢复路径（deepest_covered_ref/parent_ref+subtree 用法）。"""
    nodes = _nodes(120)
    backend = FakeBackend(windows=[_window()], ax_view=AxView(
        available=True, root_role="AXWindow", nodes=nodes, truncated=True))
    payload = _payload(_tool(backend).execute(action="snapshot", window_id=WINDOW_ID))
    page = payload["ax"]["page"]
    assert page["traversal_truncated"] is True
    recovery = page["recovery"]
    assert recovery["deepest_covered_ref"] == "0.119"
    assert recovery["parent_ref"] == "0"
    assert "subtree" in recovery["hint"]
