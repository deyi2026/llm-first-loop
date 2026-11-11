"""Peer 请求认证：四头 HMAC-SHA256 + 时钟窗 + nonce 重放窗（DESIGN §5.8.3）。

契约逐字取自设计（两侧必须一致，改动=契约变更）：

    X-Peer-Node-Id: <node_id>
    X-Peer-Ts:      <epoch 秒，十进制>
    X-Peer-Nonce:   <32 位小写 hex>
    X-Peer-Sig:     base64(HMAC-SHA256(K_oe, canonical))

    canonical = METHOD + "\\n" + PATH + "\\n" + SHA256_HEX(BODY) + "\\n" + TS + "\\n" + NONCE

- METHOD 大写；PATH **含 query、不含 host**；BODY 为空时对空串求 SHA256。
- 时间窗 ±300s → ``peer_stale_signature``；nonce 重放窗 600s（覆盖签名窗 2×300s 偏差）
  → 重复即 ``peer_replay_detected``。
- 签名比较用常量时间比较（``hmac.compare_digest``）。

校验顺序（顺序本身是安全属性）：头齐全 → 节点已知 → 时间窗 → 验签 → nonce 落账。
先验签后落 nonce，避免未认证方用垃圾 nonce 污染重放窗（nonce 中毒）。

持久防重放（设计 §6.5 / R04 / A09）：
- ``NonceCache(persist_dir=...)`` 启用持久模式：按「节点+密钥代际+时间窗」三级分桶
  落盘（``<persist_dir>/nonce/<node>/<generation>/<window_index>.jsonl``），跨进程
  ``flock`` 串行化同一代际桶树，已验签 nonce「先持久（append+fsync）、后响应」。
- 窗口内记录结构性永不淘汰（无 LRU 容量淘汰路径）；窗口整体过期后原子清理整桶
  文件（有界批次）。每代际桶保留至该代签名窗（含时钟偏差）完全结束。
- 换钥过渡：``PeerAuthenticator(previous_secret_for=...)`` 双代并验，nonce 按
  验签命中的密钥代际（``key_fingerprint``）分桶。
- 存储故障/记录损坏 fail-closed（``executor_internal_error``），绝不静默放行或
  以空记录恢复写入资格；垃圾签名不消耗持久槽位。

已知边界（不隐瞒）：
- 对称密钥认证，不是公钥签名；Ed25519 公钥只用于身份表达（公钥/短指纹）。
  ``K_oe`` 泄露=该方向可被完全冒充。
- 未启用 ``persist_dir`` 时重放窗仍是进程内内存态：重启后窗清空，此时仅剩
  ±300s 时间窗约束（默认构造不等于持久防重放，见 §6.5 过渡要求）。
- PATH 中含换行即拒绝（防 canonical 行注入）；query 不重排、不重编码。
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import hmac
import json
import os
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
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
NONCE_DIR_NAME = "nonce"
DEFAULT_KEY_GENERATION = "default"
_LAZY_CLEANUP_INTERVAL = 64
_NONCE_RE = re.compile(r"^[a-f0-9]{32}$")
_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


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


def key_fingerprint(secret: bytes) -> str:
    """密钥代际标签：sha256(secret) 前 16 hex。同一密钥稳定、换钥即分代。"""
    return hashlib.sha256(secret).hexdigest()[:16]


def _safe_segment(value: str) -> str:
    """把 node_id / 代际标签安全映射为单层目录名（拒绝路径穿越与非安全字符）。"""
    if value and value not in {".", ".."} and _SAFE_SEGMENT_RE.fullmatch(value):
        return value
    return "h" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:31]


class NonceCache:
    """nonce 重放窗：内存 LRU（默认）或持久分桶（``persist_dir``，设计 §6.5）。

    内存模式（默认，向后兼容）：node_id → OrderedDict{nonce: 过期时刻}，全局 LRU
    上限 ``max_entries``；只影响窗内保护强度，不放宽时间窗。重启即失忆。

    持久模式（``persist_dir`` 非空）：``<persist_dir>/nonce/<node>/<generation>/
    <window_index>.jsonl`` 三级分桶，窗口内结构性永不淘汰（``max_entries`` 不参与
    持久路径），跨进程 ``flock`` 串行化，每次接受恰好一次 append+fsync（``stats``
    可测量）。重放检测只读不写。窗口整体过期（含时钟偏差）后整桶原子清理；清理
    有界批次，请求路径上每 ``_LAZY_CLEANUP_INTERVAL`` 次接受惰性清一次当前代际目录。

    存储故障或记录损坏 → ``PeerError("executor_internal_error")``（fail-closed，
    与 PeerStore 同约定），绝不以空记录恢复写入资格。
    """

    def __init__(
        self,
        *,
        window_seconds: int = NONCE_WINDOW_SECONDS,
        max_entries: int = NONCE_MAX_ENTRIES,
        clock: Callable[[], float] = time.time,
        persist_dir: str | os.PathLike[str] | None = None,
        bucket_seconds: int | None = None,
        cleanup_batch: int = 16,
    ) -> None:
        self._window = int(window_seconds)
        self._max_entries = int(max_entries)
        self._clock = clock
        self._seen: OrderedDict[tuple[str, str], float] = OrderedDict()
        self._lock = threading.Lock()
        self._cleanup_batch = int(cleanup_batch)
        self.stats: dict[str, int] = {"appends": 0, "replays_detected": 0, "buckets_removed": 0}
        self._ops = 0
        if persist_dir is not None:
            self._persist_root = Path(persist_dir) / NONCE_DIR_NAME
            self._bucket_seconds = int(bucket_seconds) if bucket_seconds else self._window
            if self._window <= 0 or self._bucket_seconds <= 0:
                raise ValueError("window_seconds/bucket_seconds must be positive")
            # lookback：保证任何仍有效记录（accepted t，live 到 t+window）所在桶
            # 一定落在 [index-lookback, index] 扫描范围内。
            self._lookback = -(-self._window // self._bucket_seconds)
        else:
            self._persist_root = None
            self._bucket_seconds = self._window
            self._lookback = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._seen)

    def check_and_store(
        self,
        node_id: str,
        nonce: str,
        *,
        now: float | None = None,
        key_generation: str | None = None,
    ) -> bool:
        """首次见到 → True；窗内重复 → False（重放）。

        持久模式下 ``key_generation`` 参与分桶（换钥双代并验时按验签命中的代际
        落账）；内存模式忽略它（保持既有 (node_id, nonce) 语义）。
        """
        now_ts = self._clock() if now is None else now
        if self._persist_root is None:
            return self._memory_check_and_store(node_id, nonce, now_ts)
        generation = key_generation or DEFAULT_KEY_GENERATION
        with self._lock:
            try:
                return self._persistent_check_and_store(node_id, nonce, now_ts, generation)
            except OSError as exc:
                raise PeerError("executor_internal_error", f"nonce persistence failure: {exc}") from exc

    # ---- 内存模式（默认，向后兼容） ----

    def _memory_check_and_store(self, node_id: str, nonce: str, now_ts: float) -> bool:
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

    # ---- 持久模式（设计 §6.5：分桶、窗口内永不淘汰、整桶清理） ----

    def _persistent_check_and_store(
        self, node_id: str, nonce: str, now_ts: float, generation: str
    ) -> bool:
        gen_dir = self._persist_root / _safe_segment(node_id) / _safe_segment(generation)
        index = int(now_ts // self._bucket_seconds)
        with self._fs_lock(gen_dir):
            for back in range(self._lookback + 1):
                bucket = gen_dir / f"{index - back}.jsonl"
                if self._bucket_contains(bucket, nonce, now_ts):
                    self.stats["replays_detected"] += 1
                    return False
            # 首次接受：先持久（append+fsync）、后响应；每次请求恰好一次持久写。
            self._append_record(gen_dir / f"{index}.jsonl", nonce, now_ts + self._window)
            self.stats["appends"] += 1
            self._ops += 1
            if self._ops % _LAZY_CLEANUP_INTERVAL == 0:
                self._cleanup_gen_dir(gen_dir, now_ts)
            return True

    @contextmanager
    def _fs_lock(self, gen_dir: Path) -> Iterator[None]:
        """跨进程互斥（同 PeerStore 约定：flock + 0o600 锁文件 + 0o700 目录）。"""
        gen_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(gen_dir, 0o700)
        fd = os.open(gen_dir / ".nonce.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    @staticmethod
    def _bucket_contains(bucket: Path, nonce: str, now_ts: float) -> bool:
        try:
            raw = bucket.read_text(encoding="utf-8")
        except FileNotFoundError:
            return False  # 桶不存在或刚被有界清理移除（仅可能整体过期）
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                if record["n"] == nonce and float(record["e"]) > now_ts:
                    return True
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise PeerError(
                    "executor_internal_error", f"nonce bucket corrupted: {bucket}: {exc}"
                ) from exc
        return False

    @staticmethod
    def _append_record(bucket: Path, nonce: str, expires_at: float) -> None:
        line = json.dumps({"n": nonce, "e": expires_at}, separators=(",", ":")) + "\n"
        fd = os.open(bucket, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())  # 先持久、后响应（§6.5 安全顺序）

    def cleanup(self, *, now: float | None = None) -> int:
        """有界批次清理已整体过期的时间窗桶文件（每代际目录至多 ``cleanup_batch`` 个）。

        仅删 ``.jsonl`` 文件、不删目录；某桶可清理 ⟺ ``now ≥ (idx+1)*bucket_seconds
        + window_seconds``（桶内最晚记录也已过期——签名窗含时钟偏差完全结束）。
        """
        if self._persist_root is None:
            return 0
        now_ts = self._clock() if now is None else now
        total = 0
        if not self._persist_root.is_dir():
            return 0
        for node_name in os.listdir(self._persist_root):
            node_dir = self._persist_root / node_name
            if not node_dir.is_dir():
                continue
            for gen_name in os.listdir(node_dir):
                gen_dir = node_dir / gen_name
                if not gen_dir.is_dir():
                    continue
                with self._fs_lock(gen_dir):
                    total += self._cleanup_gen_dir(gen_dir, now_ts)
        return total

    def _cleanup_gen_dir(self, gen_dir: Path, now_ts: float) -> int:
        removed = 0
        try:
            names = os.listdir(gen_dir)
        except FileNotFoundError:
            return 0
        for name in names:
            if removed >= self._cleanup_batch:
                break
            stem = name[: -len(".jsonl")] if name.endswith(".jsonl") else ""
            if not stem.isdigit():
                continue
            bucket_index = int(stem)
            if now_ts >= (bucket_index + 1) * self._bucket_seconds + self._window:
                (gen_dir / name).unlink(missing_ok=True)
                removed += 1
        self.stats["buckets_removed"] += removed
        return removed


def _header_value(headers: Any, name: str) -> str:
    """大小写不敏感取头（兼容 dict 与 Starlette Headers）。"""
    value = headers.get(name)
    if value is None:
        value = headers.get(name.lower())
    return "" if value is None else str(value).strip()


class PeerAuthenticator:
    """请求认证器。secret_for(node_id) 返回 None ⇒ 未配对（peer_unknown_node）。

    换钥过渡（§6.5 / A09）：可选 ``previous_secret_for(node_id) → bytes | None``
    提供上一代密钥；过渡窗内双代并验（当前钥优先），nonce 按**验签命中的代际**
    （``key_fingerprint``）分桶落账——换钥后旧窗内旧钥签名重放仍被拒，旧代桶
    保留至其签名窗（含时钟偏差）完全结束。操作者在过渡结束后移除旧钥配置。
    """

    def __init__(
        self,
        *,
        secret_for: Callable[[str], bytes | None],
        nonce_cache: NonceCache | None = None,
        clock: Callable[[], float] = time.time,
        max_skew_seconds: int = MAX_SKEW_SECONDS,
        previous_secret_for: Callable[[str], bytes | None] | None = None,
    ) -> None:
        self._secret_for = secret_for
        self._previous_secret_for = previous_secret_for
        # 注意 ``is not None``：NonceCache 定义了 __len__，空缓存为 falsy，
        # 用 ``or`` 会把刚构造的持久缓存静默替换成默认内存缓存。
        self._nonces = nonce_cache if nonce_cache is not None else NonceCache(clock=clock)
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

        candidates: list[tuple[str, bytes]] = []
        primary = self._secret_for(node_id)
        if primary:
            candidates.append((key_fingerprint(primary), primary))
        if self._previous_secret_for is not None:
            previous = self._previous_secret_for(node_id)
            if previous:
                candidates.append((key_fingerprint(previous), previous))
        if not candidates:
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
        matched_generation: str | None = None
        for generation, candidate_secret in candidates:
            if hmac.compare_digest(sign(candidate_secret, canonical), signature):
                matched_generation = generation
                break
        if matched_generation is None:
            raise PeerError("peer_bad_signature", "digest mismatch")

        if not self._nonces.check_and_store(
            node_id, nonce, now=float(now), key_generation=matched_generation
        ):
            raise PeerError("peer_replay_detected", nonce)
        return node_id
