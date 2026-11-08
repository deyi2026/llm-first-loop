"""Peer 请求认证：四头 HMAC-SHA256 + 时钟窗 + nonce 重放窗（DESIGN §5.8.3）。

契约逐字取自设计（两侧必须一致，改动=契约变更）：

    X-Peer-Node-Id: <node_id>
    X-Peer-Ts:      <epoch 秒，十进制>
    X-Peer-Nonce:   <32 位小写 hex>
    X-Peer-Sig:     base64(HMAC-SHA256(K_oe, canonical))

    canonical = METHOD + "\\n" + PATH + "\\n" + SHA256_HEX(BODY) + "\\n" + TS + "\\n" + NONCE

- METHOD 大写；PATH **含 query、不含 host**；BODY 为空时对空串求 SHA256。
- 时间窗 ±300s → ``peer_stale_signature``；nonce 缓存 600s、按 node_id 分桶、
  LRU 上限 10000 → 重复即 ``peer_replay_detected``。
- 签名比较用常量时间比较（``hmac.compare_digest``）。

校验顺序（顺序本身是安全属性）：头齐全 → 节点已知 → 时间窗 → 验签 → nonce 落账。
先验签后落 nonce，避免未认证方用垃圾 nonce 污染重放窗（nonce 中毒）。

已知边界（不隐瞒）：
- 对称密钥认证，不是公钥签名；Ed25519 公钥只用于身份表达（公钥/短指纹）。
  ``K_oe`` 泄露=该方向可被完全冒充。
- 重放窗是进程内内存态：重启后窗清空，此时仅剩 ±300s 时间窗约束。
- PATH 中含换行即拒绝（防 canonical 行注入）；query 不重排、不重编码。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from .errors import PeerError

HEADER_NODE = "X-Peer-Node-Id"
HEADER_TIMESTAMP = "X-Peer-Ts"
HEADER_NONCE = "X-Peer-Nonce"
HEADER_SIGNATURE = "X-Peer-Sig"
AUTH_HEADERS: tuple[str, ...] = (HEADER_NODE, HEADER_TIMESTAMP, HEADER_NONCE, HEADER_SIGNATURE)

MAX_SKEW_SECONDS = 300
NONCE_WINDOW_SECONDS = 600
NONCE_MAX_ENTRIES = 10_000
_NONCE_RE = re.compile(r"^[a-f0-9]{32}$")


def body_digest(body: bytes | None) -> str:
    """请求体摘要；None 与 b"" 等价（设计：BODY 为空时对空串求 SHA256）。"""
    return hashlib.sha256(body or b"").hexdigest()


def compose_path(path: str, query: str = "") -> str:
    """PATH 含 query、不含 host。query 为空时不补 '?'（两侧同规则）。"""
    if query and query.startswith("?"):
        query = query[1:]
    return f"{path}?{query}" if query else path


def build_canonical(*, method: str, path: str, body_sha256: str, timestamp: str, nonce: str) -> str:
    """5 行 canonical。任一字段含换行即拒绝（防 canonical 行注入）。"""
    fields = (method.upper(), path, body_sha256, timestamp, nonce)
    for field in fields:
        if "\n" in field or "\r" in field:
            raise PeerError("peer_bad_signature", "canonical field contains newline")
    return "\n".join(fields)


def sign(secret: bytes, canonical: str) -> str:
    """返回 base64(HMAC-SHA256(K_oe, canonical))。"""
    digest = hmac.new(secret, canonical.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


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
    """生成四头（客户端侧；服务端侧用 PeerAuthenticator 对称校验）。"""
    ts = str(int(timestamp))
    canonical = build_canonical(
        method=method,
        path=compose_path(path, query),
        body_sha256=body_digest(body),
        timestamp=ts,
        nonce=nonce,
    )
    return {
        HEADER_NODE: node_id,
        HEADER_TIMESTAMP: ts,
        HEADER_NONCE: nonce,
        HEADER_SIGNATURE: sign(secret, canonical),
    }


class NonceCache:
    """进程内重放窗：node_id → OrderedDict{nonce: 过期时刻}（LRU 语义）。

    容量有界（全局 LRU 上限 ``max_entries``）；插入前先清过期项，仍超限时淘汰
    最久未使用项（只影响窗内保护强度，不放宽时间窗）。线程安全。
    """

    def __init__(
        self,
        *,
        window_seconds: int = NONCE_WINDOW_SECONDS,
        max_entries: int = NONCE_MAX_ENTRIES,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._window = int(window_seconds)
        self._max_entries = int(max_entries)
        self._clock = clock
        self._seen: OrderedDict[tuple[str, str], float] = OrderedDict()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._seen)

    def check_and_store(self, node_id: str, nonce: str, *, now: float | None = None) -> bool:
        """首次见到 → True；窗内重复 → False（重放）。"""
        now_ts = self._clock() if now is None else now
        key = (node_id, nonce)
        with self._lock:
            self._purge(now_ts)
            if key in self._seen:
                self._seen.move_to_end(key)
                return False
            self._seen[key] = now_ts + self._window
            while len(self._seen) > self._max_entries:
                self._seen.popitem(last=False)
            return True

    def _purge(self, now_ts: float) -> None:
        expired = [key for key, exp in self._seen.items() if exp <= now_ts]
        for key in expired:
            del self._seen[key]


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
        self._nonces = nonce_cache or NonceCache(clock=clock)
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
            path=compose_path(path, query),
            body_sha256=body_digest(body),
            timestamp=raw_ts,
            nonce=nonce,
        )
        if not hmac.compare_digest(sign(secret, canonical), signature):
            raise PeerError("peer_bad_signature", "digest mismatch")

        if not self._nonces.check_and_store(node_id, nonce, now=float(now)):
            raise PeerError("peer_replay_detected", nonce)
        return node_id
