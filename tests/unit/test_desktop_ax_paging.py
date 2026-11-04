# AX 续读分页纯逻辑单元测试（src/llm_loop/desktop/paging.py 委派契约）
"""paging.py 纯逻辑分页：指纹稳定性/敏感性、游标编解码往返与拒绝、
分页边界（整除/零头/大 limit/offset==total/空树）、跨树复用失效、
PageBudget 计账。

全部为离线纯函数测试（无 I/O、无 macOS 框架、无子进程），符合
hermetic 测试纪律。
"""

from __future__ import annotations

import base64
import json

import pytest

from llm_loop.desktop.models import AxNode, Pt, Size
from llm_loop.desktop.paging import (
    CURSOR_PREFIX,
    CURSOR_VERSION,
    PageBudget,
    PageCursor,
    PagedNodes,
    decode_cursor,
    encode_cursor,
    paginate,
    tree_fingerprint,
)


def _node(
    ax_ref: str = "0",
    role: str | None = "AXButton",
    subrole: str | None = None,
    title: str | None = "按钮",
    value: str | None = None,
    focused: bool = False,
    pos_pt: Pt | None = None,
    size_pt: Size | None = None,
) -> AxNode:
    return AxNode(
        ax_ref=ax_ref,
        role=role,
        subrole=subrole,
        title=title,
        value=value,
        focused=focused,
        pos_pt=pos_pt,
        size_pt=size_pt,
    )


def _tree(n: int = 6) -> list[AxNode]:
    return [_node(ax_ref=f"0.{i}", role="AXButton", title=f"第{i}项") for i in range(n)]


def _raw_token(payload: object) -> str:
    """绕过 encode_cursor、手工编码任意负载的游标（专供非法输入测试）。"""
    body = (
        base64.urlsafe_b64encode(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        .decode("ascii")
        .rstrip("=")
    )
    return f"{CURSOR_PREFIX}.{body}"


# ══ 1. 树结构指纹 ══════════════════════════════════════════════════════════
def test_fingerprint_stable_ignores_volatile_fields():
    """防回归：value/focused/pos_pt/size_pt 漂移（编辑/滚动/聚焦）不得改变
    指纹——否则本可续读的游标被无谓判为 cursor_stale，续读链路频繁断裂。"""
    base = [
        _node(
            ax_ref="0",
            role="AXTextField",
            title="搜索",
            value="旧值",
            focused=False,
            pos_pt=Pt(1.0, 2.0),
            size_pt=Size(10.0, 20.0),
        ),
        _node(ax_ref="0.0", role="AXButton", title="确定"),
    ]
    drifted = [
        _node(
            ax_ref="0",
            role="AXTextField",
            title="搜索",
            value="用户刚输入的一大段新文本",
            focused=True,
            pos_pt=Pt(999.0, -5.0),
            size_pt=Size(800.0, 600.0),
        ),
        _node(ax_ref="0.0", role="AXButton", title="确定"),
    ]
    assert tree_fingerprint(101, 3, base) == tree_fingerprint(101, 3, drifted)


def test_fingerprint_sensitive_to_structure_window_depth_order():
    """防回归：ax_ref/role/title/window_id/depth/节点顺序任一变化必须改变
    指纹——否则旧游标能切进结构不同的树，静默串页读到错误元素。"""
    nodes = [
        _node(ax_ref="0", role="AXWindow", title="主窗口"),
        _node(ax_ref="0.0", role="AXGroup", title=None),
    ]
    fp = tree_fingerprint(101, 3, nodes)
    assert fp != tree_fingerprint(
        101, 3, [_node(ax_ref="0x", role="AXWindow", title="主窗口"),
                 _node(ax_ref="0.0", role="AXGroup", title=None)]
    )  # ax_ref 变
    assert fp != tree_fingerprint(
        101, 3, [_node(ax_ref="0", role="AXSheet", title="主窗口"),
                 _node(ax_ref="0.0", role="AXGroup", title=None)]
    )  # role 变
    assert fp != tree_fingerprint(
        101, 3, [_node(ax_ref="0", role="AXWindow", title="标题改了"),
                 _node(ax_ref="0.0", role="AXGroup", title=None)]
    )  # title 变
    assert fp != tree_fingerprint(202, 3, nodes)  # window_id 变
    assert fp != tree_fingerprint(101, 4, nodes)  # depth 变
    assert fp != tree_fingerprint(101, 3, list(reversed(nodes)))  # 顺序变
    # 确定性：同输入同指纹
    assert tree_fingerprint(101, 3, nodes) == fp


# ══ 2. 游标编解码 ══════════════════════════════════════════════════════════
def test_cursor_roundtrip_zero_and_large():
    """防回归：encode/decode 必须无损往返（offset=0 与超大整数都不丢精度），
    且游标是无 '=' 的 URL 安全字符串——否则续读位置错乱或被误拒。"""
    cases = [
        PageCursor(window_id=101, depth=3, offset=0, total=1500, tree_fp="a" * 32),
        PageCursor(
            window_id=98765432109876543210,
            depth=6,
            offset=2**40,
            total=2**40 + 7,
            tree_fp="0" * 32,
        ),
    ]
    for c in cases:
        token = encode_cursor(c)
        assert token.startswith(f"{CURSOR_PREFIX}.")
        assert "=" not in token  # 尾部 padding 已剥离
        assert decode_cursor(token) == c


def test_decode_rejects_all_invalid_without_raising():
    """防回归：decode_cursor 是外部输入边界，任何 malformed 游标必须确定性
    返回 None 而不是抛异常——工具层才能稳定把它转成 cursor_invalid 回执。"""
    ok = _raw_token(
        {"v": CURSOR_VERSION, "w": 101, "d": 3, "o": 0, "t": 5, "f": "a" * 32}
    )
    assert decode_cursor(ok) is not None  # 对照组：合法组合必须通过
    not_json = (
        base64.urlsafe_b64encode(b"this is not json at all").decode().rstrip("=")
    )
    bad_inputs = [
        None,  # 非 str
        "",  # 空串
        "ax1.",  # 只有前缀、body 为空
        f"{CURSOR_PREFIX}.!!!",  # 非 base64 字符
        f"{CURSOR_PREFIX}.{not_json}",  # 合法 base64 但非 JSON
        _raw_token({"v": CURSOR_VERSION, "w": 101, "d": 3, "o": 0, "t": 5}),  # 缺 f
        _raw_token({"v": 2, "w": 101, "d": 3, "o": 0, "t": 5, "f": "a" * 32}),  # 版本不符
        _raw_token({"v": CURSOR_VERSION, "w": True, "d": 3, "o": 0, "t": 5, "f": "a" * 32}),  # w 为 bool
        _raw_token({"v": CURSOR_VERSION, "w": 101, "d": 3, "o": -1, "t": 5, "f": "a" * 32}),  # o 为负
        _raw_token({"v": CURSOR_VERSION, "w": 101, "d": 3, "o": 6, "t": 5, "f": "a" * 32}),  # o > t
        _raw_token({"v": CURSOR_VERSION, "w": 101, "d": 3, "o": 0, "t": 5, "f": 123}),  # f 非 str
        _raw_token([1, 2, 3]),  # JSON 合法但非 dict
        "bx1.eyJ2IjoxfQ",  # 无本格式前缀
    ]
    for token in bad_inputs:
        assert decode_cursor(token) is None


# ══ 3. paginate 边界 ═══════════════════════════════════════════════════════
def test_paginate_exact_multiple_last_page_no_cursor():
    """防回归：6 节点按 3/页整除分两页，末页 remaining=0、next_cursor=None
    ——末页仍发游标会让客户端拿着死游标无限续读。"""
    nodes = _tree(6)
    p1 = paginate(nodes, window_id=101, depth=3, page_limit=3)
    assert (p1.index, p1.total, len(p1.nodes), p1.remaining) == (0, 6, 3, 3)
    assert p1.next_cursor is not None
    p2 = paginate(nodes, window_id=101, depth=3, cursor=p1.next_cursor, page_limit=3)
    assert (p2.index, p2.total, len(p2.nodes), p2.remaining) == (3, 6, 3, 0)
    assert p2.nodes == tuple(nodes[3:6])
    assert p2.next_cursor is None


def test_paginate_remainder_last_page():
    """防回归：7 节点按 3/页，末页只有 1 个节点且终止——切片必须是
    nodes[index:index+limit] 的自然短切，不越界、不报错、不丢节点。"""
    nodes = _tree(7)
    cursor = None
    pages = []
    for _ in range(4):
        page = paginate(nodes, window_id=101, depth=3, cursor=cursor, page_limit=3)
        pages.append(page)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert [len(p.nodes) for p in pages] == [3, 3, 1]
    assert pages[-1].remaining == 0
    assert pages[-1].next_cursor is None
    assert [n.ax_ref for p in pages for n in p.nodes] == [n.ax_ref for n in nodes]


def test_paginate_limit_gt_total_single_page():
    """防回归：page_limit > total 时一次返回全部且无续游标——多余的
    next_cursor 是协议污染，会诱导多余的续读往返。"""
    nodes = _tree(3)
    page = paginate(nodes, window_id=101, depth=3, page_limit=200)
    assert page.nodes == tuple(nodes)
    assert (page.index, page.total, page.remaining, page.next_cursor) == (
        0,
        3,
        0,
        None,
    )


def test_paginate_offset_equals_total_empty_page():
    """防回归：offset==total 是合法边界（剩余 0 页），必须返回空 slice 与
    None 游标，而不是误判越界抛异常或进入死循环续读。"""
    nodes = _tree(4)
    fp = tree_fingerprint(101, 3, nodes)
    token = encode_cursor(
        PageCursor(window_id=101, depth=3, offset=4, total=4, tree_fp=fp)
    )
    page = paginate(nodes, window_id=101, depth=3, cursor=token, page_limit=3)
    assert page.nodes == ()
    assert (page.index, page.total, page.remaining, page.next_cursor) == (
        4,
        4,
        0,
        None,
    )


def test_paginate_empty_nodes():
    """防回归：AX 树为空时必须给出全零空页（total=0、无游标），供上层把
    "空树"与"错误"区分开，而不是抛异常或发出无意义游标。"""
    page = paginate((), window_id=101, depth=3)
    assert page == PagedNodes(
        nodes=(), index=0, total=0, remaining=0, next_cursor=None
    )


def test_paginate_bad_cursor_raises_value_error():
    """防回归：malformed 游标必须抛 ValueError（调用方转 cursor_invalid），
    绝不能静默当成无游标从头分页，掩盖客户端传参 bug。"""
    with pytest.raises(ValueError):
        paginate(_tree(6), window_id=101, depth=3, cursor="not-a-cursor")
    with pytest.raises(ValueError):
        paginate(_tree(6), window_id=101, depth=3, cursor=f"{CURSOR_PREFIX}.垃圾")


def test_paginate_non_positive_limit_raises():
    """防回归：page_limit <= 0 是参数错误，必须抛 ValueError，防止零页/
    负页静默返回空结果被误当作"树为空"。"""
    with pytest.raises(ValueError):
        paginate(_tree(6), window_id=101, depth=3, page_limit=0)
    with pytest.raises(ValueError):
        paginate(_tree(6), window_id=101, depth=3, page_limit=-3)


# ══ 4. 游标跨树复用 ════════════════════════════════════════════════════════
def test_cursor_cross_tree_tamper_or_depth_raises():
    """防回归：换树/换深度/树结构漂移后，旧游标必须被判 stale 抛
    ValueError——否则按旧 offset 在新树上静默切片就是串页读错元素。"""
    nodes = _tree(6)
    p1 = paginate(nodes, window_id=101, depth=3, page_limit=3)
    assert p1.next_cursor is not None

    # 篡改 f：格式合法但指纹对不上当前树
    forged = encode_cursor(
        PageCursor(window_id=101, depth=3, offset=3, total=6, tree_fp="f" * 32)
    )
    with pytest.raises(ValueError):
        paginate(nodes, window_id=101, depth=3, cursor=forged, page_limit=3)

    # 换深度：同批节点 depth=4 → 指纹不同 → stale
    with pytest.raises(ValueError):
        paginate(nodes, window_id=101, depth=4, cursor=p1.next_cursor, page_limit=3)

    # 真实树漂移：改一个 title 后指纹变化 → stale
    mutated = list(nodes)
    mutated[0] = _node(
        ax_ref=mutated[0].ax_ref, role=mutated[0].role, title="标题变了"
    )
    with pytest.raises(ValueError):
        paginate(mutated, window_id=101, depth=3, cursor=p1.next_cursor, page_limit=3)


def test_cursor_offset_out_of_range_raises():
    """防回归：offset > 当前 total 必须显式拒绝（cursor 越界），不能返回
    负 remaining 或空页假装成功。"""
    nodes = _tree(3)
    fp = tree_fingerprint(101, 3, nodes)
    token = encode_cursor(
        PageCursor(window_id=101, depth=3, offset=5, total=7, tree_fp=fp)
    )
    with pytest.raises(ValueError):
        paginate(nodes, window_id=101, depth=3, cursor=token, page_limit=3)


# ══ 5. PageBudget ══════════════════════════════════════════════════════════
def test_budget_charge_within_limit():
    """防回归：剩余足额必须记账并返回 True，used 反映累计消耗。"""
    budget = PageBudget(10)
    assert budget.charge("ax_nodes", 4) is True
    assert budget.used("ax_nodes") == 4
    assert budget.charge("ax_nodes", 6) is True
    assert budget.used("ax_nodes") == 10


def test_budget_per_key_accounting():
    """防回归：各 key 独立额度、互不挤占——一个 key 用满不得影响其他
    key 的判定；未出现过的 key used 为 0。"""
    budget = PageBudget(10)
    assert budget.charge("nodes", 10) is True
    assert budget.charge("audit_lines", 10) is True  # 不受 nodes 占满影响
    assert budget.used("nodes") == 10
    assert budget.used("audit_lines") == 10
    assert budget.used("never_charged") == 0


def test_budget_over_limit_rejected_without_deduction():
    """防回归：额度不足必须拒绝且绝不部分/幻影扣减——失败的申请不改变
    账面，之后按真实剩余再申请仍可成功。"""
    budget = PageBudget(5)
    assert budget.charge("k", 6) is False
    assert budget.used("k") == 0  # 未扣减
    assert budget.charge("k", 5) is True
    assert budget.charge("k", 1) is False
    assert budget.used("k") == 5  # 失败申请未污染账面
