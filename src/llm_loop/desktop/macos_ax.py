"""L1 AX tree read + D4 window binding via ctypes ApplicationServices.

Read-only: attribute reads (AXWindows/AXTitle/AXRole/AXChildren/AXPosition/
AXSize/AXFocused/AXValue/AXSubrole) only.  No action enumeration, no AXPress,
no CGEvent — mutations are M4 and out of scope.

Two pieces are deliberately pure so tests can drive them with fake elements:

- ``node_from_element`` / ``traverse``: DFS preorder, ``ax_ref`` = index path
  from the APP root (e.g. "0.2.1"), node cap with honest ``truncated``.
- ``match_ax_windows``: D4 binding.  CG title available → require title
  equality AND |Δbounds| ≤ 2pt; CG title unavailable (no Screen Recording
  grant, ``title_available=False``) → bounds-only matching.  Unique → bind;
  multiple → ambiguous; zero → unbound.  Never falls back to "frontmost".
"""

from __future__ import annotations

import ctypes
from typing import Any, Protocol

from llm_loop.desktop.macos_cf import (
    K_CFTYPE_ARRAY,
    K_CFTYPE_BOOLEAN,
    K_CFTYPE_NUMBER,
    CFTypeRef,
    CGPoint,
    CGSize,
    cf_array_count,
    cf_array_item,
    cf_release,
    cf_retain,
    cf_to_bool,
    cf_to_int,
    cf_to_str,
    cf_type_kind,
    load_framework,
    make_cfstr,
)
from llm_loop.desktop.models import (
    AX_ERROR_API_DISABLED,
    WINDOW_BIND_TOLERANCE_PT,
    AxCandidate,
    AxNode,
    AxView,
    BoundsPt,
    Pt,
    Size,
    WindowInfo,
)

K_AX_VALUE_POINT_TYPE = 1
K_AX_VALUE_SIZE_TYPE = 2

_PROTO_READY = False


def _asf() -> ctypes.CDLL:
    global _PROTO_READY
    lib = load_framework("ApplicationServices")
    if not _PROTO_READY:
        lib.AXUIElementCreateApplication.argtypes = [ctypes.c_int32]
        lib.AXUIElementCreateApplication.restype = CFTypeRef
        lib.AXUIElementCopyAttributeValue.argtypes = [
            CFTypeRef,
            CFTypeRef,
            ctypes.POINTER(CFTypeRef),
        ]
        lib.AXUIElementCopyAttributeValue.restype = ctypes.c_int32
        lib.AXValueGetTypeID.restype = ctypes.c_ulong
        lib.AXValueGetValue.argtypes = [CFTypeRef, ctypes.c_int, ctypes.c_void_p]
        lib.AXValueGetValue.restype = ctypes.c_bool
        _PROTO_READY = True
    return lib


def ax_read_attr(ref: int, name: str) -> tuple[int, int]:
    """AXUIElementCopyAttributeValue → (err, value_ref)；调用方负责释放 value。"""
    lib = _asf()
    attr = make_cfstr(name)
    try:
        out = CFTypeRef()
        err = int(lib.AXUIElementCopyAttributeValue(ctypes.c_void_p(ref), attr, ctypes.byref(out)))
        return err, int(out.value or 0)
    finally:
        cf_release(attr)


def _decode_ax_value(ref: int) -> Pt | Size | None:
    lib = _asf()
    point = CGPoint()
    if lib.AXValueGetValue(ctypes.c_void_p(ref), K_AX_VALUE_POINT_TYPE, ctypes.byref(point)):
        return Pt(x=float(point.x), y=float(point.y))
    size = CGSize()
    if lib.AXValueGetValue(ctypes.c_void_p(ref), K_AX_VALUE_SIZE_TYPE, ctypes.byref(size)):
        return Size(w=float(size.width), h=float(size.height))
    return None


class MacAxElement:
    """AXUIElement 包装：attr() 返回已解码的 Python 值（str/bool/int/数组/Pt/Size）。

    所有权约定：attr() 数组分支返回的子元素已被 retain（调用方拥有）；
    traverse() 走完一棵子树后会对有 release() 的元素统一 CFRelease，
    避免悬垂引用，也不静默累积泄漏。
    """

    __slots__ = ("_ref",)

    def __init__(self, ref: int) -> None:
        self._ref = int(ref)

    @property
    def ref(self) -> int:
        return self._ref

    def release(self) -> None:
        if self._ref:
            cf_release(self._ref)
            self._ref = 0

    def attr(self, name: str) -> Any:
        err, value = ax_read_attr(self._ref, name)
        if err != 0 or not value:
            return None
        try:
            as_str = cf_to_str(value)
            if as_str is not None:
                return as_str
            kind = cf_type_kind(value)
            if kind == K_CFTYPE_BOOLEAN:
                return cf_to_bool(value)
            if kind == K_CFTYPE_NUMBER:
                return cf_to_int(value)
            if kind == K_CFTYPE_ARRAY:
                # 取出子元素后必须 retain，再释放父数组（否则悬垂引用崩溃）
                return [
                    MacAxElement(cf_retain(cf_array_item(value, i)))
                    for i in range(cf_array_count(value))
                ]
            return _decode_ax_value(value)
        finally:
            cf_release(value)


class AxElementLike(Protocol):
    """traverse() 的最小元素合同（fake 元素实现同一形状即可离线测试）。"""

    def attr(self, name: str) -> Any: ...


def node_from_element(el: AxElementLike, ax_ref: str) -> AxNode:
    """元素 → AxNode（纯函数：所有属性读取失败 → None 字段，不猜）。"""
    value = el.attr("AXValue")
    pos = el.attr("AXPosition")
    size = el.attr("AXSize")
    focused = el.attr("AXFocused")
    return AxNode(
        ax_ref=ax_ref,
        role=_opt_str(el.attr("AXRole")),
        subrole=_opt_str(el.attr("AXSubrole")),
        title=_opt_str(el.attr("AXTitle")),
        value=_opt_str(value) if isinstance(value, (str, int, float)) else None,
        focused=(focused is True),
        pos_pt=pos if isinstance(pos, Pt) else None,
        size_pt=size if isinstance(size, Size) else None,
    )


def _opt_str(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def traverse(
    root: AxElementLike,
    depth: int,
    node_limit: int,
    root_ref: str,
) -> tuple[list[AxNode], bool]:
    """前序 DFS；depth=窗口节点自身为 0 层；超 node_limit 置 truncated（如实截断）。

    所有权：traverse 接管 root 及其全部子元素——子树走完（含截断/达到深度）
    后对提供 release() 的元素统一释放（fake 元素无 release() 则跳过），不留悬垂
    引用也不累积泄漏。
    """
    nodes: list[AxNode] = []
    truncated = False

    def _release(el: Any) -> None:
        release = getattr(el, "release", None)
        if callable(release):
            release()

    def children_of(el: AxElementLike) -> list[Any]:
        kids = el.attr("AXChildren")
        return kids if isinstance(kids, list) else []

    def walk(el: AxElementLike, ref: str, remaining: int) -> None:
        nonlocal truncated
        try:
            if len(nodes) >= node_limit:
                truncated = True
                return
            nodes.append(node_from_element(el, ref))
            if remaining <= 0:
                return
            for index, child in enumerate(children_of(el)):
                if len(nodes) >= node_limit:
                    truncated = True
                    _release(child)
                    continue
                walk(child, f"{ref}.{index}" if ref else str(index), remaining - 1)
        finally:
            _release(el)

    walk(root, root_ref, max(0, int(depth)))
    return nodes, truncated


def bounds_within(a: BoundsPt, b: BoundsPt, tolerance: float = WINDOW_BIND_TOLERANCE_PT) -> bool:
    return (
        abs(a.x - b.x) <= tolerance
        and abs(a.y - b.y) <= tolerance
        and abs(a.w - b.w) <= tolerance
        and abs(a.h - b.h) <= tolerance
    )


def _norm_title(text: str | None) -> str:
    """标题归一：折叠空白（AX 与 CG 的空格/换行不一致不该影响判定）。"""
    return " ".join((text or "").split())


def titles_compatible(cg_title: str | None, ax_title: str | None) -> bool:
    """同一窗口的两种标题呈现：相等，或较短一方是较长一方的**前缀**。

    实测反证（2026-10-28 09:59，活动监视器 pid 71527）：CG 标题 ``活动监视器``，
    AX 标题 ``活动监视器 – 所有进程``，bounds 完全相等（310,100,1064×640）。
    严格相等把这种窗口判成未绑定（``ax_window_unbound``），而它其实是同一窗口。
    前缀相容仍以 bounds 差≤2pt 为前提——只承认"同一位置的这一个窗口"，歧义照旧拒绝。
    """
    a, b = _norm_title(cg_title), _norm_title(ax_title)
    if not a or not b:
        return False
    if a == b:
        return True
    return b.startswith(a) or a.startswith(b)


def match_ax_windows_ex(
    cg_window: WindowInfo,
    ax_candidates: list[tuple[int, str | None, BoundsPt]],
    tolerance: float = WINDOW_BIND_TOLERANCE_PT,
) -> tuple[list[int], str | None]:
    """D4 绑定匹配（纯函数）。返回 ``(命中索引, 依据)``。

    依据按强度取值：``title_exact`` > ``title_relaxed`` > ``bounds_only``（CG 标题
    不可用时才退到纯 bounds，沿用原行为）。无命中返回 ``([], None)``；多命中即歧义，
    由调用方 ``window_ambiguous`` 拒绝——本函数从不"挑一个"。
    """
    strong: list[int] = []
    relaxed: list[int] = []
    bounds_only: list[int] = []
    for ax_index, ax_title, ax_bounds in ax_candidates:
        if not bounds_within(cg_window.bounds_pt, ax_bounds, tolerance):
            continue
        if not cg_window.title_available or not cg_window.title:
            bounds_only.append(ax_index)
        elif _norm_title(cg_window.title) == _norm_title(ax_title):
            strong.append(ax_index)
        elif titles_compatible(cg_window.title, ax_title):
            relaxed.append(ax_index)
    for hits, basis in (
        (strong, "title_exact"),
        (relaxed, "title_relaxed"),
        (bounds_only, "bounds_only"),
    ):
        if hits:
            return hits, basis
    return [], None


def match_ax_windows(
    cg_window: WindowInfo,
    ax_candidates: list[tuple[int, str | None, BoundsPt]],
    tolerance: float = WINDOW_BIND_TOLERANCE_PT,
) -> list[int]:
    """兼容入口：只返回命中的 ax 索引（依据见 ``match_ax_windows_ex``）。"""
    return match_ax_windows_ex(cg_window, ax_candidates, tolerance)[0]


def element_bounds(el: AxElementLike) -> BoundsPt | None:
    pos = el.attr("AXPosition")
    size = el.attr("AXSize")
    if isinstance(pos, Pt) and isinstance(size, Size):
        return BoundsPt(x=pos.x, y=pos.y, w=size.w, h=size.h)
    return None


def app_element(pid: int) -> MacAxElement | None:
    ref = int(_asf().AXUIElementCreateApplication(ctypes.c_int32(pid)) or 0)
    return MacAxElement(ref) if ref else None


def ax_readable_probe(pid: int) -> int | None:
    """只读能力探针：对指定 pid 读 ``AXWindows``，返回 AX 错误码（0=可读）。

    与 ``ax_windows_view`` 走同一条底层路径（建 app 元素 → 读属性 → 释放），因此它
    测到的就是工具真正要做的事；``AXIsProcessTrusted()`` 与 systemwide 探针都会假阴性。
    """
    app = app_element(pid)
    if app is None:
        return None
    try:
        err, value = ax_read_attr(app.ref, "AXWindows")
    finally:
        app.release()
    return err


def ax_windows_view(
    window: WindowInfo,
    depth: int,
    node_limit: int,
) -> AxView:
    """后端用组合函数：建 app 元素 → AXWindows → D4 匹配 → traverse。"""
    app = app_element(window.pid)
    if app is None:
        return AxView(available=False, failure="ax_unavailable", ax_error=AX_ERROR_API_DISABLED)
    try:
        err, value = ax_read_attr(app.ref, "AXWindows")
    finally:
        app.release()
    if err != 0:
        return AxView(available=False, failure="ax_unavailable", ax_error=err)
    if not value:
        return AxView(available=False, failure="ax_window_unbound")
    elements: list[MacAxElement] = []
    try:
        count = cf_array_count(value)
        # retain 每个子元素后再释放父数组（防悬垂引用）
        elements = [MacAxElement(cf_retain(cf_array_item(value, i))) for i in range(count)]
        candidates: list[tuple[int, str | None, BoundsPt]] = []
        for ax_index, el in enumerate(elements):
            bounds = element_bounds(el)
            if bounds is None:
                continue
            candidates.append((ax_index, _opt_str(el.attr("AXTitle")), bounds))
        hits, basis = match_ax_windows_ex(window, candidates)
        if not hits:
            return AxView(available=False, failure="ax_window_unbound")
        if len(hits) > 1:
            return AxView(
                available=False,
                failure="window_ambiguous",
                candidates=tuple(
                    AxCandidate(ax_index=i, title=t, bounds_pt=b)
                    for i, t, b in candidates
                    if i in hits
                ),
            )
        bound_index = hits[0]
        bound = elements[bound_index]
        # root_role 必须在 traverse 前读：traverse 结束时会释放 bound（所有权移交）
        root_role = _opt_str(bound.attr("AXRole")) or "AXWindow"
        nodes, truncated = traverse(bound, depth, node_limit, root_ref=str(bound_index))
        view = AxView(
            available=True,
            root_role=root_role,
            nodes=tuple(nodes),
            truncated=truncated,
            binding=basis,
        )
        return view
    finally:
        # 幂等释放全部候选窗口元素（release() 会把 ref 置 0；bound 已由
        # traverse 接管释放，再次调用是 no-op）——任何 return 路径都不留泄漏
        for el in elements:
            el.release()
        cf_release(value)

