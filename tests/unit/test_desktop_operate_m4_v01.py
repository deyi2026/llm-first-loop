# M4 desktop_operate tests (DESIGN-20261027 §5.4/§6/§9 U13-U20; RULE-AI-35 refusals)
"""M4 desktop narrow actuation: gating / tokens / allowlists / delivery.

Offline fixtures only (fake backend, fake AX views, injectable HID idle).
Session-level state (act approval, one-time token burn, force-credential
consumption) is verified THROUGH THE REAL DISPATCH PATH (ToolRegistry.execute
on a registered tool instance) with sequential calls — direct tool-object
calls alone have a known blind spot for session/ContextVar state.

Every refusal asserts the deterministic receipt AND the absence of delivery
(no act_* call reached the backend) — "refusals must actually refuse".
"""

from __future__ import annotations

import itertools
import json
import re
from pathlib import Path

import pytest

from llm_loop.core.message import ToolCall
from llm_loop.desktop import macos_actuate, macos_ax
from llm_loop.desktop.backend_macos import MacOSDesktopBackend, backend_for_platform
from llm_loop.desktop.macos_capture import check_capture_size
from llm_loop.desktop.models import (
    AX_ERROR_API_DISABLED,
    AX_NODE_LIMIT_DEFAULT,
    ActOutcome,
    AxNode,
    AxView,
    BoundsPt,
    DesktopErrorCode,
    PermissionSnapshot,
    PlatformInfo,
    Pt,
    SessionSnapshot,
    Size,
    WindowInfo,
)
from llm_loop.desktop.operate import (
    CONFIRM_TOKEN_MAX_RECORDS,
    CONFIRM_TOKEN_TTL_S,
    CORE_ACT_ALLOWLIST,
    KEY_KEYCODES,
    SESSION_APPROVAL_MAX_SESSIONS,
    SESSION_APPROVAL_TTL_S,
    ActAllowlist,
    ConfirmTokenStore,
    SessionActGate,
    action_fingerprint,
    classify_risk,
    parse_keycombo,
    parse_scroll,
    session_target_key,
    world_fingerprint,
)
from llm_loop.desktop.privacy import PrivacyPolicy
from llm_loop.tools.builtin.desktop_operate import DesktopOperateTool
from llm_loop.tools.builtin.desktop_perceive import make_jsonl_audit_sink
from llm_loop.tools.registry import ToolRegistry


# ── 离线替身 ────────────────────────────────────────────────────────────────
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


_FRONTMOST_UNSET = object()  # R5：未显式指定 → 按窗口表 fg 标志推导（兼容既有用例）


class FakeOperateBackend:
    supported = True

    def __init__(self, *, windows, ax_views=None, hid_idle=120_000, ax_probe=0,
                 session=None, perms=None, frontmost=_FRONTMOST_UNSET) -> None:
        # R5：frontmost 显式模拟「lsappinfo front+list」前台 app 探测——str=命中
        # bundle；None=探测失败（fail-closed 负例）；UNSET=按窗口表 fg 推导。
        self.frontmost_override = frontmost
        self.frontmost_calls = 0
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
        self.windows_calls = 0
        self.ax_node_limits: list[int] = []

    def platform_info(self) -> PlatformInfo:
        return PlatformInfo(os="darwin", version="15.0")

    def session_snapshot(self) -> SessionSnapshot:
        return self._session

    def permission_snapshot(self) -> PermissionSnapshot:
        return self._perms

    def list_windows(self, include_offscreen: bool = False):
        self.windows_calls += 1
        return [w for w in self.windows if include_offscreen or w.on_screen]

    def get_window(self, window_id: int):
        for w in self.windows:
            if w.window_id == int(window_id):
                return w
        return None

    def ax_snapshot(self, window, depth, node_limit):
        self.ax_node_limits.append(int(node_limit))  # S9：记录 cap 断言用
        return self._ax_views.get(window.window_id, DEFAULT_VIEW)

    def hid_idle_ms(self):
        return self.hid_idle

    def frontmost_app_bundle(self):
        """R5 台面：真后台为 lsappinfo front+list（backend_macos）；离线替身。

        UNSET 时按窗口表 fg 标志推导（等价旧行为，兼容既有用例）；显式 str/None
        用于构造「CG 序窗口序 ≠ lsappinfo 前台 app」的解耦场景。
        """
        self.frontmost_calls += 1
        if self.frontmost_override is not _FRONTMOST_UNSET:
            return self.frontmost_override
        return next(
            (w.bundle_id for w in self.windows if w.is_foreground and w.on_screen), None
        )

    def ax_probe(self, pid: int):
        return self.ax_probe_result

    def act_press(self, window, ax_ref):
        self.act_calls.append({"do": "click", "window_id": window.window_id, "ax_ref": ax_ref})
        return ActOutcome(ok=True)

    def act_set_value(self, window, ax_ref, text):
        self.act_calls.append({"do": "type", "window_id": window.window_id,
                               "ax_ref": ax_ref, "text": text})
        return ActOutcome(ok=True, verified=True)

    def act_click_point(self, x_pt, y_pt):
        self.act_calls.append({"do": "click_point", "x": x_pt, "y": y_pt})
        return ActOutcome(ok=True)

    def act_key(self, keycode, flags):
        self.act_calls.append({"do": "press_key", "keycode": keycode, "flags": flags})
        return ActOutcome(ok=True)

    def act_scroll(self, window, signed_lines):
        self.act_calls.append({"do": "scroll", "window_id": window.window_id,
                               "signed_lines": signed_lines})
        return ActOutcome(ok=True)


def _backend(**kw) -> FakeOperateBackend:
    kw.setdefault("windows", [_window()])
    return FakeOperateBackend(**kw)


def _tool(backend: FakeOperateBackend, **kwargs) -> DesktopOperateTool:
    kwargs.setdefault("writes_enabled", True)
    return DesktopOperateTool(
        backend=backend, session_id_getter=lambda: "sess-m4-test", **kwargs
    )


_IDS = itertools.count()


def _registry(tool) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(tool)
    return reg


def _dispatch(registry: ToolRegistry, **kwargs) -> dict:
    """真实派发路径：registry.execute(ToolCall) → 回执 JSON。"""
    result = registry.execute(
        ToolCall(id=f"m4-{next(_IDS)}", name="desktop_operate", arguments=kwargs)
    )
    return json.loads(result.content)


def _direct(tool: DesktopOperateTool, **kwargs) -> dict:
    return json.loads(tool.execute(**kwargs).content)


CLICK_101 = {"do": "click", "window_id": 101, "target": {"ax_ref": "0.0"}}


# ══ 1. 纯逻辑：风险分级 / 键解析 / 白名单 / 指纹 ═══════════════════════════
def test_classify_risk_heuristics_conservative():
    assert classify_risk("click", bundle_id="com.apple.finder", role="AXButton",
                         subrole=None, title="新建文件夹", keys=None) == "act"
    # 关闭按钮：无法验证未保存状态 → irreversible
    # R6/P1：真机编码 role=AXButton + subrole=AXCloseButton（父会话 live 实测 +
    # 本仓 R3 fake 树一致）必须命中；旧编码 role=AXCloseButton 兼容保留。
    assert classify_risk("click", bundle_id="com.apple.finder", role="AXButton",
                         subrole="AXCloseButton", title=None, keys=None) == "irreversible"
    assert classify_risk("click", bundle_id="com.apple.finder", role="AXButton",
                         subrole="axclosebutton", title=None, keys=None) == "irreversible"
    assert classify_risk("click", bundle_id="com.apple.finder", role="AXCloseButton",
                         subrole=None, title=None, keys=None) == "irreversible"
    # 核对清单：最小化/全屏按钮（真机同为 AXButton+subrole）是可逆动作，保持 act
    assert classify_risk("click", bundle_id="com.apple.preview", role="AXButton",
                         subrole="AXMinimizeButton", title=None, keys=None) == "act"
    assert classify_risk("click", bundle_id="com.apple.preview", role="AXButton",
                         subrole="AXZoomButton", title=None, keys=None) == "act"
    # 关键词命中（中/英、大小写）
    assert classify_risk("click", bundle_id="com.apple.finder", role="AXButton",
                         subrole=None, title="删除该项", keys=None) == "irreversible"
    assert classify_risk("click", bundle_id="com.google.Chrome", role="AXButton",
                         subrole=None, title="Publish", keys=None) == "irreversible"
    # 浏览器 Enter（表单提交经典触发键）→ irreversible；Finder Enter → act
    assert classify_risk("press_key", bundle_id="com.google.Chrome", role=None,
                         subrole=None, title=None, keys="Enter") == "irreversible"
    assert classify_risk("press_key", bundle_id="com.apple.finder", role=None,
                         subrole=None, title=None, keys="Enter") == "act"


def test_parse_keycombo_closed_set_and_blacklist():
    assert parse_keycombo("Enter")[0] == "ok"
    assert parse_keycombo("ctrl+shift+Tab")[:2] == ("ok", "ctrl+shift+tab")
    assert parse_keycombo("ctrl+shift+Tab")[2] == 0x1_0000 | 0x2_0000
    # U5/B3 黑名单族：Meta 系一律拒绝
    assert parse_keycombo("Meta+W")[0] == "blacklist"
    assert parse_keycombo("Cmd+Q")[0] == "blacklist"
    assert parse_keycombo("Ctrl+Cmd+Q")[0] == "blacklist"
    assert parse_keycombo("Meta+Tab")[0] == "blacklist"
    # 字母键：CGEvent 通道被 IME 污染（实测），不提供
    assert parse_keycombo("A")[0] == "not_allowed"
    assert parse_keycombo("ctrl+a")[0] == "not_allowed"
    # 未知名 / 裸修饰键
    assert parse_keycombo("Magic")[0] == "not_allowed"
    assert parse_keycombo("ctrl")[0] == "not_allowed"
    assert parse_keycombo("")[0] == "invalid"


def test_parse_scroll_spec():
    assert parse_scroll("down") == ("ok", "down", -3)
    assert parse_scroll("up:5") == ("ok", "up", 5)
    assert parse_scroll("down:0")[0] == "invalid"
    assert parse_scroll("down:99")[0] == "invalid"
    assert parse_scroll("sideways")[0] == "invalid"
    assert parse_scroll("")[0] == "invalid"


def test_act_allowlist_core_and_terminal_readonly():
    allow = ActAllowlist()
    assert allow.core_items == CORE_ACT_ALLOWLIST
    assert allow.is_actable("com.apple.finder") == (True, "ok")
    assert allow.is_actable("com.apple.safari") == (True, "ok")
    assert allow.is_actable("com.google.chrome") == (True, "ok")  # 大小写归一
    assert allow.is_actable("com.apple.preview") == (True, "ok")
    assert allow.is_actable("com.example.Notes")[1] == "not_in_allowlist"
    # 终端/IDE 只读：追加白名单也不能放开（T3）
    assert allow.is_terminal_or_ide("com.apple.Terminal") is True
    assert allow.is_terminal_or_ide("com.googlecode.iterm2") is True
    assert allow.is_terminal_or_ide("com.microsoft.VSCode") is True
    assert allow.is_terminal_or_ide("com.jetbrains.pycharm") is True
    widened = ActAllowlist(extra=("com.apple.terminal", "com.example.notes"))
    assert widened.is_actable("com.apple.Terminal") == (False, "terminal_readonly")
    assert widened.is_actable("com.example.notes") == (True, "ok")  # 追加只对非终端生效


def test_world_fingerprint_value_excluded_title_sensitive():
    a = world_fingerprint(_window(), DEFAULT_VIEW.nodes, "com.google.Chrome")
    # value 变化（type 写入本身会改 value）不得打破 pre 指纹
    nodes2 = (_node("0", "AXWindow", "某文档"),
              _node("0.0", "AXButton", "新建"),
              _node("0.1", "AXTextArea", "正文", value="typed-text"))
    assert world_fingerprint(_window(), nodes2, "com.google.Chrome") == a
    # 标题/前台/树形变化必须打破
    assert world_fingerprint(_window(title="别的"), DEFAULT_VIEW.nodes, "com.google.Chrome") != a
    assert world_fingerprint(_window(), DEFAULT_VIEW.nodes, "com.apple.finder") != a
    nodes3 = (_node("0", "AXWindow", "某文档"), _node("0.0", "AXButton", "改名"))
    assert world_fingerprint(_window(), nodes3, "com.google.Chrome") != a
    # include_value 时 value 参与指纹（post_sha256 语义）
    assert world_fingerprint(_window(), nodes2, "com.google.Chrome", include_value=True) != a


def test_token_store_one_shot_and_bindings():
    store = ConfirmTokenStore()
    fp = action_fingerprint("click", 101, {"kind": "ax_ref", "ax_ref": "0.0"}, None, None)
    token = store.issue(window_id=101, do="click", action_fp=fp,
                        world_version="w1", risk_class="act")
    assert token.startswith("dtkm-")
    # 错 window：mismatch 且令牌已烧
    status, _ = store.redeem(token, window_id=102, do="click", action_fp=fp)
    assert status == "mismatch"
    # 重放：replayed（已知令牌任何展示都烧）
    status, _ = store.redeem(token, window_id=101, do="click", action_fp=fp)
    assert status == "replayed"
    # 未知令牌：invalid
    assert store.redeem("dtkm-deadbeef", window_id=101, do="click", action_fp=fp)[0] == "invalid"
    # 正常一次性：issue→ok→replay 拒
    token2 = store.issue(window_id=101, do="click", action_fp=fp,
                         world_version="w1", risk_class="act")
    assert store.redeem(token2, window_id=101, do="click", action_fp=fp)[0] == "ok"
    assert store.redeem(token2, window_id=101, do="click", action_fp=fp)[0] == "replayed"


def test_session_gate_approval_and_force_consumption():
    gate = SessionActGate()
    # R6/P2-1：放行记账带目标身份键（session_target_key：window+稳定寻址）
    k0 = session_target_key(101, {"kind": "ax_ref", "ax_ref": "0.0"})
    assert gate.is_approved("s1", "com.google.Chrome", "click", target_key=k0) is False
    gate.mark_approved("s1", "com.google.Chrome", "click", target_key=k0)
    assert gate.is_approved("s1", "com.google.Chrome", "click", target_key=k0) is True
    assert gate.is_approved("s1", "com.google.Chrome", "type", target_key=k0) is False  # 同 do 才放行
    assert gate.is_approved("s2", "com.google.Chrome", "click", target_key=k0) is False  # 会话隔离
    assert gate.is_approved("s1", "com.apple.finder", "click", target_key=k0) is False  # 同 app 才放行
    # R6/P2-1：同 app 同 do 换目标（不同 ax_ref / 换窗口）→ 不放行
    assert gate.is_approved(
        "s1", "com.google.Chrome", "click",
        target_key=session_target_key(101, {"kind": "ax_ref", "ax_ref": "0.3"}),
    ) is False
    assert gate.is_approved(
        "s1", "com.google.Chrome", "click",
        target_key=session_target_key(107, {"kind": "ax_ref", "ax_ref": "0.0"}),
    ) is False
    # 目标键口径：text/keys 不入键（type 换文本/press_key 换键=同目标）；point 坐标数值归一
    assert k0 == session_target_key(101, {"kind": "ax_ref", "ax_ref": "0.0", "title": "x"})
    assert session_target_key(101, {"kind": "point", "x": 700.0, "y": 850.0}) == session_target_key(
        101, {"kind": "point", "x": 700, "y": 850}
    )
    assert gate.force_consumed("s1") is False
    gate.mark_force_consumed("s1")
    assert gate.force_consumed("s1") is True
    assert gate.force_consumed("s2") is False


# ══ 2. 平台/会话前置 ═══════════════════════════════════════════════════════
def test_unsupported_platform_backend_none(monkeypatch):
    tool = DesktopOperateTool(backend=None, session_id_getter=lambda: "s")
    payload = _direct(tool, **CLICK_101, dry_run=True)
    assert payload["ok"] is False
    assert payload["error_code"] == "unsupported_platform"
    assert "macOS" in payload["guidance"]


def test_no_gui_and_screen_locked():
    backend = _backend(session=SessionSnapshot(gui_available=False, console_user=None,
                                               screen_locked=None))
    payload = _direct(_tool(backend), **CLICK_101, dry_run=True)
    assert payload["error_code"] == "no_gui_session"
    backend2 = _backend(session=SessionSnapshot(gui_available=True, console_user="u",
                                                screen_locked=True))
    payload2 = _direct(_tool(backend2), **CLICK_101, dry_run=True)
    assert payload2["error_code"] == "screen_locked"
    assert backend2.act_calls == []


# ══ 3. U13 敏感应用：拒绝且零投递 ═══════════════════════════════════════════
def test_u13_sensitive_app_refused_no_delivery_no_leak():
    backend = _backend(windows=[_window(window_id=104, bundle_id="com.1password.mac",
                                        title="1Password", is_foreground=True)])
    tool = _tool(backend)
    payload = _direct(tool, **CLICK_101 | {"window_id": 104}, dry_run=True)
    assert payload["ok"] is False
    assert payload["error_code"] == "privacy_blocked"
    assert payload["privacy_blocked"] is True
    assert backend.act_calls == []
    assert payload.get("window") is None  # 敏感窗口元数据不给（不泄露）


def test_u13_privacy_core_list_hardcoded_and_append_only():
    policy = PrivacyPolicy()
    for sensitive in ("com.1password.mac", "com.bitwarden.desktop", "com.apple.keychainaccess",
                      "com.apple.SecurityAgent", "com.apple.Passwords", "com.apple.loginwindow"):
        assert policy.is_sensitive(sensitive) is True
    policy_extra = PrivacyPolicy(extra_substrings=("com.mybank.app",))
    assert policy_extra.is_sensitive("com.mybank.app") is True
    assert policy_extra.is_sensitive("com.1password.mac") is True  # 核心项删不掉


# ══ 4. U14 白名单外 + 终端/IDE 只读 ═══════════════════════════════════════
def test_u14_app_outside_act_allowlist_refused():
    backend = _backend(windows=[_window(window_id=106, app="Notes",
                                        bundle_id="com.apple.Notes", is_foreground=True)])
    payload = _direct(_tool(backend), do="click", window_id=106,
                      target={"ax_ref": "0.0"}, dry_run=True)
    assert payload["error_code"] == "app_not_allowed"
    assert backend.act_calls == []


def test_u14_terminal_act_refused_with_readonly_guidance():
    backend = _backend(windows=[_window(window_id=103, app="Terminal",
                                        bundle_id="com.apple.Terminal",
                                        title="zsh", is_foreground=True)])
    payload = _direct(_tool(backend), do="click", window_id=103,
                      target={"ax_ref": "0.0"}, dry_run=True)
    assert payload["error_code"] == "app_not_allowed"
    assert "只读" in payload["guidance"]
    assert "execute_command" in payload["guidance"]
    assert backend.act_calls == []


# ══ 5. U15 用户在场（D7）与 force 凭据 ════════════════════════════════════
def test_u15_user_present_refuses_then_force_credential_flow():
    backend = _backend(hid_idle=5_000)  # HID idle=5s：在场
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, **CLICK_101, dry_run=True)
    token = dry["confirm_token"]
    blocked = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=token)
    assert blocked["error_code"] == "user_present"
    assert "HID idle=5000ms" in blocked["guidance"]
    assert backend.act_calls == []
    # force 缺凭据配置（宿主 env 空）→ force_credential_missing，不自造放行
    missing = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=token, force=True)
    assert missing["error_code"] == "force_credential_missing"
    assert backend.act_calls == []
    # 凭据错误配置：值不匹配 → invalid
    backend2 = _backend(hid_idle=5_000)
    reg2 = _registry(_tool(backend2, force_credential="s3cret"))
    dry2 = _dispatch(reg2, **CLICK_101, dry_run=True)
    token2 = dry2["confirm_token"]
    wrong = _dispatch(reg2, **CLICK_101, dry_run=False, confirm_token=token2,
                      force=True, force_credential="nope")
    assert wrong["error_code"] == "force_credential_invalid"
    assert backend2.act_calls == []
    # 正确凭据：恰好放行一次（一次性，消耗）
    ok = _dispatch(reg2, **CLICK_101, dry_run=False, confirm_token=token2,
                   force=True, force_credential="s3cret")
    assert ok["ok"] is True and ok["applied"] is True and ok["force_used"] is True
    assert backend2.act_calls and backend2.act_calls[0]["do"] == "click"
    # 第二次 force（凭据已消耗）→ invalid（先 dry_run 拿新 token 再 force）
    dry3 = _dispatch(reg2, **CLICK_101, dry_run=True)
    consumed = _dispatch(reg2, **CLICK_101, dry_run=False,
                         confirm_token=dry3["confirm_token"],
                         force=True, force_credential="s3cret")
    assert consumed["error_code"] == "force_credential_invalid"


def test_u15_hid_probe_failure_fails_closed_as_present():
    backend = _backend(hid_idle=None)  # 探针失败 → 按在场
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, **CLICK_101, dry_run=True)
    payload = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=dry["confirm_token"])
    assert payload["error_code"] == "user_present"
    assert "探针不可用" in payload["guidance"]
    assert backend.act_calls == []


# ══ 6. U16 前台/世界漂移：令牌作废 ═════════════════════════════════════════
def test_u16_world_drift_invalidates_token_then_replay_rejected():
    backend = _backend()
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, **CLICK_101, dry_run=True)
    token = dry["confirm_token"]
    # 世界漂移：目标按钮改名（前台不变）→ world_version 不符
    backend._ax_views[101] = _view(
        _node("0", "AXWindow", "某文档"),
        _node("0.0", "AXButton", "改名后的按钮"),
        _node("0.1", "AXTextArea", "正文", value=""),
    )
    drift = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=token)
    assert drift["error_code"] == "foreground_changed"
    assert drift["world_version_expected"] != drift["world_version_actual"]
    assert backend.act_calls == []
    # 令牌已作废：重放 → replayed
    replay = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=token)
    assert replay["error_code"] == "confirm_token_replayed"


# ══ 6b. §6.5 计量面：world 漂移归因（stale_breaks） ═════════════════════════
# 闸要的是"每次漂移的具体打破项分类"，归因必须能从回执读到才可统计。这些
# 用例锁的是归因口径；门控行为不变（仍只看 world_version）。
def test_u16_drift_breaks_target_subtree_not_double_counted():
    """目标自身改名 → target_subtree；同一改动不得同时记进无关节点。"""
    backend = _backend()
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, **CLICK_101, dry_run=True)
    backend._ax_views[101] = _view(
        _node("0", "AXWindow", "某文档"),
        _node("0.0", "AXButton", "改名后的按钮"),
        _node("0.1", "AXTextArea", "正文", value=""),
    )
    drift = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=dry["confirm_token"])
    assert drift["error_code"] == "foreground_changed"
    breaks = drift["stale_breaks"]
    assert breaks["breaks"] == ["target_subtree"]
    assert breaks["primary"] == "target_subtree"
    assert breaks["unrelated"] == {"added": 0, "removed": 0, "changed": 0, "sample": []}


def test_u16_drift_breaks_unrelated_nodes():
    """目标以外的节点变化 → unrelated_nodes（闸要数的就是这一类）。"""
    backend = _backend()
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, **CLICK_101, dry_run=True)
    backend._ax_views[101] = _view(
        _node("0", "AXWindow", "某文档"),
        _node("0.0", "AXButton", "新建"),
        _node("0.1", "AXTextArea", "正文", value=""),
        _node("0.2", "AXButton", "侧栏新出现"),
    )
    drift = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=dry["confirm_token"])
    breaks = drift["stale_breaks"]
    assert breaks["breaks"] == ["unrelated_nodes"]
    assert breaks["unrelated"]["added"] == 1
    assert breaks["unrelated"]["sample"] == ["0.2"]


def test_u16_drift_breaks_foreground_on_early_gate_exit():
    """前台 app 切换走早退路径，仍必须带归因（否则最常见一类在闸里无分子）。"""
    backend = _backend()
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, **CLICK_101, dry_run=True)
    backend.frontmost_override = "com.apple.finder"
    drift = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=dry["confirm_token"])
    assert drift["error_code"] == "foreground_changed"
    breaks = drift["stale_breaks"]
    assert breaks["primary"] == "foreground"
    assert breaks["unrelated"] == {"skipped": "no_tree_loaded"}


def test_u16_drift_gate_breaks_window_missing_is_defensive():
    """窗口消失实际先被 `_gate_window_bound` 以 WINDOW_NOT_FOUND 拦下，world 门里
    的 `fresh_window is None` 只覆盖"674 之后、1245 之前"的窄竞态。故这里直接锁
    该方法的口径，不伪装成可从回执端到端触发。"""
    from types import SimpleNamespace

    from llm_loop.desktop.operate import world_digest

    tool = _tool(_backend())
    # 旧令牌（拆分前签发）无 digest：如实 unavailable，不猜
    assert tool._world_gate_breaks(None, None, "com.google.Chrome") == {
        "unavailable": "token_has_no_world_digest"
    }

    rec = SimpleNamespace(world_digest=world_digest(_window(), (), "com.google.Chrome"))
    assert tool._world_gate_breaks(rec, None, "com.google.Chrome") == {
        "breaks": ["window_identity"],
        "primary": "window_identity",
        "unrelated": {"skipped": "window_missing"},
    }


def test_u16_drift_window_identity_suppresses_unrelated_count():
    """身份变时不得统计无关节点：ax_ref 会整体重排，否则虚增闸分子。"""
    backend = _backend()
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, **CLICK_101, dry_run=True)
    backend.windows = [_window(title="换了标题")]
    backend._ax_views[101] = _view(
        _node("0", "AXWindow", "某文档"),
        _node("0.0", "AXButton", "新建"),
        _node("0.1", "AXTextArea", "正文", value=""),
        _node("0.2", "AXButton", "侧栏新出现"),
    )
    drift = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=dry["confirm_token"])
    breaks = drift["stale_breaks"]
    assert breaks["primary"] == "window_identity"
    assert breaks["unrelated"] == {"suppressed_by": "window_identity"}


# ── 纯函数层：归因口径本身 ──────────────────────────────────────────────────
def test_world_drift_breaks_clean_and_head_path():
    from llm_loop.desktop.operate import (
        world_digest,
        world_drift_breaks,
        world_head_breaks,
    )

    w = _window()
    nodes = (_node("0", "AXWindow", "某文档"), _node("0.0", "AXButton", "新建"))
    base = world_digest(w, nodes, w.bundle_id)
    assert world_drift_breaks(base, base) == {
        "breaks": [],
        "primary": None,
        "unrelated": {"added": 0, "removed": 0, "changed": 0, "sample": []},
    }
    # head 路径（树未加载）：unrelated 如实报 skipped，不伪装成"树没变"
    assert world_head_breaks(base, world_digest(w, (), w.bundle_id)) == {
        "breaks": [],
        "primary": None,
        "unrelated": {"skipped": "no_tree_loaded"},
    }
    # 前台段变：head 路径能抓到 foreground
    moved = world_head_breaks(base, world_digest(w, (), "com.apple.finder"))
    assert moved["primary"] == "foreground"


def test_u16_drift_report_unavailable_without_digest():
    """旧令牌（无 world_digest）→ 归因报 unavailable，绝不猜测分类。"""
    tool = _tool(_backend())
    assert tool._world_drift_report(
        None, _window(), _view(), "com.google.Chrome", None
    ) == {"unavailable": "token_has_no_world_digest"}


# 拆分前实现在下列固定输入上的**字面输出**（硬编码，不是重算）。只有硬编码
# 才是真正的跨重构等值锁定：重算 world_digest().material() 属自证（审查 P2-2）。
_GOLDEN_MATERIAL = (
    "win=101|pid=96579|bundle=com.google.chrome|bounds=0.0,38.0,1512.0,877.0"
    "|title=某文档 - Google Chrome|fg=True|frontmost=com.google.chrome"
    "|ax;0|AXWindow|某文档|fo=0|"
    "|ax;0.0|AXButton|新建|fo=1|"
    "|ax;0.1|AXTextArea|正文|fo=0|abc"
    "|ax;T:0.0|AXButton|新建|fo=1|"
)
_GOLDEN_SHA = "b5e07b589022ba4355b520d2dea0540929c9846f32e3c7ad9ea65be83441f857"


def test_world_fingerprint_golden_bytes_unchanged():
    """锁定拆分前的字面哈希原料与 sha：任何格式漂移都会在这里红。"""
    from llm_loop.desktop.operate import world_digest, world_fingerprint

    w = _window()
    nodes = (
        _node("0", "AXWindow", "某文档"),
        _node("0.0", "AXButton", "新建", focused=True),
        _node("0.1", "AXTextArea", "正文", value="abc"),
    )
    digest = world_digest(
        w, nodes, "com.google.Chrome", include_value=True, target_node=nodes[1]
    )
    assert digest.material() == _GOLDEN_MATERIAL
    assert (
        world_fingerprint(
            w, nodes, "com.google.Chrome", include_value=True, target_node=nodes[1]
        )
        == _GOLDEN_SHA
    )


def test_u16_token_window_id_mismatch_rejected():
    backend = _backend(windows=[
        _window(),  # 101 Chrome（前台）
        _window(window_id=102, pid=500, app="Finder", bundle_id="com.apple.finder",
                title="下载", bounds=(100.0, 100.0, 800.0, 600.0), is_foreground=False),
    ])
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, do="click", window_id=101, target={"ax_ref": "0.0"}, dry_run=True)
    token = dry["confirm_token"]
    # 用 window 101 的令牌 apply window 102 → mismatch
    payload = _dispatch(reg, do="click", window_id=102, target={"ax_ref": "0.0"},
                        dry_run=False, confirm_token=token)
    assert payload["error_code"] == "confirm_token_mismatch"
    assert backend.act_calls == []


# ══ 7. U17 令牌重放（含审计留痕）══════════════════════════════════════════
def test_u17_token_replay_rejected_and_audited(tmp_path: Path):
    audit_path = tmp_path / "audit" / "desktop_operate.jsonl"
    backend = _backend()
    reg = _registry(_tool(backend, audit_sink=make_jsonl_audit_sink(audit_path)))
    dry = _dispatch(reg, **CLICK_101, dry_run=True)
    ok = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=dry["confirm_token"])
    assert ok["applied"] is True
    replay = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=dry["confirm_token"])
    assert replay["error_code"] == "confirm_token_replayed"
    assert replay["applied"] is False
    assert len(backend.act_calls) == 1  # 只有首次 apply 真投递
    rows = [json.loads(line) for line in audit_path.read_text().splitlines()]
    assert any(r.get("error_code") == "confirm_token_replayed" for r in rows)
    assert any(r.get("applied") is True for r in rows)


def test_u17_unknown_token_invalid():
    reg = _registry(_tool(_backend()))
    payload = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token="dtkm-not-a-token")
    assert payload["error_code"] == "confirm_token_invalid"


# ══ 8. U18 投递前自检失败：ax_unavailable + 指引，零投递 ══════════════════
def test_u18_ax_probe_failure_refuses_with_guidance():
    backend = _backend(ax_probe=AX_ERROR_API_DISABLED)  # -25211
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, **CLICK_101, dry_run=True)
    payload = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=dry["confirm_token"])
    assert payload["error_code"] == "ax_unavailable"
    assert "辅助功能" in payload["guidance"]  # 修复指引
    assert backend.act_calls == []


# ══ 9. U19 坐标合同（点单位、越界拒绝、px/pt 换算断言）════════════════════
def test_u19_point_click_points_unit_in_bounds():
    backend = _backend()
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, do="click", window_id=101,
                    target={"point": {"x": 755.5, "y": 476.5}}, dry_run=True)
    ok = _dispatch(reg, do="click", window_id=101,
                   target={"point": {"x": 755.5, "y": 476.5}}, dry_run=False,
                   confirm_token=dry["confirm_token"])
    assert ok["applied"] is True
    # 投递坐标 == 输入点坐标（无 ×scale 换算：CGEvent 与 AX 同为点单位）
    assert backend.act_calls == [{"do": "click_point", "x": 755.5, "y": 476.5}]


def test_u19_point_out_of_bounds_rejected():
    backend = _backend()
    payload = _direct(_tool(backend), do="click", window_id=101,
                      target={"point": {"x": 3000.0, "y": 100.0}}, dry_run=True)
    assert payload["error_code"] == "coordinate_out_of_bounds"
    assert "单位=点" in payload["guidance"]
    assert backend.act_calls == []


def test_u19_capture_size_math_px_pt_consistency():
    # 1512×877 点窗口 ×scale2.0 → 3024×1754 px（U19 断言的原样复验）
    assert check_capture_size(3024, 1754, BoundsPt(0.0, 38.0, 1512.0, 877.0), 2.0) == []
    assert check_capture_size(1512, 877, BoundsPt(0.0, 38.0, 1512.0, 877.0), 2.0) == [
        "capture_size_mismatch"
    ]


# ══ 10. U20 绑定窗口漂移：回执仍报告绑定窗口 ═════════════════════════════
def test_u20_bound_window_reported_on_foreground_drift():
    backend = _backend(windows=[
        _window(),  # 101 Chrome（绑定时前台）
        _window(window_id=202, pid=71527, app="活动监视器",
                bundle_id="com.apple.ActivityMonitor", title="活动监视器",
                bounds=(310.0, 100.0, 1064.0, 640.0), is_foreground=False),
    ])
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, **CLICK_101, dry_run=True)
    assert dry["foreground_before"] == "com.google.Chrome"
    # 用户切到别的 app：绑定窗口不再是前台
    backend.windows = [
        _window(is_foreground=False),
        _window(window_id=202, pid=71527, app="活动监视器",
                bundle_id="com.apple.ActivityMonitor", title="活动监视器",
                bounds=(310.0, 100.0, 1064.0, 640.0), is_foreground=True),
    ]
    payload = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=dry["confirm_token"])
    assert payload["error_code"] == "foreground_changed"
    # U20 核心：回执报告的是“绑定窗口”事实（window 101），不是新前台窗口
    assert payload["window"]["window_id"] == 101
    assert payload["window"]["bundle_id"] == "com.google.Chrome"
    # foreground_before 如实反映 apply 时刻前台（漂移事实本身）；dry_run 时为 Chrome
    assert payload["foreground_before"] == "com.apple.ActivityMonitor"
    assert dry["foreground_before"] == "com.google.Chrome"
    assert backend.act_calls == []


# ══ 11. 跳过 dry_run / 会话放行 / irreversible 单步（经 registry 真实派发）══
def test_skip_dry_run_direct_apply_refused():
    backend = _backend()
    reg = _registry(_tool(backend))
    payload = _dispatch(reg, **CLICK_101, dry_run=False)  # 无 token 首次 apply
    assert payload["error_code"] == "dry_run_required"
    assert payload["needs_confirmation"] is True
    assert backend.act_calls == []


def test_session_approval_scoped_by_app_and_do_via_registry():
    backend = _backend(windows=[
        _window(),
        _window(window_id=105, pid=808, app="Safari", bundle_id="com.apple.Safari",
                title="页面", bounds=(0.0, 38.0, 1200.0, 800.0), is_foreground=False),
    ])
    reg = _registry(_tool(backend))
    # Chrome click：dry_run → token → apply（记会话放行；R6 起记账带目标身份）
    dry = _dispatch(reg, **CLICK_101, dry_run=True)
    ok = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=dry["confirm_token"])
    assert ok["applied"] is True
    # 同 app 同 do 同目标（ax_ref=0.0）：免 token 直接 apply（§6.2 session 内
    # 放行；连续多次调用验证——目标维度负例见 test_r6_session_exemption_*）
    for _ in range(3):
        again = _dispatch(reg, **CLICK_101, dry_run=False)
        assert again["applied"] is True
    # 同 app 不同 do（type）：不放行 → dry_run_required
    other_do = _dispatch(reg, do="type", window_id=101,
                         target={"ax_ref": "0.1"}, text="hello", dry_run=False)
    assert other_do["error_code"] == "dry_run_required"
    # 不同 app（Safari，切前台后）：不放行
    backend.windows = [
        _window(is_foreground=False),
        _window(window_id=105, pid=808, app="Safari", bundle_id="com.apple.Safari",
                title="页面", bounds=(0.0, 38.0, 1200.0, 800.0), is_foreground=True),
    ]
    other_app = _dispatch(reg, do="click", window_id=105, target={"ax_ref": "0.0"}, dry_run=False)
    assert other_app["error_code"] == "dry_run_required"


def test_irreversible_never_session_approved_every_apply_needs_token():
    # R6/P1：关闭钮模型改用真机编码 role=AXButton + subrole=AXCloseButton
    # （与 R3 fake 树 / live 冒烟脚本一致；旧编码兼容另见 R6 测试）。
    close_view = _view(
        _node("0", "AXWindow", "某文档"),
        _node("0.2", "AXButton", None, subrole="AXCloseButton"),
    )
    backend = _backend(ax_views={101: close_view})
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, do="click", window_id=101, target={"ax_ref": "0.2"}, dry_run=True)
    assert dry["risk_class"] == "irreversible"
    assert dry["risk_note"]  # 不构成安全保证的声明必须在场
    ok = _dispatch(reg, do="click", window_id=101, target={"ax_ref": "0.2"},
                   dry_run=False, confirm_token=dry["confirm_token"])
    assert ok["applied"] is True
    # 第二次同动作：即使 (app,do) 已确认过，irreversible 仍要求新 token
    second = _dispatch(reg, do="click", window_id=101, target={"ax_ref": "0.2"}, dry_run=False)
    assert second["error_code"] == "dry_run_required"
    assert second["risk_class"] == "irreversible"
    dry2 = _dispatch(reg, do="click", window_id=101, target={"ax_ref": "0.2"}, dry_run=True)
    ok2 = _dispatch(reg, do="click", window_id=101, target={"ax_ref": "0.2"},
                    dry_run=False, confirm_token=dry2["confirm_token"])
    assert ok2["applied"] is True


# ══ 12. Chrome 边界（路线 A：网页内容目标拒绝并指向 browser_operate）══════
def test_web_target_refused_points_to_browser_operate():
    chrome_web_view = _view(
        _node("0", "AXWindow", "某文档 - Google Chrome"),
        _node("0.0", "AXWebArea", "某文档"),
        _node("0.0.1", "AXButton", "登录"),
    )
    backend = _backend(ax_views={101: chrome_web_view})
    tool = _tool(backend)
    # 目标自身是 AXWebArea
    p1 = _direct(tool, do="click", window_id=101, target={"ax_ref": "0.0"}, dry_run=True)
    assert p1["error_code"] == "web_target_not_allowed"
    # 目标是 AXWebArea 的子节点（祖先命中）
    p2 = _direct(tool, do="click", window_id=101, target={"ax_ref": "0.0.1"}, dry_run=True)
    assert p2["error_code"] == "web_target_not_allowed"
    assert "browser_operate" in p2["guidance"]
    assert backend.act_calls == []
    # 窗口 chrome 级目标（非 web 子树）不受影响
    chrome_chrome_view = _view(
        _node("0", "AXWindow", "某文档 - Google Chrome"),
        _node("0.1", "AXButton", None, subrole="AXCloseButton"),  # 真机编码（R6/P1）
    )
    backend._ax_views[101] = chrome_chrome_view
    p3 = _direct(tool, do="click", window_id=101, target={"ax_ref": "0.1"}, dry_run=True)
    assert p3["ok"] is True
    assert p3["risk_class"] == "irreversible"  # AXCloseButton → irreversible（保守）


# ══ 13. press_key / type / scroll ══════════════════════════════════════════
def test_press_key_blacklist_rejected_no_delivery():
    backend = _backend()
    tool = _tool(backend)
    for combo in ("Meta+W", "Cmd+Q", "Meta+Tab", "Ctrl+Cmd+Q", "Meta+Alt+Esc", "a", "ctrl+a"):
        payload = _direct(tool, do="press_key", window_id=101, keys=combo, dry_run=True)
        assert payload["error_code"] == "key_not_allowed", combo
    assert backend.act_calls == []


def test_press_key_closed_set_delivers_keycode_flags():
    backend = _backend()
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, do="press_key", window_id=101, keys="Escape", dry_run=True)
    ok = _dispatch(reg, do="press_key", window_id=101, keys="Escape", dry_run=False,
                   confirm_token=dry["confirm_token"])
    assert ok["applied"] is True
    assert backend.act_calls == [{"do": "press_key", "keycode": 53, "flags": 0}]


def test_type_full_loop_with_readback_verification():
    backend = _backend()
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, do="type", window_id=101, target={"ax_ref": "0.1"},
                    text="你好 M4", dry_run=True)
    assert dry["ok"] is True and dry["needs_confirmation"] is True
    ok = _dispatch(reg, do="type", window_id=101, target={"ax_ref": "0.1"},
                   text="你好 M4", dry_run=False, confirm_token=dry["confirm_token"])
    assert ok["applied"] is True and ok["verified"] is True
    assert backend.act_calls[0]["text"] == "你好 M4"


def test_type_text_too_long_rejected():
    backend = _backend()
    payload = _direct(_tool(backend), do="type", window_id=101,
                      target={"ax_ref": "0.1"}, text="x" * 2001, dry_run=True)
    assert payload["error_code"] == "type_text_too_long"
    assert backend.act_calls == []


def test_type_password_field_refused():
    secure_view = _view(
        _node("0", "AXWindow", "登录"),
        _node("0.0", "AXTextField", "密码", subrole="AXSecureTextField"),
    )
    backend = _backend(ax_views={101: secure_view})
    payload = _direct(_tool(backend), do="type", window_id=101,
                      target={"ax_ref": "0.0"}, text="hunter2", dry_run=True)
    assert payload["error_code"] == "privacy_blocked"
    assert "密码型输入框" in payload["guidance"]
    assert backend.act_calls == []


def test_scroll_delivery_signed_lines():
    backend = _backend()
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, do="scroll", window_id=101, target={"ax_ref": "0"},
                    keys="down:5", dry_run=True)
    ok = _dispatch(reg, do="scroll", window_id=101, target={"ax_ref": "0"},
                   keys="down:5", dry_run=False, confirm_token=dry["confirm_token"])
    assert ok["applied"] is True
    assert backend.act_calls == [{"do": "scroll", "window_id": 101, "signed_lines": -5}]


# ══ 14. 写能力开关（默认关；dry_run 不受限）═══════════════════════════════
def test_writes_disabled_default_blocks_apply_not_dry_run():
    backend = _backend()
    reg = _registry(_tool(backend, writes_enabled=False))
    dry = _dispatch(reg, **CLICK_101, dry_run=True)
    assert dry["ok"] is True and dry["confirm_token"]  # dry_run 不受限，令牌照发
    blocked = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=dry["confirm_token"])
    assert blocked["error_code"] == "writes_disabled"
    assert blocked["applied"] is False
    assert "LFL_DESKTOP_OPERATE_ENABLED" in blocked["guidance"]
    assert backend.act_calls == []


# ══ 15. 参数形状（闭合键集）═══════════════════════════════════════════════
def test_arg_shape_failures():
    tool = _tool(_backend())

    def _msg(result):  # S6：校验失败也是 JSON 信封，可解析出 guidance/error_code
        payload = json.loads(result.content)
        assert payload["ok"] is False
        return payload

    assert "do 不受支持" in _msg(tool.execute(**(CLICK_101 | {"do": "drag"})))["guidance"]
    p_extra = _msg(tool.execute(**(CLICK_101 | {"speed": 1})))
    assert "fields_mismatch" in p_extra["guidance"] and p_extra["error_code"] == "invalid_args"
    assert "click 不接受 text/keys" in _msg(
        tool.execute(**(CLICK_101 | {"text": "x"})))["guidance"]
    assert "text 必填" in _msg(tool.execute(do="type", window_id=101,
                                            target={"ax_ref": "0.1"}, dry_run=True))["guidance"]
    assert "target 必填" in _msg(tool.execute(
        do="click", window_id=101, dry_run=True))["guidance"]
    assert "keys 必填" in _msg(tool.execute(
        do="press_key", window_id=101, dry_run=True))["guidance"]
    assert "window_id 必填" in _msg(tool.execute(
        do="click", target={"ax_ref": "0"}))["guidance"]
    bad_target = tool.execute(do="click", window_id=101,
                              target={"ax_ref": "0", "point": {"x": 1, "y": 1}}, dry_run=True)
    assert "键互斥" in json.loads(bad_target.content)["guidance"]
    bad_point = tool.execute(do="click", window_id=101,
                             target={"point": {"x": 1}}, dry_run=True)
    assert "target.point 形如" in json.loads(bad_point.content)["guidance"]


# ══ 16. 审计（§6.4 字段齐全；append-only）════════════════════════════════
def test_audit_jsonl_fields_complete_append_only(tmp_path: Path):
    audit_path = tmp_path / "audit" / "desktop_operate.jsonl"
    backend = _backend()
    reg = _registry(_tool(backend, audit_sink=make_jsonl_audit_sink(audit_path)))
    dry = _dispatch(reg, **CLICK_101, dry_run=True)
    _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=dry["confirm_token"])
    _dispatch(reg, do="click", window_id=101, target={"ax_ref": "0.0"}, dry_run=False,
              confirm_token=dry["confirm_token"])  # 重放也留痕
    rows = [json.loads(line) for line in audit_path.read_text().splitlines()]
    assert len(rows) == 3
    required = {"ts", "session_id", "tool", "do", "app_bundle", "window_id",
                "target_identity", "risk_class", "dry_run", "confirm_token_id",
                "applied", "pre_sha256", "post_sha256", "foreground_before",
                "foreground_after", "hid_idle_ms", "error_code"}
    for row in rows:
        assert required <= set(row), sorted(required - set(row))
    assert rows[0]["dry_run"] is True and rows[0]["applied"] is False
    assert rows[1]["applied"] is True and rows[1]["post_sha256"]
    # M4（R1）：审计只记令牌的 sha256 前 16 位十六进制摘要——不落明文/前缀
    assert re.fullmatch(r"[0-9a-f]{16}", rows[1]["confirm_token_id"] or "")
    assert rows[2]["error_code"] == "confirm_token_replayed"
    assert all(row["tool"] == "desktop_operate" for row in rows)
    # 审计文件全文不含令牌明文及其前缀（M4）
    audit_raw = audit_path.read_text()
    assert dry["confirm_token"] not in audit_raw
    assert dry["confirm_token"][:12] not in audit_raw
    # 无删除/改写接口：sink 只有 append（make_jsonl_audit_sink 以 "a" 模式打开）


# ══ 17. 工厂装配（默认关写能力；audit 路径落位）═══════════════════════════
def test_factory_registration_defaults(tmp_path: Path):
    import llm_loop.factory as factory_module
    from llm_loop.config import load_settings

    settings = load_settings({
        "LLM_API_KEY": "k", "LLM_BASE_URL": "http://127.0.0.1", "LLM_MODEL": "m",
        "LFL_DATA_DIR": str(tmp_path),
    })
    registered: dict[str, object] = {}
    factory_module._register_desktop_perceive(
        lambda name, tool: registered.__setitem__(name, tool), settings
    )
    assert set(registered) == {"desktop_perceive", "desktop_operate"}
    tool = registered["desktop_operate"]
    assert isinstance(tool, DesktopOperateTool)
    assert tool._writes_enabled is False  # T8：写能力默认关
    assert tool._act_allowlist.core_items == CORE_ACT_ALLOWLIST
    assert tool._force_secret == ""  # force 凭据默认无来源 → force 永久拒绝
    # env 开关路径：LFL_DESKTOP_OPERATE_ENABLED=1 → 写能力开（逐会话不自动获得）
    settings_on = load_settings({
        "LLM_API_KEY": "k", "LLM_BASE_URL": "http://127.0.0.1", "LLM_MODEL": "m",
        "LFL_DATA_DIR": str(tmp_path),
        "LFL_DESKTOP_OPERATE_ENABLED": "1",
        "LFL_DESKTOP_FORCE_CREDENTIAL": "cred-1",
        "LFL_DESKTOP_ACT_ALLOWLIST_EXTRA": "com.example.extra",
    })
    registered_on: dict[str, object] = {}
    factory_module._register_desktop_perceive(
        lambda name, tool: registered_on.__setitem__(name, tool), settings_on
    )
    tool_on = registered_on["desktop_operate"]
    assert tool_on._writes_enabled is True
    assert tool_on._force_secret == "cred-1"
    assert tool_on._act_allowlist.is_actable("com.example.extra") == (True, "ok")


# ══ 18. 后端平台判定（非 darwin 拒绝）═════════════════════════════════════
def test_backend_for_platform_non_darwin_none():
    assert backend_for_platform("linux") is None
    assert backend_for_platform("win32") is None


# ═══════════════════════════════════════════════════════════════════════════
# R1 修复轮（M1-M4 / S1-S10）：每条负例均断言零投递（backend.act_calls == []）
# ═══════════════════════════════════════════════════════════════════════════

# Chrome 窗口带 AXWebArea（bounds 与 _window 默认 bounds 对齐：web 区 (0,78)-(1512,778)）
CHROME_WEB_BOUNDED = _view(
    _node("0", "AXWindow", "某文档 - Google Chrome"),
    _node("0.0", "AXWebArea", "某文档", pos=(0.0, 78.0), size=(1512.0, 700.0)),
    _node("0.0.1", "AXButton", "登录"),
    _node("0.0.2", "AXTextField", "网页输入框", focused=True),
)


# ── M1：路线 A 边界不得被 point/scroll/press_key 绕过 ──────────────────────
def test_m1_point_in_browser_web_area_refused():
    backend = _backend(ax_views={101: CHROME_WEB_BOUNDED})
    tool = _tool(backend)
    p = _direct(tool, do="click", window_id=101,
                target={"point": {"x": 700.0, "y": 400.0}}, dry_run=True)
    assert p["error_code"] == "web_target_not_allowed"
    assert "browser_operate" in p["guidance"]
    assert backend.act_calls == []


def test_m1_point_web_area_without_bounds_refused_fail_closed():
    unbounded = _view(
        _node("0", "AXWindow", "某文档 - Google Chrome"),
        _node("0.0", "AXWebArea", "某文档"),  # 无 pos/size：无法排除 → 拒绝
    )
    backend = _backend(ax_views={101: unbounded})
    p = _direct(_tool(backend), do="click", window_id=101,
                target={"point": {"x": 700.0, "y": 400.0}}, dry_run=True)
    assert p["error_code"] == "web_target_not_allowed"
    assert backend.act_calls == []


def test_m1_point_browser_snapshot_unavailable_refused_fail_closed():
    unavailable = AxView(available=False, failure="ax_unavailable")
    backend = _backend(ax_views={101: unavailable})
    p = _direct(_tool(backend), do="click", window_id=101,
                target={"point": {"x": 700.0, "y": 400.0}}, dry_run=True)
    assert p["error_code"] == "web_target_not_allowed"
    assert "快照不可用" in p["guidance"]
    assert backend.act_calls == []


def test_m1_browser_point_outside_web_area_irreversible_and_token_every_time():
    backend = _backend(ax_views={101: CHROME_WEB_BOUNDED})
    reg = _registry(_tool(backend))
    point = {"point": {"x": 700.0, "y": 850.0}}  # 窗口内、web 区外（底部状态栏带）
    dry = _dispatch(reg, do="click", window_id=101, target=point, dry_run=True)
    assert dry["ok"] is True
    assert dry["risk_class"] == "irreversible"  # 浏览器 point 不落普通 act（M1）
    ok = _dispatch(reg, do="click", window_id=101, target=point, dry_run=False,
                   confirm_token=dry["confirm_token"])
    assert ok["applied"] is True
    assert backend.act_calls == [{"do": "click_point", "x": 700.0, "y": 850.0}]
    # 同 (app, do) 已确认过也不放行：point 通道永不进会话免令牌路径
    again = _dispatch(reg, do="click", window_id=101, target=point, dry_run=False)
    assert again["error_code"] == "dry_run_required"
    assert "不享受会话内放行" in again["guidance"]
    assert len(backend.act_calls) == 1


def test_m1_native_point_click_no_session_freepass():
    finder = _window(window_id=108, pid=318, app="Finder", bundle_id="com.apple.finder",
                     title="下载", bounds=(100.0, 100.0, 800.0, 600.0), is_foreground=True)
    backend = _backend(windows=[finder])
    reg = _registry(_tool(backend))
    point = {"point": {"x": 300.0, "y": 300.0}}
    dry = _dispatch(reg, do="click", window_id=108, target=point, dry_run=True)
    assert dry["risk_class"] == "act"  # 原生 app 的 point 仍是 act 级
    ok = _dispatch(reg, do="click", window_id=108, target=point, dry_run=False,
                   confirm_token=dry["confirm_token"])
    assert ok["applied"] is True
    # M1：坐标点击每次都要令牌 + world 比对（免令牌会话放行只属于 ax_ref 通道）
    second = _dispatch(reg, do="click", window_id=108, target=point, dry_run=False)
    assert second["error_code"] == "dry_run_required"
    assert len(backend.act_calls) == 1


def test_m1_scroll_in_browser_with_web_area_refused():
    backend = _backend(ax_views={101: CHROME_WEB_BOUNDED})
    p = _direct(_tool(backend), do="scroll", window_id=101,
                target={"ax_ref": "0"}, keys="down", dry_run=True)
    assert p["error_code"] == "web_target_not_allowed"
    assert "browser_operate" in p["guidance"]
    assert backend.act_calls == []


def test_m1_scroll_in_browser_without_web_area_downgraded_irreversible():
    # 本机实测形态：Chrome AX 树 AXWebArea=0（网页层不可达）→ 无法证明 → 不可逆+令牌
    backend = _backend()
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, do="scroll", window_id=101, target={"ax_ref": "0"},
                    keys="down", dry_run=True)
    assert dry["risk_class"] == "irreversible"
    no_token = _dispatch(reg, do="scroll", window_id=101, target={"ax_ref": "0"},
                         keys="down", dry_run=False)
    assert no_token["error_code"] == "dry_run_required"
    assert backend.act_calls == []


def test_m1_press_key_focused_in_web_area_refused():
    backend = _backend(ax_views={101: CHROME_WEB_BOUNDED})  # 0.0.2 focused 在 web 子树
    p = _direct(_tool(backend), do="press_key", window_id=101, keys="Escape", dry_run=True)
    assert p["error_code"] == "web_target_not_allowed"
    assert backend.act_calls == []


def test_m1_press_key_in_browser_upgraded_irreversible():
    backend = _backend()  # DEFAULT_VIEW：无 AXWebArea、无 focused 节点（焦点不可见）
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, do="press_key", window_id=101, keys="tab", dry_run=True)
    assert dry["risk_class"] == "irreversible"  # 网页焦点不可证 → 降级不可逆+令牌
    ok = _dispatch(reg, do="press_key", window_id=101, keys="tab", dry_run=False,
                   confirm_token=dry["confirm_token"])
    assert ok["applied"] is True
    again = _dispatch(reg, do="press_key", window_id=101, keys="tab", dry_run=False)
    assert again["error_code"] == "dry_run_required"
    assert len(backend.act_calls) == 1


# ── M2：发布/提交/支付类目标 fail-closed（宿主发表闸缺失 ⇒ 不自行放行）────
def test_m2_publish_axref_target_review_required():
    preview = _window(window_id=107, pid=221, app="Preview", bundle_id="com.apple.Preview",
                      title="文章.pdf", bounds=(0.0, 38.0, 900.0, 700.0), is_foreground=True)
    publish_view = _view(
        _node("0", "AXWindow", "文章.pdf"),
        _node("0.0", "AXButton", "发布"),
    )
    backend = _backend(windows=[preview], ax_views={107: publish_view})
    tool = _tool(backend)
    p = _direct(tool, do="click", window_id=107, target={"ax_ref": "0.0"}, dry_run=True)
    assert p["error_code"] == "review_required"
    assert "宿主" in p["guidance"] and "不自行放行" in p["guidance"]
    assert "confirm_token" not in p  # dry_run 也不签发令牌
    assert backend.act_calls == []
    # 带任意 token 的 apply 同样拒绝（在令牌校验之前）
    p2 = _direct(tool, do="click", window_id=107, target={"ax_ref": "0.0"},
                 dry_run=False, confirm_token="dtkm-forged")
    assert p2["error_code"] == "review_required"
    assert backend.act_calls == []


def test_m2_payment_point_target_window_title_review_required():
    finder = _window(window_id=109, pid=319, app="Finder", bundle_id="com.apple.finder",
                     title="订单支付确认", bounds=(0.0, 38.0, 800.0, 600.0),
                     is_foreground=True)
    backend = _backend(windows=[finder])
    # point 无法证明点的是什么 → 窗口标题命中支付类标记即 fail-closed
    p = _direct(_tool(backend), do="click", window_id=109,
                target={"point": {"x": 400.0, "y": 300.0}}, dry_run=True)
    assert p["error_code"] == "review_required"
    assert backend.act_calls == []


# ── M3：EXEC_MODE 分级（默认空 = 零回归）───────────────────────────────────
def test_m3_exec_mode_blocked_and_readonly_refuse_delivery():
    for mode in ("blocked", "readonly"):
        backend = _backend()
        reg = _registry(_tool(backend, exec_mode=mode))
        dry = _dispatch(reg, **CLICK_101, dry_run=True)
        assert dry["ok"] is True and dry["confirm_token"]  # dry_run 不受限
        blocked = _dispatch(reg, **CLICK_101, dry_run=False,
                            confirm_token=dry["confirm_token"])
        assert blocked["error_code"] == "exec_mode_blocked"
        assert mode in blocked["guidance"] and "EXEC_MODE" in blocked["guidance"]
        assert backend.act_calls == []


def test_m3_exec_mode_allowlist_requires_explicit_entry():
    backend = _backend()
    reg = _registry(_tool(backend, exec_mode="allowlist"))
    dry = _dispatch(reg, **CLICK_101, dry_run=True)
    blocked = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=dry["confirm_token"])
    assert blocked["error_code"] == "exec_mode_blocked"
    assert backend.act_calls == []
    backend2 = _backend()
    reg2 = _registry(_tool(backend2, exec_mode="allowlist",
                           exec_allowlist=("desktop_operate",)))
    dry2 = _dispatch(reg2, **CLICK_101, dry_run=True)
    ok = _dispatch(reg2, **CLICK_101, dry_run=False, confirm_token=dry2["confirm_token"])
    assert ok["applied"] is True and backend2.act_calls


def test_m3_exec_mode_empty_zero_regression():
    # 默认（空 = 不启用分级）：行为与既有用例一致（真实投递不受 exec_mode 影响）
    backend = _backend()
    reg = _registry(_tool(backend))  # exec_mode 缺省 ""
    dry = _dispatch(reg, **CLICK_101, dry_run=True)
    ok = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=dry["confirm_token"])
    assert ok["applied"] is True


# ── M4：审计/回执不得出现令牌明文片段；force 凭据不入审计/回执 ─────────────
def test_m4_force_credential_and_token_absent_from_audit_and_receipts(tmp_path: Path):
    audit_path = tmp_path / "audit" / "desktop_operate.jsonl"
    backend = _backend(hid_idle=5_000)
    reg = _registry(_tool(backend, force_credential="FORCE-SENTINEL-9f31",
                          audit_sink=make_jsonl_audit_sink(audit_path)))
    dry = _dispatch(reg, **CLICK_101, dry_run=True)
    ok = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=dry["confirm_token"],
                   force=True, force_credential="FORCE-SENTINEL-9f31")
    assert ok["applied"] is True and ok["force_used"] is True
    audit_raw = audit_path.read_text()
    assert "FORCE-SENTINEL-9f31" not in audit_raw  # 凭据不入审计
    assert dry["confirm_token"] not in audit_raw  # 令牌明文不入审计
    assert "FORCE-SENTINEL-9f31" not in json.dumps(ok, ensure_ascii=False)
    assert dry["confirm_token"] not in json.dumps(ok, ensure_ascii=False)  # apply 回执不回显


def test_m4_token_id_is_irreversible_digest():
    store = ConfirmTokenStore()
    token = store.issue(window_id=1, do="click", action_fp="x", world_version="w",
                        risk_class="act")
    digest = store.token_id(token)
    assert re.fullmatch(r"[0-9a-f]{16}", digest)
    assert digest != token[:12] and token[:12] not in digest
    assert store.token_id("") == ""


# ── S1：type+point 在校验层拒绝（TYPE_ARGS_INVALID，非投递层 KeyError）──────
def test_s1_type_point_rejected_type_args_invalid():
    backend = _backend()
    p = _direct(_tool(backend), do="type", window_id=101,
                target={"point": {"x": 100.0, "y": 200.0}}, text="hi", dry_run=True)
    assert p["error_code"] == "type_args_invalid"
    assert "ax_ref" in p["guidance"]
    assert backend.act_calls == []


# ── S2：force 凭据消耗移到「即将投递」之后 ─────────────────────────────────
def test_s2_force_credential_not_burned_by_refusals():
    backend = _backend(hid_idle=5_000)  # 在场 → force 路径
    tool = _tool(backend, writes_enabled=False, force_credential="s3cret")
    reg = _registry(tool)
    dry = _dispatch(reg, **CLICK_101, dry_run=True)
    refused = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=dry["confirm_token"],
                        force=True, force_credential="s3cret")
    assert refused["error_code"] == "writes_disabled"  # 写开关关闭：拒绝且不投递
    assert backend.act_calls == []
    # 开关打开后同一凭据仍可用（未被上面的拒绝烧掉）——S2 核心断言
    tool._writes_enabled = True
    dry2 = _dispatch(reg, **CLICK_101, dry_run=True)
    ok = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=dry2["confirm_token"],
                   force=True, force_credential="s3cret")
    assert ok["applied"] is True and ok["force_used"] is True


# ── S3：compare_digest（恒时）+ 失败节流 ────────────────────────────────────
def test_s3_force_failures_throttled():
    backend = _backend(hid_idle=5_000)
    tool = _tool(backend, force_credential="s3cret")
    reg = _registry(tool)
    dry = _dispatch(reg, **CLICK_101, dry_run=True)
    token = dry["confirm_token"]
    for _ in range(3):  # 三次错误凭据（拒绝发生在令牌赎回之前，token 不被烧）
        wrong = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=token,
                          force=True, force_credential="nope")
        assert wrong["error_code"] == "force_credential_invalid"
    assert backend.act_calls == []
    # 阈值后：正确凭据也被节流拒绝
    locked = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=token,
                       force=True, force_credential="s3cret")
    assert locked["error_code"] == "force_credential_invalid"
    assert "锁定" in locked["guidance"]
    assert backend.act_calls == []
    # 锁定窗过期后正确凭据放行（测试直接把锁过期，避免真实等待 60s）
    tool._force_lock_until = 0.0
    ok = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=token,
                   force=True, force_credential="s3cret")
    assert ok["applied"] is True
    assert tool._force_fail_count == 0  # 成功后计数复位


# ── S4：cg_post_click 空事件不投递（与 cg_post_key 对齐）────────────────────
def test_s4_cg_post_click_null_event_not_posted(monkeypatch):
    posts: list[object] = []

    class _FakeLib:
        pass

    lib = _FakeLib()
    lib.CGEventCreateMouseEvent = lambda source, kind, where, button: None  # 空事件
    lib.CGEventPost = lambda tap, event: posts.append(event)

    monkeypatch.setattr(macos_actuate, "_cg", lambda: lib)
    # P2-6（R2）：事件未成对创建 → 明确 OSError（投递层映射确定性错误码），
    # 不再静默返回；同时绝不 post（S4 语义保持）。
    with pytest.raises(OSError):
        macos_actuate.cg_post_click(10.0, 20.0)
    assert posts == []  # 空事件绝不 post（S4）


# ── S5：早期拒绝也写审计行 ─────────────────────────────────────────────────
def test_s5_early_refusals_audited():
    rows: list[dict] = []
    sink = rows.append
    # 参数校验失败
    DesktopOperateTool(backend=_backend(), session_id_getter=lambda: "s5",
                       audit_sink=sink).execute(**(CLICK_101 | {"do": "drag"}))
    # unsupported_platform（无后端）
    DesktopOperateTool(backend=None, session_id_getter=lambda: "s5",
                       audit_sink=sink).execute(**CLICK_101, dry_run=True)
    # no_gui_session / screen_locked
    _tool(_backend(session=SessionSnapshot(gui_available=False, console_user=None,
                                           screen_locked=None)),
          audit_sink=sink).execute(**CLICK_101, dry_run=True)
    _tool(_backend(session=SessionSnapshot(gui_available=True, console_user="u",
                                           screen_locked=True)),
          audit_sink=sink).execute(**CLICK_101, dry_run=True)
    # window_not_found
    _tool(_backend(), audit_sink=sink).execute(
        **(CLICK_101 | {"window_id": 999}), dry_run=True)
    codes = {row.get("error_code") for row in rows}
    assert {"invalid_args", "unsupported_platform", "no_gui_session",
            "screen_locked", "window_not_found"} <= codes
    assert all(row["tool"] == "desktop_operate" and row["session_id"] for row in rows)


# ── S7：CF 释放异常安全 ────────────────────────────────────────────────────
def test_s7_resolve_element_early_exit_releases(monkeypatch):
    class _FakeEl:
        """R3：镜像真包装类 release 语义——release 后 _ref=0、attr() 一律 None。"""

        def __init__(self) -> None:
            self._ref = 1
            self.released = 0

        def attr(self, name):  # noqa: ANN001
            if not self._ref:  # 死元素不可再读（真类对 _ref=0 读属性 → AX err → None）
                return None
            assert name == "AXChildren"
            return ["child-0"]  # 只有一个子节点：索引 5 越界 → 早退分支

        def release(self) -> None:
            if self._ref:
                self.released += 1
                self._ref = 0

    fake = _FakeEl()
    monkeypatch.setattr(macos_actuate, "resolve_window_element", lambda window: (fake, None))
    el, failure = macos_actuate.resolve_element_by_axref(_window(), "0.5")
    assert el is None and failure == "ax_ref_not_found"
    assert fake.released == 1  # 早退分支也释放（S7）
    assert fake._ref == 0
    assert fake.attr("AXChildren") is None  # 释放后不可读（镜像真语义，防假绿）


def test_s7_window_candidates_release_on_midway_exception(monkeypatch):
    created: list[int] = []
    released: list[int] = []

    class _FakeEl:
        def __init__(self, ref: int) -> None:
            self._ref = ref
            created.append(ref)

        def release(self) -> None:  # R3：置 0 镜像（重复 release 是 no-op，同真类）
            if self._ref:
                released.append(self._ref)
                self._ref = 0

    def _fake_item(value, i):  # noqa: ANN001
        if i >= 1:
            raise RuntimeError("boom at index 1")
        return 0x100 + i

    monkeypatch.setattr(macos_actuate, "ax_read_attr", lambda ref, name: (0, 0xABC))
    monkeypatch.setattr(macos_actuate, "cf_array_count", lambda value: 3)
    monkeypatch.setattr(macos_actuate, "cf_array_item", _fake_item)
    monkeypatch.setattr(macos_actuate, "cf_retain", lambda ref: ref)
    monkeypatch.setattr(macos_actuate, "cf_release", lambda ref: None)
    monkeypatch.setattr(macos_actuate, "MacAxElement", _FakeEl)
    try:
        macos_actuate._ax_window_candidates(1)
        raise AssertionError("应当在中途异常传播")
    except RuntimeError as exc:
        assert "boom" in str(exc)
    assert created == [0x100]  # 只构造了第 0 个
    assert released == [0x100]  # 异常路径把它释放（S7：不泄漏）


# ── S8：act_set_value 失败 detail 不回显键入内容 ───────────────────────────
def test_s8_set_value_mismatch_detail_no_echo(monkeypatch):
    class _FakeEl:
        def release(self) -> None:
            return None

    monkeypatch.setattr(macos_actuate, "resolve_element_by_axref",
                        lambda window, ax_ref: (_FakeEl(), None))
    monkeypatch.setattr(macos_actuate, "ax_set_value", lambda el, text: 0)
    monkeypatch.setattr(macos_actuate, "ax_read_value_string",
                        lambda el: "DIFFERENT-READBACK")
    outcome = MacOSDesktopBackend().act_set_value(_window(), "0.1", "SECRET-TYPED-TEXT")
    assert outcome.ok is False and outcome.verified is False
    assert "SECRET-TYPED-TEXT" not in str(outcome.detail)
    assert "expect_len=" in str(outcome.detail) and "不回显键入内容" in str(outcome.detail)


# ── S9：AX 节点 cap 与 perceive 对齐；目标行无条件进 world 指纹 ─────────────
def test_s9_operate_ax_node_cap_matches_perceive():
    backend = _backend()
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, **CLICK_101, dry_run=True)
    _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=dry["confirm_token"])
    assert backend.ax_node_limits  # dry/deliver/post 三次快照都记录了 cap
    assert set(backend.ax_node_limits) == {AX_NODE_LIMIT_DEFAULT}


def test_s9_world_fingerprint_target_row_breaks_on_deep_target_drift():
    w = _window()
    many = tuple(_node(str(i), "AXButton", f"t{i}") for i in range(300))
    deep = many[299]
    fp_a = world_fingerprint(w, many, "fg", target_node=deep)
    renamed = many[:299] + (_node("299", "AXButton", "CHANGED"),)
    fp_b = world_fingerprint(w, renamed, "fg", target_node=renamed[299])
    assert fp_a != fp_b  # 深位（>200）目标改名 → 令牌 world 作废（S9）
    # 演示旧行为盲区（不传 target_node 时前 200 行覆盖不到 299 号节点）：
    assert world_fingerprint(w, many, "fg") == world_fingerprint(w, renamed, "fg")


# ── S10：desktop_see_allowlist 对 act 对齐 ─────────────────────────────────
def test_s10_see_allowlist_blocks_act():
    backend = _backend()  # 默认 Chrome 窗口
    tool = _tool(backend, see_allowlist=("com.apple.finder",))
    p = _direct(tool, **CLICK_101, dry_run=True)
    assert p["error_code"] == "app_not_allowed"
    assert "see_allowlist" in p["guidance"]
    assert backend.act_calls == []
    # 空名单（默认）= 不限制：既有全部用例即回归证明


def test_s10_factory_passes_see_allowlist_and_exec_mode(tmp_path: Path):
    import llm_loop.factory as factory_module
    from llm_loop.config import load_settings

    settings = load_settings({
        "LLM_API_KEY": "k", "LLM_BASE_URL": "http://127.0.0.1", "LLM_MODEL": "m",
        "LFL_DATA_DIR": str(tmp_path),
        "LFL_DESKTOP_SEE_ALLOWLIST": "com.apple.finder",
        "EXEC_MODE": "blocked",
    })
    registered: dict[str, object] = {}
    factory_module._register_desktop_perceive(
        lambda name, tool: registered.__setitem__(name, tool), settings
    )
    tool = registered["desktop_operate"]
    assert isinstance(tool, DesktopOperateTool)
    assert tool._see_allowlist.is_allowed("com.apple.finder") is True
    assert tool._see_allowlist.is_allowed("com.google.chrome") is False
    assert tool._exec_mode == "blocked"  # M3 装配生效


# ── R1 杂项：终端子串表补全 + 描述声明语义 ─────────────────────────────────
def test_r1_terminal_substrings_extended():
    allow = ActAllowlist()
    for bundle in ("net.kovidgoyal.kitty", "com.mitchellh.ghostty",
                   "dev.warp.Warp-Stable", "org.alacritty", "com.electron.hyper.hyper"):
        assert allow.is_terminal_or_ide(bundle) is True, bundle
        assert allow.is_actable(bundle) == (False, "terminal_readonly"), bundle


def test_r1_descriptions_declare_semantics():
    # 会话免令牌放行「不重做 world 比对」的语义必须显式声明（延期项要求）
    assert "不重做 world 比对" in DesktopOperateTool.description
    assert "review_required" in DesktopOperateTool.description
    assert "exec_mode_blocked" in DesktopOperateTool.description
    from llm_loop.tools.registry import _COMPACT_TOOL_DESCRIPTIONS

    compact = _COMPACT_TOOL_DESCRIPTIONS["desktop_operate"]
    assert "review_required" in compact
    assert "exec_mode_blocked" in compact
    assert "point" in compact  # point 通道语义入 compact 描述


# ═══════════════════════════════════════════════════════════════════════════
# R2 修复轮（P1 F 键键码 + P2-1/P2-3/P2-4/P2-5/P2-6/P2-7）：负例同样断言零投递
# ═══════════════════════════════════════════════════════════════════════════

# ── P1：F1-F12 字面量真值表（macOS 虚拟键码非连续）──────────────────────────
def test_r2_fkey_keycodes_literal_truth_table():
    fkeys = {k: v for k, v in KEY_KEYCODES.items() if k.startswith("f")}
    assert fkeys == {
        "f1": 122, "f2": 120, "f3": 99, "f4": 118,
        "f5": 96, "f6": 97, "f7": 98, "f8": 100,
        "f9": 101, "f10": 109, "f11": 103, "f12": 111,
    }


def test_r2_fkey_keycodes_disjoint_from_arrow_keys():
    arrows = {KEY_KEYCODES[name] for name in ("left", "right", "down", "up")}
    fkeys = {v for k, v in KEY_KEYCODES.items() if k.startswith("f")}
    assert fkeys.isdisjoint(arrows)  # 旧 `122+i` 推导 f2=123 与 left 冲突（P1 根因）
    assert len(fkeys) == 12  # F 键键码自身无重复


def test_r2_press_key_f2_delivers_true_keycode_not_arrow():
    backend = _backend()
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, do="press_key", window_id=101, keys="F2", dry_run=True)
    ok = _dispatch(reg, do="press_key", window_id=101, keys="F2", dry_run=False,
                   confirm_token=dry["confirm_token"])
    assert ok["applied"] is True
    # 真值 120；旧实现会送 123（＝left，左箭头）
    assert backend.act_calls == [{"do": "press_key", "keycode": 120, "flags": 0}]


# ── P2-4：门控顺序文档/提示语与实现一致（D7 → writes_enabled → EXEC_MODE）──
def test_r2_docstring_gate_order_matches_implementation():
    from llm_loop.tools.builtin import desktop_operate as desktop_operate_module

    apply_seg = (desktop_operate_module.__doc__ or "").split("[apply:", 1)[1]
    assert apply_seg.index("D7 HID idle") < apply_seg.index("writes_enabled")
    assert apply_seg.index("writes_enabled") < apply_seg.index("EXEC_MODE")


def test_r2_user_present_guidance_honest_when_writes_disabled():
    backend = _backend(hid_idle=5_000)  # 用户在场
    tool = _tool(backend, writes_enabled=False)  # 写开关默认关
    dry = _direct(tool, **CLICK_101, dry_run=True)
    blocked = _direct(tool, **CLICK_101, dry_run=False, confirm_token=dry["confirm_token"])
    assert blocked["error_code"] == "user_present"  # D7 先于写开关（实现顺序未变）
    assert "writes_disabled" in blocked["guidance"]  # P2-4：提示语如实说明 force 不够
    assert "LFL_DESKTOP_OPERATE_ENABLED" in blocked["guidance"]
    assert backend.act_calls == []


# ── P2-6：cg_post_click 部分失败（半点击）消除 + 明确错误码 + 审计标记 ────────
def test_r2_cg_post_click_no_half_click_on_up_creation_failure(monkeypatch):
    posts: list[object] = []
    released: list[object] = []

    class _FakeLib:
        pass

    lib = _FakeLib()
    lib.CGEventCreateMouseEvent = (
        lambda source, kind, where, button: "down-event"
        if kind == macos_actuate.K_CGEVENT_LEFT_MOUSE_DOWN else None  # up 创建失败
    )
    lib.CGEventPost = lambda tap, event: posts.append(event)
    monkeypatch.setattr(macos_actuate, "_cg", lambda: lib)
    monkeypatch.setattr(macos_actuate, "cf_release", lambda ref: released.append(ref))
    with pytest.raises(OSError):
        macos_actuate.cg_post_click(10.0, 20.0)
    assert posts == []  # down 创建成功但未成对 → 不投递（按钮不卡按下态）
    assert released == ["down-event"]  # 已建句柄释放（不泄漏）


def test_r2_cg_post_click_posts_paired_down_then_up(monkeypatch):
    posts: list[object] = []

    class _FakeLib:
        pass

    lib = _FakeLib()
    lib.CGEventCreateMouseEvent = lambda source, kind, where, button: f"ev{kind}"
    lib.CGEventPost = lambda tap, event: posts.append(event)
    monkeypatch.setattr(macos_actuate, "_cg", lambda: lib)
    monkeypatch.setattr(macos_actuate, "cf_release", lambda ref: None)
    macos_actuate.cg_post_click(10.0, 20.0)
    assert posts == [
        f"ev{macos_actuate.K_CGEVENT_LEFT_MOUSE_DOWN}",
        f"ev{macos_actuate.K_CGEVENT_LEFT_MOUSE_UP}",
    ]


def test_r2_cg_post_click_compensating_repost_when_up_post_raises(monkeypatch):
    posts: list[object] = []
    up_attempts = 0

    class _FakeLib:
        pass

    lib = _FakeLib()
    lib.CGEventCreateMouseEvent = (
        lambda source, kind, where, button: "down"
        if kind == macos_actuate.K_CGEVENT_LEFT_MOUSE_DOWN else "up"
    )

    def _post(tap, event):
        nonlocal up_attempts
        if event == "up":
            up_attempts += 1
            if up_attempts == 1:
                raise OSError("transient post failure")  # down 已投递、up 首投失败
        posts.append(event)

    lib.CGEventPost = _post
    monkeypatch.setattr(macos_actuate, "_cg", lambda: lib)
    monkeypatch.setattr(macos_actuate, "cf_release", lambda ref: None)
    macos_actuate.cg_post_click(5.0, 5.0)  # 补偿重投成功 → 不抛
    assert posts == ["down", "up"]
    assert up_attempts == 2


def test_r2_cg_post_key_no_half_keydown_on_creation_failure(monkeypatch):
    posts: list[object] = []

    class _FakeLib:
        pass

    lib = _FakeLib()
    lib.CGEventCreateKeyboardEvent = lambda source, keycode, down: "kd" if down else None
    lib.CGEventSetFlags = lambda event, flags: None
    lib.CGEventPost = lambda tap, event: posts.append(event)
    monkeypatch.setattr(macos_actuate, "_cg", lambda: lib)
    monkeypatch.setattr(macos_actuate, "cf_release", lambda ref: None)
    with pytest.raises(OSError):
        macos_actuate.cg_post_key(120, 0)
    assert posts == []  # keydown 未成对创建 → 不投递（无卡键自动重复）


def test_r2_backend_maps_click_creation_failure_to_backend_error(monkeypatch):
    def _boom(x_pt, y_pt):
        raise OSError("CGEventCreateMouseEvent 未成对创建 down/up（点击未投递，无半点击）")

    monkeypatch.setattr(macos_actuate, "cg_post_click", _boom)
    outcome = MacOSDesktopBackend().act_click_point(700.0, 400.0)
    assert outcome.ok is False
    assert outcome.error == DesktopErrorCode.BACKEND_ERROR
    assert "点击未投递" in str(outcome.detail)  # 明确错误码 + 确定性原因文本


def test_r2_failed_click_delivery_marked_in_audit():
    rows: list[dict] = []
    backend = _backend()
    backend.act_click_point = lambda x_pt, y_pt: ActOutcome(
        ok=False, error=DesktopErrorCode.BACKEND_ERROR,
        detail="CGEvent 点击投递失败: OSError: CGEventCreateMouseEvent 未成对创建 down/up"
               "（点击未投递，无半点击）",
    )
    reg = _registry(_tool(backend, audit_sink=rows.append))
    point = {"point": {"x": 700.0, "y": 850.0}}
    dry = _dispatch(reg, do="click", window_id=101, target=point, dry_run=True)
    payload = _dispatch(reg, do="click", window_id=101, target=point, dry_run=False,
                        confirm_token=dry["confirm_token"])
    assert payload["error_code"] == "backend_error"
    assert payload["applied"] is False
    # P2-6：部分失败在审计行有明确错误码标记（applied=false + backend_error）
    assert any(
        r.get("error_code") == "backend_error" and r.get("applied") is False for r in rows
    )


# ── P2-5：死状态 key_flags 已删除 ───────────────────────────────────────────
def test_r2_dead_key_flags_state_removed():
    from llm_loop.tools.builtin import desktop_operate as desktop_operate_module

    source = Path(desktop_operate_module.__file__).read_text(encoding="utf-8")
    assert 'options["key_flags"]' not in source  # 死状态已删除（_deliver 侧重解析）


# ── P2-3：令牌 TTL + 上限淘汰；会话 TTL + 上限；过期按过期拒绝 ────────────────
def test_r2_token_ttl_expired_rejected_at_store_level():
    store = ConfirmTokenStore()
    fp = action_fingerprint("click", 101, {"kind": "ax_ref", "ax_ref": "0.0"}, None, None)
    fresh = store.issue(window_id=101, do="click", action_fp=fp,
                        world_version="w", risk_class="act", now=1_000.0)
    stale = store.issue(window_id=101, do="click", action_fp=fp,
                        world_version="w", risk_class="act", now=1_000.0)
    assert store.redeem(fresh, window_id=101, do="click", action_fp=fp,
                        now=1_000.0 + CONFIRM_TOKEN_TTL_S - 1.0)[0] == "ok"
    assert store.redeem(stale, window_id=101, do="click", action_fp=fp,
                        now=1_000.0 + CONFIRM_TOKEN_TTL_S + 1.0)[0] == "expired"


def test_r2_token_store_bounded_by_cap_with_fifo_eviction():
    store = ConfirmTokenStore()
    fp = "fp"
    tokens = [
        store.issue(window_id=1, do="click", action_fp=fp, world_version="w",
                    risk_class="act", now=1_000.0 + i)
        for i in range(CONFIRM_TOKEN_MAX_RECORDS + 5)
    ]
    assert store.size() == CONFIRM_TOKEN_MAX_RECORDS  # 无界增长被上限拦截
    redeem_at = 1_000.0 + CONFIRM_TOKEN_TTL_S - 1.0
    assert store.redeem(tokens[0], window_id=1, do="click", action_fp=fp,
                        now=redeem_at)[0] == "invalid"  # 最旧令牌被上限淘汰
    assert store.redeem(tokens[-1], window_id=1, do="click", action_fp=fp,
                        now=redeem_at)[0] == "ok"


def test_r2_expired_token_rejected_tool_level():
    backend = _backend()
    tool = _tool(backend)
    reg = _registry(tool)
    fp = action_fingerprint("click", 101, {"kind": "ax_ref", "ax_ref": "0.0"}, None, None)
    token = tool._tokens.issue(window_id=101, do="click", action_fp=fp,
                               world_version="stale", risk_class="act",
                               now=1_000.0)  # 真实时钟下必然已超 TTL
    payload = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=token)
    assert payload["error_code"] == "confirm_token_expired"
    assert payload["applied"] is False
    assert backend.act_calls == []


def test_r2_session_gate_approval_ttl_and_force_persistence():
    gate = SessionActGate()
    k0 = session_target_key(101, {"kind": "ax_ref", "ax_ref": "0.0"})
    gate.mark_approved("s1", "com.google.Chrome", "click", target_key=k0, now=100.0)
    assert gate.is_approved("s1", "com.google.Chrome", "click", target_key=k0,
                            now=100.0 + SESSION_APPROVAL_TTL_S - 1.0) is True
    assert gate.is_approved("s1", "com.google.Chrome", "click", target_key=k0,
                            now=100.0 + SESSION_APPROVAL_TTL_S + 1.0) is False  # TTL 过期
    # force 一次性消耗不随 TTL 复活（淘汰不得重置安全事实）；reset 是唯一回收口
    gate.mark_force_consumed("sf", now=100.0)
    assert gate.force_consumed("sf") is True
    gate.reset("sf")
    assert gate.force_consumed("sf") is False


def test_r2_session_gate_bounded_by_cap():
    gate = SessionActGate()
    k0 = session_target_key(101, {"kind": "ax_ref", "ax_ref": "0.0"})
    for i in range(SESSION_APPROVAL_MAX_SESSIONS + 10):
        gate.mark_approved(f"s{i}", "com.apple.finder", "click", target_key=k0, now=1_000.0 + i)
    at = 1_100.0  # 全部会话仍在 TTL 内 → 只可能因上限被淘汰
    assert gate.is_approved("s0", "com.apple.finder", "click", target_key=k0, now=at) is False  # 最旧被淘汰
    assert gate.is_approved(
        f"s{SESSION_APPROVAL_MAX_SESSIONS + 9}", "com.apple.finder", "click",
        target_key=k0, now=at,
    ) is True


# ── P2-1：focused 入 world 指纹（焦点漂移打破令牌）─────────────────────────
def test_r2_world_fingerprint_includes_focus_flag():
    a = world_fingerprint(_window(), DEFAULT_VIEW.nodes, "com.google.Chrome")
    refocused = (
        _node("0", "AXWindow", "某文档"),
        _node("0.0", "AXButton", "新建"),
        _node("0.1", "AXTextArea", "正文", value="", focused=True),
    )
    assert world_fingerprint(_window(), refocused, "com.google.Chrome") != a  # 焦点漂移


def test_r2_focus_drift_invalidates_confirm_token():
    backend = _backend()
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, **CLICK_101, dry_run=True)
    backend._ax_views[101] = _view(  # dry_run 与 apply 之间焦点移入正文
        _node("0", "AXWindow", "某文档"),
        _node("0.0", "AXButton", "新建"),
        _node("0.1", "AXTextArea", "正文", value="", focused=True),
    )
    payload = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=dry["confirm_token"])
    assert payload["error_code"] == "foreground_changed"
    assert backend.act_calls == []


# ── P2-7：审计写失败 best-effort 但不再完全静默（回执带 audit_write_failed）──
def test_r2_audit_write_failure_signaled_in_receipt():
    def _broken_sink(row):
        raise OSError("disk full")

    backend = _backend()
    reg = _registry(_tool(backend, audit_sink=_broken_sink))
    dry = _dispatch(reg, **CLICK_101, dry_run=True)
    assert dry["ok"] is True  # best-effort：审计失败不改工具语义
    assert dry.get("audit_write_failed", 0) >= 1  # P2-7：失败信号进回执
    ok = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=dry["confirm_token"])
    assert ok["applied"] is True
    assert ok.get("audit_write_failed", 0) >= 2  # 计数累计


# ══ R3：P0 所有权回归——resolve_window_element 返回的元素必须活到调用方 release ══
# 真机证据（父会话 2026-10-31 live 投递实测）：旧实现返回的 bound 包装在 finally
# 里被 release()（_ref 置 0）→ resolve_element_by_axref 必然 "ax_ref_not_found" →
# 误报 window_unbound，act-time ax_ref 寻址在真机 100% 失败。以下 fake 镜像真包装
# 语义（release 置 0 / 死元素 attr→None / AXChildren 整层 retain）+ 引用计数守恒
# 断言。自证（回退修复→红）：回退所有权修复 3 failed（本节前 3 条链路测试）；
# 回退 ax_ref_not_found 分口径映射再 2 failed——修复后全绿。

_APP_REF = 0x900
_ARRAY_REF = 0xABC
_WIN_REF = 0x1000
_CLOSE_REF = 0x1001
_TEXT_REF = 0x1002
_BASELINE = {_APP_REF: 0, _ARRAY_REF: 0, _WIN_REF: 1, _CLOSE_REF: 1, _TEXT_REF: 1}


def _make_fake_ax_state():
    """每测试独立的 (FakeEl 类, 元素注册表, 引用计数表)。

    FakeEl 镜像 MacAxElement 的全部所有权语义（R3 假绿修复的核心）：
    - release()：计数 -1 且 _ref 置 0；对已释放包装重复 release 是 no-op；
    - _ref=0 后 attr() 一律 None（真类对死 ref 读属性 → AX err → None）；
    - attr("AXChildren") 返回**整层已 retain** 的子元素（与真类数组契约一致）。
    计数表由 FakeEl 与 monkeypatch 后的 cf_retain/cf_release 共用，可断言守恒。
    """
    counts: dict[int, int] = {}
    registry: dict[int, dict] = {}

    class FakeEl:
        def __init__(self, ref: int) -> None:
            self._ref = int(ref)

        @property
        def ref(self) -> int:
            return self._ref

        def release(self) -> None:
            if self._ref:
                counts[self._ref] = counts.get(self._ref, 0) - 1
                self._ref = 0

        def attr(self, name: str):
            if not self._ref:
                return None
            data = registry.get(self._ref, {})
            if name == "AXChildren":
                out = []
                for child_ref in data.get("children", ()):
                    counts[child_ref] = counts.get(child_ref, 0) + 1  # retain 整层
                    out.append(FakeEl(child_ref))
                return out
            return data.get("attrs", {}).get(name)

    return FakeEl, registry, counts


def _build_fake_tree(registry, counts):  # noqa: ANN001
    """窗口(AXWindow,"live-smoke") → [关闭钮(AXButton/AXCloseButton), 文本区(AXTextArea)]。"""
    registry[_WIN_REF] = {
        "attrs": {
            "AXRole": "AXWindow",
            "AXTitle": "live-smoke",
            "AXPosition": Pt(100.0, 100.0),
            "AXSize": Size(400.0, 300.0),
        },
        "children": [_CLOSE_REF, _TEXT_REF],
    }
    registry[_CLOSE_REF] = {
        "attrs": {
            "AXRole": "AXButton",
            "AXSubrole": "AXCloseButton",
            "AXPosition": Pt(1060.0, 110.0),
            "AXSize": Size(14.0, 16.0),
        },
        "children": [],
    }
    registry[_TEXT_REF] = {
        "attrs": {
            "AXRole": "AXTextArea",
            "AXTitle": "正文",
            "AXPosition": Pt(120.0, 150.0),
            "AXSize": Size(360.0, 200.0),
        },
        "children": [],
    }
    counts.update({_WIN_REF: 1, _CLOSE_REF: 1, _TEXT_REF: 1})  # 树自身的外部基线持有


def _wire_macos_actuate(monkeypatch, fake_el, counts):  # noqa: ANN001
    """把 resolve_window_element 的模块级依赖全部换成 fake（app → AXWindows → 窗口元素）。"""

    def fake_app_element(pid):  # noqa: ANN001, ARG001
        counts[_APP_REF] = counts.get(_APP_REF, 0) + 1  # Create 语义：调用方拥有
        return fake_el(_APP_REF)

    def fake_ax_read_attr(ref, name):  # noqa: ANN001
        assert (int(ref), name) == (_APP_REF, "AXWindows")
        counts[_ARRAY_REF] = counts.get(_ARRAY_REF, 0) + 1  # Copy 语义：调用方拥有返回值
        return 0, _ARRAY_REF

    def fake_cf_retain(ref):  # noqa: ANN001
        ref = int(ref or 0)
        if ref:
            counts[ref] = counts.get(ref, 0) + 1
        return ref

    def fake_cf_release(ref):  # noqa: ANN001
        if ref:
            ref = int(ref)
            counts[ref] = counts.get(ref, 0) - 1

    monkeypatch.setattr(macos_actuate, "app_element", fake_app_element)
    monkeypatch.setattr(macos_actuate, "ax_read_attr", fake_ax_read_attr)
    monkeypatch.setattr(macos_actuate, "cf_array_count", lambda value: 1)
    monkeypatch.setattr(macos_actuate, "cf_array_item", lambda value, i: _WIN_REF)
    monkeypatch.setattr(macos_actuate, "cf_retain", fake_cf_retain)
    monkeypatch.setattr(macos_actuate, "cf_release", fake_cf_release)
    monkeypatch.setattr(macos_actuate, "MacAxElement", fake_el)


def _smoke_window() -> WindowInfo:
    return _window(title="live-smoke", bounds=(100.0, 100.0, 400.0, 300.0))


def test_r3_resolve_window_element_returns_live_wrapper_and_refcounts_conserve(monkeypatch):
    fake_el_cls, registry, counts = _make_fake_ax_state()
    _build_fake_tree(registry, counts)
    _wire_macos_actuate(monkeypatch, fake_el_cls, counts)
    el, failure = macos_actuate.resolve_window_element(_smoke_window())
    assert failure is None and el is not None
    # ── P0 回归核心：返回的元素必须活着（旧实现 finally release → _ref=0 → 红）
    assert el.ref != 0
    children = el.attr("AXChildren")
    assert isinstance(children, list) and len(children) == 2  # 旧实现这里 None → 红
    assert el.attr("AXRole") == "AXWindow"
    for child in children:
        child.release()  # attr 契约：整层兄弟归调用方
    el.release()
    el.release()  # 重复 release 是 no-op（不二次计数）
    assert el.attr("AXRole") is None  # release 后不可再读（镜像真语义）
    # 计数守恒：全部回到基线（旧实现窗口 ref 泄漏 +1 → 红）
    assert counts == dict(_BASELINE)


def test_r3_resolve_element_by_axref_resolves_live_element_and_reports_ax_ref_not_found(
    monkeypatch,
):
    fake_el_cls, registry, counts = _make_fake_ax_state()
    _build_fake_tree(registry, counts)
    _wire_macos_actuate(monkeypatch, fake_el_cls, counts)
    win = _smoke_window()
    # 深一层路径 0.0：窗口 → 第 0 个子（关闭钮）——旧实现必 ax_ref_not_found → 红
    el, failure = macos_actuate.resolve_element_by_axref(win, "0.0")
    assert failure is None and el is not None
    assert el.attr("AXRole") == "AXButton"
    assert el.attr("AXSubrole") == "AXCloseButton"
    el.release()
    assert counts == dict(_BASELINE)
    # 越界路径 → ax_ref_not_found，且兄弟层同样释放（R3 泄漏修复；计数仍守恒）
    miss, failure2 = macos_actuate.resolve_element_by_axref(win, "0.9")
    assert miss is None and failure2 == "ax_ref_not_found"
    assert counts == dict(_BASELINE)
    # 解析失败回执分口径：ax_ref_not_found 而非 window_unbound（R3 前是 window_unbound → 红）
    outcome = MacOSDesktopBackend._resolution_failure("ax_ref_not_found")
    assert outcome.ok is False
    assert outcome.error is DesktopErrorCode.AX_REF_NOT_FOUND
    assert outcome.error.value == "ax_ref_not_found"
    # 窗口解绑口径不变（ax_window_unbound 仍是 window_unbound）
    outcome2 = MacOSDesktopBackend._resolution_failure("ax_window_unbound")
    assert outcome2.error is DesktopErrorCode.WINDOW_UNBOUND


def test_r3_backend_resolution_failure_maps_ax_ref_not_found(monkeypatch):
    monkeypatch.setattr(
        macos_actuate, "resolve_element_by_axref", lambda window, ax_ref: (None, "ax_ref_not_found")
    )
    outcome = MacOSDesktopBackend().act_press(_window(), "0.5")
    assert outcome.ok is False
    assert outcome.error is DesktopErrorCode.AX_REF_NOT_FOUND  # R3 前 = window_unbound → 红
    assert "ax_ref" in str(outcome.detail)


def test_r3_tool_receipt_reports_ax_ref_not_found_not_window_unbound():
    payload = _direct(_tool(_backend()), do="click", window_id=101,
                      target={"ax_ref": "9.9"}, dry_run=True)
    assert payload["ok"] is False
    assert payload["error_code"] == "ax_ref_not_found"  # R3 前 = window_unbound → 红
    assert "重新 snapshot" in payload["guidance"]


def test_r3_offline_act_time_chain_snapshot_pick_resolve_same_node(monkeypatch):
    """act-time 链路离线端到端：snapshot → 选节点 → resolve → 断言同一节点。"""
    # 1) snapshot：真 traverse 走假树（镜像 perceive 只读快照；traverse 接管并释放元素）
    fake_el_cls, registry, counts = _make_fake_ax_state()
    _build_fake_tree(registry, counts)
    counts[_WIN_REF] += 1  # 快照根交 traverse 接管（真路径来自 AXWindows 数组的 retain）
    nodes, truncated = macos_ax.traverse(fake_el_cls(_WIN_REF), depth=4, node_limit=100, root_ref="0")
    assert truncated is False
    target = next(n for n in nodes if n.subrole == "AXCloseButton")
    assert target.ax_ref == "0.0"
    assert (target.role, target.subrole) == ("AXButton", "AXCloseButton")
    assert counts == {_WIN_REF: 1, _CLOSE_REF: 1, _TEXT_REF: 1}  # traverse 释放整棵树
    # 2) act-time：全新解析（真机即重新读 AX）→ resolve_window_element → resolve_element_by_axref
    _wire_macos_actuate(monkeypatch, fake_el_cls, counts)
    el, failure = macos_actuate.resolve_element_by_axref(_smoke_window(), target.ax_ref)
    assert failure is None and el is not None
    # 同一节点：snapshot 选中的 role/subrole 与 act-time 解析出的活元素一致（P0 核心）
    assert el.attr("AXRole") == target.role
    assert el.attr("AXSubrole") == target.subrole
    el.release()
    assert counts == dict(_BASELINE)


# ══ R5：前台判据 = 前台 app（lsappinfo 口径）；CG 窗口序不作投递门控 ════════
# 真机证据（父会话 2026-10-31 live 实测）：CG 序首个 layer-0 窗口是 Chrome
# （window 121487），而 lsappinfo front 指向 com.apple.Preview——旧判据
# （fresh_window.is_foreground）把对 Preview 窗口的合法投递误拒为
# foreground_changed。以下用例构造「CG 序前台窗口属 X / lsappinfo 前台 = Y」
# 的解耦场景，验证新判据：窗口所属 app == 前台 app 才放行；探测失败 fail-closed。
_PREVIEW_WIN = dict(window_id=303, pid=777, app="Preview", bundle_id="com.apple.Preview",
                    title="lfl-m4-live.png", bounds=(0.0, 38.0, 800.0, 600.0))


def test_r5_non_cg_frontmost_window_allowed_when_app_is_frontmost():
    """CG 序第一窗口属 Chrome（fg=True），lsappinfo 前台 = Preview：目标窗口属
    Preview → 允许进入投递路径并成功（旧 CG 序判据会误拒——is_foreground=False）。"""
    backend = _backend(windows=[
        _window(is_foreground=True),  # CG 序第一：Chrome（仅展示口径）
        _window(**_PREVIEW_WIN, is_foreground=False),
    ], frontmost="com.apple.Preview")
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, do="click", window_id=303, target={"ax_ref": "0.0"}, dry_run=True)
    assert dry["ok"] is True
    # R5 口径：foreground_before = 前台 app 的 bundle_id（lsappinfo），非 CG 序窗口
    assert dry["foreground_before"] == "com.apple.Preview"
    payload = _dispatch(reg, do="click", window_id=303, target={"ax_ref": "0.0"},
                        dry_run=False, confirm_token=dry["confirm_token"])
    assert payload["applied"] is True
    assert payload["foreground_after"] == "com.apple.Preview"
    assert backend.act_calls == [{"do": "click", "window_id": 303, "ax_ref": "0.0"}]


def test_r5_window_app_not_frontmost_refused_zero_delivery():
    """前台 app = Preview、目标窗口属 Chrome（CG 序第一）→ foreground_changed + 零投递。"""
    backend = _backend(frontmost="com.apple.Preview")  # 默认 windows=[Chrome 101]
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, **CLICK_101, dry_run=True)
    assert dry["ok"] is True  # dry_run 不做前台门控（不投递）
    payload = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=dry["confirm_token"])
    assert payload["error_code"] == "foreground_changed"
    assert payload["applied"] is False
    # U20 语义保持：回执仍报告绑定窗口事实
    assert payload["window"]["window_id"] == 101
    assert payload["foreground_before"] == "com.apple.Preview"  # R5 口径（apply 次扫描）
    assert backend.act_calls == []


def test_r5_frontmost_probe_failure_fails_closed():
    """前台 app 探测失败（lsappinfo 超时/无 ASN/无匹配 → None）→ fail-closed：
    apply 拒绝 foreground_changed + 零投递（不得当成"通过"）。"""
    backend = _backend(frontmost=None)
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, **CLICK_101, dry_run=True)
    assert dry["ok"] is True
    assert dry["foreground_before"] is None  # 探测失败如实为 None
    payload = _dispatch(reg, **CLICK_101, dry_run=False, confirm_token=dry["confirm_token"])
    assert payload["error_code"] == "foreground_changed"
    assert payload["applied"] is False
    assert backend.act_calls == []


def test_r5_frontmost_probe_consulted_on_dispatch():
    """前台探测确实被消费（dry 扫描 + apply 门控/post 观测），非死代码。"""
    backend = _backend()
    reg = _registry(_tool(backend))
    _dispatch(reg, **CLICK_101, dry_run=True)
    _dispatch(reg, **CLICK_101, dry_run=False,
              confirm_token=_dispatch(reg, **CLICK_101, dry_run=True)["confirm_token"])
    assert backend.frontmost_calls >= 3  # dry 扫描 1 + 第二次 dry 1 + apply ≥1


def test_r5_backend_frontmost_app_bundle_asn_match(monkeypatch):
    """真后台 frontmost_app_bundle：front ASN → list 记录按 ASN 归一匹配 bundle。"""
    from llm_loop.desktop import backend_macos

    backend = backend_macos.MacOSDesktopBackend()
    listing = (
        '1) "Chrome" ASN:0x0-0xa9a3999:\n'
        '   bundleID="com.google.Chrome"\n'
        '2) "Preview" ASN:0x0-0xbbb0001:\n'
        '   bundleID="com.apple.Preview"\n'
    )

    def _fake_run(args):
        return listing if args == ["list"] else "ASN:0x0-0xbbb0001"

    monkeypatch.setattr(backend, "_run_lsappinfo", _fake_run)
    assert backend.frontmost_app_bundle() == "com.apple.Preview"


def test_r5_backend_frontmost_app_bundle_failures_return_none(monkeypatch):
    """真后台 frontmost_app_bundle：front 无 ASN / 子进程异常 → None（不外抛）。"""
    from llm_loop.desktop import backend_macos

    backend = backend_macos.MacOSDesktopBackend()
    monkeypatch.setattr(backend, "_run_lsappinfo", lambda args: "")
    assert backend.frontmost_app_bundle() is None

    def _boom(args):
        raise backend_macos.DesktopBackendError("lsappinfo front 超时")

    monkeypatch.setattr(backend, "_run_lsappinfo", _boom)
    assert backend.frontmost_app_bundle() is None


# ═══════════════════════════════════════════════════════════════════════════
# R6 修复轮（收口轮）：P1 关闭钮真机编码误判 + P2-1 会话免令牌按目标记账
# 负例同样断言零投递（refusals must actually refuse）。
# ═══════════════════════════════════════════════════════════════════════════

def test_r6_close_button_real_machine_encoding_irreversible_and_never_session_exempt():
    """P1：真机编码（role=AXButton + subrole=AXCloseButton）的关闭点击必须判
    irreversible（risk_note 免责声明浮现），且一次令牌确认后的后续关闭点击
    不得命中 session 免令牌通道——每次 apply 都要新令牌（审核 P1(a)(b)）。"""
    close_view = _view(
        _node("0", "AXWindow", "某文档"),
        _node("0.2", "AXButton", None, subrole="AXCloseButton"),
    )
    backend = _backend(ax_views={101: close_view})
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, do="click", window_id=101, target={"ax_ref": "0.2"}, dry_run=True)
    assert dry["ok"] is True
    assert dry["risk_class"] == "irreversible"  # R6 前真机编码被判 act（P1 根因）
    assert dry["risk_note"]  # 免责声明必须在场（P1(a)：不构成安全保证）
    assert dry["target_identity"]["role"] == "AXButton"
    assert dry["target_identity"]["subrole"] == "AXCloseButton"
    ok = _dispatch(reg, do="click", window_id=101, target={"ax_ref": "0.2"},
                   dry_run=False, confirm_token=dry["confirm_token"])
    assert ok["applied"] is True
    assert len(backend.act_calls) == 1
    # P1(b)：第二次关闭点击（无 token）→ dry_run_required，绝不免令牌投递
    second = _dispatch(reg, do="click", window_id=101, target={"ax_ref": "0.2"}, dry_run=False)
    assert second["error_code"] == "dry_run_required"
    assert second["risk_class"] == "irreversible"
    assert "irreversible" in second["guidance"]
    assert len(backend.act_calls) == 1  # 负例零投递
    # 补一次 dry_run+token 后可再投递（单步语义保持）
    dry2 = _dispatch(reg, do="click", window_id=101, target={"ax_ref": "0.2"}, dry_run=True)
    ok2 = _dispatch(reg, do="click", window_id=101, target={"ax_ref": "0.2"},
                    dry_run=False, confirm_token=dry2["confirm_token"])
    assert ok2["applied"] is True
    assert len(backend.act_calls) == 2


def test_r6_close_button_legacy_role_encoding_still_irreversible():
    """P1 兼容断言：旧编码（role=AXCloseButton，无 subrole）仍判 irreversible。"""
    close_view = _view(
        _node("0", "AXWindow", "某文档"),
        _node("0.2", "AXCloseButton", None),
    )
    backend = _backend(ax_views={101: close_view})
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, do="click", window_id=101, target={"ax_ref": "0.2"}, dry_run=True)
    assert dry["risk_class"] == "irreversible"
    assert dry["risk_note"]


def test_r6_session_exemption_scoped_to_target_identity_via_registry():
    """P2-1：同 app 同 do 换目标 → 必须重新要令牌（负例零投递）；
    同 app 同 do 同目标 → 免令牌路径仍可用（既定能力不收回）。"""
    two_targets = _view(
        _node("0", "AXWindow", "某文档"),
        _node("0.0", "AXButton", "新建"),
        _node("0.3", "AXButton", "打开"),
    )
    backend = _backend(ax_views={101: two_targets})
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, do="click", window_id=101, target={"ax_ref": "0.0"}, dry_run=True)
    ok = _dispatch(reg, do="click", window_id=101, target={"ax_ref": "0.0"},
                   dry_run=False, confirm_token=dry["confirm_token"])
    assert ok["applied"] is True
    # 同 app 同 do 同目标（ax_ref=0.0）：免令牌路径仍可用
    for _ in range(2):
        again = _dispatch(reg, do="click", window_id=101, target={"ax_ref": "0.0"}, dry_run=False)
        assert again["applied"] is True
    # 同 app 同 do 换目标（ax_ref=0.3）：不放行 → dry_run_required + 零投递
    delivered = len(backend.act_calls)
    other = _dispatch(reg, do="click", window_id=101, target={"ax_ref": "0.3"}, dry_run=False)
    assert other["error_code"] == "dry_run_required"
    assert "目标" in other["guidance"]  # 提示语按目标口径说明
    assert len(backend.act_calls) == delivered  # 负例零投递
    # 换目标后按规矩补 dry_run+token 即可投递；随后同目标免令牌可用
    dry2 = _dispatch(reg, do="click", window_id=101, target={"ax_ref": "0.3"}, dry_run=True)
    ok2 = _dispatch(reg, do="click", window_id=101, target={"ax_ref": "0.3"},
                    dry_run=False, confirm_token=dry2["confirm_token"])
    assert ok2["applied"] is True
    third = _dispatch(reg, do="click", window_id=101, target={"ax_ref": "0.3"}, dry_run=False)
    assert third["applied"] is True
    # 旧目标（0.0）的放行不受新目标确认影响（各自独立记账）
    still = _dispatch(reg, do="click", window_id=101, target={"ax_ref": "0.0"}, dry_run=False)
    assert still["applied"] is True


def test_r6_session_exemption_same_axref_other_window_requires_token():
    """P2-1：目标身份含 window——同 app 同 ax_ref 但换窗口也须新令牌。"""
    win2 = _window(window_id=107, pid=808, app="Google Chrome", bundle_id="com.google.Chrome",
                   title="另一文档 - Google Chrome", bounds=(0.0, 38.0, 1512.0, 877.0))
    backend = _backend(windows=[_window(), win2])
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, do="click", window_id=101, target={"ax_ref": "0.0"}, dry_run=True)
    ok = _dispatch(reg, do="click", window_id=101, target={"ax_ref": "0.0"},
                   dry_run=False, confirm_token=dry["confirm_token"])
    assert ok["applied"] is True
    other_window = _dispatch(reg, do="click", window_id=107, target={"ax_ref": "0.0"}, dry_run=False)
    assert other_window["error_code"] == "dry_run_required"
    assert len(backend.act_calls) == 1  # 负例零投递


def test_r6_session_exemption_keeps_text_freedom_for_type():
    """P2-1：目标身份不含 text——同窗口同文本框 type 换文本仍属同目标
    （既定「同 app 同 do 同目标免令牌」能力保持；text 漂移不再烧免令牌）。"""
    backend = _backend()
    reg = _registry(_tool(backend))
    dry = _dispatch(reg, do="type", window_id=101, target={"ax_ref": "0.1"},
                    text="第一段", dry_run=True)
    ok = _dispatch(reg, do="type", window_id=101, target={"ax_ref": "0.1"},
                   text="第一段", dry_run=False, confirm_token=dry["confirm_token"])
    assert ok["applied"] is True
    again = _dispatch(reg, do="type", window_id=101, target={"ax_ref": "0.1"},
                      text="第二段", dry_run=False)  # 同目标换文本 → 免令牌
    assert again["applied"] is True
    assert backend.act_calls[-1]["text"] == "第二段"


def test_r6_descriptions_declare_session_scope_and_residuals():
    """P2-1/P2-2/P2-4 披露契约：会话免令牌目标记账与「跳过 world 比对」、
    全局 HID 浮层残余、type 整体替换破坏性、scroll 方向未验证、CGEventPost
    不可观测——均必须在工具描述（与 compact 描述）可见。"""
    desc = DesktopOperateTool.description
    # P2-1：会话免令牌按目标记账 + 跳过 world 比对（显式残余）
    assert "同目标" in desc
    assert "不重做 world 比对" in desc
    assert "同一 ax_ref 指向不同元素" in desc
    # P2-2：全局 HID 投递残余（world 指纹无 Z 序/键盘焦点 → 浮层可收到事件）
    assert "全局 HID tap" in desc
    assert "Z 序" in desc
    assert "浮层" in desc
    # P2-4：type 整体替换破坏性 / scroll 方向符号未验证 / CGEvent 投递不可观测
    assert "整体替换" in desc
    assert "覆盖字段原内容" in desc
    assert "未经 live 验证" in desc
    assert "不可观测" in desc
    # 参数描述同步披露
    params = DesktopOperateTool.parameters["properties"]
    assert "覆盖字段原内容" in params["text"]["description"]
    assert "未经 live 验证" in params["keys"]["description"]
    assert "浮层" in params["target"]["description"]
    from llm_loop.tools.registry import _COMPACT_TOOL_DESCRIPTIONS

    compact = _COMPACT_TOOL_DESCRIPTIONS["desktop_operate"]
    assert "同目标" in compact
    assert "不重做world比对" in compact
    assert "浮层" in compact
    assert "整体替换" in compact
    assert "未经live验证" in compact
    assert "不可观测" in compact
