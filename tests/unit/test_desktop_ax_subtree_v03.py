# D-03：macos_ax.ax_windows_view 的 subtree 定向续读（真实 backend 组合函数层）
"""monkeypatch 模块内部件（app_element/ax_read_attr/cf_*/match_ax_windows_ex），
端到端覆盖：命中（refs 全局编码）、未命中（ax_ref_not_found）、根-only（整树重开）、
元素释放计数（traverse 接管子树根、中间层即时释放、候选幂等释放）。"""

from __future__ import annotations

import pytest

from llm_loop.desktop import macos_ax
from llm_loop.desktop.models import WindowInfo


class FakeEl:
    def __init__(self, role: str, title: str | None = None,
                 children: list[FakeEl] | None = None, bounds=(10.0, 20.0, 300.0, 200.0)):
        self.role, self.title, self.children = role, title, children or []
        self.bounds = bounds
        self.releases = 0
        # ax_windows_view 以 ax_read_attr(app.ref, "AXWindows") 取窗口列表——
        # 替身需暴露 .ref（真实 MacAxElement.ref 是其 CF ref，这里用自身）
        self.ref = self

    def attr(self, name: str):
        if name == "AXRole":
            return self.role
        if name == "AXTitle":
            return self.title
        if name == "AXChildren":
            return list(self.children)
        if name == "AXPosition":
            return {"x": self.bounds[0], "y": self.bounds[1]}
        if name == "AXSize":
            return {"w": self.bounds[2], "h": self.bounds[3]}
        return None

    def release(self):
        self.releases += 1


def _win() -> WindowInfo:
    return WindowInfo(
        window_id=77, pid=900, app="Notes", bundle_id="com.apple.Notes", title="笔记",
        title_available=True, title_redacted=False, bounds_pt=(10.0, 20.0, 300.0, 200.0),
        layer=0, on_screen=True, is_foreground=True,
    )


def _tree() -> FakeEl:
    inner = FakeEl("AXButton", "深层", [FakeEl("AXButton", "叶子1"), FakeEl("AXButton", "叶子2")])
    return FakeEl("AXWindow", "笔记", [FakeEl("AXGroup", "组A", [inner]), FakeEl("AXGroup", "组B")])


@pytest.fixture
def patched(monkeypatch):
    window_root = _tree()
    app = FakeEl("AXApplication", "Notes")
    ax_windows = [window_root]

    monkeypatch.setattr(macos_ax, "app_element", lambda pid: app, raising=False)
    monkeypatch.setattr(
        macos_ax, "ax_read_attr",
        lambda ref, name: (0, ax_windows if name == "AXWindows" else ref.attr(name)),
        raising=False,
    )
    monkeypatch.setattr(macos_ax, "cf_array_count", lambda v: len(v), raising=False)
    monkeypatch.setattr(macos_ax, "cf_array_item", lambda v, i: v[i], raising=False)
    monkeypatch.setattr(macos_ax, "cf_retain", lambda item: item, raising=False)
    # MacAxElement.__init__ 会 int(ref) 包装 CF 层 ref；替身直接以 AxElementLike
    # 鸭子协议（attr/release/bounds）进入 elements 列表，与 traverse 契约一致
    monkeypatch.setattr(macos_ax, "MacAxElement", lambda ref: ref, raising=False)
    monkeypatch.setattr(macos_ax, "cf_release", lambda v: None, raising=False)
    monkeypatch.setattr(macos_ax, "element_bounds", lambda el: el.bounds, raising=False)
    monkeypatch.setattr(
        macos_ax, "match_ax_windows_ex", lambda w, cands: ([0], "exact"), raising=False,
    )
    return window_root


def test_subtree_hit_global_refs(patched):
    view = macos_ax.ax_windows_view(_win(), depth=6, node_limit=50, subtree="0.0.0")
    assert view.available is True
    refs = [n.ax_ref for n in view.nodes]
    # 子树根 + 两叶子，全局编码
    assert refs == ["0.0.0", "0.0.0.0", "0.0.0.1"]
    assert view.root_role == "AXButton"
    assert view.truncated is False


def test_subtree_miss_deterministic(patched):
    view = macos_ax.ax_windows_view(_win(), depth=3, node_limit=50, subtree="0.0.9")
    assert view.available is False
    assert view.failure == "ax_ref_not_found"


def test_subtree_root_only_rereads_whole_tree(patched):
    view = macos_ax.ax_windows_view(_win(), depth=6, node_limit=50, subtree="0")
    assert view.available is True
    refs = [n.ax_ref for n in view.nodes]
    assert "0.0" in refs and "0.0.0" in refs  # 整树、全局编码根
    assert view.root_role == "AXWindow"


def test_subtree_release_ownership(patched):
    root = patched
    inner = root.children[0].children[0]
    macos_ax.ax_windows_view(_win(), depth=6, node_limit=50, subtree="0.0.0")
    # 中间层（组A）即时释放；子树根与叶子由 traverse 接管释放（恰好一次）
    assert root.children[0].releases == 1
    assert inner.releases == 1
    for leaf in inner.children:
        assert leaf.releases == 1
    # 窗口根不由 subtree 链释放，由 finally 候选幂等释放恰好一次（subtree 路径
    # 中 bound 未移交 traverse，该 release 是真实释放而非 no-op）
    assert root.releases == 1


def test_no_subtree_legacy_path_unchanged(patched):
    view = macos_ax.ax_windows_view(_win(), depth=6, node_limit=50)
    assert view.available is True
    assert [n.ax_ref for n in view.nodes][:2] == ["0", "0.0"]
