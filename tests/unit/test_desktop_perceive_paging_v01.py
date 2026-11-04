# B-1/B-2 desktop_perceive 续读分页 / 渲染档位 / 焦点摘要
# (DESIGN-20261104-desktop-ax-payload-continuation-and-wait §6.1/§6.2/§6.3)
"""FR-01/FR-02/FR-03 验收：真实生产层 + 离线 fake backend。

本机 ax_trusted=false（无法读真实 AX 树），因此这里只断言**机制**：
字段存在性、可续性、游标失效的确定性拒绝码、渲染档位的字段语义。
不写 token 目标值——没有真实树基线与 tokenizer 时，任何绝对值都是伪造的。
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

NODE_ROW_FIELDS = {
    "ax_ref",
    "role",
    "subrole",
    "title",
    "value",
    "focused",
    "pos_pt",
    "size_pt",
}


# ── 离线替身 ────────────────────────────────────────────────────────────
class FakeBackend:
    supported = True

    def __init__(self, *, windows: list[WindowInfo], ax_view: AxView | None = None) -> None:
        self.windows = list(windows)
        self._ax_view = ax_view
        self.ax_calls: list[dict[str, Any]] = []
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
        return list(self.windows)

    def get_window(self, window_id: int):
        for window in self.windows:
            if window.window_id == window_id:
                return window
        return None

    def ax_snapshot(self, window, depth, node_limit):
        self.ax_calls.append({"window_id": window.window_id, "depth": depth, "node_limit": node_limit})
        if self._ax_view is None:
            return AxView(available=False, failure="ax_window_unbound")
        return self._ax_view

    def capture_window(self, window):
        return None


def _window(window_id: int = 101) -> WindowInfo:
    return WindowInfo(
        window_id=window_id,
        pid=4242,
        app="Notes",
        bundle_id="com.apple.Notes",
        title="笔记",
        title_available=True,
        title_redacted=False,
        bounds_pt=(0.0, 38.0, 1200.0, 800.0),
        layer=0,
        on_screen=True,
        is_foreground=True,
    )


def _nodes(count: int, *, focused_at: int | None = None, role: str = "AXButton") -> tuple[AxNode, ...]:
    out = []
    for index in range(count):
        out.append(
            AxNode(
                ax_ref=f"0.{index}",
                role=role if index % 2 == 0 else "AXStaticText",
                subrole=None,
                title=f"节点{index}",
                value=None if index % 3 else f"值{index}",
                focused=(focused_at == index),
                pos_pt=Pt(x=float(index), y=float(index)),
                size_pt=Size(w=10.0, h=10.0),
            )
        )
    return tuple(out)


def _view(nodes: tuple[AxNode, ...], *, truncated: bool = False) -> AxView:
    return AxView(available=True, root_role="AXWindow", nodes=nodes, truncated=truncated)


def _tool(backend: FakeBackend) -> DesktopPerceiveTool:
    return DesktopPerceiveTool(backend=backend, session_id_getter=lambda: "sess-b1-test")


def _payload(result) -> dict[str, Any]:
    return json.loads(result.content)


# ── FR-02 默认路径防退化 ────────────────────────────────────────────────
def test_default_snapshot_rows_match_legacy_and_no_editable_leak():
    """AxNode 新增的 editable 绝不能渗进节点行：它是 focused 块专用，
    若随行出现会给每个节点凭空加一个 null 键，与本设计降体积的目标相反。"""
    backend = FakeBackend(windows=[_window()], ax_view=_view(_nodes(3)))
    payload = _payload(_tool(backend).execute(action="snapshot", window_id=101))

    assert payload["ok"] is True
    assert payload["ax"]["page"]["render"] == "full"
    assert payload["ax"]["page"]["geometry_dropped"] is False
    assert payload["ax"]["page"]["index"] == 0
    assert payload["ax"]["page"]["next_cursor"] is None
    for row in payload["ax"]["nodes"]:
        assert set(row) == NODE_ROW_FIELDS


# ── FR-01 续读分页 ──────────────────────────────────────────────────────
def test_pagination_covers_tree_exactly_once():
    """5 节点、每页 2：逐页取到 next_cursor 为空，拼接结果与原始顺序逐项相等。"""
    nodes = _nodes(5)
    backend = FakeBackend(windows=[_window()], ax_view=_view(nodes))
    tool = _tool(backend)

    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        kwargs: dict[str, Any] = {"action": "snapshot", "window_id": 101, "node_limit": 2}
        if cursor is not None:
            kwargs["node_cursor"] = cursor
        payload = _payload(tool.execute(**kwargs))
        assert payload["ok"] is True
        page = payload["ax"]["page"]
        assert page["total"] == 5
        assert page["page_limit"] == 2
        seen.extend(row["ax_ref"] for row in payload["ax"]["nodes"])
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            assert page["remaining"] == 0
            break
        assert page["remaining"] > 0

    assert pages == 3
    assert seen == [node.ax_ref for node in nodes]


def test_cursor_bound_to_tree_fingerprint_returns_cursor_stale():
    """游标不是"上次位置"而是"上次位置+那棵树的身份"。树变了必须拒绝，
    否则会把新树的一段当成旧树的续页，静默错位。"""
    backend = FakeBackend(windows=[_window()], ax_view=_view(_nodes(4)))
    tool = _tool(backend)
    first = _payload(tool.execute(action="snapshot", window_id=101, node_limit=2))
    cursor = first["ax"]["page"]["next_cursor"]
    assert cursor

    backend._ax_view = _view(_nodes(4, role="AXTextField"))  # 同长度、不同 role
    stale = _payload(tool.execute(action="snapshot", window_id=101, node_limit=2, node_cursor=cursor))
    assert stale["ok"] is False
    assert stale["error_code"] == "cursor_stale"
    assert "不" in stale["guidance"]


def test_unparseable_cursor_returns_cursor_invalid_not_silent_restart():
    backend = FakeBackend(windows=[_window()], ax_view=_view(_nodes(4)))
    payload = _payload(_tool(backend).execute(action="snapshot", window_id=101, node_cursor="garbage"))
    assert payload["ok"] is False
    assert payload["error_code"] == "cursor_invalid"
    # 关键：不得退化成"从头返回第一页"，否则调用方会以为翻页成功
    assert "nodes" not in payload.get("ax", {})


def test_changing_node_kinds_invalidates_cursor():
    """过滤在分页之前 ⇒ 改过滤等于换了一棵树，旧游标必须失效。"""
    backend = FakeBackend(windows=[_window()], ax_view=_view(_nodes(6)))
    tool = _tool(backend)
    first = _payload(tool.execute(action="snapshot", window_id=101, node_limit=2, node_kinds=["axbutton"]))
    cursor = first["ax"]["page"]["next_cursor"]
    assert cursor

    stale = _payload(
        tool.execute(
            action="snapshot",
            window_id=101,
            node_limit=2,
            node_cursor=cursor,
            node_kinds=["axstatictext"],
        )
    )
    assert stale["ok"] is False
    assert stale["error_code"] == "cursor_stale"


def test_node_kinds_filters_before_paging():
    nodes = _nodes(6)  # 偶数 AXButton、奇数 AXStaticText
    backend = FakeBackend(windows=[_window()], ax_view=_view(nodes))
    payload = _payload(
        _tool(backend).execute(action="snapshot", window_id=101, node_kinds=["AXBUTTON"])
    )
    ax = payload["ax"]
    assert ax["node_count"] == 6          # 遍历到的全树
    assert ax["filtered_count"] == 3      # 过滤后的可续读总量
    assert ax["page"]["total"] == 3
    assert {row["role"] for row in ax["nodes"]} == {"AXButton"}


def test_page_budget_exhausted_after_offset_cap():
    """全树枚举不是本工具用途：额度耗尽要明确拒绝，而不是无声继续烧上下文。"""
    backend = FakeBackend(windows=[_window()], ax_view=_view(_nodes(2100)))
    tool = _tool(backend)

    cursor: str | None = None
    for _ in range(4):  # offset 0 / 500 / 1000 / 1500
        kwargs: dict[str, Any] = {"action": "snapshot", "window_id": 101, "node_limit": 500}
        if cursor is not None:
            kwargs["node_cursor"] = cursor
        payload = _payload(tool.execute(**kwargs))
        assert payload["ok"] is True
        cursor = payload["ax"]["page"]["next_cursor"]
        assert cursor

    exhausted = _payload(
        tool.execute(action="snapshot", window_id=101, node_limit=500, node_cursor=cursor)
    )
    assert exhausted["ok"] is False
    assert exhausted["error_code"] == "page_budget_exhausted"


def test_traversal_truncated_marks_degraded():
    """AX_NODE_LIMIT_DEFAULT 截断 ⇒ total 只是"已遍历部分"。若不标注，
    调用方会把 remaining=0 误读成"整棵树都看完了"。"""
    backend = FakeBackend(windows=[_window()], ax_view=_view(_nodes(3), truncated=True))
    payload = _payload(_tool(backend).execute(action="snapshot", window_id=101))
    assert payload["ax"]["page"]["traversal_truncated"] is True
    assert "ax_traversal_truncated" in payload["degraded"]


# ── FR-02 渲染档位 ──────────────────────────────────────────────────────
def test_sparse_drops_null_and_false_keeps_ax_ref_shorter():
    backend = FakeBackend(windows=[_window()], ax_view=_view(_nodes(4)))
    tool = _tool(backend)
    full = tool.execute(action="snapshot", window_id=101)
    sparse = tool.execute(action="snapshot", window_id=101, render="sparse")

    payload = _payload(sparse)
    for row in payload["ax"]["nodes"]:
        assert row["ax_ref"]
        for value in row.values():
            assert value is not None
            assert value is not False
    # 同一棵树、同一页：sparse 必须严格更短（缩进+空字段都省掉了）
    assert len(sparse.content) < len(full.content)


def test_geometry_none_drops_geometry_and_flags():
    """几何是 point 寻址的唯一依据。丢它必须标注，否则调用方会拿着
    没有坐标的节点去点。"""
    backend = FakeBackend(windows=[_window()], ax_view=_view(_nodes(3)))
    payload = _payload(_tool(backend).execute(action="snapshot", window_id=101, geometry="none"))
    assert payload["ax"]["page"]["geometry_dropped"] is True
    for row in payload["ax"]["nodes"]:
        assert "pos_pt" not in row
        assert "size_pt" not in row
        assert row["ax_ref"]


def test_invalid_render_and_geometry_rejected_at_entry():
    backend = FakeBackend(windows=[_window()], ax_view=_view(_nodes(2)))
    tool = _tool(backend)
    assert "render 只接受" in tool.execute(action="snapshot", window_id=101, render="compact").content
    assert "geometry 只接受" in tool.execute(action="snapshot", window_id=101, geometry="half").content
    assert backend.ax_calls == []  # 入口拒绝 = 零 AX 遍历


# ── FR-03 焦点摘要 ──────────────────────────────────────────────────────
def test_focused_block_available_without_paging_to_it():
    """焦点常在树尾，正是最贵的一页；摘要要独立于当前页存在。"""
    backend = FakeBackend(windows=[_window()], ax_view=_view(_nodes(10, focused_at=9)))
    payload = _payload(_tool(backend).execute(action="snapshot", window_id=101, node_limit=2))

    focused = payload["ax"]["focused"]
    assert focused["present"] is True
    assert focused["ax_ref"] == "0.9"
    assert focused["in_page"] is False           # 本页只有前 2 个
    assert focused["value_len"] is not None
    # editable 未经 AXEditable 读到就是 None，不得用 role 反推成 True/False
    assert focused["editable"] is None


def test_no_focused_node_reports_present_false():
    backend = FakeBackend(windows=[_window()], ax_view=_view(_nodes(3)))
    payload = _payload(_tool(backend).execute(action="snapshot", window_id=101))
    assert payload["ax"]["focused"] == {"present": False}


def test_focused_block_in_page_true():
    backend = FakeBackend(windows=[_window()], ax_view=_view(_nodes(4, focused_at=0)))
    payload = _payload(_tool(backend).execute(action="snapshot", window_id=101, node_limit=2))
    assert payload["ax"]["focused"]["in_page"] is True


def test_value_preview_truncated_at_limit():
    nodes = (
        AxNode(
            ax_ref="0.0",
            role="AXTextField",
            subrole=None,
            title=None,
            value="长" * 400,
            focused=True,
            pos_pt=None,
            size_pt=None,
        ),
    )
    backend = FakeBackend(windows=[_window()], ax_view=_view(nodes))
    focused = _payload(_tool(backend).execute(action="snapshot", window_id=101))["ax"]["focused"]
    assert focused["value_len"] == 400
    assert len(focused["value_preview"]) == 120
    assert focused["value_truncated"] is True


def test_ax_unavailable_degrades_not_fails():
    backend = FakeBackend(
        windows=[_window()],
        ax_view=AxView(available=False, failure="ax_unavailable", ax_error=AX_ERROR_API_DISABLED),
    )
    payload = _payload(_tool(backend).execute(action="snapshot", window_id=101))
    assert payload["ok"] is True
    assert "ax_unavailable" in payload["degraded"]
    assert payload["ax"]["nodes"] == []
    assert payload["ax"]["page"]["total"] == 0
