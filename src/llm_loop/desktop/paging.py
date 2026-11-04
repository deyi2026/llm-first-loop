"""桌面 AX 续读分页的纯逻辑（结构指纹 / 续读游标 / 切页 / 预算）。

动机：desktop_perceive 的 AX 快照可能超过单次回执预算，需要"本页 +
续读游标"的机械分页。游标绑定树结构指纹：树漂移即失效（调用方转
cursor_stale）；value/几何等易变字段绝不入指纹——value 随编辑漂移、
几何随滚动漂移，纳入指纹会让本可续读的游标无谓失效。

契约：纯函数、纯 stdlib、无 I/O、无 macOS 依赖、不 import 工具层。
本模块唯一抛出的异常类型是 ValueError（paginate 的游标校验路径，
调用方负责转错误码）；decode_cursor 任何异常都吞掉并返回 None。
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass

from llm_loop.desktop.models import AxNode

# 游标线格式版本：语义不兼容变更时递增，旧版本游标 decode 返回 None。
CURSOR_VERSION = 1
# 游标字符串前缀：肉眼可辨 + 快速拒绝非本格式的字符串。
CURSOR_PREFIX = "ax1"


@dataclass(frozen=True)
class PageCursor:
    """已解码的续读游标：绑定 (window_id, depth, tree_fp, offset, total)。"""

    window_id: int
    depth: int
    offset: int
    total: int
    tree_fp: str


@dataclass(frozen=True)
class PagedNodes:
    """paginate 结果：本页节点与分页元数据。"""

    nodes: tuple[AxNode, ...]
    index: int  # 本页起始偏移（0-based）
    total: int  # 参与分页的节点总数（调用方已过滤后的）
    remaining: int  # total - (index + len(nodes))，不小于 0
    next_cursor: str | None  # 还有剩余则非 None


def tree_fingerprint(window_id: int, depth: int, nodes: Sequence[AxNode]) -> str:
    """树结构指纹：sha256 hexdigest 前 32 位。

    原料 = f"{window_id}:{depth}|" + 逐节点 "ax_ref|role|title"。
    绝不包含 value / focused / pos_pt / size_pt——value 随编辑漂移、
    几何随滚动漂移，纳入指纹会让本可续读的游标无谓失效。
    """
    material = (
        f"{window_id}:{depth}|"
        + ";".join(f"{n.ax_ref}|{n.role or ''}|{n.title or ''}" for n in nodes)
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def encode_cursor(c: PageCursor) -> str:
    """PageCursor → 紧凑游标 "ax1.<urlsafe-base64(json)>"（去尾部 '='）。"""
    payload = json.dumps(
        {
            "v": CURSOR_VERSION,
            "w": c.window_id,
            "d": c.depth,
            "o": c.offset,
            "t": c.total,
            "f": c.tree_fp,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    b64 = base64.urlsafe_b64encode(payload.encode("utf-8")).rstrip(b"=")
    return f"{CURSOR_PREFIX}.{b64.decode('ascii')}"


def decode_cursor(token: str) -> PageCursor | None:
    """游标 → PageCursor；任何异常/不合规格都返回 None，绝不抛出。

    必须拒绝：非 str、无前缀、base64 解码失败、非 JSON、非 dict、缺键、
    v != CURSOR_VERSION、w/d/o/t 非 int 或为 bool、f 非 str、
    o < 0、t < 0、o > t。
    """
    if not isinstance(token, str):
        return None
    prefix = f"{CURSOR_PREFIX}."
    if not token.startswith(prefix):
        return None
    body = token[len(prefix):]
    try:
        padded = body + "=" * (-len(body) % 4)
        raw = base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
        obj = json.loads(raw.decode("utf-8"))
    except Exception:  # 契约：解析阶段任何异常一律 None，绝不外抛
        return None
    if not isinstance(obj, dict):
        return None
    if not {"v", "w", "d", "o", "t", "f"}.issubset(obj):
        return None
    # v 按非 bool 的 int 校验：True == 1 / 1.0 == 1 在 Python 里会伪装成版本 1。
    if isinstance(obj["v"], bool) or not isinstance(obj["v"], int):
        return None
    if obj["v"] != CURSOR_VERSION:
        return None
    for key in ("w", "d", "o", "t"):
        if isinstance(obj[key], bool) or not isinstance(obj[key], int):
            return None
    if not isinstance(obj["f"], str):
        return None
    if obj["o"] < 0 or obj["t"] < 0 or obj["o"] > obj["t"]:
        return None
    return PageCursor(
        window_id=obj["w"],
        depth=obj["d"],
        offset=obj["o"],
        total=obj["t"],
        tree_fp=obj["f"],
    )


def paginate(
    nodes: Sequence[AxNode],
    *,
    window_id: int,
    depth: int,
    cursor: str | None = None,
    page_limit: int = 200,
) -> PagedNodes:
    """按 page_limit 切页；游标失效/越界/参数非法抛 ValueError（唯一异常）。

    - 无 cursor → index=0；有 cursor → decode 失败抛 ValueError
      （调用方转 cursor_invalid）。
    - window_id/depth/tree_fp 与当前 nodes 计算值不一致 → ValueError
      （调用方转 cursor_stale）。
    - offset > total → ValueError（cursor 越界）。
    - page_limit <= 0 → ValueError。
    - nodes 为空 → 全零空页（nodes=(), index=0, total=0, remaining=0,
      next_cursor=None）。
    """
    total = len(nodes)
    tree_fp = tree_fingerprint(window_id, depth, nodes)
    if cursor is None:
        index = 0
    else:
        c = decode_cursor(cursor)
        if c is None:
            raise ValueError("cursor 无法解析（cursor_invalid）")
        if c.window_id != window_id or c.depth != depth or c.tree_fp != tree_fp:
            raise ValueError("cursor 与当前树不一致（cursor_stale）")
        if c.offset > total:
            raise ValueError("cursor 越界（offset > total）")
        index = c.offset
    if page_limit <= 0:
        raise ValueError("page_limit 必须为正整数")
    page = tuple(nodes[index : index + page_limit])
    remaining = max(0, total - index - len(page))
    next_cursor = None
    if remaining > 0:
        next_cursor = encode_cursor(
            PageCursor(
                window_id=window_id,
                depth=depth,
                offset=index + len(page),
                total=total,
                tree_fp=tree_fp,
            )
        )
    return PagedNodes(
        nodes=page,
        index=index,
        total=total,
        remaining=remaining,
        next_cursor=next_cursor,
    )


class PageBudget:
    """按 key 独立计账的额度：剩余足额才扣减，不足则原样保留。

    用途：单次回执内各部分（节点 / 截图 / 审计行……）各占一个 key，
    防"每一项单独看都合法、合计却失控"；超额返回 False 且绝不部分扣减。
    """

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._used: dict[str, int] = {}

    def charge(self, key: str, amount: int) -> bool:
        """剩余额度 >= amount 则记账并返回 True；否则不扣减并返回 False。"""
        current = self._used.get(key, 0)
        if current + amount <= self._limit:
            self._used[key] = current + amount
            return True
        return False

    def used(self, key: str) -> int:
        """该 key 已消耗的额度（未见过的 key 为 0）。"""
        return self._used.get(key, 0)
