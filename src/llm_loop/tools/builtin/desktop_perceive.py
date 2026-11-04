"""Model-facing read-only desktop perception tool — M3 (DESIGN-20261027 §5.3).

Contract highlights (delegated M3 spec + U13/U14/U18/U19):

- Four single-dispatch read-only actions: status / apps / windows / snapshot.
  No hydrate/wait/operate; no AXPress, no typing, no clicking (M4).
- Every call returns the same envelope keys: ok / action / error_code /
  guidance / permissions / platform / session / elapsed_ms.  Deterministic
  receipts only — no exceptions, no stack traces.
- Graded honesty: a missing layer is reported where it is missing (degraded),
  never as a whole-call failure; but a privacy hit (D8) or allowlist miss
  (U14) refuses the snapshot outright with zero capture and zero AX reads.
- vision=evidence is per-call explicit (default none); screen capture is
  prefetched with CGPreflightScreenCaptureAccess and, when ungranted, the
  tool refuses BEFORE any screencapture run (no black images, U18).
"""

from __future__ import annotations

import contextlib
import json
import platform as _platform
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.desktop.models import (
    AX_NODE_LIMIT_DEFAULT,
    DEFAULT_AX_DEPTH,
    AxNode,
    DesktopErrorCode,
    PermissionSnapshot,
    WindowInfo,
    ax_error_reason,
    clamp_depth,
    jsonable,
)
from llm_loop.desktop.paging import PagedNodes, decode_cursor, paginate
from llm_loop.desktop.privacy import PrivacyPolicy, SeeAllowlist
from llm_loop.desktop.waiting import MAX_WAIT_POLLS, WaitPredicate, wait_for
from llm_loop.timekeeping import system_local_now

_ACTIONS = ("status", "apps", "windows", "snapshot", "wait")

# ── FR-01/FR-02 常量（DESIGN-20261104 §6.1/§6.2）─────────────────────────
# 每页节点宽度：默认 200。1500 节点按最省渲染仍约 3 万 token，单页 200 是把
# "一次回执摧毁上下文" 换成 "按需翻页"。
DEFAULT_PAGE_LIMIT = 200
MAX_PAGE_LIMIT = 500
# 单棵树累计可续读节点上限。无状态实现：由游标里的 offset 判定，不依赖进程内
# 计数器（工具实例生命周期跨调用不可假定），所以重启/多会话下口径一致。
# 取值必须**可达**：遍历受 AX_NODE_LIMIT_DEFAULT(1500) 限制，故上限必须 < 1500，
# 否则该闸门在生产里永不触发（曾经写成 2000 就是死逻辑）。600 ≈ 默认页宽 200 的
# 三页，足够定位到任何可见控件，又不会把上下文烧掉。
MAX_PAGED_NODES = 600
# focused 摘要里 value 的预览长度：够判断"光标在哪个框"，不足以泄漏整段内容。
FOCUS_VALUE_PREVIEW = 120

# ── FR-05 恒定值（§6.5）─────────────────────────────────────────────────
DEFAULT_WAIT_WITHIN_MS = 10000
MAX_WAIT_WITHIN_MS = 60000
DEFAULT_SETTLE_MS = 300
MIN_SETTLE_MS = 50
MAX_SETTLE_MS = 10000
WAIT_KINDS = ("exists", "absent", "focused", "enabled", "value_equals", "value_contains")
#: 只有这些 kind 接受 expected 取反；`value_*` 的取反语义歧义（"等它不等于"？），
#: 直接拒绝而不是猜。
BOOL_WAIT_KINDS = ("exists", "absent", "focused", "enabled")


def _wait_interval_ms(within_ms: int) -> int:
    """轮询间隔：窗口越短探得越密，但绝不低于 50ms（别把 AX 打爆）。"""
    return max(50, min(150, within_ms // 20))

# 节点行渲染的字段白名单。**显式列举而不 asdict 全字段**：AxNode.editable 是
# FR-03 专用（focused 块消费），若随行出现会给每个节点凭空加一个 null 键，
# 与"降低单次回执体积"的目标正相反。
_NODE_ROW_FIELDS = ("ax_ref", "role", "subrole", "title", "value", "focused", "pos_pt", "size_pt")


def _node_row(node: AxNode, *, render: str, geometry: str) -> dict[str, Any]:
    """单个节点 → 回执行。render=full 与既有负载逐字一致（防退化）。"""
    raw = jsonable(node)
    row: dict[str, Any] = {key: raw.get(key) for key in _NODE_ROW_FIELDS}
    if geometry == "none":
        # 丢几何 ⇒ point 寻址目标不可从本页取得；调用方在 page 块标注
        # geometry_dropped=true，不靠模型自己记。
        row.pop("pos_pt", None)
        row.pop("size_pt", None)
    if render == "sparse":
        # 缺字段 ⇔ null/false（回执口径已写在工具 description 里）。
        row = {k: v for k, v in row.items() if v is not None and v is not False}
        # ax_ref 与 role 是寻址/判型的最小身份，任何档位都不许省。
        # role 为 None 时才需要强制回填——否则 sparse 会把"未知角色"变成
        # "字段不存在"，两者对调用方的含义完全不同。
        row["ax_ref"] = node.ax_ref
        row.setdefault("role", None)
    return row


def _focused_block(node: AxNode, *, page_refs: set[str]) -> dict[str, Any]:
    """FR-03：焦点摘要。回答"光标在哪、是不是可编辑框、里面有多少字"，
    而不必把树翻到焦点所在页——焦点常在树尾，正是最贵的那一页。"""
    value = node.value
    preview: str | None = None
    if value is not None:
        preview = value[:FOCUS_VALUE_PREVIEW]
    return {
        "present": True,
        "ax_ref": node.ax_ref,
        "role": node.role,
        "subrole": node.subrole,
        "title": node.title,
        # None = 该元素没读到 AXEditable（角色不支持或 AX 报错），**不是**不可编辑。
        # 由 role 反推 editable 属冒充已读，本实现不做。
        "editable": node.editable,
        "value_len": len(value) if value is not None else None,
        "value_preview": preview,
        "value_truncated": bool(value is not None and len(value) > FOCUS_VALUE_PREVIEW),
        # 焦点节点是否落在本页：false 时可以直接按 ax_ref 翻页取上下文。
        "in_page": node.ax_ref in page_refs,
    }


_ALLOWED_FIELDS: dict[str, set[str]] = {
    "status": {"action"},
    "apps": {"action"},
    "windows": {"action", "include_offscreen"},
    "snapshot": {
        "action", "window_id", "depth", "vision",
        # FR-01 续读：过滤在分页之前做（先按 role 收敛再切片，否则分页只是把
        # 同一批噪声切成多页）。
        "node_cursor", "node_limit", "node_kinds",
        # FR-02 渲染档位：sparse 丢 None/false；geometry=none 丢 pos_pt/size_pt
        # （point 寻址随之失效，回执显式标注）。
        "render", "geometry",
    },
    # FR-05 等待：服务端轮询，替代模型自己 sleep-轮询
    "wait": {
        "action", "window_id", "depth", "ax_ref",
        "kind", "value", "expected", "within_ms", "settle_ms",
    },
}

GUIDANCE_AX = (
    "AX（辅助功能）未授权：打开 系统设置 → 隐私与安全性 → 辅助功能，"
    "将运行 LFL 的终端/宿主应用加入并开启，然后重试 status 自检。"
    "授权绑定启动进程，重启宿主后需复核。"
)
GUIDANCE_CAPTURE = (
    "屏幕录制未授权：打开 系统设置 → 隐私与安全性 → 屏幕录制，"
    "将运行 LFL 的终端/宿主应用加入并开启。未授权时 screencapture 会静默产出"
    "黑图/壁纸，本工具已拒绝调用它；授权后重试。"
)
GUIDANCE_UNSUPPORTED = "desktop_perceive 仅支持 macOS（darwin）；当前平台不支持，工具保持只读不可用。"
GUIDANCE_NO_GUI = "当前进程无图形控制台会话（SSH/无登录用户）；需在已登录桌面会话内运行。"
GUIDANCE_LOCKED = "屏幕已锁定；解锁后重试（锁屏下感知被拒绝）。"
GUIDANCE_NOT_FOUND = "window_id 不在当前窗口清单中；先调用 windows 获取有效 CGWindowID 再 snapshot。"


def _guidance_for_error(code: DesktopErrorCode) -> str:
    return {
        DesktopErrorCode.UNSUPPORTED_PLATFORM: GUIDANCE_UNSUPPORTED,
        DesktopErrorCode.NO_GUI_SESSION: GUIDANCE_NO_GUI,
        DesktopErrorCode.SCREEN_LOCKED: GUIDANCE_LOCKED,
        DesktopErrorCode.AX_UNAVAILABLE: GUIDANCE_AX,
        DesktopErrorCode.CAPTURE_UNAVAILABLE: GUIDANCE_CAPTURE,
        DesktopErrorCode.WINDOW_NOT_FOUND: GUIDANCE_NOT_FOUND,
    }.get(code, "")


def make_jsonl_audit_sink(path: Path | str) -> Callable[[dict[str, Any]], None]:
    """§6.4 append-only JSONL 审计：vision=evidence 与 privacy_blocked 事件各一行。

    无删除/改写接口；文件以追加模式打开（宿主进程写入，模型侧只读）。
    """
    target = Path(path)

    def sink(row: dict[str, Any]) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    return sink


class DesktopPerceiveTool:
    name = "desktop_perceive"
    description = (
        "桌面只读感知（macOS，M3/D2 分级）。status=TCC 权限/显示器/进程能力自检："
        "ax_trusted/screen_capture_granted 如实回 false 并给可执行修复指引，绝不产黑图；"
        "apps=lsappinfo 应用清单（bundle_id/pid/是否前台/是否隐藏/allowed，无需授权）；"
        "windows=CGWindowList 窗口清单（bounds_pt 单位为点；无屏幕录制授权时窗口标题为空 → "
        "title_available=false，不用应用名冒充标题）；snapshot=按 CGWindowID 取窗口元数据+AX 树"
        "（depth 默认 3 上限 6、节点上限 1500、ax_ref 为 app 根索引路径；AX 缺失记 degraded 不整单失败）"
        "；节点过多时可续读：node_kinds 先按 role 收敛，node_limit 控每页宽度（默认 200），"
        "回执 page.next_cursor 非空则用 node_cursor 取下一页（游标绑定树指纹，树变了回 cursor_stale）；"
        "渲染可降档 render=sparse / geometry=none，sparse 下字段缺失等价于 null/false。"
        "回执另含 focused 摘要（焦点节点的 ax_ref/role/value 长度与预览/editable），"
        "可判断光标在哪而无需翻到那一页"
        "+可选 vision=evidence 窗口截图（默认 none 零落盘，逐次显式；截图前先 CGPreflight，"
        "无授权确定性 capture_unavailable 且不调用 screencapture；像素/点双单位并校验 "
        "|px-pt*scale|≤2，超差记 capture_size_mismatch）。敏感应用（1Password/Bitwarden/Keychain/"
        "登录窗口等硬编码核心名单）windows 隐去标题、snapshot 直接 privacy_blocked（零截图零 AX，"
        "连窗口元数据也不给）；desktop.see_allowlist 非空时名单外 app 的 snapshot 拒绝 app_not_allowed。"
        "非 macOS 返回 unsupported_platform；本工具不导航、不键入、不点击（操作属 M4）。"
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "apps", "windows", "snapshot", "wait"],
                "description": (
                    "status=权限/能力自检；apps=应用清单；windows=窗口清单；"
                    "snapshot=单窗口 L0+AX+可选截图（可续读分页）；"
                    "wait=轮询 AX 对象状态直到谓词成立或超时（超时≠对象不存在）"
                ),
            },
            "window_id": {
                "type": "integer",
                "minimum": 0,
                "description": "snapshot 必填：目标窗口 CGWindowID（来自 windows 回执的 window_id）",
            },
            "depth": {
                "type": "integer",
                "minimum": 0,
                "maximum": 6,
                "description": "snapshot：AX 遍历深度，默认 3；0..6 之外会被裁剪并回执 clipped_depth=true",
            },
            "vision": {
                "type": "string",
                "enum": ["none", "evidence"],
                "description": (
                    "snapshot：默认 none（零截图、零落盘、零子进程）。evidence=逐次显式请求窗口级截图"
                    "（PNG 落盘 workspace 缓存目录，回执 image{ref,path,sha256,像素宽高,scale,bounds_pt}）"
                ),
            },
            "include_offscreen": {
                "type": "boolean",
                "description": "windows：默认 false 只列在屏窗口；true 时包含离屏窗口",
            },
            # ── FR-01 续读（DESIGN-20261104 §6.1）──────────────────────────
            "node_kinds": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "description": (
                    "snapshot：按 role 过滤（大小写不敏感，如 [\"axbutton\",\"axtextfield\"]）。"
                    "过滤发生在分页之前——先用它把树收敛，比翻页更省。空数组=不过滤。"
                ),
            },
            "node_limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 500,
                "description": (
                    "snapshot：每页节点上限，默认 200（1..500 超出被机械限幅）。"
                    "节点总数超过它时回执 page.next_cursor 非空。"
                ),
            },
            "node_cursor": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "snapshot：续读游标，取上一次回执的 page.next_cursor。"
                    "游标绑定（window_id, depth, 过滤后树的 fingerprint）；树变了返回 "
                    "cursor_stale、游标不可解析返回 cursor_invalid——两者都不静默重来。"
                    "单棵树可续读节点总量有上限，超过返回 page_budget_exhausted。"
                ),
            },
            # ── FR-02 渲染档位（§6.2）─────────────────────────────────────
            "render": {
                "type": "string",
                "enum": ["full", "sparse"],
                "description": (
                    "snapshot：full=默认（字段齐全，含 null/false）；sparse=丢 null 与 focused=false "
                    "并压缩分隔符。sparse 下**字段缺失即等价于 null/false**，不是没读到。"
                ),
            },
            "geometry": {
                "type": "string",
                "enum": ["full", "none"],
                "description": (
                    "snapshot：full=默认保留 pos_pt/size_pt（point 寻址依赖它）；"
                    "none=丢几何（更省，但回执标注 geometry_dropped=true，"
                    "此后 point 寻址目标不可从本页取得）。"
                ),
            },
            # ── FR-05 等待（§6.5）────────────────────────────────────────
            "ax_ref": {
                "type": "string",
                "minLength": 1,
                "description": "wait：要等待的目标，来自 snapshot 回执的 ax_ref。",
            },
            "kind": {
                "type": "string",
                "enum": ["exists", "absent", "focused", "enabled", "value_equals", "value_contains"],
                "description": (
                    "wait：谓词类型。exists/absent=存在/消失；focused/enabled=焦点/可用态；"
                    "value_equals/value_contains=值匹配。checked/selected 暂不支持"
                    "（AxNode 无该字段，未验证通道不编）。"
                ),
            },
            "expected": {
                "type": "boolean",
                "description": (
                    "wait：期望谓词为真(true)还是为假(false)，默认 true。"
                    "仅 exists/absent/focused/enabled 接受；value_* 给 expected 会被拒。"
                    "expected=false 属「否定型」，需持续成立满 settle_ms 才返回。"
                ),
            },
            "value": {
                "type": "string",
                "description": "wait：value_equals/value_contains 的比对值；其它 kind 给 value 会被拒。",
            },
            "within_ms": {
                "type": "integer",
                "minimum": 1,
                "maximum": 60000,
                "description": "wait：最长等待毫秒，默认 10000、上限 60000。",
            },
            "settle_ms": {
                "type": "integer",
                "minimum": 50,
                "maximum": 10000,
                "description": (
                    "wait：否定型谓词的稳定窗口，默认 300。谓词须持续成立满该时长，"
                    "中途回闪即重置——防「重绘空窗被判成已消失」。"
                ),
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }
    lazy_parameters = parameters

    def __init__(
        self,
        *,
        backend: Any | None = None,
        session_id_getter: Callable[[], str] | None = None,
        audit_sink: Callable[[dict[str, Any]], None] | None = None,
        privacy_extra: tuple[str, ...] = (),
        see_allowlist: tuple[str, ...] = (),
    ) -> None:
        self._backend = backend
        self._session_id_getter = session_id_getter or (lambda: "")
        self._audit = audit_sink
        self._privacy = PrivacyPolicy(privacy_extra)
        self._allowlist = SeeAllowlist(see_allowlist)

    # ── 基础回执 ─────────────────────────────────────────────────────────
    def _fail(self, message: str) -> ToolResult:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=message,
            tool_call_id="",
            tool_name=self.name,
        )

    def _result(
        self, ok: bool, payload: dict[str, Any], *, compact: bool = False
    ) -> ToolResult:
        # compact 只由 render=sparse 触发。缩进与分隔符是大头（约 −20% 字符），
        # 但 full 档必须与既有回执逐字一致——既有测试与模型侧阅读习惯都建立在
        # indent=1 格式上，默认路径不得漂移。
        if compact:
            content = json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
        else:
            content = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1)
        return ToolResult(
            status=(ToolResultStatus.SUCCESS if ok else ToolResultStatus.FAILURE),
            content=content,
            tool_call_id="",
            tool_name=self.name,
        )

    def _envelope(
        self,
        *,
        action: str,
        ok: bool,
        error_code: DesktopErrorCode | None,
        guidance: str | None,
        started: float,
        permissions: dict[str, Any] | None = None,
        platform_info: dict[str, Any] | None = None,
        session: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        compact: bool = False,
    ) -> ToolResult:
        receipt: dict[str, Any] = {
            "ok": bool(ok),
            "action": action,
            "error_code": (error_code.value if error_code else None),
            "guidance": guidance or None,
            "permissions": permissions or {"ax_trusted": False, "screen_capture_granted": False},
            "platform": platform_info or {"os": _platform.system().lower(), "version": ""},
            "session": session
            or {"gui_available": False, "console_user": None, "screen_locked": None},
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
        if payload:
            receipt.update(payload)
        return self._result(ok, receipt, compact=compact)

    def _audit_event(
        self,
        *,
        window_id: int | None,
        app_bundle: str | None,
        error_code: str | None,
        sha256: str | None,
    ) -> None:
        if self._audit is None:
            return
        row = {
            "ts": system_local_now().isoformat(timespec="milliseconds"),
            "session_id": str(self._session_id_getter() or ""),
            "tool": self.name,
            "window_id": window_id,
            "app_bundle": app_bundle,
            "risk_class": "see",
            "error_code": error_code,
            "sha256": sha256,
        }
        with contextlib.suppress(Exception):  # 审计写失败不得改变工具回执语义
            self._audit(row)

    # ── 参数校验 ─────────────────────────────────────────────────────────
    def _parse_snapshot_render_and_paging(
        self, kwargs: dict[str, Any], options: dict[str, Any]
    ) -> ToolResult | None:
        """FR-01/FR-02 参数解析与校验：渲染档位、role 过滤、每页宽度、续读游标。

        独立成函数而非塞进 `_validate`：R9 棘轮对 `_validate` 有 119 行上限，
        而分页新增的校验分支本身就占 40 余行。语义上这也是一件事——
        "把 snapshot 的可选参数归一成 options"，与 action 分派无关。
        """
        # FR-02：渲染档位（默认 full —— 与既有负载逐字兼容）
        render = str(kwargs.get("render") or "full").strip()
        if render not in ("full", "sparse"):
            return self._fail(
                "[desktop_perceive:snapshot] render 只接受 full | sparse（默认 full）。"
            )
        options["render"] = render
        geometry = str(kwargs.get("geometry") or "full").strip()
        if geometry not in ("full", "none"):
            return self._fail(
                "[desktop_perceive:snapshot] geometry 只接受 full | none（默认 full）。"
            )
        options["geometry"] = geometry
        # FR-01：过滤 → 分页（顺序不可换：先收敛再切片）
        kinds_raw = kwargs.get("node_kinds")
        if kinds_raw is None:
            kinds_raw = []
        if not isinstance(kinds_raw, (list, tuple)):
            return self._fail(
                "[desktop_perceive:snapshot] node_kinds 必须是字符串数组。"
            )
        kinds: list[str] = []
        for item in kinds_raw:
            if not isinstance(item, str) or not item.strip():
                return self._fail(
                    "[desktop_perceive:snapshot] node_kinds 每项必须是非空字符串。"
                )
            kinds.append(item.strip().lower())
        options["node_kinds"] = tuple(sorted(set(kinds)))
        node_limit = kwargs.get("node_limit", DEFAULT_PAGE_LIMIT)
        if isinstance(node_limit, bool) or not isinstance(node_limit, int):
            return self._fail(
                "[desktop_perceive:snapshot] node_limit 必须是整数（1..500）。"
            )
        if node_limit < 1 or node_limit > MAX_PAGE_LIMIT:
            # 确定性拒绝，不做静默限幅：静默改参数会让"我以为只取 10 个"
            # 变成悄悄取 500 个，恰恰是这次要治的问题。
            return self._fail(
                f"[desktop_perceive:snapshot] invalid_args: node_limit 必须在 "
                f"1..{MAX_PAGE_LIMIT} 之间（收到 {node_limit}），不做静默限幅——"
                "要更省请配合 node_kinds 收敛。"
            )
        options["node_limit"] = node_limit
        cursor = kwargs.get("node_cursor")
        if cursor is not None:
            if not isinstance(cursor, str) or not cursor.strip():
                return self._fail(
                    "[desktop_perceive:snapshot] node_cursor 必须是非空字符串"
                    "（取上次回执的 page.next_cursor）。"
                )
            options["node_cursor"] = cursor.strip()

    def _validate(self, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any], ToolResult | None]:
        action = str(kwargs.get("action") or "").strip()
        if action not in _ACTIONS:
            return action, {}, self._fail(
                f"[desktop_perceive] action 不受支持: {action or '<missing>'}"
                f"（可选: {', '.join(_ACTIONS)}）。"
            )
        allowed = _ALLOWED_FIELDS[action]
        extras = sorted(set(kwargs) - allowed)
        if extras:
            return action, {}, self._fail(
                f"[desktop_perceive:{action}] fields_mismatch: action 不接受字段 {extras}。"
            )
        options: dict[str, Any] = {}
        if action == "snapshot":
            window_id = kwargs.get("window_id")
            if isinstance(window_id, bool) or not isinstance(window_id, int) or window_id < 0:
                return action, {}, self._fail(
                    "[desktop_perceive:snapshot] window_id 必填且必须是非负整数"
                    "（来自 windows 回执的 CGWindowID）。"
                )
            options["window_id"] = int(window_id)
            depth_raw = kwargs.get("depth", DEFAULT_AX_DEPTH)
            if isinstance(depth_raw, bool) or not isinstance(depth_raw, int):
                return action, {}, self._fail("[desktop_perceive:snapshot] depth 必须是整数（0..6）。")
            options["depth_raw"] = int(depth_raw)
            vision = str(kwargs.get("vision") or "none").strip()
            if vision not in ("none", "evidence"):
                return action, {}, self._fail(
                    "[desktop_perceive:snapshot] vision 只接受 none | evidence（默认 none）。"
                )
            options["vision"] = vision
            error = self._parse_snapshot_render_and_paging(kwargs, options)
            if error is not None:
                return action, {}, error
        if action == "wait":
            window_id = kwargs.get("window_id")
            if isinstance(window_id, bool) or not isinstance(window_id, int):
                return action, {}, self._fail(
                    "[desktop_perceive:wait] window_id 必填且必须是整数。"
                )
            options["window_id"] = window_id
            options["depth_raw"] = kwargs.get("depth", DEFAULT_AX_DEPTH)
            ax_ref = kwargs.get("ax_ref")
            if not isinstance(ax_ref, str) or not ax_ref.strip():
                return action, {}, self._fail(
                    "[desktop_perceive:wait] ax_ref 必填（取 snapshot 回执里的 ax_ref）。"
                )
            options["ax_ref"] = ax_ref.strip()
            kind = kwargs.get("kind")
            if kind not in WAIT_KINDS:
                return action, {}, self._fail(
                    f"[desktop_perceive:wait] kind 只接受 {' | '.join(WAIT_KINDS)}；"
                    "checked/selected 暂不支持（AxNode 无该字段，未验证通道不编）。"
                )
            options["kind"] = kind
            expected = kwargs.get("expected", True)
            if not isinstance(expected, bool):
                return action, {}, self._fail(
                    "[desktop_perceive:wait] expected 必须是布尔值。"
                )
            if kind == "absent" and expected is False:
                # absent 本身就是否定谓词；再取反等于 exists，语义重复且易错。
                return action, {}, self._fail(
                    "[desktop_perceive:wait] kind=absent 不接受 expected=false；"
                    "要等它出现请用 kind=exists。"
                )
            value = kwargs.get("value")
            if kind in ("value_equals", "value_contains"):
                if not isinstance(value, str):
                    return action, {}, self._fail(
                        f"[desktop_perceive:wait] kind={kind} 必须给 value（字符串）。"
                    )
                if expected is False:
                    return action, {}, self._fail(
                        "[desktop_perceive:wait] fields_mismatch: value_* 不接受 "
                        "expected=false（「等它不等于」语义歧义，拒绝而不猜）。"
                    )
            elif value is not None:
                return action, {}, self._fail(
                    f"[desktop_perceive:wait] fields_mismatch: kind={kind} 不接受 value。"
                )
            options["value"] = value
            options["expected"] = expected
            within = kwargs.get("within_ms", DEFAULT_WAIT_WITHIN_MS)
            if isinstance(within, bool) or not isinstance(within, int) or within < 1:
                return action, {}, self._fail(
                    "[desktop_perceive:wait] within_ms 必须是正整数（1..60000）。"
                )
            options["within_ms"] = min(MAX_WAIT_WITHIN_MS, within)
            settle = kwargs.get("settle_ms", DEFAULT_SETTLE_MS)
            if isinstance(settle, bool) or not isinstance(settle, int) or settle < MIN_SETTLE_MS:
                return action, {}, self._fail(
                    f"[desktop_perceive:wait] settle_ms 必须是 >= {MIN_SETTLE_MS} 的整数。"
                )
            options["settle_ms"] = min(MAX_SETTLE_MS, settle)
        if action == "windows":
            include_offscreen = kwargs.get("include_offscreen", False)
            if not isinstance(include_offscreen, bool):
                return action, {}, self._fail(
                    "[desktop_perceive:windows] include_offscreen 必须是布尔值。"
                )
            options["include_offscreen"] = include_offscreen
        return action, options, None

    # ── 预检与分发 ───────────────────────────────────────────────────────
    def execute(self, **kwargs: Any) -> ToolResult:
        started = time.monotonic()
        action, options, invalid = self._validate(dict(kwargs))
        if invalid is not None:
            return invalid
        backend = self._backend
        if backend is None or not bool(getattr(backend, "supported", False)):
            return self._envelope(
                action=action,
                ok=False,
                error_code=DesktopErrorCode.UNSUPPORTED_PLATFORM,
                guidance=GUIDANCE_UNSUPPORTED,
                started=started,
            )
        try:
            platform_info = backend.platform_info()
            session = backend.session_snapshot()
        except Exception:  # noqa: BLE001 - 后端异常确定性回执，不带栈
            return self._envelope(
                action=action,
                ok=False,
                error_code=DesktopErrorCode.BACKEND_ERROR,
                guidance="桌面后端初始化失败（平台/会话探测异常）；本回执不含栈，请重试或检查运行环境。",
                started=started,
            )
        platform_dict = jsonable(platform_info)
        session_dict = jsonable(session)
        if not session.gui_available:
            return self._envelope(
                action=action,
                ok=False,
                error_code=DesktopErrorCode.NO_GUI_SESSION,
                guidance=GUIDANCE_NO_GUI,
                started=started,
                platform_info=platform_dict,
                session=session_dict,
            )
        if session.screen_locked:
            return self._envelope(
                action=action,
                ok=False,
                error_code=DesktopErrorCode.SCREEN_LOCKED,
                guidance=GUIDANCE_LOCKED,
                started=started,
                platform_info=platform_dict,
                session=session_dict,
            )
        try:
            perms = backend.permission_snapshot()
        except Exception:  # noqa: BLE001 - 权限探测失败按未授权口径报告
            perms = PermissionSnapshot(ax_trusted=False, screen_capture_granted=False, ax_error=None)
        context = {
            "backend": backend,
            "perms": perms,
            "platform": platform_dict,
            "session": session_dict,
        }
        try:
            if action == "status":
                return self._status_action(started, **context)
            if action == "apps":
                return self._apps_action(started, **context)
            if action == "wait":
                return self._wait_action(started, options=options, **context)
            if action == "windows":
                return self._windows_action(started, include_offscreen=options["include_offscreen"], **context)
            return self._snapshot_action(started, options=options, **context)
        except Exception:  # noqa: BLE001 - 分发层兜底：确定性 backend_error，无栈
            return self._envelope(
                action=action,
                ok=False,
                error_code=DesktopErrorCode.BACKEND_ERROR,
                guidance="桌面后端执行失败（确定性回执，不含栈）；可重试 status 自检定位缺失层。",
                started=started,
                permissions=self._perms_dict(perms),
                platform_info=platform_dict,
                session=session_dict,
            )

    @staticmethod
    def _perms_dict(perms: PermissionSnapshot, include_error: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "ax_trusted": bool(perms.ax_trusted),
            "screen_capture_granted": bool(perms.screen_capture_granted),
        }
        if include_error:
            data["ax_error"] = perms.ax_error
        return data

    # ── status ──────────────────────────────────────────────────────────
    def _status_action(self, started: float, *, backend: Any, perms: PermissionSnapshot,
                       platform: dict, session: dict) -> ToolResult:
        try:
            displays = [jsonable(item) for item in backend.list_displays()]
            process = backend.process_info()
            capability = backend.capability_snapshot()
        except Exception:  # noqa: BLE001
            return self._envelope(
                action="status", ok=False, error_code=DesktopErrorCode.BACKEND_ERROR,
                guidance="status 自检后端调用失败（确定性回执，不含栈）。",
                started=started, permissions=self._perms_dict(perms, include_error=True),
                platform_info=platform, session=session,
            )
        guidance_parts = []
        if not bool(capability.get("can_read_ax")):
            guidance_parts.append(GUIDANCE_AX)
        if not perms.screen_capture_granted:
            guidance_parts.append(GUIDANCE_CAPTURE)
        return self._envelope(
            action="status",
            ok=True,
            error_code=None,
            guidance=(" ".join(guidance_parts) if guidance_parts else None),
            started=started,
            permissions=self._perms_dict(perms, include_error=True),
            platform_info=platform,
            session=session,
            payload={
                "displays": displays,
                "process": process,
                "capability": capability,
            },
        )

    # ── apps ────────────────────────────────────────────────────────────
    def _apps_action(self, started: float, *, backend: Any, perms: PermissionSnapshot,
                     platform: dict, session: dict) -> ToolResult:
        apps = [
            {**jsonable(app), "allowed": self._allowlist.is_allowed(app.bundle_id)}
            for app in backend.list_apps()
        ]
        return self._envelope(
            action="apps",
            ok=True,
            error_code=None,
            guidance=None,
            started=started,
            permissions=self._perms_dict(perms),
            platform_info=platform,
            session=session,
            payload={"apps": apps},
        )

    # ── windows ─────────────────────────────────────────────────────────
    def _redact_window(self, window: Any) -> dict[str, Any]:
        data = jsonable(window)
        if self._privacy.is_sensitive(window.bundle_id) or not self._allowlist.is_allowed(
            window.bundle_id
        ):
            # D8/U14：命中核心隐私名单或 see 名单外 → 标题置空并显式标注，绝不过滤行
            data["title"] = None
            data["title_redacted"] = True
        return data

    def _windows_action(self, started: float, *, include_offscreen: bool, backend: Any,
                        perms: PermissionSnapshot, platform: dict, session: dict) -> ToolResult:
        windows = [
            self._redact_window(window)
            for window in backend.list_windows(include_offscreen=include_offscreen)
        ]
        return self._envelope(
            action="windows",
            ok=True,
            error_code=None,
            guidance=None,
            started=started,
            permissions=self._perms_dict(perms),
            platform_info=platform,
            session=session,
            payload={"windows": windows},
        )

    # ── wait（FR-05）────────────────────────────────────────────────────
    def _wait_action(self, started: float, *, options: dict[str, Any], backend: Any,
                     perms: PermissionSnapshot, platform: dict, session: dict) -> ToolResult:
        """服务端轮询 AX 谓词。只读：不动光标、不投递事件、不截图。

        与 snapshot 共用同一套隐私/白名单门——不能因为"只是等等"就绕过：
        wait 每轮都要读 AX，绕过等于开了条不经过 D8 的感知侧信道。
        """
        window, bundle, blocked = self._bind_window(
            options=options,
            backend=backend,
            action="wait",
            started=started,
            perms=perms,
            platform=platform,
            session=session,
        )
        if blocked is not None:
            return blocked
        depth, clipped = clamp_depth(options.get("depth_raw", DEFAULT_AX_DEPTH))
        degraded: list[str] = []
        if not perms.ax_trusted:
            degraded.append("ax_not_trusted")
        within_ms = int(options["within_ms"])
        predicate = WaitPredicate(
            kind=str(options["kind"]),
            expected=bool(options["expected"]),
            value=options.get("value"),
            settle_ms=int(options["settle_ms"]),
        )
        ax_ref = str(options["ax_ref"])
        observed_failures: list[str] = []

        def snapshot() -> Any:
            view = backend.ax_snapshot(window, depth, AX_NODE_LIMIT_DEFAULT)
            if not view.available and "ax_unavailable" not in observed_failures:
                observed_failures.append("ax_unavailable")
            if view.truncated and "ax_traversal_truncated" not in observed_failures:
                observed_failures.append("ax_traversal_truncated")
            return view.nodes

        outcome = wait_for(
            snapshot,
            ax_ref,
            predicate,
            within_ms=within_ms,
            interval_ms=_wait_interval_ms(within_ms),
            max_polls=MAX_WAIT_POLLS,
        )
        degraded.extend(observed_failures)
        guidance: str | None = None
        if not outcome.satisfied:
            guidance = (
                f"[desktop_perceive:wait] 超时：{outcome.elapsed_ms}ms 内未观察到谓词成立"
                f"（kind={predicate.kind}）。超时≠对象不存在——只代表这个窗口内没等到，"
                "不要据此判定操作失败；可加长 within_ms，或直接用 snapshot 看当前状态。"
            )
        if "ax_unavailable" in degraded:
            degraded.append("wait_without_ax: 谓词永不成立，本次等待的结果不可解释")
        return self._envelope(
            action="wait",
            ok=True,
            error_code=None,
            guidance=guidance,
            started=started,
            permissions=self._perms_dict(perms),
            platform_info=platform,
            session=session,
            payload={
                "wait": {
                    "kind": predicate.kind,
                    "ax_ref": ax_ref,
                    "expected": predicate.expected,
                    "value": predicate.value,
                    "settle_ms": predicate.settle_ms,
                    "within_ms": within_ms,
                    "elapsed_ms": outcome.elapsed_ms,
                    "polls": outcome.polls,
                    "state": outcome.state,
                    "satisfied": outcome.satisfied,
                    "observed": outcome.observed,
                    "clipped_depth": bool(clipped),
                },
                "degraded": degraded,
            },
        )

    def _capture_evidence(self, *, backend: Any, window: WindowInfo, bundle: str,
                          degraded: list[str], error_code: DesktopErrorCode | None,
                          guidance: str | None,
                          ) -> tuple[DesktopErrorCode | None, str | None, dict[str, Any] | None]:
        """vision=evidence 的截图采集 + 审计。失败不抛，转成 error_code/guidance。"""
        image_payload: dict[str, Any] | None = None
        outcome = backend.capture_window(window)
        if outcome.error is not None:
            error_code = outcome.error
            guidance = " ".join(
                part
                for part in (
                    outcome.detail,
                    GUIDANCE_CAPTURE
                    if outcome.error == DesktopErrorCode.CAPTURE_UNAVAILABLE
                    else "",
                )
                if part
            )
            self._audit_event(
                window_id=window.window_id,
                app_bundle=bundle,
                error_code=outcome.error.value,
                sha256=None,
            )
        else:
            degraded.extend(outcome.degraded)
            image_payload = jsonable(outcome.image)
            self._audit_event(
                window_id=window.window_id,
                app_bundle=bundle,
                error_code=None,
                sha256=outcome.image.sha256 if outcome.image else None,
            )
        return error_code, guidance, image_payload

    def _build_ax_payload(self, *, ax_view: Any, all_nodes: tuple[AxNode, ...],
                          filtered: tuple[AxNode, ...], page: PagedNodes, render: str,
                          geometry: str, page_limit: int, kinds: tuple[str, ...],
                          clipped: bool, degraded: list[str]) -> dict[str, Any]:
        """本页节点行 + 分页元信息 + 焦点摘要 → ax payload。

        纯数据整形，不碰门控也不回执；抽出来是为了让 `_snapshot_action` 回到
        R9 棘轮登记的 121 行以内（加大分页/渲染/焦点三块后它一度 178 行）。
        """
        page_rows = [_node_row(node, render=render, geometry=geometry) for node in page.nodes]
        page_refs = {str(row["ax_ref"]) for row in page_rows}
        # FR-03：焦点摘要取全树（不是本页）——焦点常在树尾，正是最贵的那一页，
        # "要读焦点就得翻到最后一页"是本设计要消掉的成本。
        focus_node = next((node for node in all_nodes if node.focused), None)
        if ax_view.truncated:
            # 遍历本身被 AX_NODE_LIMIT_DEFAULT 截断 ⇒ total 只是"已遍历部分"的总量，
            # 余下节点翻页也拿不到，只能降 depth / 加过滤。必须显式，否则调用方会把
            # remaining=0 误读成"整棵树都看完了"。
            degraded.append("ax_traversal_truncated")
        ax_payload: dict[str, Any] = {
            "available": bool(ax_view.available),
            "root_role": ax_view.root_role,
            "node_count": len(all_nodes),
            "truncated": bool(ax_view.truncated),
            "clipped_depth": bool(clipped),
            "nodes": page_rows,
            "filtered_count": len(filtered),
            "node_kinds": list(kinds),
            "page": {
                "index": page.index,
                "returned": len(page.nodes),
                "total": page.total,
                "remaining": page.remaining,
                "next_cursor": page.next_cursor,
                "page_limit": page_limit,
                "render": render,
                "geometry": geometry,
                "geometry_dropped": geometry == "none",
                "traversal_truncated": bool(ax_view.truncated),
            },
            "focused": (
                _focused_block(focus_node, page_refs=page_refs)
                if focus_node is not None
                else {"present": False}
            ),
        }
        return ax_payload

    def _cursor_error(self, *, window: WindowInfo, code: DesktopErrorCode, guidance: str,
                      started: float, perms: PermissionSnapshot, platform: dict,
                      session: dict) -> ToolResult:
        """游标类失败的统一回执。三种坏法（坏串/额度/树变）共用同一信封形状，
        调用方按 error_code 分支即可，不必解析文案。"""
        return self._envelope(
            action="snapshot",
            ok=False,
            error_code=code,
            guidance=guidance,
            started=started,
            permissions=self._perms_dict(perms),
            platform_info=platform,
            session=session,
            payload={"window": jsonable(window)},
        )

    def _resolve_page(self, *, filtered: tuple[AxNode, ...], window: WindowInfo, depth: int,
                      cursor_raw: str | None, page_limit: int, started: float,
                      perms: PermissionSnapshot, platform: dict, session: dict,
                      ) -> PagedNodes | ToolResult:
        """过滤后节点 → 本页。失败时返回回执而非抛异常，调用方 isinstance 分流。"""
        if cursor_raw is not None:
            decoded = decode_cursor(str(cursor_raw))
            if decoded is None:
                return self._cursor_error(
                    window=window,
                    code=DesktopErrorCode.CURSOR_INVALID,
                    guidance=(
                        "[desktop_perceive:snapshot] cursor_invalid: node_cursor 不可解析"
                        "（前缀/版本/字段类型不符）。游标是上次回执 page.next_cursor 的"
                        "原样字符串，不要手工构造；要从头取页就省略 node_cursor。"
                    ),
                    started=started, perms=perms, platform=platform, session=session,
                )
            if decoded.offset >= MAX_PAGED_NODES:
                return self._cursor_error(
                    window=window,
                    code=DesktopErrorCode.PAGE_BUDGET_EXHAUSTED,
                    guidance=(
                        f"[desktop_perceive:snapshot] page_budget_exhausted: 单棵树已续读到 "
                        f"{decoded.offset} 节点，上限 {MAX_PAGED_NODES}。"
                        "全树枚举不是本工具的用途：请用 node_kinds 收敛 role，"
                        "或降低 depth 重新取第一页。"
                    ),
                    started=started, perms=perms, platform=platform, session=session,
                )
        try:
            return paginate(
                filtered,
                window_id=int(window.window_id),
                depth=depth,
                cursor=(str(cursor_raw) if cursor_raw is not None else None),
                page_limit=page_limit,
            )
        except ValueError as exc:
            # decode 已通过，能走到这里只剩两种可能：树变了，或游标越过了当前树尾。
            # 两者处置相同（重新取第一页），故合并为 cursor_stale，不硬拆成假区分。
            return self._cursor_error(
                window=window,
                code=DesktopErrorCode.CURSOR_STALE,
                guidance=(
                    f"[desktop_perceive:snapshot] cursor_stale: 游标绑定的树已变（{exc}）。"
                    "游标绑定 (window_id, depth, 过滤后树的结构指纹)；窗口内容变化、"
                    "depth 或 node_kinds 改变都会使其失效。请省略 node_cursor 从第一页"
                    "重新取——不要复用旧游标。"
                ),
                started=started, perms=perms, platform=platform, session=session,
            )

    # ── snapshot ────────────────────────────────────────────────────────
    def _bind_window(self, *, options: dict[str, Any], backend: Any, action: str,
                     started: float, perms: PermissionSnapshot,
                     platform: dict, session: dict,
                     ) -> tuple[WindowInfo | None, str, ToolResult | None]:
        """窗口绑定 + 三道拒绝闸（privacy_blocked > app_not_allowed > 放行）。

        返回 (window, bundle, 阻塞回执)。snapshot 与 wait 必须走**同一套**闸，
        否则 wait 就成了绕过隐私/白名单的旁路；action 只影响回执里的 action 字段，
        不改变闸的判定顺序与结论。
        """
        window = backend.get_window(int(options["window_id"]))
        if window is None:
            return None, "", self._envelope(
                action=action, ok=False,
                error_code=DesktopErrorCode.WINDOW_NOT_FOUND, guidance=GUIDANCE_NOT_FOUND,
                started=started, permissions=self._perms_dict(perms),
                platform_info=platform, session=session,
            )
        bundle = window.bundle_id
        if self._privacy.is_sensitive(bundle):
            self._audit_event(
                window_id=window.window_id, app_bundle=bundle,
                error_code=DesktopErrorCode.PRIVACY_BLOCKED.value, sha256=None,
            )
            return None, bundle, self._envelope(
                action=action, ok=False,
                error_code=DesktopErrorCode.PRIVACY_BLOCKED,
                guidance=(
                    f"目标窗口属于隐私核心名单（bundle_id={bundle}）；按 D8 拒绝读取，"
                    "不提供窗口元数据、不读 AX、不截图、不轮询，无降级路径。"
                ),
                started=started, permissions=self._perms_dict(perms),
                platform_info=platform, session=session,
            )
        if not self._allowlist.is_allowed(bundle):
            return None, bundle, self._envelope(
                action=action, ok=False,
                error_code=DesktopErrorCode.APP_NOT_ALLOWED,
                guidance=(
                    f"目标应用不在 desktop.see_allowlist（bundle_id={bundle}，U14）；"
                    "需要读取时由用户在配置中追加该 bundle_id。"
                ),
                started=started, permissions=self._perms_dict(perms),
                platform_info=platform, session=session,
                payload={"window": self._redact_window(window)},
            )

        return window, bundle, None

    def _snapshot_action(self, started: float, *, options: dict[str, Any], backend: Any,
                         perms: PermissionSnapshot, platform: dict, session: dict) -> ToolResult:
        window, bundle, blocked = self._bind_window(
            options=options,
            backend=backend,
            action="snapshot",
            started=started,
            perms=perms,
            platform=platform,
            session=session,
        )
        if blocked is not None:
            return blocked
        depth, clipped = clamp_depth(options.get("depth_raw", DEFAULT_AX_DEPTH))
        vision = str(options.get("vision") or "none")
        render = str(options.get("render") or "full")
        geometry = str(options.get("geometry") or "full")
        kinds = tuple(options.get("node_kinds") or ())
        page_limit = int(options.get("node_limit") or DEFAULT_PAGE_LIMIT)
        ax_view = backend.ax_snapshot(window, depth, AX_NODE_LIMIT_DEFAULT)
        degraded: list[str] = []
        all_nodes = tuple(ax_view.nodes)
        # FR-01：过滤**先于**分页。翻页只解决"单页太大"；把树收敛得靠过滤。
        # 顺序反了就是把同一批噪声切成多页——看着省了，其实一页页翻更贵。
        filtered = (
            tuple(node for node in all_nodes if str(node.role or "").strip().lower() in kinds)
            if kinds
            else all_nodes
        )
        cursor_raw = options.get("node_cursor")
        page = self._resolve_page(
            filtered=filtered,
            window=window,
            depth=depth,
            cursor_raw=cursor_raw,
            page_limit=page_limit,
            started=started,
            perms=perms,
            platform=platform,
            session=session,
        )
        if isinstance(page, ToolResult):
            return page
        ax_payload = self._build_ax_payload(
            ax_view=ax_view,
            all_nodes=all_nodes,
            filtered=filtered,
            page=page,
            render=render,
            geometry=geometry,
            page_limit=page_limit,
            kinds=kinds,
            clipped=clipped,
            degraded=degraded,
        )
        error_code: DesktopErrorCode | None = None
        guidance: str | None = None
        if ax_view.available and ax_view.binding == "title_relaxed":
            # 绑定不是"标题完全相等"，而是"同一位置 + 标题前缀相容"。回执必须显式标注：
            # 调用方要能区分"确证同一窗口"与"按前缀相容认定"。
            degraded.append("ax_title_relaxed")
            ax_payload["binding"] = ax_view.binding
        elif ax_view.available and ax_view.binding:
            ax_payload["binding"] = ax_view.binding
        if not ax_view.available:
            failure = str(ax_view.failure or "ax_unavailable")
            degraded.append(failure)
            if failure == "window_ambiguous":
                error_code = DesktopErrorCode.WINDOW_AMBIGUOUS
                guidance = (
                    "AX 侧存在多个 (标题相等且 bounds 差≤2pt) 的候选窗口，绑定歧义；"
                    "请换用无歧义的 window_id 或稍后重试。回执附候选清单。"
                )
                ax_payload["candidates"] = [jsonable(c) for c in ax_view.candidates]
            else:
                guidance = self._ax_failure_guidance(ax_view)
        image_payload: dict[str, Any] | None = None
        if vision == "evidence":
            error_code, guidance, image_payload = self._capture_evidence(
                backend=backend,
                window=window,
                bundle=bundle,
                degraded=degraded,
                error_code=error_code,
                guidance=guidance,
            )
        ok = error_code is None
        return self._envelope(
            action="snapshot",
            ok=ok,
            error_code=error_code,
            guidance=(guidance or None),
            started=started,
            permissions=self._perms_dict(perms),
            platform_info=platform,
            session=session,
            payload={
                "window": jsonable(window),
                "ax": ax_payload,
                "image": image_payload,
                "degraded": degraded,
            },
            # FR-02：sparse 档连信封一起压（缩进是纯格式开销）；full 档保持原样。
            compact=(render == "sparse"),
        )

    @staticmethod
    def _ax_failure_guidance(ax_view: Any) -> str:
        """AX 缺层的指引：-25211 给修复指引；其余给确定性原因；未绑定给不猜声明。"""
        if ax_view.ax_error is not None:
            reason = ax_error_reason(ax_view.ax_error)
            if ax_view.ax_error == -25211:
                return f"{reason}。{GUIDANCE_AX}"
            return reason
        return "AX 绑定未命中（title 相等且 bounds 差≤2pt 无唯一窗口）；不猜测、不退回前台窗口。"


