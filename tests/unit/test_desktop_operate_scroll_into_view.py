# scroll_into_view（AXScrollToVisible）单测——fixture 照抄 tests/unit/test_desktop_operate_m4_v01.py
"""desktop_operate 新增 do=scroll_into_view：门控/令牌/投递与入口拒收。

Offline fixtures only（fake backend + fake AX 视图）。会话级状态经真实派发
路径（ToolRegistry.execute → ToolCall）顺序调用验证；每个拒绝用例同时断言
零投递（backend.act_calls 为空——"refusals must actually refuse"），
并证明既有门控未退化：dry_run 签发一次性 confirm_token、apply 需令牌、
point 通道/缺 target/text/keys 一律入口拒绝、risk_class 保持 act。
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
    PermissionSnapshot,
    PlatformInfo,
    Pt,
    SessionSnapshot,
    Size,
    WindowInfo,
)
from llm_loop.desktop.operate import channel_risk_override, classify_risk
from llm_loop.tools.builtin.desktop_operate import DesktopOperateTool
from llm_loop.tools.registry import ToolRegistry


# ── 离线替身（与 m4 v01 同构的最小子集 + act_scroll_into_view）──────────────
def _node(ax_ref: str, role: str = "AXButton", title: str | None = None,
          subrole: str | None = None, value: str | None = None, *,
          focused: bool = False, pos: tuple[float, float] | None = None,
          size: tuple[float, float] | None = None) -> AxNode:
    return AxNode(ax_ref=ax_ref, role=role, subrole=subrole, title=title,
                  value=value, focused=focused,
                  pos_pt=Pt(*pos) if pos else None,
                  size_pt=Size(*size) if size else None)


def _view(*nodes: AxNode) -> AxView:
    return AxView(available=True, root_role="AXWindow", nodes=nodes, binding="title_exact")


DEFAULT_VIEW = _view(
    _node("0", "AXWindow", "某文档"),
    _node("0.0", "AXButton", "新建"),
    _node("0.1", "AXTextArea", "正文", value=""),
)


def _window(window_id=101, pid=96579, app="Google Chrome", bundle_id="com.google.Chrome",
            title="某文档 - Google Chrome", bounds=(0.0, 38.0, 1512.0, 877.0),
            on_screen=True, is_foreground=True) -> WindowInfo:
    return WindowInfo(
        window_id=window_id, pid=pid, app=app, bundle_id=bundle_id,
        title=title, title_available=True, title_redacted=False,
        bounds_pt=BoundsPt(*bounds), layer=0, on_screen=on_screen,
        is_foreground=is_foreground,
    )


class FakeOperateBackend:
    supported = True

    def __init__(self, *, windows, ax_views=None, hid_idle=120_000, ax_probe=0,
                 session=None, perms=None) -> None:
        self.windows = list(windows)
        self._ax_views = dict(ax_views or {})
        self.hid_idle = hid_idle
        self.ax_probe_result = ax_probe
        self._session = session or SessionSnapshot(
            gui_available=True, console_user="tester", screen_locked=False
        )
        self._perms = perms or PermissionSnapshot(
            ax_trusted=True, screen_capture_granted=True, ax_error=None
        )
        self.act_calls: list[dict] = []

    def platform_info(self) -> PlatformInfo:
        return PlatformInfo(os="darwin", version="15.0")

    def session_snapshot(self) -> SessionSnapshot:
        return self._session

    def permission_snapshot(self) -> PermissionSnapshot:
        return self._perms

    def get_window(self, window_id: int):
        for w in self.windows:
            if w.window_id == int(window_id):
                return w
        return None

    def ax_snapshot(self, window, depth, node_limit):
        return self._ax_views.get(window.window_id, DEFAULT_VIEW)

    def hid_idle_ms(self):
        return self.hid_idle

    def frontmost_app_bundle(self):
        return next(
            (w.bundle_id for w in self.windows if w.is_foreground and w.on_screen), None
        )

    def ax_probe(self, pid: int):
        return self.ax_probe_result

    def act_scroll_into_view(self, window, ax_ref):
        self.act_calls.append({"do": "scroll_into_view", "window_id": window.window_id,
                               "ax_ref": ax_ref})
        return ActOutcome(ok=True)


def _backend(**kw) -> FakeOperateBackend:
    kw.setdefault("windows", [_window()])
    return FakeOperateBackend(**kw)


def _tool(backend: FakeOperateBackend, **kwargs) -> DesktopOperateTool:
    kwargs.setdefault("writes_enabled", True)
    return DesktopOperateTool(
        backend=backend, session_id_getter=lambda: "sess-scroll-into-view", **kwargs
    )


_IDS = itertools.count()


def _registry(tool) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(tool)
    return reg


def _dispatch(registry: ToolRegistry, **kwargs) -> dict:
    """真实派发路径：registry.execute(ToolCall) → 回执 JSON。"""
    result = registry.execute(
        ToolCall(id=f"siv-{next(_IDS)}", name="desktop_operate", arguments=kwargs)
    )
    return json.loads(result.content)


def _direct(tool: DesktopOperateTool, **kwargs) -> dict:
    return json.loads(tool.execute(**kwargs).content)


SIV_101 = {"do": "scroll_into_view", "window_id": 101, "target": {"ax_ref": "0.0"}}


# ══ 1. dry_run：签发令牌、不投递、risk_class=act ═════════════════════════════
def test_dry_run_issues_token_without_delivery():
    backend = _backend()
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, **SIV_101, dry_run=True)
    assert dry["ok"] is True
    assert dry["applied"] is False
    assert dry["needs_confirmation"] is True
    assert str(dry["confirm_token"]).startswith("dtkm-")
    assert dry["risk_class"] == "act"  # 需求：滚动可逆，不进 irreversible
    assert backend.act_calls == []  # dry_run 零投递


# ══ 2. apply：带一次性令牌 → backend.act_scroll_into_view(window_id, ax_ref) ══
def test_apply_with_token_reaches_act_scroll_into_view():
    backend = _backend()
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, **SIV_101, dry_run=True)
    ok = _dispatch(reg, **SIV_101, dry_run=False, confirm_token=dry["confirm_token"])
    assert ok["ok"] is True
    assert ok["applied"] is True
    assert ok["risk_class"] == "act"
    assert backend.act_calls == [
        {"do": "scroll_into_view", "window_id": 101, "ax_ref": "0.0"}
    ]


def test_apply_without_token_refused_no_delivery():
    backend = _backend()
    payload = _direct(_tool(backend), **SIV_101, dry_run=False)
    assert payload["ok"] is False
    assert payload["applied"] is False
    assert backend.act_calls == []  # 拒绝必须真的拒绝


# ══ 3. point 通道：入口拒绝（invalid_args，fields_mismatch 文案）═════════════
def test_point_target_rejected_invalid_args():
    backend = _backend()
    payload = _direct(_tool(backend), do="scroll_into_view", window_id=101,
                      target={"point": {"x": 755.5, "y": 476.5}}, dry_run=True)
    assert payload["ok"] is False
    assert payload["error_code"] == "invalid_args"
    assert "fields_mismatch" in payload["guidance"]
    assert "只接受 target={ax_ref}" in payload["guidance"]
    assert backend.act_calls == []


# ══ 4. 缺 target：拒绝 ══════════════════════════════════════════════════════
def test_missing_target_rejected():
    backend = _backend()
    payload = _direct(_tool(backend), do="scroll_into_view", window_id=101, dry_run=True)
    assert payload["ok"] is False
    assert payload["error_code"] == "invalid_args"
    assert "target 必填" in payload["guidance"]
    assert backend.act_calls == []


# ══ 5. text/keys 同时给：fields_mismatch 拒绝 ═══════════════════════════════
def test_text_or_keys_rejected_fields_mismatch():
    backend = _backend()
    with_text = _direct(_tool(backend), do="scroll_into_view", window_id=101,
                        target={"ax_ref": "0.0"}, text="hi", dry_run=True)
    assert with_text["ok"] is False
    assert with_text["error_code"] == "invalid_args"
    assert "fields_mismatch" in with_text["guidance"]
    with_keys = _direct(_tool(backend), do="scroll_into_view", window_id=101,
                        target={"ax_ref": "0.0"}, keys="down", dry_run=True)
    assert with_keys["ok"] is False
    assert with_keys["error_code"] == "invalid_args"
    assert "fields_mismatch" in with_keys["guidance"]
    assert backend.act_calls == []


# ══ 6. 风险分级与接线：act（含浏览器 ax_ref 通道不被抬升）════════════════════
def test_risk_is_act_and_backend_wiring_present():
    # classify_risk 默认分支：scroll_into_view 不命中任何 irreversible 判据
    assert classify_risk("scroll_into_view", bundle_id="com.apple.finder",
                         role="AXButton", subrole=None, title="段落标题",
                         keys=None) == "act"
    # channel_risk_override 只抬升 point/press_key/scroll；ax_ref 通道保持 act
    # （浏览器网页层目标由 _resolve_ax_ref_target 的路线 A 边界另行拒绝）
    assert channel_risk_override("act", browser=True, do="scroll_into_view",
                                 target_kind="ax_ref") == "act"
    # 投递面已接线（_deliver 不会 AttributeError）
    assert callable(macos_actuate.ax_scroll_to_visible)
    assert callable(MacOSDesktopBackend.act_scroll_into_view)
