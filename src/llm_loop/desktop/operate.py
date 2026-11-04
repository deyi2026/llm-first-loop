"""M4 gating logic: risk classes / act allowlist / one-time tokens / session gate.

Pure Python (no framework loads) so every rule here is offline-testable.  The
tool layer composes these with a backend; tests drive them directly AND
through the registered dispatch path (registry.execute).

Design anchors (DESIGN-20261027):

- §6.2 three risk classes.  The irreversible heuristic is DELIBERATELY
  conservative and DELIBERATELY declared unreliable — ``RISK_HEURISTIC_DISCLAIMER``
  must surface in receipts/docs; it lowers the probability of a mistake, it
  is not a safety guarantee.
- §6.1 T6 replay: confirm tokens are one-shot and bound to the exact action
  (window_id + do + target identity + text/keys) AND the world_version they
  were dry-run against.  Any redemption attempt on a KNOWN token burns it.
- §6.2/T3: the act allowlist core (Finder/Safari/Chrome/Preview) is hardcoded;
  config can only APPEND; terminal/IDE bundle ids are hardcoded READ-ONLY and
  deny even when appended (act on a terminal == unsandboxed arbitrary shell).
"""

from __future__ import annotations

import hashlib
import secrets as _secrets
import threading
import time
from dataclasses import dataclass, field

from llm_loop.desktop.models import AxNode, WindowInfo

# ── D6 act 白名单（核心硬编码；配置只能追加）───────────────────────────────
CORE_ACT_ALLOWLIST: tuple[str, ...] = (
    "com.apple.finder",
    "com.apple.safari",
    "com.google.chrome",
    "com.apple.preview",
)
# T3/Q-05：终端与 IDE 永远只读。子串匹配（小写）；追加 act 名单也不能放开。
TERMINAL_IDE_SUBSTRINGS: tuple[str, ...] = (
    "com.apple.terminal",
    "iterm2",
    "vscode",
    "visualstudio",
    "com.jetbrains",
    "com.todesktop",
    "wezterm",
    "neovide",
    "xcode",
    "com.apple.dt.xcode",
    # R1 子串表补全（原缺口见 dev report）：宁可误拒（fail-closed 方向），
    # 已知第三方终端家族逐个登记；子串匹配仍非穷尽（残余风险已登记）。
    "kitty",
    "ghostty",
    "warp",
    "alacritty",
    "hyper",
)

# M1（R1）：浏览器 bundle —— 网页内容层属路线 A 裁决域（browser_operate/CDP）
BROWSER_BUNDLES: tuple[str, ...] = ("com.google.chrome", "com.apple.safari")

RISK_HEURISTIC_DISCLAIMER = (
    "risk_class 由默认规则+关键词启发式判定，无法可靠识别全部不可逆动作；"
    "该分类只降低误操作概率，不构成安全保证。"
)

# §6.2 irreversible 关键词启发式（命中即升 irreversible，宁可多确认）
IRREVERSIBLE_TITLE_MARKERS: tuple[str, ...] = (
    "删除", "移除", "清倒", "清空", "卸载", "格式化",
    "delete", "remove", "trash", "uninstall", "erase",
    "发布", "publish", "提交", "submit",
    "支付", "购买", "pay", "payment", "purchase",
    "覆盖", "替换", "overwrite", "replace",
)

# M2（R1，设计 §6.2/§6.3 MUST）：发布/提交/支付类目标不得由本工具令牌自行放行。
# 命中即 fail-closed 拒绝（review_required），与 irreversible 启发式分离：后者仍可
# 凭一次性 token 投递，前者必须走宿主发表闸（宿主闸当前无桌面动作入口 ⇒ 拒绝）。
REVIEW_REQUIRED_MARKERS: tuple[str, ...] = (
    "发布", "publish", "提交", "submit",
    "支付", "购买", "pay", "payment", "purchase",
)

# press_key 闭合键集（非 IME 污染通道可投递的命名键；字母/数字一律走 do=type）
# P1（R2）：F1-F12 为**字面量真值表**——macOS 虚拟键码（HIToolbox Events.h）非连续，
# 旧的 `122+i` 推导会让 f2=123 与 left 冲突（＝左箭头）、f3/f4/f5 撞 right/down/up、
# f6-f12 落入未分配码段。F 键键码与方向键键码必须互斥（单测整表断言）。
KEY_KEYCODES: dict[str, int] = {
    "enter": 36, "return": 36, "escape": 53, "esc": 53, "tab": 48,
    "delete": 117, "backspace": 51, "space": 49,
    "left": 123, "right": 124, "down": 125, "up": 126,
    "home": 115, "end": 119, "pageup": 116, "pagedown": 121,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118,
    "f5": 96, "f6": 97, "f7": 98, "f8": 100,
    "f9": 101, "f10": 109, "f11": 103, "f12": 111,
}
ALLOWED_KEY_MODIFIERS: dict[str, int] = {
    "ctrl": 0x1_0000,          # kCGEventFlagMaskControl
    "shift": 0x2_0000,         # kCGEventFlagMaskShift
    "alt": 0x8_0000,           # kCGEventFlagMaskAlternate
    "option": 0x8_0000,
}
# B3 黑名单（§5.1，硬编码不可配置放宽）：摧毁宿主现场且不可撤销
KEY_BLACKLIST: tuple[str, ...] = (
    "meta+w", "meta+q", "meta+tab", "meta+shift+q", "ctrl+cmd+q", "meta+alt+esc",
)
_MOD_ALIAS = {"cmd": "meta", "command": "meta", "control": "ctrl", "option": "alt"}

MAX_TYPE_CHARS = 2000  # §5.5 type_text_too_long
SCROLL_MAX_LINES = 20
SCROLL_DEFAULT_LINES = 3


def _norm_bundle(raw: str | None) -> str:
    return str(raw or "").strip().lower()


class ActAllowlist:
    """act 层白名单：核心四项硬编码 + 配置追加；终端/IDE 硬拒绝。"""

    def __init__(self, extra: tuple[str, ...] = ()) -> None:
        extras = [_norm_bundle(item) for item in extra if _norm_bundle(item)]
        self._core = CORE_ACT_ALLOWLIST
        self._extra = tuple(dict.fromkeys(extras))

    @property
    def core_items(self) -> tuple[str, ...]:
        return self._core

    def is_terminal_or_ide(self, bundle_id: str | None) -> bool:
        candidate = _norm_bundle(bundle_id)
        if not candidate:
            return False
        return any(needle in candidate for needle in TERMINAL_IDE_SUBSTRINGS)

    def is_actable(self, bundle_id: str | None) -> tuple[bool, str]:
        """返回 (允许, 拒绝种类)；种类 ∈ "ok"|"terminal_readonly"|"not_in_allowlist"."""
        if self.is_terminal_or_ide(bundle_id):
            return False, "terminal_readonly"
        candidate = _norm_bundle(bundle_id)
        if candidate in self._core or candidate in self._extra:
            return True, "ok"
        return False, "not_in_allowlist"


def classify_risk(
    do: str,
    *,
    bundle_id: str | None,
    role: str | None,
    subrole: str | None,
    title: str | None,
    keys: str | None,
) -> str:
    """§6.2 启发式：返回 "act" | "irreversible"。

    依据（保守优先）：
    1. 关闭按钮 —— 无法验证窗口有无未保存内容，一律 irreversible。
       R6/P1：真机编码是 role=AXButton + subrole=AXCloseButton（父会话
       live 实测 Preview 关闭钮；本仓 R3 fake 树同编码），旧实现只按
       role=="axclosebutton" 判定导致真机永不命中（关闭点击被判普通 act，
       且一次确认后落入 session 免令牌通道）。现 role 与 subrole 两通道
       均匹配（各自大小写不敏感），旧编码 role=AXCloseButton 兼容保留；
    2. 目标标题命中 irreversible 关键词（大小写不敏感）；
    3. 浏览器（Chrome/Safari）上 Enter —— 网页表单提交的经典触发键，
       网页层不在 AX 可见面内，无法进一步判定，宁可多确认；
    4. 密码型输入框由工具层另行 privacy_blocked，不进本函数。
    """
    if (
        str(role or "").strip().lower() == "axclosebutton"
        or str(subrole or "").strip().lower() == "axclosebutton"
    ):
        return "irreversible"
    text = " ".join(str(part or "") for part in (title, subrole)).strip().lower()
    if text and any(marker in text for marker in IRREVERSIBLE_TITLE_MARKERS):
        return "irreversible"
    if (
        do == "press_key"
        and str(keys or "").strip().lower() in ("enter", "return")
        and _norm_bundle(bundle_id) in BROWSER_BUNDLES
    ):
        return "irreversible"
    # scroll_into_view（AXScrollToVisible）落到下方默认 "act"：滚动可逆，
    # 不进 irreversible；其浏览器网页层目标由 ax_ref 通道的路线 A 边界另行拒绝。
    return "act"


# ── M1（R1）：路线 A 边界的纯判定（浏览器 web 内容命中）────────────────────

def is_browser_bundle(bundle_id: str | None) -> bool:
    return _norm_bundle(bundle_id) in BROWSER_BUNDLES


def _ancestry_refs(ax_ref: str) -> list[str]:
    refs: list[str] = []
    prefix = ""
    for part in str(ax_ref or "").split("."):
        prefix = f"{prefix}.{part}" if prefix else part
        refs.append(prefix)
    return refs


def is_web_subtree(ax_ref: str, nodes: tuple[AxNode, ...]) -> bool:
    """ax_ref 自身或任何祖先命中 AXWebArea → 属网页内容层（路线 A 域）。"""
    node_map = {n.ax_ref: n for n in nodes}
    return any(
        (node_map[ref].role or "").lower() == "axwebarea"
        for ref in _ancestry_refs(ax_ref)
        if ref in node_map
    )


def has_web_area(nodes: tuple[AxNode, ...]) -> bool:
    return any((n.role or "").lower() == "axwebarea" for n in nodes)


def web_area_rects(nodes: tuple[AxNode, ...]) -> tuple[tuple[float, float, float, float], ...]:
    """AXWebArea 节点的全局包围盒（x0,y0,x1,y1，单位=点）；无 bounds 的节点跳过。"""
    rects: list[tuple[float, float, float, float]] = []
    for node in nodes:
        if (node.role or "").lower() != "axwebarea" or node.pos_pt is None or node.size_pt is None:
            continue
        rects.append(
            (
                float(node.pos_pt.x),
                float(node.pos_pt.y),
                float(node.pos_pt.x) + float(node.size_pt.w),
                float(node.pos_pt.y) + float(node.size_pt.h),
            )
        )
    return tuple(rects)


def point_in_web_area(px: float, py: float, nodes: tuple[AxNode, ...]) -> bool:
    return any(
        x0 <= px < x1 and y0 <= py < y1 for (x0, y0, x1, y1) in web_area_rects(nodes)
    )


def focused_ax_ref(nodes: tuple[AxNode, ...]) -> str | None:
    for node in nodes:
        if node.focused:
            return node.ax_ref
    return None


def channel_risk_override(
    risk_class: str, *, browser: bool, do: str, target_kind: str
) -> str:
    """M1（R1）：浏览器窗口内 point/press_key/scroll 通道不得落在普通 act。

    point 无法做 web 边界证明时的兜底、press_key 作用于（通常不可见的）网页
    焦点、scroll 投递到 app 进程（默认作用于网页视口）——三者一律按
    irreversible 处理（每次都要新令牌 + world 比对），取「不可逆」而非「放行」。
    """
    if browser and (target_kind == "point" or do in ("press_key", "scroll")):
        return "irreversible"
    return risk_class


# ── M2（R1）：发布/提交/支付类目标命中判定 ──────────────────────────────────

def hits_review_markers(*texts: str | None) -> bool:
    joined = " ".join(str(part or "") for part in texts).strip().lower()
    return bool(joined) and any(marker in joined for marker in REVIEW_REQUIRED_MARKERS)


# ── world_version / pre-post 指纹（D4 绑定期世界）──────────────────────────

def world_fingerprint(
    window: WindowInfo,
    nodes: tuple[AxNode, ...],
    frontmost_bundle: str | None,
    *,
    include_value: bool = False,
    target_node: AxNode | None = None,
) -> str:
    """绑定期世界指纹：窗口身份 + 前台归属 + AX 树（ax_ref|role|title|focused[|value]）。

    - 不含全局窗口清单（任何无关 app 弹通知都会打破它，实用性为零）；
      绑定的是"这个窗口 + 这棵目标子树 + 前台归属"。
    - include_value 仅供 post_sha256：type 动作后的世界应反映新 value，
      而 pre 指纹必须排除 value（否则 dry_run 后任何输入都判 world 漂移）。
    - 节点截 200 个：目标子树的稳定性信号，不是全树 diff。
    - P2-1（R2）：节点行与目标行纳入 focused 标志——焦点漂移（目标树内焦点
      移走/移入）必须打破 world_version（令牌作废），不再是指纹盲区。
    - target_node（R1/S9）：ax_ref 通道把解析到的目标节点行**无条件**追加进
      指纹（即使它排在 200 截断之外）——深位目标自身的 role/title 漂移必须
      打破 world_version（令牌作废），不能只靠前 200 行碰巧覆盖。
    实现上不再是手写拼串：原料由 ``world_digest`` 产出（按打破项分组），本函数
    只取它的 sha256。等值性由测试锁定（``material()`` 逐字复现拆分前的串）。
    """
    return hashlib.sha256(
        world_digest(
            window,
            nodes,
            frontmost_bundle,
            include_value=include_value,
            target_node=target_node,
        )
        .material()
        .encode("utf-8")
    ).hexdigest()


# 指纹只取前 N 节点：目标子树的稳定性信号，不是全树 diff（既有口径，勿改）。
WORLD_NODE_LIMIT = 200

# §6.5 开工闸的四类打破项；元组顺序即 primary 归因的优先级。
WORLD_BREAK_WINDOW_IDENTITY = "window_identity"
WORLD_BREAK_FOREGROUND = "foreground"
WORLD_BREAK_TARGET_SUBTREE = "target_subtree"
WORLD_BREAK_UNRELATED_NODES = "unrelated_nodes"


@dataclass(frozen=True)
class WorldDigest:
    """world 指纹的**分解形态**：同一份原料按打破项分组，供 §6.5 归因。

    存在理由：闸要的是"每次漂移的具体打破项分类"（窗口身份 / 前台归属 /
    目标子树 / 无关前 200 节点）。只留 sha256 时只能判"变了"，判不出"哪类
    变了"——事件可数，归因不可核，闸的分子（无关节点占比）因此算不出来。

    不改变任何判定：``world_fingerprint`` 现在就是 ``material()`` 的 sha256，
    而 ``material()`` 逐字复现拆分前的哈希原料（等值由测试锁定）。
    """

    identity: str  # win|pid|bundle|bounds|title
    foreground: str  # fg|frontmost
    rows: tuple[tuple[str, str], ...]  # (ax_ref, 行)
    target: tuple[str, str] | None  # (ax_ref, "T:..." 行)

    def material(self) -> str:
        """哈希原料：与拆分前 ``world_fingerprint`` 拼出的串逐字一致。"""
        parts = [row for _ref, row in self.rows]
        if self.target is not None:
            parts.append(self.target[1])
        return "|ax;".join([f"{self.identity}|{self.foreground}", *parts])


def _world_row(node: AxNode, include_value: bool) -> str:
    row = f"{node.ax_ref}|{node.role or ''}|{node.title or ''}|fo={int(bool(node.focused))}"
    if include_value:
        row += f"|{node.value or ''}"
    return row


def world_digest(
    window: WindowInfo,
    nodes: tuple[AxNode, ...],
    frontmost_bundle: str | None,
    *,
    include_value: bool = False,
    target_node: AxNode | None = None,
) -> WorldDigest:
    """``world_fingerprint`` 的原料，按打破项分组（判定语义完全同源）。"""
    bounds = window.bounds_pt
    identity = (
        f"win={window.window_id}|pid={window.pid}|bundle={_norm_bundle(window.bundle_id)}"
        f"|bounds={bounds.x:.1f},{bounds.y:.1f},{bounds.w:.1f},{bounds.h:.1f}"
        f"|title={window.title or ''}"
    )
    rows = tuple(
        (node.ax_ref, _world_row(node, include_value))
        for node in list(nodes)[:WORLD_NODE_LIMIT]
    )
    target = None
    if target_node is not None:
        target = (target_node.ax_ref, "T:" + _world_row(target_node, include_value))
    return WorldDigest(
        identity=identity,
        foreground=f"fg={window.is_foreground}|frontmost={_norm_bundle(frontmost_bundle)}",
        rows=rows,
        target=target,
    )


def world_drift_breaks(expected: WorldDigest, actual: WorldDigest) -> dict[str, object]:
    """比对两次 digest，给出 §6.5 要求的打破项归因（只做计量，不参与门控）。

    归因口径是闸数据可信与否的关键，两条都是刻意的：

    - **窗口身份破时不统计无关节点差异**。身份变（pid/bounds/title）会让 ax_ref
      整体重排，此时把行差异记成"无关节点 churn"会把真实身份变化虚报成闸的
      分子，直接污染"无关打破占比"。改以 ``unrelated.suppressed_by`` 如实标注。
    - 无关节点一栏排除目标节点自身那一行——它归 target_subtree；不排除会让
      一次目标改动被记两次。

    前提：``ax_ref`` 在单棵树内唯一。若出现重复 ref，``dict(rows)`` 会 last-wins
    折叠，added/removed/changed 计数会偏小；这只影响计量口径，不影响指纹
    （``material()`` 用原始 tuple，逐行保留）。

    返回 ``{"breaks": 全部命中项, "primary": 最高优先级一项或 None,
    "unrelated": 计数 + sample}``。一次事件可同时命中多类，故同时给全集与
    primary，使"任一命中"与"主因"两种统计口径都可算。
    """
    breaks: list[str] = []
    if expected.identity != actual.identity:
        breaks.append(WORLD_BREAK_WINDOW_IDENTITY)
    if expected.foreground != actual.foreground:
        breaks.append(WORLD_BREAK_FOREGROUND)
    if expected.target != actual.target:
        breaks.append(WORLD_BREAK_TARGET_SUBTREE)

    unrelated: dict[str, object]
    if expected.identity != actual.identity:
        unrelated = {"suppressed_by": WORLD_BREAK_WINDOW_IDENTITY}
    else:
        target_refs = {item[0] for item in (expected.target, actual.target) if item}
        before, after = dict(expected.rows), dict(actual.rows)
        added = [ref for ref in after if ref not in target_refs and ref not in before]
        removed = [ref for ref in before if ref not in target_refs and ref not in after]
        changed = [
            ref
            for ref in before
            if ref not in target_refs and ref in after and before[ref] != after[ref]
        ]
        if added or removed or changed:
            breaks.append(WORLD_BREAK_UNRELATED_NODES)
        unrelated = {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
            "sample": (added + removed + changed)[:5],
        }
    return {
        "breaks": breaks,
        "primary": breaks[0] if breaks else None,
        "unrelated": unrelated,
    }


def world_head_breaks(expected: WorldDigest, actual: WorldDigest) -> dict[str, object]:
    """只比身份/前台两段——树尚未加载时的归因（前台门早退路径）。

    那条路径 `_gate_world_rebind` 还没取 AX 树就拒绝了（窗口消失/前台不符），
    没有 rows 可比。此处如实报 ``unrelated: {"skipped": "no_tree_loaded"}``，
    不把"没取树"伪装成"树没变"或"树全变"——伪装任何一种都会污染闸的分母。
    """
    breaks: list[str] = []
    if expected.identity != actual.identity:
        breaks.append(WORLD_BREAK_WINDOW_IDENTITY)
    if expected.foreground != actual.foreground:
        breaks.append(WORLD_BREAK_FOREGROUND)
    return {
        "breaks": breaks,
        "primary": breaks[0] if breaks else None,
        "unrelated": {"skipped": "no_tree_loaded"},
    }


def window_gone_fingerprint(window_id: int) -> str:
    return hashlib.sha256(f"window_gone:{int(window_id)}".encode()).hexdigest()


# ── T6 一次性 confirm_token ────────────────────────────────────────────────

# P2-3（R2）：一次性令牌 TTL 与存量上限——超时未兑换按 expired 拒绝；
# store 不再无界增长（签发时先淘汰过期记录，仍超上限再按签发序淘汰最旧）。
CONFIRM_TOKEN_TTL_S = 600.0
CONFIRM_TOKEN_MAX_RECORDS = 256


def _now(now: float | None) -> float:
    """时钟注入助手：None → 真实时钟；显式值 → 单测可确定性行使 TTL。"""
    return time.time() if now is None else float(now)


@dataclass
class _TokenRecord:
    secret: str
    window_id: int
    do: str
    action_fingerprint: str
    world_version: str
    risk_class: str
    # §6.5 计量面：签发时 world 指纹的**分解形态**，只用于事后归因，不参与任何
    # 门控比对（门控仍只比 world_version）。None = 拆分前签发/未提供，此时归因
    # 如实报 unavailable，绝不猜。
    world_digest: WorldDigest | None = None
    consumed: bool = False
    issued_at: float = 0.0


def action_fingerprint(
    do: str, window_id: int, target_identity: dict, text: str | None, keys: str | None
) -> str:
    """令牌绑定的 action_id：请求指纹（§6.3 同构于 escalation 的命令 sha 绑定）。"""
    material = (
        f"{do}|{int(window_id)}|{target_identity}|{text or ''}|{str(keys or '').strip().lower()}"
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def session_target_key(window_id: int, binding_address: dict) -> str:
    """P2-1（R6）：会话免令牌放行的**目标身份键**（同 app 同 do 还须同目标）。

    与令牌绑定的稳定寻址同源（window_id + kind + ax_ref / point 坐标 /
    focused），刻意**不含 text/keys**：type 换文本、press_key 换键仍是
    「同目标」（既定的免令牌能力保持）；换目标——不同 ax_ref、不同 point
    坐标、或换窗口（window_id 入键）——即换键，须重新 dry_run 取新令牌。
    point 通道本就永不进会话放行（M1），其键仅供记账口径统一。
    """
    kind = str(binding_address.get("kind") or "")
    if kind == "ax_ref":
        detail = str(binding_address.get("ax_ref") or "")
    elif kind == "point":
        # 入口已校验 point{x,y} 为数字；None 分支仅为类型完备（不可达）。
        raw_x = binding_address.get("x")
        raw_y = binding_address.get("y")
        detail = (
            f"{float(raw_x if raw_x is not None else 0.0):.3f},"
            f"{float(raw_y if raw_y is not None else 0.0):.3f}"
        )
    else:
        detail = ""
    material = f"{int(window_id)}|{kind}|{detail}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class ConfirmTokenStore:
    """一次性令牌（进程内、按需签发；replay 一律拒绝并留痕给调用方审计）。

    P2-3（R2）：issued_at 真正参与判定——签发后 ``CONFIRM_TOKEN_TTL_S`` 内未兑换
    即过期（兑换按 expired 拒绝，与 invalid/replayed/mismatch 区分）；签发时做
    过期淘汰 + 存量上限淘汰（FIFO，按签发序），内存不再无界增长。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, _TokenRecord] = {}

    def _prune_locked(self, now: float) -> None:
        # 调用方须持锁。先淘汰已过期记录（它们本就只能换来 expired 拒绝），
        # 仍达上限则按签发序（dict 插入序）淘汰最旧。
        for token in [
            t for t, r in self._records.items() if now - r.issued_at >= CONFIRM_TOKEN_TTL_S
        ]:
            del self._records[token]
        while len(self._records) >= CONFIRM_TOKEN_MAX_RECORDS:
            self._records.pop(next(iter(self._records)))

    def issue(
        self,
        *,
        window_id: int,
        do: str,
        action_fp: str,
        world_version: str,
        risk_class: str,
        world_digest: WorldDigest | None = None,
        now: float | None = None,
    ) -> str:
        token = f"dtkm-{_secrets.token_hex(16)}"
        at = _now(now)
        with self._lock:
            self._prune_locked(at)
            self._records[token] = _TokenRecord(
                secret=token,
                window_id=int(window_id),
                do=str(do),
                action_fingerprint=str(action_fp),
                world_version=str(world_version),
                risk_class=str(risk_class),
                world_digest=world_digest,
                issued_at=at,
            )
        return token

    def token_id(self, token: str) -> str:
        """令牌的**不可逆**短 id（审计/回执展示用）：sha256 前 16 位十六进制。

        M4（R1）：不得返回明文前缀（旧实现 raw[:12] 会把令牌明文片段写进
        append-only 审计 JSONL——拿到审计文件即可缩小令牌爆破空间）。
        """
        raw = str(token or "")
        if not raw:
            return ""
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def redeem(
        self,
        token: str,
        *,
        window_id: int,
        do: str,
        action_fp: str,
        now: float | None = None,
    ) -> tuple[str, _TokenRecord | None]:
        """校验并消费。返回 (status, record)；status ∈
        "ok" | "invalid" | "replayed" | "expired" | "mismatch"。

        已知令牌的任何 redemption 尝试都将其置 consumed（T6：宁可烧掉）；
        超过 ``CONFIRM_TOKEN_TTL_S`` 未兑换的令牌按 expired 拒绝（P2-3/R2）。
        world_version 不在 redeem 内比对——调用方需在成功 redeem 后与
        当前世界比对（world 漂移用 foreground_changed 语义，令牌同样已烧）。
        """
        raw = str(token or "").strip()
        if not raw:
            return "invalid", None
        at = _now(now)
        with self._lock:
            record = self._records.get(raw)
            if record is None:
                return "invalid", None
            if record.consumed:
                return "replayed", record
            record.consumed = True  # 任何已知令牌的展示即烧毁（含 mismatch/expired）
            if at - record.issued_at >= CONFIRM_TOKEN_TTL_S:
                return "expired", record
            if (
                record.window_id != int(window_id)
                or record.do != str(do)
                or record.action_fingerprint != str(action_fp)
            ):
                return "mismatch", record
            return "ok", record

    def size(self) -> int:
        with self._lock:
            return len(self._records)


# ── §6.2 会话级门控状态（act 放行 / force 凭据消耗）───────────────────────

# P2-3（R2）：会话放行记录 TTL 与会话数上限（最近触碰优先保留）——
# approved 集合不再无界增长；force 一次性消耗记录**不受 TTL 约束**（见下）。
SESSION_APPROVAL_TTL_S = 600.0
SESSION_APPROVAL_MAX_SESSIONS = 128


@dataclass
class _SessionState:
    # P2-1（R6）：记账维度 (app, do) → (app, do, 目标身份键)——同 app 内
    # 换目标（不同 ax_ref/坐标/窗口）不再免令牌，见 SessionActGate docstring。
    approved: set[tuple[str, str, str]] = field(default_factory=set)
    last_touched: float = 0.0


class SessionActGate:
    """同 app 同 do **同目标** session 内放行；irreversible 永不进 approved。

    P2-1（R6）：记账维度从 (app, do) 收紧到 (app, do, 目标身份键)
    （``session_target_key``：window_id + 稳定寻址）——此前同 app 内换一个
    目标元素也能免令牌，审核判定与 P1（真机关闭钮误判 act）叠加会放大
    免令牌面；收紧后换目标即须重新 dry_run 取新令牌，「同 app 同 do 同
    目标免令牌」的既定能力保持。免令牌路径仍校验窗口存在 + 前台 app
    口径（工具层 _gate_world_rebind，R5 frontmost_app_bundle），但按
    §6.2 字面**不重做 world 指纹比对**（该跳过已在工具描述显式披露为
    残余：结构漂移可能使同一 ax_ref 指向不同元素而不被该路径发现）。

    P2-3（R2）：approved 放行记录带 TTL 与数量上限（按最近**批准写入**时间
    淘汰；只读查询不续命）——免令牌放行在静默 ``SESSION_APPROVAL_TTL_S``
    后失效，须重新 dry_run 取新令牌（保守方向：该路径本就不重做 world
    比对，定期强制再确认收紧暴露面）。force 凭据的「本会话已消耗」标记
    是**一次性语义的安全事实**，刻意不做 TTL/上限淘汰——淘汰会让已消耗
    的一次性凭据复活为可用；其增长被实际消耗（须凭有效凭据）自然限界，
    显式回收口只有 reset()（会话终态）。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, _SessionState] = {}
        self._force_consumed_at: dict[str, float] = {}

    def _prune_locked(self, now: float) -> None:
        # 调用方须持锁。先回收 TTL 外的会话，仍超上限则按 last_touched 淘汰最旧。
        for sid in [
            s for s, st in self._sessions.items()
            if now - st.last_touched >= SESSION_APPROVAL_TTL_S
        ]:
            del self._sessions[sid]
        overflow = len(self._sessions) - SESSION_APPROVAL_MAX_SESSIONS
        if overflow > 0:
            for sid in sorted(
                self._sessions, key=lambda s: self._sessions[s].last_touched
            )[:overflow]:
                del self._sessions[sid]

    def _lookup(self, session_id: str, now: float) -> _SessionState | None:
        """只读查询（不创建、不续命）。"""
        self._prune_locked(now)
        return self._sessions.get(str(session_id or ""))

    def _touch(self, session_id: str, now: float) -> _SessionState:
        """批准写入：创建/续期会话记录（last_touched=now）。"""
        self._prune_locked(now)
        key = str(session_id or "")
        state = self._sessions.get(key)
        if state is None:
            state = _SessionState(last_touched=now)
            self._sessions[key] = state
        else:
            state.last_touched = now
        return state

    def is_approved(
        self,
        session_id: str,
        bundle_id: str | None,
        do: str,
        *,
        target_key: str,
        now: float | None = None,
    ) -> bool:
        """P2-1（R6）：target_key 必填（session_target_key 产物）——强制调用方
        显式给出目标身份，防止退回 (app, do) 二元组口径。"""
        with self._lock:
            state = self._lookup(session_id, _now(now))
            return state is not None and (
                _norm_bundle(bundle_id),
                str(do),
                str(target_key),
            ) in state.approved

    def mark_approved(
        self,
        session_id: str,
        bundle_id: str | None,
        do: str,
        *,
        target_key: str,
        now: float | None = None,
    ) -> None:
        with self._lock:
            self._touch(session_id, _now(now)).approved.add(
                (_norm_bundle(bundle_id), str(do), str(target_key))
            )

    def force_consumed(self, session_id: str) -> bool:
        # 不做 TTL：一次性语义不得因淘汰而复活（见类 docstring）。
        with self._lock:
            return str(session_id or "") in self._force_consumed_at

    def mark_force_consumed(self, session_id: str, *, now: float | None = None) -> None:
        with self._lock:
            self._force_consumed_at[str(session_id or "")] = _now(now)

    def reset(self, session_id: str) -> None:
        """会话终态清理（测试/宿主回收用；不影响审计事实）。"""
        with self._lock:
            self._sessions.pop(str(session_id or ""), None)
            self._force_consumed_at.pop(str(session_id or ""), None)


# ── press_key / scroll 参数解析（纯函数）───────────────────────────────────

def parse_keycombo(raw: str) -> tuple[str, str, int]:
    """解析 "Ctrl+Shift+Enter" → ("ok", canonical, flags)；
    ("blacklist"|"not_allowed"|"invalid", 原因, 0)。

    - Meta/Cmd/Command 一律拒绝（B3 黑名单族 + 系统级快捷键不可投递）；
    - 字母/未知键拒绝：字母键的 CGEvent 通道被本机输入法污染（已实测），
      文本输入必须走 do=type 的 AX set-value 通道；
    - 修饰键去重排序后 canonical 化。
    """
    text = str(raw or "").strip().lower()
    if not text:
        return "invalid", "keys 为空", 0
    parts = [part.strip() for part in text.split("+") if part.strip()]
    if not parts or any(not part for part in parts):
        return "invalid", "组合键格式不合法", 0
    normalized: list[str] = []
    for part in parts:
        normalized.append(_MOD_ALIAS.get(part, part))
    main = normalized[-1]
    modifiers = normalized[:-1]
    canonical = "+".join([*modifiers, main])
    if "meta" in normalized:
        if canonical in KEY_BLACKLIST:
            return "blacklist", f"按键黑名单命中（B3）: {canonical}", 0
        return "blacklist", f"含系统级修饰键 Meta/Cmd，不可投递（黑名单族 B3）: {canonical}", 0
    if main not in KEY_KEYCODES:
        return (
            "not_allowed",
            f"键名不在闭合键集内: {main}（字母/数字文本输入走 do=type；"
            "CGEvent 字母通道被输入法污染，M4 不提供）",
            0,
        )
    flags = 0
    seen: set[str] = set()
    for modifier in modifiers:
        if modifier not in ALLOWED_KEY_MODIFIERS:
            return "not_allowed", f"修饰键不受支持: {modifier}", 0
        flags |= ALLOWED_KEY_MODIFIERS[modifier]
        seen.add(modifier)
    return "ok", canonical, flags


def parse_scroll(raw: str) -> tuple[str, str, int]:
    """scroll 规格："down"|"up"（可带 ":n" 行数 1..20，默认 3）→
    ("ok", direction, signed_lines)。"down" 映射为负（CGEvent 惯例：正=向上滚）。

    方向映射当前未做 live 投递验证（报告"未验证边界"登记）。
    """
    text = str(raw or "").strip().lower()
    if not text:
        return "invalid", "scroll 需要 keys 指定方向（down/up，可带 :n 行数）", 0
    direction, _, count_raw = text.partition(":")
    if count_raw:
        if not count_raw.isdigit():
            return "invalid", f"行数不是正整数: {count_raw}", 0
        lines = int(count_raw)
        if not 1 <= lines <= SCROLL_MAX_LINES:
            return "invalid", f"行数超出 1..{SCROLL_MAX_LINES}: {lines}", 0
    else:
        lines = SCROLL_DEFAULT_LINES
    if direction == "down":
        return "ok", "down", -lines
    if direction == "up":
        return "ok", "up", lines
    return "invalid", f"方向只接受 down|up: {direction}", 0
