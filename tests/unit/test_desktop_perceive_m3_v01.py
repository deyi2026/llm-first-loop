# M3 desktop_perceive tests (DESIGN-20261027 §5.3/§8-M3; U13/U14/U18/U19)
"""M3 desktop read-only perception: parsing / models / AX / permissions / privacy.

Every capability runs the REAL production layers (pure parsers, traverse/bind
functions, capture size math, tool dispatch) against offline fixtures:
lsappinfo fixed samples, CGWindowList-shaped dicts, fake AX elements, fake
backends.  Negative cases assert the deterministic receipt AND the absence of
side effects (no screencapture run, no file written, no AX traversal) -
RULE-AI-35: "refusals must actually refuse".
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

from llm_loop.desktop import macos_capture
from llm_loop.desktop.apps_probe import (
    build_apps,
    parse_hidden_info,
    parse_lsappinfo_front,
    parse_lsappinfo_list,
)
from llm_loop.desktop.backend_macos import backend_for_platform
from llm_loop.desktop.macos_ax import (
    bounds_within,
    match_ax_windows,
    match_ax_windows_ex,
    node_from_element,
    titles_compatible,
    traverse,
)
from llm_loop.desktop.macos_windows import display_scale_for_bounds, window_infos_from_raw
from llm_loop.desktop.models import (
    AX_ERROR_API_DISABLED,
    AX_ERROR_CANNOT_COMPLETE,
    BoundsPt,
    DesktopErrorCode,
    DisplayInfo,
    PermissionSnapshot,
    PlatformInfo,
    Pt,
    SessionSnapshot,
    Size,
    WindowInfo,
    ax_error_reason,
    ax_error_to_code,
    clamp_depth,
)
from llm_loop.desktop.privacy import (
    CORE_PRIVACY_BUNDLE_SUBSTRINGS,
    PrivacyPolicy,
    SeeAllowlist,
    split_bundle_config,
)
from llm_loop.tools.builtin.desktop_perceive import (
    DesktopPerceiveTool,
    make_jsonl_audit_sink,
)


# ── 离线替身（无 GUI、无框架加载、无子进程）───────────────────────────────
class FakeAxElement:
    """最小 AxElementLike：attrs dict + children 列表。"""

    def __init__(self, attrs: dict[str, Any] | None = None, children: list | None = None):
        self.attrs = dict(attrs or {})
        self.children = list(children or [])

    def attr(self, name: str) -> Any:
        if name == "AXChildren":
            return self.children
        return self.attrs.get(name)


class FakeBackend:
    """注入型后端：记录调用次数用于"零副作用"断言。"""

    supported = True

    def __init__(
        self,
        *,
        windows: list[WindowInfo] | None = None,
        apps: list | None = None,
        ax_view=None,
        capture_outcome=None,
        perms: PermissionSnapshot | None = None,
        session: SessionSnapshot | None = None,
    ) -> None:
        self.windows = list(windows or [])
        self.apps = list(apps or [])
        self._ax_view = ax_view
        self._capture_outcome = capture_outcome
        self._perms = perms or PermissionSnapshot(
            ax_trusted=False, screen_capture_granted=False, ax_error=AX_ERROR_API_DISABLED
        )
        self._session = session or SessionSnapshot(
            gui_available=True, console_user="tester", screen_locked=False
        )
        self.ax_calls: list[dict] = []
        self.capture_calls: list[WindowInfo] = []
        self.windows_calls: list[bool] = []
        self.apps_calls = 0
        self.displays = []

    def platform_info(self) -> PlatformInfo:
        return PlatformInfo(os="darwin", version="15.0")

    def session_snapshot(self) -> SessionSnapshot:
        return self._session

    def permission_snapshot(self) -> PermissionSnapshot:
        return self._perms

    def capability_snapshot(self) -> dict[str, bool]:
        return {
            "can_list_windows": True,
            "can_read_ax": self._perms.ax_trusted,
            "can_capture": self._perms.screen_capture_granted,
        }

    def list_displays(self):
        return self.displays

    def process_info(self):
        return {"pid": 4242, "executable": "/usr/local/bin/python", "python": "3.13"}

    def list_apps(self):
        self.apps_calls += 1
        return self.apps

    def list_windows(self, include_offscreen: bool = False):
        self.windows_calls.append(bool(include_offscreen))
        return [w for w in self.windows if include_offscreen or w.on_screen]

    def get_window(self, window_id: int):
        for window in self.windows:
            if window.window_id == window_id:
                return window
        return None

    def ax_snapshot(self, window, depth, node_limit):
        from llm_loop.desktop.models import AxView

        self.ax_calls.append({"window_id": window.window_id, "depth": depth})
        if self._ax_view is None:
            return AxView(available=False, failure="ax_window_unbound")
        return self._ax_view

    def capture_window(self, window):
        self.capture_calls.append(window)
        return self._capture_outcome


def _window(
    window_id: int = 101,
    pid: int = 96579,
    app: str = "Google Chrome",
    bundle_id: str | None = "com.google.Chrome",
    title: str | None = None,
    title_available: bool = False,
    bounds: tuple = (0.0, 38.0, 1512.0, 877.0),
    layer: int = 0,
    on_screen: bool = True,
    is_foreground: bool = True,
) -> WindowInfo:
    return WindowInfo(
        window_id=window_id,
        pid=pid,
        app=app,
        bundle_id=bundle_id,
        title=title,
        title_available=title_available,
        title_redacted=False,
        bounds_pt=BoundsPt(*bounds),
        layer=layer,
        on_screen=on_screen,
        is_foreground=is_foreground,
    )


def _tool(backend: FakeBackend, **kwargs) -> DesktopPerceiveTool:
    return DesktopPerceiveTool(
        backend=backend,
        session_id_getter=lambda: "sess-m3-test",
        **kwargs,
    )


def _payload(result) -> dict:
    return json.loads(result.content)


LSAPPINFO_SAMPLE = ''' 1) "loginwindow" ASN:0x0-0x3003:
    bundleID="com.apple.loginwindow"
    bundle path="/System/Library/CoreServices/loginwindow.app"
    executable path="/System/Library/CoreServices/loginwindow.app/Contents/MacOS/loginwindow"
    pid = 424 type="UIElement" flavor=3 Version="3085.5.3" fileType="APPL" creator="lgnw" Arch=ARM64
    coalition: 394
 2) "universalaccessd" ASN:0x0-0x8008:
    bundleID=[ NULL ]
    executable path="/usr/sbin/universalaccessd"
    pid = 720 !signalled type="BackgroundOnly" flavor=3 Version=[ NULL ] Arch=ARM64
 3) "Google Chrome" ASN:0x0-0x95c75be:
    bundleID="com.google.Chrome"
    executable path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    pid = 96579 type="Foreground" flavor=3 Version="8059.85" Arch=ARM64 sandboxed
'''

CG_ROWS = [
    {"id": 501, "owner": "Google Chrome", "name": "某文档 - Google Chrome", "layer": 0,
     "bounds": {"x": 0.0, "y": 38.0, "w": 1512.0, "h": 877.0}, "pid": 96579, "on_screen": True},
    {"id": 502, "owner": "Finder", "name": "", "layer": 0,
     "bounds": {"x": 10.0, "y": 10.0, "w": 800.0, "h": 600.0}, "pid": 500, "on_screen": True},
    {"id": 503, "owner": "Dock", "name": "", "layer": 25,
     "bounds": {"x": 0.0, "y": 950.0, "w": 1512.0, "h": 32.0}, "pid": 400, "on_screen": True},
]


# ══ 1. lsappinfo 解析 ═════════════════════════════════════════════════════
def test_parse_lsappinfo_list_bundle_ids_and_null():
    records = parse_lsappinfo_list(LSAPPINFO_SAMPLE)
    assert [r.bundle_id for r in records] == [
        "com.apple.loginwindow",
        None,
        "com.google.Chrome",
    ]


def test_parse_lsappinfo_list_pid_and_type():
    records = parse_lsappinfo_list(LSAPPINFO_SAMPLE)
    chrome = records[2]
    assert chrome.pid == 96579
    assert chrome.app_type == "Foreground"
    assert chrome.name == "Google Chrome"
    assert records[1].app_type == "BackgroundOnly"


def test_parse_lsappinfo_front_asn():
    assert parse_lsappinfo_front("ASN:0x0-0x95c75be:") == "asn:0x0-0x95c75be"
    assert parse_lsappinfo_front("") is None


def test_parse_hidden_info_variants():
    assert parse_hidden_info('"Hidden"=false') is False
    assert parse_hidden_info('"Hidden"=true') is True
    assert parse_hidden_info("error") is None


def test_build_apps_foreground_and_hidden_lookup():
    records = parse_lsappinfo_list(LSAPPINFO_SAMPLE)
    hidden_seen: list[str] = []

    def lookup(name: str):
        hidden_seen.append(name)
        return name == "Google Chrome"

    apps = build_apps(records, hidden_lookup=lookup)
    chrome = next(a for a in apps if a.name == "Google Chrome")
    assert chrome.is_foreground is True
    assert chrome.is_hidden is True
    # hidden_lookup 对每个有 pid 的记录各查一次（三记录全有 pid）
    assert hidden_seen == ["loginwindow", "universalaccessd", "Google Chrome"]
    loginwindow = next(a for a in apps if a.name == "loginwindow")
    assert loginwindow.is_foreground is False


# ══ 2. CGWindowList 行 → WindowInfo ═══════════════════════════════════════
def test_window_infos_title_availability_honesty():
    infos = window_infos_from_raw(CG_ROWS, {96579: "com.google.Chrome"}, on_screen_default=True)
    by_id = {w.window_id: w for w in infos}
    assert by_id[501].title == "某文档 - Google Chrome"
    assert by_id[501].title_available is True
    # 空标题（无屏幕录制授权的真实形态）→ null + title_available=false，不用 owner 冒充
    assert by_id[502].title is None
    assert by_id[502].title_available is False
    assert by_id[502].app == "Finder"


def test_window_infos_foreground_first_layer0_onscreen():
    infos = window_infos_from_raw(
        CG_ROWS, {96579: "com.google.Chrome"}, on_screen_default=True
    )
    foregrounds = [w for w in infos if w.is_foreground]
    assert len(foregrounds) == 1
    assert foregrounds[0].window_id == 501  # front→back 第一个 layer==0
    assert foregrounds[0].bundle_id == "com.google.Chrome"


def test_window_infos_bounds_points_serialization():
    infos = window_infos_from_raw(CG_ROWS, {}, on_screen_default=True)
    first = infos[0]
    assert first.bounds_pt == BoundsPt(x=0.0, y=38.0, w=1512.0, h=877.0)


def test_display_scale_for_bounds_center_hit_and_miss():
    displays = [
        DisplayInfo(id=1, is_main=True, scale=2.0, bounds_pt=BoundsPt(0, 0, 1512, 982)),
    ]
    assert display_scale_for_bounds(displays, BoundsPt(0, 0, 1512, 877)) == 2.0
    # 离屏窗口：中心不在任何显示器 → 回退主屏 scale
    assert display_scale_for_bounds(displays, BoundsPt(-4000, -4000, 100, 100)) == 2.0
    assert display_scale_for_bounds([], BoundsPt(0, 0, 10, 10)) is None


# ══ 3. depth / AX 错误码模型 ══════════════════════════════════════════════
def test_clamp_depth_boundaries():
    assert clamp_depth(3) == (3, False)
    assert clamp_depth(0) == (0, False)
    assert clamp_depth(6) == (6, False)
    assert clamp_depth(9) == (6, True)
    assert clamp_depth(-1) == (0, True)
    assert clamp_depth("x") == (3, True)


def test_ax_error_mapping_25211_and_25204():
    assert ax_error_to_code(AX_ERROR_API_DISABLED) == DesktopErrorCode.AX_UNAVAILABLE
    assert ax_error_to_code(AX_ERROR_CANNOT_COMPLETE) == DesktopErrorCode.AX_UNAVAILABLE
    assert "-25211" in ax_error_reason(AX_ERROR_API_DISABLED)
    assert "-25204" in ax_error_reason(AX_ERROR_CANNOT_COMPLETE)
    assert ax_error_to_code(-25199) == DesktopErrorCode.BACKEND_ERROR


# ══ 4. AX 遍历 / 绑定（fake 元素，纯函数）═════════════════════════════════
def _tree() -> FakeAxElement:
    leaf_a = FakeAxElement({"AXRole": "AXButton", "AXTitle": "新建", "AXFocused": True})
    leaf_b = FakeAxElement({"AXRole": "AXButton", "AXTitle": "关闭"})
    group = FakeAxElement({"AXRole": "AXGroup"}, [leaf_a, leaf_b])
    return FakeAxElement({"AXRole": "AXWindow", "AXTitle": "主窗口"}, [group])


def test_traverse_ax_ref_paths_from_app_root():
    root = _tree()
    nodes, truncated = traverse(root, depth=2, node_limit=1500, root_ref="0")
    assert truncated is False
    assert [n.ax_ref for n in nodes] == ["0", "0.0", "0.0.0", "0.0.1"]


def test_traverse_ownership_releases_real_elements():
    """traverse 接管所有权：有 release() 的元素在子树走完后统一释放（含截断）。"""

    class ReleasingAxElement(FakeAxElement):
        def __init__(self, attrs=None, children=None):
            super().__init__(attrs, children)
            self.released = 0

        def release(self):
            self.released += 1

    leaf_a = ReleasingAxElement({"AXRole": "AXButton"})
    leaf_b = ReleasingAxElement({"AXRole": "AXButton"})
    group = ReleasingAxElement({"AXRole": "AXGroup"}, [leaf_a, leaf_b])
    root = ReleasingAxElement({"AXRole": "AXWindow"}, [group])
    nodes, truncated = traverse(root, depth=2, node_limit=1500, root_ref="0")
    assert truncated is False
    assert len(nodes) == 4
    assert root.released == 1 and group.released == 1
    assert leaf_a.released == 1 and leaf_b.released == 1

    # 截断路径同样释放：node_limit=1 → root 释放、未走到的子树也释放
    leaf_c = ReleasingAxElement({"AXRole": "AXButton"})
    root2 = ReleasingAxElement({"AXRole": "AXWindow"}, [leaf_c])
    nodes2, truncated2 = traverse(root2, depth=3, node_limit=1, root_ref="0")
    assert len(nodes2) == 1 and truncated2 is True
    assert root2.released == 1 and leaf_c.released == 1


def test_traverse_depth_clip_stops_deeper_nodes():
    root = _tree()
    nodes, _ = traverse(root, depth=1, node_limit=1500, root_ref="0")
    assert [n.ax_ref for n in nodes] == ["0", "0.0"]


def test_traverse_node_limit_sets_truncated():
    root = _tree()
    nodes, truncated = traverse(root, depth=6, node_limit=2, root_ref="0")
    assert len(nodes) == 2
    assert truncated is True


def test_node_from_element_field_mapping():
    el = FakeAxElement(
        {
            "AXRole": "AXTextField",
            "AXSubrole": "AXSearchField",
            "AXTitle": "搜索",
            "AXValue": "lfl",
            "AXFocused": True,
            "AXPosition": Pt(x=10.0, y=20.0),
            "AXSize": Size(w=100.0, h=24.0),
        }
    )
    node = node_from_element(el, "0.2.1")
    assert node.role == "AXTextField"
    assert node.subrole == "AXSearchField"
    assert node.value == "lfl"
    assert node.focused is True
    assert node.pos_pt is not None and (node.pos_pt.x, node.pos_pt.y) == (10.0, 20.0)
    assert node.size_pt is not None and (node.size_pt.w, node.size_pt.h) == (100.0, 24.0)


def test_bounds_within_tolerance():
    a = BoundsPt(0, 0, 100, 50)
    assert bounds_within(a, BoundsPt(1.9, -1.9, 101.9, 48.1)) is True
    assert bounds_within(a, BoundsPt(2.5, 0, 100, 50)) is False


def _cand(index: int, title, bounds: tuple):
    return (index, title, BoundsPt(*bounds))


def test_match_ax_windows_unique_with_title():
    cg = _window(title="主窗口", title_available=True, bounds=(0, 38, 1512, 877))
    hits = match_ax_windows(
        cg,
        [
            _cand(0, "别的窗口", (5, 5, 800, 600)),
            _cand(1, "主窗口", (0, 38, 1512, 877)),
        ],
    )
    assert hits == [1]


def test_match_ax_windows_ambiguous_duplicates():
    cg = _window(title="同题", title_available=True, bounds=(0, 0, 800, 600))
    hits = match_ax_windows(
        cg, [_cand(0, "同题", (0, 0, 800, 600)), _cand(1, "同题", (1, 1, 800, 600))]
    )
    assert hits == [0, 1]


def test_match_ax_windows_zero_hits_and_bounds_only_fallback():
    cg_titled = _window(title="主窗口", title_available=True)
    assert match_ax_windows(cg_titled, [_cand(0, "不同标题", (0, 38, 1512, 877))]) == []
    # 标题不可用（无屏幕录制授权）→ 退化为纯 bounds 匹配（确定性，不猜前台）
    cg_untitled = _window(title=None, title_available=False, bounds=(0, 38, 1512, 877))
    assert match_ax_windows(cg_untitled, [_cand(0, "任意标题", (1, 39, 1513, 878))]) == [0]


# ══ 4b. D4 标题前缀相容（实测反证驱动）═════════════════════════════════════
# 反证来源：2026-10-28 09:59 活动监视器 pid 71527 —— CG 标题 "活动监视器"，
# AX 标题 "活动监视器 – 所有进程"，bounds 完全相等；严格相等导致 ax_window_unbound。
def test_match_ax_windows_ex_prefix_is_relaxed_not_exact():
    cg = _window(title="活动监视器", title_available=True, bounds=(310, 100, 1064, 640))
    hits, basis = match_ax_windows_ex(
        cg, [_cand(0, "活动监视器 – 所有进程", (310, 100, 1064, 640))]
    )
    assert hits == [0]
    assert basis == "title_relaxed"


def test_match_ax_windows_ex_reverse_prefix():
    # CG 标题更长、AX 标题是它的前缀，同样视为同一窗口
    cg = _window(title="report.md — 编辑", title_available=True, bounds=(0, 0, 800, 600))
    hits, basis = match_ax_windows_ex(cg, [_cand(0, "report.md", (0, 0, 800, 600))])
    assert (hits, basis) == ([0], "title_relaxed")


def test_match_ax_windows_ex_exact_keeps_strongest_basis():
    cg = _window(title="主窗口", title_available=True, bounds=(0, 38, 1512, 877))
    hits, basis = match_ax_windows_ex(cg, [_cand(1, "主窗口", (0, 38, 1512, 877))])
    assert (hits, basis) == ([1], "title_exact")


def test_match_ax_windows_ex_bounds_only_basis_when_title_missing():
    cg = _window(title=None, title_available=False, bounds=(0, 38, 1512, 877))
    hits, basis = match_ax_windows_ex(cg, [_cand(0, "任意标题", (1, 39, 1513, 878))])
    assert (hits, basis) == ([0], "bounds_only")


def test_match_ax_windows_ex_prefix_still_ambiguity_when_duplicated():
    # 前缀相容也必须是"唯一"：两个候选都相容时照旧多命中，由调用方拒绝
    cg = _window(title="同题", title_available=True, bounds=(0, 0, 800, 600))
    hits, basis = match_ax_windows_ex(
        cg, [_cand(0, "同题 – A", (0, 0, 800, 600)), _cand(1, "同题 – B", (1, 1, 800, 600))]
    )
    assert hits == [0, 1]
    assert basis == "title_relaxed"


def test_titles_compatible_rejects_unrelated_and_empty():
    assert titles_compatible("主窗口", "不同标题") is False
    assert titles_compatible("", "任意") is False
    assert titles_compatible("任意", None) is False
    # 归一化：空白差异不影响判定
    assert titles_compatible("活动  监视器", "活动 监视器 – 所有进程") is True


# ══ 5. 隐私与 U14 名单 ════════════════════════════════════════════════════
def test_privacy_core_hits_three_sensitive_families():
    policy = PrivacyPolicy()
    assert policy.is_sensitive("com.1password.mac") is True
    assert policy.is_sensitive("com.bitwarden.desktop") is True
    assert policy.is_sensitive("com.apple.keychainaccess") is True
    assert policy.is_sensitive("com.apple.loginwindow") is True
    assert policy.is_sensitive("COM.APPLE.LOGINWINDOW") is True  # 大小写归一
    assert policy.is_sensitive("com.google.Chrome") is False
    assert policy.is_sensitive(None) is False


def test_privacy_config_append_only_cannot_remove_core():
    policy = PrivacyPolicy(extra_substrings=("com.mybank.app",))
    assert policy.is_sensitive("com.mybank.app") is True  # 追加生效
    assert policy.is_sensitive("com.1password.mac") is True  # 核心项仍在
    # 构造面不存在"删除"入口：core_items 恒等于硬编码名单
    assert policy.core_items == CORE_PRIVACY_BUNDLE_SUBSTRINGS
    with_extras = PrivacyPolicy(extra_substrings=())
    assert with_extras.core_items == CORE_PRIVACY_BUNDLE_SUBSTRINGS


def test_see_allowlist_default_empty_allows_everything():
    allowlist = SeeAllowlist()
    assert allowlist.is_empty is True
    assert allowlist.is_allowed("com.anything.dev") is True
    assert allowlist.is_allowed(None) is True


def test_see_allowlist_exact_match_not_prefix():
    allowlist = SeeAllowlist(("com.allowed.app", "Other.App"))
    assert allowlist.is_empty is False
    assert allowlist.is_allowed("com.allowed.app") is True
    assert allowlist.is_allowed("com.allowed.app.evil") is False  # 精确匹配，前缀不沾光
    assert allowlist.is_allowed("other.app") is True  # 大小写归一
    assert allowlist.is_allowed("com.google.Chrome") is False


def test_split_bundle_config_normalization():
    assert split_bundle_config("") == ()
    assert split_bundle_config(" a.b , c.d ,, ") == ("a.b", "c.d")


def test_privacy_priority_over_allowlist():
    # 名单内允许 com.apple.loginwindow 也拦（核心隐私 > 配置允许）
    backend = FakeBackend(windows=[_window(window_id=9, bundle_id="com.apple.loginwindow")])
    tool = _tool(backend, see_allowlist=("com.apple.loginwindow",))
    payload = _payload(tool.execute(action="snapshot", window_id=9))
    assert payload["error_code"] == "privacy_blocked"


# ══ 6. 工具层错误映射（确定性回执 + 零副作用）════════════════════════════
def test_unsupported_platform_and_no_framework_load(monkeypatch):
    from llm_loop.desktop import macos_cf

    loaded: list[str] = []

    def _no_cdll(name, *args, **kwargs):  # pragma: no cover - must never run
        loaded.append(str(name))
        raise AssertionError(f"非 darwin 平台不得加载框架: {name}")

    monkeypatch.setattr(ctypes, "CDLL", _no_cdll)
    monkeypatch.setattr(sys, "platform", "linux")
    backend = backend_for_platform("linux")
    assert backend is None
    tool = DesktopPerceiveTool(backend=backend, session_id_getter=lambda: "s")
    result = tool.execute(action="status")
    payload = _payload(result)
    assert payload["ok"] is False
    assert payload["error_code"] == "unsupported_platform"
    assert "macOS" in payload["guidance"]
    assert loaded == []
    assert macos_cf._FRAMEWORKS == {}


def test_no_gui_session_error():
    backend = FakeBackend(
        session=SessionSnapshot(gui_available=False, console_user=None, screen_locked=None)
    )
    payload = _payload(_tool(backend).execute(action="windows"))
    assert payload["ok"] is False
    assert payload["error_code"] == "no_gui_session"
    assert payload["session"]["gui_available"] is False
    # 探针失败/无会话 → locked 为 null（"未知"），不是 False（"断言未锁"）
    assert payload["session"]["screen_locked"] is None


def test_screen_locked_error():
    backend = FakeBackend(
        session=SessionSnapshot(gui_available=True, console_user="u", screen_locked=True)
    )
    payload = _payload(_tool(backend).execute(action="windows"))
    assert payload["error_code"] == "screen_locked"
    assert payload["session"]["screen_locked"] is True


def test_invalid_action_and_field_mismatch():
    tool = _tool(FakeBackend())
    assert "action 不受支持" in tool.execute(action="hydrate").content
    assert "fields_mismatch" in tool.execute(action="status", window_id=1).content
    assert "window_id 必填" in tool.execute(action="snapshot").content
    assert "depth 必须是整数" in tool.execute(action="snapshot", window_id=1, depth="3").content
    assert "vision 只接受" in tool.execute(action="snapshot", window_id=1, vision="always").content
    assert "include_offscreen 必须是布尔值" in tool.execute(action="windows", include_offscreen="yes").content


def test_status_receipt_self_check_shape():
    backend = FakeBackend()
    payload = _payload(_tool(backend).execute(action="status"))
    assert payload["ok"] is True
    assert payload["action"] == "status"
    assert payload["permissions"] == {
        "ax_trusted": False,
        "screen_capture_granted": False,
        "ax_error": AX_ERROR_API_DISABLED,
    }
    assert payload["capability"] == {
        "can_list_windows": True,
        "can_read_ax": False,
        "can_capture": False,
    }
    assert payload["platform"]["os"] == "darwin"
    assert payload["session"]["console_user"] == "tester"
    assert isinstance(payload["elapsed_ms"], int)


def test_status_guidance_when_permissions_missing():
    backend = FakeBackend()  # ax/capture 均 false
    payload = _payload(_tool(backend).execute(action="status"))
    assert "辅助功能" in payload["guidance"]
    assert "屏幕录制" in payload["guidance"]


def test_status_guidance_null_when_all_granted():
    backend = FakeBackend(
        perms=PermissionSnapshot(ax_trusted=True, screen_capture_granted=True, ax_error=None)
    )
    payload = _payload(_tool(backend).execute(action="status"))
    assert payload["guidance"] is None
    assert payload["permissions"]["ax_error"] is None


def test_snapshot_ax_25211_degrades_not_fails():
    from llm_loop.desktop.models import AxView

    backend = FakeBackend(
        windows=[_window()],
        ax_view=AxView(available=False, failure="ax_unavailable", ax_error=AX_ERROR_API_DISABLED),
    )
    payload = _payload(_tool(backend).execute(action="snapshot", window_id=101))
    # vision=none + AX 不可用 → ok=true，缺层记在 degraded（不整单失败）
    assert payload["ok"] is True
    assert payload["degraded"] == ["ax_unavailable"]
    assert payload["ax"]["available"] is False
    assert payload["image"] is None
    assert "-25211" in payload["guidance"]


def test_snapshot_ax_25204_deterministic_reason():
    from llm_loop.desktop.models import AxView

    backend = FakeBackend(
        windows=[_window()],
        ax_view=AxView(available=False, failure="ax_unavailable", ax_error=AX_ERROR_CANNOT_COMPLETE),
    )
    payload = _payload(_tool(backend).execute(action="snapshot", window_id=101))
    assert payload["ok"] is True
    assert payload["degraded"] == ["ax_unavailable"]
    assert "-25204" in payload["guidance"]


def test_snapshot_window_not_found():
    backend = FakeBackend(windows=[_window()])
    payload = _payload(_tool(backend).execute(action="snapshot", window_id=999))
    assert payload["ok"] is False
    assert payload["error_code"] == "window_not_found"
    assert backend.ax_calls == []


def test_snapshot_window_ambiguous_returns_candidates():
    from llm_loop.desktop.models import AxCandidate, AxView

    backend = FakeBackend(
        windows=[_window(title="同题", title_available=True)],
        ax_view=AxView(
            available=False,
            failure="window_ambiguous",
            candidates=(
                AxCandidate(ax_index=0, title="同题", bounds_pt=BoundsPt(0, 0, 800, 600)),
                AxCandidate(ax_index=1, title="同题", bounds_pt=BoundsPt(1, 1, 800, 600)),
            ),
        ),
    )
    payload = _payload(_tool(backend).execute(action="snapshot", window_id=101))
    assert payload["ok"] is False
    assert payload["error_code"] == "window_ambiguous"
    assert [c["ax_index"] for c in payload["ax"]["candidates"]] == [0, 1]


def test_snapshot_ax_unbound_degraded():
    from llm_loop.desktop.models import AxView

    backend = FakeBackend(
        windows=[_window()], ax_view=AxView(available=False, failure="ax_window_unbound")
    )
    payload = _payload(_tool(backend).execute(action="snapshot", window_id=101))
    assert payload["ok"] is True
    assert payload["degraded"] == ["ax_window_unbound"]
    assert "不猜测" in payload["guidance"]


# ══ 7. 坐标双单位与截图（U18/U19）═════════════════════════════════════════
def _png_bytes(width: int, height: int) -> bytes:
    return (
        macos_capture.PNG_SIGNATURE
        + b"\x00\x00\x00\x0d"
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x00" * 16
    )


def test_png_dimensions_parses_and_rejects():
    assert macos_capture.png_dimensions(_png_bytes(3024, 1754)) == (3024, 1754)
    assert macos_capture.png_dimensions(b"not a png at all") is None
    assert macos_capture.png_dimensions(b"") is None


def test_check_capture_size_threshold_u19():
    bounds = BoundsPt(0, 38, 1512, 877)
    assert macos_capture.check_capture_size(3024, 1754, bounds, 2.0) == []
    assert macos_capture.check_capture_size(3025, 1754, bounds, 2.0) == []  # 1px ≤ 容差
    assert macos_capture.check_capture_size(3027, 1754, bounds, 2.0) == ["capture_size_mismatch"]
    assert macos_capture.check_capture_size(3024, 1757, bounds, 2.0) == ["capture_size_mismatch"]
    assert macos_capture.check_capture_size(100, 100, bounds, 0) == ["capture_size_mismatch"]


def test_capture_refuses_without_preflight_zero_subprocess(monkeypatch, tmp_path):
    calls: list[list[str]] = []

    def _runner(argv, **kwargs):  # pragma: no cover - must never run
        calls.append(list(argv))
        raise AssertionError("无授权时不得调用 screencapture")

    outcome = macos_capture.capture_window(
        _window(), tmp_path / "vision", 2.0, runner=_runner, preflight=lambda: False
    )
    assert outcome.error == DesktopErrorCode.CAPTURE_UNAVAILABLE
    assert outcome.image is None
    assert "黑图" in outcome.detail
    assert calls == []
    assert list((tmp_path).rglob("*.png")) == []


def test_capture_timeout_maps_to_capture_timeout_and_cleans_partial(tmp_path):
    def _runner(argv, **kwargs):
        Path(argv[-1]).write_bytes(b"\x89PNG\r\n\x1a\npartial")  # 半截文件残留场景
        raise subprocess.TimeoutExpired(cmd=argv, timeout=10)

    outcome = macos_capture.capture_window(
        _window(), tmp_path, 2.0, runner=_runner, preflight=lambda: True
    )
    assert outcome.error == DesktopErrorCode.CAPTURE_TIMEOUT
    assert list(tmp_path.rglob("*.png")) == []  # 半截文件不得冒充证据留在盘上


def test_capture_rc_nonzero_maps_to_capture_unavailable(tmp_path):
    def _runner(argv, **kwargs):
        Path(argv[-1]).write_bytes(b"garbage-not-png")
        return subprocess.CompletedProcess(argv, returncode=1, stderr=b"could not create image")

    outcome = macos_capture.capture_window(
        _window(), tmp_path, 2.0, runner=_runner, preflight=lambda: True
    )
    assert outcome.error == DesktopErrorCode.CAPTURE_UNAVAILABLE
    assert "could not create image" in (outcome.detail or "")
    assert list(tmp_path.rglob("*.png")) == []  # 失败产物已清理


def test_capture_non_png_output_is_cleaned(tmp_path):
    def _runner(argv, **kwargs):
        Path(argv[-1]).write_bytes(b"\x89PNG\r\n\x1a\nbut-not-a-real-ihdr" + b"\x00" * 8)
        return subprocess.CompletedProcess(argv, returncode=0, stderr=b"")

    outcome = macos_capture.capture_window(
        _window(), tmp_path, 2.0, runner=_runner, preflight=lambda: True
    )
    assert outcome.error == DesktopErrorCode.CAPTURE_UNAVAILABLE
    assert "PNG" in (outcome.detail or "")
    assert list(tmp_path.rglob("*.png")) == []


def test_capture_happy_path_disk_and_sha(tmp_path):
    blob = _png_bytes(3024, 1754)

    def _runner(argv, **kwargs):
        Path(argv[-1]).write_bytes(blob)
        return subprocess.CompletedProcess(argv, returncode=0, stderr=b"")

    outcome = macos_capture.capture_window(
        _window(), tmp_path / "vision", 2.0, runner=_runner, preflight=lambda: True
    )
    assert outcome.error is None and outcome.image is not None
    image = outcome.image
    assert image.sha256 == hashlib.sha256(blob).hexdigest()
    assert (image.width, image.height) == (3024, 1754)
    assert image.scale == 2.0
    assert image.bytes == len(blob)
    assert f"win-{_window().window_id}-" in Path(image.path).name
    assert Path(image.path).exists()
    assert image.ref.startswith("vision://desktop/v0.1/")


def test_capture_same_content_same_sha(tmp_path):
    blob = _png_bytes(3024, 1754)

    def _runner(argv, **kwargs):
        Path(argv[-1]).write_bytes(blob)
        return subprocess.CompletedProcess(argv, returncode=0, stderr=b"")

    a = macos_capture.capture_window(_window(), tmp_path, 2.0, runner=_runner, preflight=lambda: True)
    b = macos_capture.capture_window(_window(), tmp_path, 2.0, runner=_runner, preflight=lambda: True)
    assert a.image is not None and b.image is not None
    assert a.image.sha256 == b.image.sha256
    assert a.image.ref == b.image.ref


def test_vision_none_zero_capture_zero_files(tmp_path):
    from llm_loop.desktop.models import AxView

    backend = FakeBackend(
        windows=[_window()],
        ax_view=AxView(available=True, root_role="AXWindow"),
    )
    payload = _payload(_tool(backend).execute(action="snapshot", window_id=101))
    assert payload["ok"] is True
    assert payload["image"] is None
    assert backend.capture_calls == []
    assert list(tmp_path.rglob("*.png")) == []


def test_vision_evidence_unavailable_fails_whole_receipt(tmp_path):
    from llm_loop.desktop.models import AxView, CaptureOutcome

    backend = FakeBackend(
        windows=[_window()],
        ax_view=AxView(available=True, root_role="AXWindow"),
        capture_outcome=CaptureOutcome(
            image=None,
            error=DesktopErrorCode.CAPTURE_UNAVAILABLE,
            detail="屏幕录制授权未授予；已拒绝调用 screencapture",
        ),
    )
    result = _tool(backend).execute(action="snapshot", window_id=101, vision="evidence")
    payload = _payload(result)
    assert payload["ok"] is False
    assert payload["error_code"] == "capture_unavailable"
    assert payload["image"] is None
    assert backend.capture_calls == [_window()]  # 后端被调用（其内部预检拒绝），无文件产生
    assert list(tmp_path.rglob("*.png")) == []


def test_vision_evidence_size_mismatch_degrades_only():
    from llm_loop.desktop.models import AxView, CaptureOutcome, ImageInfo

    image = ImageInfo(
        ref="vision://desktop/v0.1/x",
        path="/tmp/x.png",
        sha256="x" * 64,
        width=9999,
        height=1754,
        scale=2.0,
        bounds_pt=BoundsPt(0, 38, 1512, 877),
        captured_at="2026-10-27T00:00:00+00:00",
        bytes=10,
    )
    backend = FakeBackend(
        windows=[_window()],
        ax_view=AxView(available=True, root_role="AXWindow"),
        capture_outcome=CaptureOutcome(image=image, error=None, degraded=("capture_size_mismatch",)),
    )
    payload = _payload(_tool(backend).execute(action="snapshot", window_id=101, vision="evidence"))
    # 超差不算 error：ok=true + degraded 记录（U19）
    assert payload["ok"] is True
    assert payload["degraded"] == ["capture_size_mismatch"]
    assert payload["image"]["width"] == 9999


# ══ 8. 工具回执形态：apps / windows / snapshot / 审计 / U14 ═══════════════
def _app(name="Google Chrome", bundle="com.google.Chrome", pid=96579, fg=True, hidden=False):
    from llm_loop.desktop.models import AppInfo

    return AppInfo(bundle_id=bundle, name=name, pid=pid, is_foreground=fg, is_hidden=hidden)


def test_apps_receipt_marks_allowlist_false_but_keeps_rows():
    backend = FakeBackend(apps=[_app(), _app(name="1Password", bundle="com.1password.mac")])
    tool = _tool(backend, see_allowlist=("com.google.Chrome",))
    payload = _payload(tool.execute(action="apps"))
    assert payload["ok"] is True
    by_bundle = {a["bundle_id"]: a for a in payload["apps"]}
    assert by_bundle["com.google.Chrome"]["allowed"] is True
    assert by_bundle["com.1password.mac"]["allowed"] is False  # 标记，不过滤
    assert len(payload["apps"]) == 2


def test_apps_receipt_default_allowlist_all_allowed():
    backend = FakeBackend(apps=[_app(), _app(name="Finder", bundle="com.apple.finder")])
    payload = _payload(_tool(backend).execute(action="apps"))
    assert all(a["allowed"] is True for a in payload["apps"])


def test_windows_receipt_redacts_privacy_titles_u13():
    windows = [
        _window(window_id=1, title="Chrome 窗口", title_available=True),
        _window(window_id=2, bundle_id="com.1password.mac", title="我的金库", title_available=True),
        _window(window_id=3, bundle_id="com.apple.keychainaccess", title="钥匙串访问", title_available=True),
    ]
    payload = _payload(_tool(FakeBackend(windows=windows)).execute(action="windows"))
    by_id = {w["window_id"]: w for w in payload["windows"]}
    assert by_id[1]["title"] == "Chrome 窗口"
    assert by_id[1]["title_redacted"] is False
    assert by_id[2]["title"] is None
    assert by_id[2]["title_redacted"] is True
    assert by_id[3]["title"] is None
    assert by_id[3]["title_redacted"] is True


def test_windows_receipt_allowlist_miss_redacts_title_u14():
    windows = [
        _window(window_id=1, title="允许的", title_available=True),
        _window(window_id=2, pid=500, app="Finder", bundle_id="com.apple.finder",
                title="桌面", title_available=True),
    ]
    tool = _tool(FakeBackend(windows=windows), see_allowlist=("com.google.Chrome",))
    payload = _payload(tool.execute(action="windows"))
    by_id = {w["window_id"]: w for w in payload["windows"]}
    assert by_id[1]["title"] == "允许的"
    assert by_id[2]["title"] is None
    assert by_id[2]["title_redacted"] is True


def test_windows_include_offscreen_passthrough():
    windows = [_window(window_id=1, on_screen=True), _window(window_id=2, on_screen=False)]
    backend = FakeBackend(windows=windows)
    payload = _payload(_tool(backend).execute(action="windows", include_offscreen=True))
    assert backend.windows_calls == [True]
    assert {w["window_id"] for w in payload["windows"]} == {1, 2}
    payload_onscreen = _payload(_tool(backend).execute(action="windows"))
    assert backend.windows_calls == [True, False]
    assert {w["window_id"] for w in payload_onscreen["windows"]} == {1}


def test_snapshot_privacy_blocked_zero_ax_zero_capture_no_l0():
    backend = FakeBackend(
        windows=[
            _window(
                window_id=7,
                bundle_id="com.bitwarden.desktop",
                title="金库",
                title_available=True,
            )
        ]
    )
    tool = _tool(backend)
    payload = _payload(tool.execute(action="snapshot", window_id=7))
    assert payload["ok"] is False
    assert payload["error_code"] == "privacy_blocked"
    assert "window" not in payload  # 连 L0 也不给
    assert backend.ax_calls == []  # 零 AX 遍历
    assert backend.capture_calls == []  # 零截图


def test_snapshot_app_not_allowed_zero_ax_zero_capture_keeps_l0_redacted():
    backend = FakeBackend(
        windows=[_window(window_id=8, bundle_id="com.unlisted.app", title="窗口", title_available=True)]
    )
    tool = _tool(backend, see_allowlist=("com.google.Chrome",))
    payload = _payload(tool.execute(action="snapshot", window_id=8))
    assert payload["ok"] is False
    assert payload["error_code"] == "app_not_allowed"
    assert backend.ax_calls == []
    assert backend.capture_calls == []
    assert payload["window"]["title"] is None  # L0 保留但标题隐去
    assert payload["window"]["title_redacted"] is True


def test_snapshot_default_empty_allowlist_not_blocked():
    backend = FakeBackend(windows=[_window()])
    payload = _payload(_tool(backend).execute(action="snapshot", window_id=101))
    assert payload["ok"] is True
    assert payload["error_code"] is None


def test_snapshot_happy_receipt_shape():
    from llm_loop.desktop.models import AxNode, AxView

    ax_view = AxView(
        available=True,
        root_role="AXWindow",
        nodes=(
            AxNode(ax_ref="0", role="AXWindow", subrole=None, title="主窗口", value=None,
                   focused=True, pos_pt=Pt(x=0.0, y=38.0), size_pt=Size(w=1512.0, h=877.0)),
            AxNode(ax_ref="0.0", role="AXButton", subrole="AXCloseButton", title="关闭",
                   value=None, focused=False, pos_pt=None, size_pt=None),
        ),
    )
    backend = FakeBackend(windows=[_window()], ax_view=ax_view)
    payload = _payload(_tool(backend).execute(action="snapshot", window_id=101))
    assert payload["ok"] is True
    assert payload["window"]["window_id"] == 101
    assert payload["ax"]["available"] is True
    assert payload["ax"]["root_role"] == "AXWindow"
    assert payload["ax"]["node_count"] == 2
    assert payload["ax"]["nodes"][1]["ax_ref"] == "0.0"
    assert payload["degraded"] == []
    assert payload["image"] is None


def test_snapshot_depth_clipped_receipt():
    from llm_loop.desktop.models import AxView

    backend = FakeBackend(windows=[_window()], ax_view=AxView(available=True, root_role="AXWindow"))
    payload = _payload(_tool(backend).execute(action="snapshot", window_id=101, depth=9))
    assert payload["ax"]["clipped_depth"] is True
    assert backend.ax_calls[0]["depth"] == 6
    payload_ok = _payload(_tool(backend).execute(action="snapshot", window_id=101, depth=4))
    assert payload_ok["ax"]["clipped_depth"] is False
    assert backend.ax_calls[1]["depth"] == 4


def test_every_receipt_has_envelope_keys():
    backend = FakeBackend(windows=[_window()])
    tool = _tool(backend)
    for kwargs in (
        {"action": "status"},
        {"action": "apps"},
        {"action": "windows"},
        {"action": "snapshot", "window_id": 101},
        {"action": "snapshot", "window_id": 424242},  # 错误路径也带全信封
    ):
        payload = _payload(tool.execute(**kwargs))
        for key in ("ok", "action", "error_code", "guidance", "permissions",
                    "platform", "session", "elapsed_ms"):
            assert key in payload, (kwargs, key)
        assert set(payload["permissions"]) <= {"ax_trusted", "screen_capture_granted", "ax_error"}
        assert "os" in payload["platform"] and "version" in payload["platform"]


def test_failure_receipts_are_json_and_toolresult_failure():
    backend = FakeBackend(windows=[_window(window_id=9, bundle_id="com.apple.loginwindow")])
    result = _tool(backend).execute(action="snapshot", window_id=9)
    assert result.status.value == "failure"  # ok=false ⇒ ToolResult FAILURE，内容仍是 JSON 回执
    payload = json.loads(result.content)
    assert payload["error_code"] == "privacy_blocked"


# ══ 9. 审计 JSONL（§6.4）══════════════════════════════════════════════════
def test_audit_rows_for_vision_evidence_and_privacy(tmp_path):
    from llm_loop.desktop.models import AxView, CaptureOutcome, ImageInfo

    audit_path = tmp_path / "audit" / "desktop_perceive.jsonl"
    image = ImageInfo(
        ref="vision://desktop/v0.1/abc", path=str(tmp_path / "w.png"), sha256="a" * 64,
        width=3024, height=1754, scale=2.0, bounds_pt=BoundsPt(0, 38, 1512, 877),
        captured_at="2026-10-27T00:00:00+00:00", bytes=99,
    )
    backend = FakeBackend(
        windows=[
            _window(),
            _window(window_id=5, bundle_id="com.1password.mac", title="x", title_available=True),
        ],
        ax_view=AxView(available=True, root_role="AXWindow"),
        capture_outcome=CaptureOutcome(image=image, error=None),
    )
    tool = DesktopPerceiveTool(
        backend=backend,
        session_id_getter=lambda: "sess-audit",
        audit_sink=make_jsonl_audit_sink(audit_path),
    )
    _payload(tool.execute(action="snapshot", window_id=101, vision="evidence"))
    _payload(tool.execute(action="snapshot", window_id=5))
    lines = [json.loads(line) for line in audit_path.read_text().splitlines()]
    assert len(lines) == 2
    evidence_row, privacy_row = lines
    assert evidence_row["sha256"] == "a" * 64
    assert evidence_row["risk_class"] == "see"
    assert evidence_row["window_id"] == 101
    assert evidence_row["app_bundle"] == "com.google.Chrome"
    assert evidence_row["error_code"] is None
    assert evidence_row["tool"] == "desktop_perceive"
    assert evidence_row["session_id"] == "sess-audit"
    assert privacy_row["error_code"] == "privacy_blocked"
    assert privacy_row["sha256"] is None
    for row in lines:
        assert set(row) == {"ts", "session_id", "tool", "window_id", "app_bundle",
                            "risk_class", "error_code", "sha256"}


def test_audit_vision_none_writes_nothing(tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    from llm_loop.desktop.models import AxView

    backend = FakeBackend(windows=[_window()], ax_view=AxView(available=True, root_role="AXWindow"))
    tool = DesktopPerceiveTool(
        backend=backend,
        session_id_getter=lambda: "s",
        audit_sink=make_jsonl_audit_sink(audit_path),
    )
    _payload(tool.execute(action="snapshot", window_id=101))
    assert not audit_path.exists()  # vision=none 无截图诉求 → 不写审计


def test_audit_append_only_no_rewrite(tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    sink = make_jsonl_audit_sink(audit_path)
    sink({"n": 1})
    first_line = audit_path.read_text().splitlines()[0]
    sink({"n": 2})
    lines = audit_path.read_text().splitlines()
    assert lines[0] == first_line  # 追加不改写历史行
    assert lines[1] == json.dumps({"n": 2}, sort_keys=True)


# ══ 10. schema 与 factory 装配一致性 ══════════════════════════════════════
def test_tool_schema_contract_fields():
    params = DesktopPerceiveTool.parameters
    assert params["properties"]["action"]["enum"] == ["status", "apps", "windows", "snapshot"]
    assert params["required"] == ["action"]
    assert params["additionalProperties"] is False
    assert params["properties"]["vision"]["enum"] == ["none", "evidence"]
    assert params["properties"]["depth"]["minimum"] == 0
    assert params["properties"]["depth"]["maximum"] == 6
    assert DesktopPerceiveTool.lazy_parameters == DesktopPerceiveTool.parameters


def test_compact_description_registered():
    from llm_loop.tools.registry import _COMPACT_TOOL_DESCRIPTIONS

    compact = _COMPACT_TOOL_DESCRIPTIONS["desktop_perceive"]
    assert "只读" in compact
    assert "vision=evidence" in compact


def test_factory_registers_desktop_perceive(tmp_path):
    from llm_loop.config import Settings
    from llm_loop.factory import build_engine

    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
    )
    engine = build_engine(settings)  # type: ignore[arg-type]
    assert "desktop_perceive" in engine.registry.names()
    schemas = {entry["name"]: entry for entry in engine.registry.schemas()}
    desktop = schemas["desktop_perceive"]
    assert desktop["parameters"]["required"] == ["action"]
    lazy = {entry["name"]: entry for entry in engine.registry.schemas(lazy=True)}
    assert "desktop_perceive" in lazy
    assert "只读" in lazy["desktop_perceive"]["description"]


def test_config_env_names_parse(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://x/v1")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("LFL_DESKTOP_PRIVACY_EXTRA", "com.bank.app, x.y")
    monkeypatch.setenv("LFL_DESKTOP_SEE_ALLOWLIST", "com.google.Chrome")
    from llm_loop.config import load_settings

    settings = load_settings()
    assert settings.desktop_privacy_extra == "com.bank.app, x.y"
    assert settings.desktop_see_allowlist == "com.google.Chrome"


# ── 能力真值取自实测探针，不取 AXIsProcessTrusted()（2026-10-27 假阴性反证） ──


def test_ax_readable_prefers_probe_over_trust_flag(monkeypatch):
    from llm_loop.desktop import backend_macos, macos_permissions

    monkeypatch.setattr(macos_permissions, "ax_error_probe", lambda: 0)
    monkeypatch.setattr(macos_permissions, "ax_trusted", lambda: False)
    assert backend_macos._ax_readable() is True

    monkeypatch.setattr(macos_permissions, "ax_error_probe", lambda: AX_ERROR_API_DISABLED)
    monkeypatch.setattr(macos_permissions, "ax_trusted", lambda: True)
    assert backend_macos._ax_readable() is False


def test_ax_readable_falls_back_to_trust_when_probe_unavailable(monkeypatch):
    from llm_loop.desktop import backend_macos, macos_permissions

    monkeypatch.setattr(macos_permissions, "ax_error_probe", lambda: None)
    monkeypatch.setattr(macos_permissions, "ax_trusted", lambda: True)
    assert backend_macos._ax_readable() is True


def test_status_no_ax_guidance_when_probe_readable_despite_trust_false():
    """信任位为 false 但探针可读时，不得催用户去授权（假阴性会把用户赶去做无用动作）。"""
    backend = FakeBackend(
        perms=PermissionSnapshot(
            ax_trusted=False, screen_capture_granted=True, ax_error=0
        )
    )
    backend.capability_snapshot = lambda: {  # type: ignore[method-assign]
        "can_list_windows": True,
        "can_read_ax": True,
        "can_capture": True,
    }
    payload = _payload(_tool(backend).execute(action="status"))
    assert payload["permissions"]["ax_trusted"] is False
    assert payload["capability"]["can_read_ax"] is True
    assert payload["guidance"] is None


def test_status_ax_guidance_when_probe_disabled_despite_trust_true():
    backend = FakeBackend(
        perms=PermissionSnapshot(
            ax_trusted=True, screen_capture_granted=True, ax_error=AX_ERROR_API_DISABLED
        )
    )
    backend.capability_snapshot = lambda: {  # type: ignore[method-assign]
        "can_list_windows": True,
        "can_read_ax": False,
        "can_capture": True,
    }
    payload = _payload(_tool(backend).execute(action="status"))
    assert payload["capability"]["can_read_ax"] is False
    assert "辅助功能" in payload["guidance"]


def test_frontmost_pid_skips_nonzero_layer():
    from llm_loop.desktop.backend_macos import _frontmost_pid

    rows = [
        {"layer": 20, "pid": 11},
        {"layer": None, "pid": 12},
        {"layer": 0, "pid": 13},
        {"layer": 0, "pid": 14},
    ]
    assert _frontmost_pid(rows) == 13
    assert _frontmost_pid([]) is None


def test_ax_readable_uses_real_app_probe_when_frontmost_known(monkeypatch):
    """探针即实际路径：前台 pid 上 AXWindows 可读 → true（哪怕授权位与 systemwide 均为假）。"""
    from llm_loop.desktop import backend_macos, macos_ax, macos_permissions

    seen: list[int] = []

    def fake_probe(pid: int) -> int:
        seen.append(pid)
        return 0

    monkeypatch.setattr(macos_ax, "ax_readable_probe", fake_probe)
    monkeypatch.setattr(macos_permissions, "ax_trusted", lambda: False)
    monkeypatch.setattr(macos_permissions, "ax_error_probe", lambda: None)

    assert backend_macos._ax_readable([{"layer": 0, "pid": 4242}]) is True
    assert seen == [4242]


def test_ax_readable_false_when_real_app_probe_denied(monkeypatch):
    from llm_loop.desktop import backend_macos, macos_ax, macos_permissions

    monkeypatch.setattr(macos_ax, "ax_readable_probe", lambda pid: AX_ERROR_API_DISABLED)
    monkeypatch.setattr(macos_permissions, "ax_error_probe", lambda: AX_ERROR_API_DISABLED)
    monkeypatch.setattr(macos_permissions, "ax_trusted", lambda: True)

    assert backend_macos._ax_readable([{"layer": 0, "pid": 99}]) is False



