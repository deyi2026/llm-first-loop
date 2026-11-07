"""Peer 请求认证：四头 HMAC-SHA256 + 时钟窗 + nonce 重放窗（lfl.peer.v1）。

契约（两侧必须逐字一致，改动=契约变更）：

    头：X-LFL-Peer-Node / X-LFL-Peer-Timestamp / X-LFL-Peer-Nonce / X-LFL-Peer-Signature
    ts：整数 epoch 秒（字符串形式）
    nonce：32 位小写 hex（16 字节随机），窗内单次使用
    body_sha256：请求体原始字节的 sha256 hexdigest；无体请求用空字节的摘要
                 （而不是省略该行——省略会让"空体"与"无体"两种请求共用签名）
    canonical：8 行，用 "\\n" 连接，字段内禁止出现 "\\n"
                "lfl.peer.v1" / METHOD(大写) / path / query(原始串) / node_id / ts / nonce / body_sha256
    signature：HMAC-SHA256(link_secret, canonical) 的小写 hexdigest（64 字符）

校验顺序（顺序本身是安全属性）：头齐全 → 节点已知 → 时间窗 → 签名 → nonce 落账。
先验签后落 nonce，避免未认证方用垃圾 nonce 污染重放窗（nonce 中毒）。

已知边界（不隐瞒）：
- 这是对称密钥认证（HMAC），不是公钥签名。Ed25519 公钥只用于身份展示与短指纹，
  请求真实性由 link_secret 保证——link_secret 泄露=该节点可被完全冒充。
- 重放窗是进程内内存态：重启后窗清空，此时仅剩 ±300s 时间窗约束。
- query 按原始串参与签名，两侧不得重排/重编码参数；需要规范化就改契约。
"""

from __future__ import annotations

import hashlib
import hmac
import re
import threading
import time
from collections.abc import Callable
from typing import Any

from .errors import PeerError

SCHEMA_VERSION = "lfl.peer.v1"

HEADER_NODE = "X-LFL-Peer-Node"
HEADER_TIMESTAMP = "X-LFL-Peer-Timestamp"
HEADER_NONCE = "X-LFL-Peer-Nonce"
HEADER_SIGNATURE = "X-LFL-Peer-Signature"
AUTH_HEADERS: tuple[str, ...] = (HEADER_NODE, HEADER_TIMESTAMP, HEADER_NONCE, HEADER_SIGNATURE)

MAX_SKEW_SECONDS = 300
_NONCE_RE = re.compile(r"^[a-f0-9]{32}$")


def body_digest(body: bytes | None) -> str:
    """请求体摘要；None 与 b"" 等价（空体也必须有摘要行）。"""
    return hashlib.sha256(body or b"").hexdigest()


def build_canonical(
    *,
    method: str,
    path: str,
    query: str,
    node_id: str,
    timestamp: str,
    nonce: str,
    body_sha256: str,
) -> str:
    """拼 canonical 串。任何字段含换行即拒绝（防 canonical 注入/歧义）。"""
    fields = (
        SCHEMA_VERSION,
        method.upper(),
        path,
        query,
        node_id,
        timestamp,
        nonce,
        body_sha256,
    )
    for field in fields:
        if "\n" in field or "\r" in field:
            raise PeerError("peer_bad_signature", "canonical field contains newline")
    return "\n".join(fields)


def sign(secret: bytes, canonical: str) -> str:
    return hmac.new(secret, canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def sign_request(
    *,
    secret: bytes,
    method: str,
    path: str,
    query: str = "",
    node_id: str,
    nonce: str,
    timestamp: int,
    body: bytes | None = None,
) -> dict[str, str]:
    """生成四头（客户端侧；服务端侧用 verify_request 对称校验）。"""
    ts = str(int(timestamp))
    canonical = build_canonical(
        method=method,
        path=path,
        query=query,
        node_id=node_id,
        timestamp=ts,
        nonce=nonce,
        body_sha256=body_digest(body),
    )
    return {
        HEADER_NODE: node_id,
        HEADER_TIMESTAMP: ts,
        HEADER_NONCE: nonce,
        HEADER_SIGNATURE: sign(secret, canonical),
    }


class NonceCache:
    """进程内重放窗：node_id → {nonce: 过期时刻}。

    容量有界：插入前先清过期项；仍超限时按最早过期优先淘汰（只影响窗内保护强度，
    不放宽时间窗）。线程安全（Web 侧多线程 handler）。
    """

    def __init__(
        self,
        *,
        window_seconds: int = MAX_SKEW_SECONDS,
        max_entries: int = 8192,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._window = int(window_seconds)
        self._max_entries = int(max_entries)
        self._clock = clock
        self._seen: dict[str, dict[str, float]] = {}
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            return sum(len(bucket) for bucket in self._seen.values())

    def check_and_store(self, node_id: str, nonce: str, *, now: float | None = None) -> bool:
        """首次见到 → True；窗内重复 → False（重放）。"""
        now_ts = self._clock() if now is None else now
        with self._lock:
            self._purge(now_ts)
            bucket = self._seen.setdefault(node_id, {})
            if nonce in bucket:
                return False
            bucket[nonce] = now_ts + self._window
            self._enforce_capacity()
            return True

    def _purge(self, now_ts: float) -> None:
        for node_id in list(self._seen):
            bucket = self._seen[node_id]
            for nonce in [n for n, exp in bucket.items() if exp <= now_ts]:
                del bucket[nonce]
            if not bucket:
                del self._seen[node_id]

    def _enforce_capacity(self) -> None:
        total = sum(len(b) for b in self._seen.values())
        if total <= self._max_entries:
            return
        flat = sorted(
            ((exp, node_id, nonce) for node_id, bucket in self._seen.items() for nonce, exp in bucket.items())
        )
        for _exp, node_id, nonce in flat[: total - self._max_entries]:
            self._seen[node_id].pop(nonce, None)
            if not self._seen[node_id]:
                del self._seen[node_id]


def _header_value(headers: Any, name: str) -> str:
    """大小写不敏感取头（兼容 dict 与 Starlette Headers）。"""
    value = headers.get(name)
    if value is None:
        value = headers.get(name.lower())
    return "" if value is None else str(value).strip()


class PeerAuthenticator:
    """请求认证器。secret_for(node_id) 返回 None ⇒ 未配对（peer_unknown_node）。"""

    def __init__(
        self,
        *,
        secret_for: Callable[[str], bytes | None],
        nonce_cache: NonceCache | None = None,
        clock: Callable[[], float] = time.time,
        max_skew_seconds: int = MAX_SKEW_SECONDS,
    ) -> None:
        self._secret_for = secret_for
        self._nonces = nonce_cache or NonceCache(window_seconds=max_skew_seconds, clock=clock)
        self._clock = clock
        self._max_skew = int(max_skew_seconds)

    def verify_request(
        self,
        *,
        method: str,
        path: str,
        query: str = "",
        headers: Any,
        body: bytes | None = None,
    ) -> str:
        """通过则返回 node_id，否则抛 PeerError（reason_code 属封闭集）。"""
        node_id = _header_value(headers, HEADER_NODE)
        raw_ts = _header_value(headers, HEADER_TIMESTAMP)
        nonce = _header_value(headers, HEADER_NONCE)
        signature = _header_value(headers, HEADER_SIGNATURE)
        if not (node_id and raw_ts and nonce and signature):
            missing = [
                name
                for name, value in (
                    (HEADER_NODE, node_id),
                    (HEADER_TIMESTAMP, raw_ts),
                    (HEADER_NONCE, nonce),
                    (HEADER_SIGNATURE, signature),
                )
                if not value
            ]
            raise PeerError("peer_bad_signature", f"missing header(s): {','.join(missing)}")

        secret = self._secret_for(node_id)
        if not secret:
            raise PeerError("peer_unknown_node", node_id)

        if not _NONCE_RE.match(nonce):
            raise PeerError("peer_bad_signature", "malformed nonce")
        try:
            ts = int(raw_ts)
        except ValueError:
            raise PeerError("peer_bad_signature", "malformed timestamp") from None
        now = int(self._clock())
        if abs(now - ts) > self._max_skew:
            raise PeerError("peer_stale_signature", f"skew={now - ts}s")

        canonical = build_canonical(
            method=method,
            path=path,
            query=query,
            node_id=node_id,
            timestamp=raw_ts,
            nonce=nonce,
            body_sha256=body_digest(body),
        )
        if not hmac.compare_digest(sign(secret, canonical), signature):
            raise PeerError("peer_bad_signature", "digest mismatch")

        if not self._nonces.check_and_store(node_id, nonce, now=float(now)):
            raise PeerError("peer_replay_detected", nonce)
        return node_id
