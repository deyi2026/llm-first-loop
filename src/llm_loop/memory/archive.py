"""压缩档案 ArchiveStore（design.md T22: 另存提取替代截断）.

边界说明（M11）: 本模块负责压缩档案存取（JSONL + 确定性提取）;记忆条目存取（index.json）在 memory/store.py，二者存储对象与文件格式不同，不合并。

"截断不是目的"——上下文超长/工具结果超长时，将被丢弃的信息
**原文完整另存 + 关键事实/关键路径/摘要作为检索索引**（信息零丢失），
AI 可通过 search_archive 检索找回。

存储: JSONL `data/archives/<session_id>.jsonl`；
条目含 id/ts/role/source/tool_name/tool_call_id/status/key_facts/key_paths/
summary/chars/original。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from llm_loop.timekeeping import system_local_now

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX retains process-local locking
    fcntl = None  # type: ignore[assignment]

_ARCHIVE_PROCESS_LOCK = threading.RLock()
_LOCK_FILENAME = ".__archive_store.lock"
_DIR_FSYNC_ATTEMPTS = 3
_PATH_TOKEN_RE = re.compile(r"[\w./\\\-]+")
_FILE_EXT_RE = re.compile(r"\.\w{1,8}$")
_URL_RE = re.compile(r"https?://\S+")


def _now() -> str:
    return system_local_now().isoformat()


class ArchivePersistError(OSError):
    """Archive mutation is confirmed not to have reached a durable commit."""


class ArchiveCommitUncertainError(OSError):
    """Archive bytes might be visible despite an unconfirmed durability fence."""

    def __init__(
        self,
        message: str,
        *,
        path: Path,
        operation: str,
        expected_sha256: str,
        visible_state: str,
    ) -> None:
        super().__init__(message)
        self.path = path
        self.operation = operation
        self.expected_sha256 = expected_sha256
        self.visible_state = visible_state


def _fsync_directory(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _bytes_visible(path: Path, expected: bytes) -> str:
    try:
        return "matches" if path.read_bytes() == expected else "mismatch"
    except OSError:
        return "unreadable"


def _fsync_parent_or_uncertain(
    path: Path, expected: bytes, *, operation: str,
    directories: tuple[Path, ...] | None = None,
) -> None:
    for directory in directories or (path.parent,):
        last_error: OSError | None = None
        for _ in range(_DIR_FSYNC_ATTEMPTS):
            try:
                _fsync_directory(directory)
                break
            except OSError as exc:
                last_error = exc
        else:
            raise ArchiveCommitUncertainError(
                f"Archive {operation} visible but directory fsync unconfirmed: {last_error}",
                path=path, operation=operation,
                expected_sha256=hashlib.sha256(expected).hexdigest(),
                visible_state=_bytes_visible(path, expected),
            )


def _atomic_replace_bytes(path: Path, payload: bytes, *, operation: str) -> None:
    """Atomic segment or derived-index replacement (caller holds store lock)."""
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError as exc:
        raise ArchivePersistError(f"Archive {operation} not committed: {exc}") from exc
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
    _fsync_parent_or_uncertain(path, payload, operation=operation)


@dataclass
class ArchiveEntry:
    """压缩档案条目（原文完整 + 检索索引）."""

    id: str
    ts: str
    role: str
    source: str
    content: str  # 原文（完整另存）
    session_id: str = ""  # 新格式显式owner，消除legacy `<sid>-N.jsonl`命名歧义
    summary: str = ""  # 摘要/头尾片段（检索索引）
    key_facts: list[str] = field(default_factory=list)  # 关键事实/要点
    key_paths: list[str] = field(default_factory=list)  # 关键路径/URL（检索索引）
    tool_name: str | None = None
    tool_call_id: str | None = None
    status: str | None = None
    chars: int = 0
    summary_source: str = "deterministic"  # T28/R5: llm/deterministic/none/identity_filtered
    embedding: list[float] | None = None  # T35: 可选语义向量（不可用仍可关键词命中）
    reasoning_content: str | None = None  # P0-2: 思考链完整另存（随压缩归档，检索域含）

    def to_dict(self) -> dict:
        return asdict(self)


def extract_key_info(
    text: str, max_facts: int = 5, head_tail: int = 300
) -> tuple[list[str], list[str], str]:
    """确定性提取关键信息（P0）: 路径/URL 作为关键路径；头尾片段作为摘要.

    P1 可扩展为 LLM 摘要（接口不变）。
    """
    # 关键路径: 文件路径 token + URL
    paths: list[str] = []
    seen: set[str] = set()
    # 先线性扫描允许出现在路径中的连续 token，再做 O(1) 形态判定。
    # 旧实现把“任意长 token + 必须出现扩展名”写进同一个正则；对于
    # `"k" * 300_000` 这类大工具输出，findall 会从每个起点反复回溯，
    # 呈 O(n²) 并让摘要/归档路径卡住数分钟。
    for m in _PATH_TOKEN_RE.finditer(text):
        tok = m.group(0).strip()
        if len(tok) >= 4 and tok not in seen:
            if "/" not in tok and "\\" not in tok and _FILE_EXT_RE.search(tok) is None:
                continue
            seen.add(tok)
            paths.append(tok)
    for m in _URL_RE.findall(text):
        if m not in seen:
            seen.add(m)
            paths.append(m)

    # 关键事实: 含动作/结果信号的行（P0 简单规则: 首行 + 含状态词的行）
    facts: list[str] = []
    signal_words = ("成功", "失败", "完成", "错误", "已", "结果", "返回", "错误", "异常")
    for line in text.splitlines():
        line = line.strip()
        if not line or line in facts:
            continue
        if len(line) <= 200 and any(w in line for w in signal_words):
            facts.append(line[:200])
        if len(facts) >= max_facts:
            break

    # 摘要: 头尾片段
    if len(text) <= head_tail * 2:
        summary = text
    else:
        summary = (
            f"{text[:head_tail]} …[中间省略 {len(text) - head_tail * 2} 字符]… {text[-head_tail:]}"
        )
    return facts, paths, summary


def _validate_session_id(session_id: str) -> str:
    """档案会话ID必须是安全basename；同时拒绝glob元字符扩大段匹配。"""
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("非法 session_id: 不能为空")
    if (
        session_id in {".", ".."}
        or "/" in session_id
        or "\\" in session_id
        or "\x00" in session_id
        or any(ch in session_id for ch in "*?[]")
    ):
        raise ValueError("非法 session_id: 不得包含路径分隔符、NUL、目录跳转或glob元字符")
    return session_id


class ArchiveStore:
    """压缩档案存储（JSONL 分片 + sidecar 检索索引，T3b/T3c）.

    单会话base存 `data/archives/<session_id>.jsonl`；单文件达到 segment_bytes
    阈值后新写 `<session_id>.segments/<seq>.jsonl`。旧 `<session_id>-<seq>.jsonl`
    仍可读，但通过entry session_id/外部已知session证据避免与合法数字后缀sid串台。

    T3c sidecar 索引：每段伴随 `<segment>.idx` 追加写（id/ts/chars/summary/key_facts/
    key_paths/content_head/tool_call_id/offset），检索走"索引快速通道 + 全文补齐"
    （limit 截断语义等价）；存量段无索引 → 全文扫描 fail-open。
    """

    _CONTENT_HEAD_CHARS = 800  # 索引 content_head 截断（对齐 search content_preview 口径）

    def __init__(
        self,
        archive_dir: str | Path,
        *,
        segment_bytes: int = 100 * 1024 * 1024,
        known_session_id_fn: Callable[[str], bool] | None = None,
    ) -> None:
        self._dir = Path(archive_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._segment_bytes = segment_bytes  # T3b: 单文件分片阈值（0=不分片，兼容旧行为）
        self._known_session_id_fn = known_session_id_fn
        self._post_save_hooks: list[Callable[[ArchiveEntry], None]] = []
        # P3: async historical backfill and newer-run appends may target the same segment.
        # Serialize physical archive mutations without judging whether either fact is
        # semantically current; both remain valid historical truth.
        self._mutation_lock = threading.RLock()
        # EVO-20260922 增量统计缓存: sid → {seg_path: ((mtime_ns, size), count, chars)}
        # （读路径并发依赖 CPython dict 原子操作；最坏情形=并发重复扫描一次，不损正确性）
        self._stats_cache: dict[str, dict[str, tuple[tuple[int, int], int, int]]] = {}

    @contextlib.contextmanager
    def _writer_guard(self):
        """One physical writer across ArchiveStore instances and processes.

        Acquisition errors fail-closed. Exceptions from the mutation inside
        yield retain their original typed outcome.
        """
        with _ARCHIVE_PROCESS_LOCK, self._mutation_lock:
            if fcntl is None:
                yield
                return
            fd: int | None = None
            try:
                fd = os.open(self._dir / _LOCK_FILENAME, os.O_CREAT | os.O_RDWR, 0o600)
                fcntl.flock(fd, fcntl.LOCK_EX)
            except OSError as exc:
                if fd is not None:
                    with contextlib.suppress(OSError):
                        os.close(fd)
                raise ArchivePersistError(f"Archive writer lock unavailable: {exc}") from exc
            try:
                yield
            finally:
                with contextlib.suppress(OSError):
                    fcntl.flock(fd, fcntl.LOCK_UN)
                with contextlib.suppress(OSError):
                    os.close(fd)

    def add_post_save_hook(self, hook: Callable[[ArchiveEntry], None]) -> None:
        """Register a fail-open observer invoked after a durable archive append."""
        if hook not in self._post_save_hooks:
            self._post_save_hooks.append(hook)

    def _notify_post_save(self, entry: ArchiveEntry) -> None:
        for hook in list(self._post_save_hooks):
            try:
                hook(entry)
            except Exception:  # noqa: BLE001 - derived cache must not break archive writes
                logging.getLogger(__name__).debug(
                    "archive post-save hook failed (fail-open)", exc_info=True
                )

    def _path(self, session_id: str) -> Path:
        session_id = _validate_session_id(session_id)
        return self._dir / f"{session_id}.jsonl"

    @staticmethod
    def _index_path(segment: Path) -> Path:
        """段文件 → sidecar 索引路径（`<segment>.idx`）."""
        return Path(str(segment) + ".idx")

    # ── T3b 分片：段解析/枚举/追加目标 ──

    @staticmethod
    def _segment_seq(path: Path) -> tuple[str, int]:
        """解析legacy扁平段：`<sid>.jsonl`=0；`<sid>-N.jsonl`=N。"""
        stem = path.stem
        dash = stem.rfind("-")
        if dash > 0 and stem[dash + 1 :].isdigit():
            return stem[:dash], int(stem[dash + 1 :])
        return stem, 0

    def _segments_dir(self, session_id: str) -> Path:
        session_id = _validate_session_id(session_id)
        return self._dir / f"{session_id}.segments"

    def _declared_session_id(self, path: Path) -> str | None:
        """读取新条目显式owner；legacy段无字段返回None，混合owner则fail-closed。"""
        owners: set[str] = set()
        try:
            with path.open("r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    owner = entry.get("session_id")
                    if isinstance(owner, str) and owner:
                        owners.add(owner)
                        if len(owners) > 1:
                            raise ValueError(f"档案段包含多个session_id owner: {path}")
        except OSError as exc:
            raise ValueError(f"档案段不可读，无法判定owner: {path}: {exc}") from exc
        return next(iter(owners), None)

    def _known_session_id(self, session_id: str) -> bool:
        if self._known_session_id_fn is None:
            return False
        try:
            return bool(self._known_session_id_fn(session_id))
        except Exception as exc:  # noqa: BLE001 — 无法证明不是邻居时fail-closed排除legacy候选
            logging.getLogger(__name__).warning(
                "档案session ownership探针失败（按已占用处理）: %s: %s", session_id, exc
            )
            return True

    def _segment_owner(self, path: Path) -> str:
        """段文件真实owner：新目录/entry元数据优先，legacy才回退文件名。"""
        if path.parent != self._dir and path.parent.name.endswith(".segments"):
            return path.parent.name[: -len(".segments")]
        declared = self._declared_session_id(path)
        if declared:
            return declared
        candidate_sid = path.stem
        if self._known_session_id(candidate_sid):
            return candidate_sid
        return self._segment_seq(path)[0]

    def all_segment_paths(self) -> list[Path]:
        """枚举全部base/legacy/new-layout JSONL段（供索引/盘点/全局检索）。"""
        paths = list(self._dir.glob("*.jsonl"))
        for seg_dir in self._dir.glob("*.segments"):
            if seg_dir.is_dir():
                paths.extend(
                    p for p in seg_dir.glob("*.jsonl") if p.stem.isdigit()
                )
        return sorted(set(paths), key=lambda p: str(p))

    def session_ids(self) -> list[str]:
        """从段owner元数据/目录/legacy证据枚举唯一session ids。"""
        owners: set[str] = set()
        for path in self.all_segment_paths():
            try:
                owner = self._segment_owner(path)
                if owner:
                    owners.add(owner)
            except ValueError as exc:
                logging.getLogger(__name__).warning("档案owner不可判定（全局枚举跳过）: %s", exc)
        return sorted(owners)

    def _segment_order(self, session_id: str, path: Path) -> int:
        if path == self._path(session_id):
            return 0
        if path.parent == self._segments_dir(session_id) and path.stem.isdigit():
            return int(path.stem)
        return self._segment_seq(path)[1]

    def _segment_paths(self, session_id: str) -> list[Path]:
        """枚举精确sid段：base + 新`.segments` + 可证明归属的legacy flat段。"""
        session_id = _validate_session_id(session_id)
        segs: list[Path] = []
        base = self._path(session_id)
        if base.exists():
            owner = self._segment_owner(base)
            if owner != session_id:
                raise ValueError(
                    f"档案base owner不匹配: path={base.name} owner={owner} expected={session_id}"
                )
            segs.append(base)

        prefix = f"{session_id}-"
        for path in self._dir.glob(f"{session_id}-*.jsonl"):
            suffix = path.stem[len(prefix) :] if path.stem.startswith(prefix) else ""
            if not suffix.isdigit():
                continue
            if self._segment_owner(path) == session_id:
                segs.append(path)

        seg_dir = self._segments_dir(session_id)
        if seg_dir.is_dir():
            segs.extend(p for p in seg_dir.glob("*.jsonl") if p.stem.isdigit())
        segs = list(dict.fromkeys(segs))
        segs.sort(key=lambda p: self._segment_order(session_id, p))
        return segs

    def delete_session(self, session_id: str) -> int:
        """物理删除精确sid全部base/legacy/new segments及sidecar索引。"""
        session_id = _validate_session_id(session_id)
        with self._writer_guard():
            return self._delete_session_locked(session_id)

    def _delete_session_locked(self, session_id: str) -> int:
        """Do not race session deletion against append/summary/GC writers."""
        removed = 0
        touched_dirs: set[Path] = set()
        for segment in self._segment_paths(session_id):
            idx = self._index_path(segment)
            if idx.exists():
                idx.unlink()
                removed += 1
                touched_dirs.add(idx.parent)
            if segment.exists():
                segment.unlink()
                removed += 1
                touched_dirs.add(segment.parent)
        seg_dir = self._segments_dir(session_id)
        if seg_dir.exists():
            seg_dir.rmdir()  # 非空说明存在未知sidecar/段，必须失败而非误报物理删除完成
            touched_dirs.add(self._dir)
            touched_dirs.discard(seg_dir)
        for directory in sorted(touched_dirs):
            try:
                _fsync_directory(directory)
            except OSError as exc:
                raise ArchiveCommitUncertainError(
                    f"Archive deletion visible but directory fsync unconfirmed: {exc}",
                    path=self._dir, operation="delete_session",
                    expected_sha256="", visible_state="unconfirmed",
                ) from exc
        return removed

    def _append_path(self, session_id: str) -> Path:
        """追加目标段：新分片只写`<sid>.segments/<seq>.jsonl`，不再制造扁平歧义。"""
        segs = self._segment_paths(session_id)
        if segs:
            last = segs[-1]
            if self._segment_bytes > 0 and last.stat().st_size >= self._segment_bytes:
                last_seq = max(self._segment_order(session_id, p) for p in segs)
                seg_dir = self._segments_dir(session_id)
                seg_dir.mkdir(parents=True, exist_ok=True)
                return seg_dir / f"{last_seq + 1}.jsonl"
            return last
        return self._path(session_id)

    def archive(
        self,
        session_id: str,
        *,
        role: str,
        source: str,
        content: str,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        status: str | None = None,
        reasoning_content: str | None = None,  # P0-2: 思考链完整另存
        summary_override: str | None = None,
        key_facts_override: list[str] | None = None,
        key_paths_override: list[str] | None = None,
        summary_source_override: str | None = None,
    ) -> ArchiveEntry:
        """另存一条消息/结果为压缩档案条目（原文完整 + 派生索引）.

        R5 的 override 只改变长期摘要/索引投影；``content`` 与
        ``reasoning_content`` 始终原样另存，保证 search_archive 可逆恢复。
        """
        facts, paths, summary = extract_key_info(content)
        if summary_override is not None:
            summary = summary_override
        if key_facts_override is not None:
            facts = list(key_facts_override)
        if key_paths_override is not None:
            paths = list(key_paths_override)
        entry = ArchiveEntry(
            id=f"ARC-{system_local_now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}",
            ts=_now(),
            role=role,
            source=source,
            content=content,
            session_id=session_id,
            summary=summary,
            key_facts=facts,
            key_paths=paths,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            status=status,
            chars=len(content),
            summary_source=summary_source_override or "deterministic",
            reasoning_content=reasoning_content,
        )
        with self._writer_guard():
            p = self._append_path(session_id)  # T3b: 超阈值开新段
            p.parent.mkdir(parents=True, exist_ok=True)
            # T3c: 二进制追加取字节偏移（sidecar 索引定位用），UTF-8 无 BOM 下偏移稳定
            line_bytes = (json.dumps(entry.to_dict(), ensure_ascii=False) + "\n").encode("utf-8")
            offset = self._append_primary_locked(p, line_bytes, entry.id)
            self._index_append(p, offset, entry)
        self._notify_post_save(entry)
        return entry

    def _append_primary_locked(self, path: Path, line: bytes, entry_id: str) -> int:
        """Durably append source bytes before derived index and observer effects.

        On a failed append/fsync, roll back only the new tail while holding the
        store lock. A failed rollback reports uncertain, never safe-to-retry.
        The append itself remains T1: one complete JSONL line, not a T2 RMW.
        """
        created = not path.exists()
        try:
            with path.open("ab") as f:
                offset = f.tell()
                try:
                    written = f.write(line)
                    if written != len(line):
                        raise OSError("short archive append")
                    f.flush()
                    os.fsync(f.fileno())
                except OSError as exc:
                    try:
                        f.truncate(offset)
                        f.flush()
                        os.fsync(f.fileno())
                        if os.fstat(f.fileno()).st_size != offset:
                            raise OSError("tail rollback size mismatch")
                    except OSError as rollback_error:
                        raise ArchiveCommitUncertainError(
                            f"Archive append failed and rollback unconfirmed: {exc}; {rollback_error}",
                            path=path, operation="archive_append",
                            expected_sha256=hashlib.sha256(line).hexdigest(),
                            visible_state=self._append_visible(path, offset, line),
                        ) from rollback_error
                    raise ArchivePersistError(f"Archive append rolled back: {exc}") from exc
        except (ArchivePersistError, ArchiveCommitUncertainError):
            raise
        except OSError as exc:
            raise ArchivePersistError(f"Archive append not started: {exc}") from exc
        if created:
            # New segment file and potentially a new .segments directory are
            # directory entries; both fences matter for restart visibility.
            expected = line  # first entry of this new file
            dirs = (path.parent, self._dir) if path.parent != self._dir else (self._dir,)
            _fsync_parent_or_uncertain(
                path, expected, operation=f"archive_append:{entry_id}", directories=dirs,
            )
        return offset

    @staticmethod
    def _append_visible(path: Path, offset: int, line: bytes) -> str:
        try:
            with path.open("rb") as f:
                f.seek(offset)
                actual = f.read(len(line))
            return "matches" if actual == line else "mismatch"
        except OSError:
            return "unreadable"

    # ── T3c sidecar 索引：写入/读取 ──

    def _index_append(self, segment: Path, offset: int, entry: ArchiveEntry) -> None:
        """索引追加写（fail-open：索引失败不影响档案原文与主流程）."""
        idx = self._index_path(segment)
        try:
            rec = {
                "id": entry.id,
                "session_id": entry.session_id,
                "ts": entry.ts,
                "chars": entry.chars,
                "summary": entry.summary,
                "key_facts": entry.key_facts,
                "key_paths": entry.key_paths,
                "content_head": entry.content[: self._CONTENT_HEAD_CHARS],
                "tool_call_id": entry.tool_call_id,
                "tool_name": entry.tool_name,
                "role": entry.role,
                "offset": offset,
            }
            with idx.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError:
            logger = logging.getLogger(__name__)
            logger.warning("档案索引写失败（fail-open，检索回退全文扫描）: %s", idx)

    def rebuild_segment_index(self, segment: Path) -> int:
        """R3(2026-08-14): 为单个段文件重建 sidecar 索引（存量段补索引）.

        扫描段内每行，按与 _index_append 一致的 rec 格式写出索引（覆盖式重建，幂等）。
        损坏行跳过（fail-open）；返回成功索引的条目数。
        """
        with self._writer_guard():
            return self._rebuild_segment_index_locked(segment)

    def _rebuild_segment_index_locked(self, segment: Path) -> int:
        """Atomic derived index rebuild; primary segment remains authoritative."""
        idx = self._index_path(segment)
        count = 0
        try:
            lines_out: list[str] = []
            offset = 0
            with segment.open("rb") as f:
                while True:
                    raw = f.readline()
                    if not raw:
                        break
                    line = raw.decode("utf-8", errors="replace").strip()
                    if line:
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            offset += len(raw)
                            continue  # 损坏行跳过（fail-open）
                        rec = {
                            "id": entry.get("id", ""),
                            "session_id": entry.get("session_id", ""),
                            "ts": entry.get("ts", ""),
                            "chars": entry.get("chars", 0),
                            "summary": entry.get("summary", ""),
                            "key_facts": entry.get("key_facts", []),
                            "key_paths": entry.get("key_paths", []),
                            "content_head": (entry.get("content") or "")[: self._CONTENT_HEAD_CHARS],
                            "tool_call_id": entry.get("tool_call_id"),
                            "tool_name": entry.get("tool_name"),
                            "role": entry.get("role", ""),
                            "offset": offset,
                        }
                        lines_out.append(json.dumps(rec, ensure_ascii=False))
                        count += 1
                    offset += len(raw)
            payload = ("\n".join(lines_out) + ("\n" if lines_out else "")).encode("utf-8")
            _atomic_replace_bytes(idx, payload, operation="index_rebuild")
        except OSError:
            logger = logging.getLogger(__name__)
            logger.warning("档案索引重建失败（fail-open）: %s", segment)
            return 0
        return count

    def rebuild_all_indexes(self) -> dict:
        """R3: 遍历全部段文件重建索引（存量段补 sidecar；幂等可重复执行）.

        Returns: {"segments": N, "entries": M, "failed": K}
        """
        total_segments = 0
        total_entries = 0
        failed = 0
        for p in self.all_segment_paths():
            total_segments += 1
            try:
                total_entries += self.rebuild_segment_index(p)
            except Exception:  # noqa: BLE001 — 单段失败 fail-open 继续
                failed += 1
        return {"segments": total_segments, "entries": total_entries, "failed": failed}

    def _line_at(self, segment: Path, offset: int) -> str | None:
        """按字节偏移读取段文件一行（fail-open：越界/损坏返回 None）."""
        try:
            with segment.open("rb") as f:
                f.seek(offset)
                raw = f.readline()
            return raw.decode("utf-8")
        except (OSError, UnicodeDecodeError, ValueError, TypeError):
            return None

    def search(
        self,
        session_id: str,
        query: str,
        limit: int = 10,
        *,
        role: str | None = None,
        tool_name: str | None = None,
    ) -> list[dict]:
        """按关键词检索压缩档案（匹配摘要+关键事实+关键路径+原文片段）.

        返回结构化命中（原文片段 + 时间 + 来源定位，可溯源）。
        分片后按段倒序遍历（最近段先，limit 命中即停，不读更旧段）。

        T3c 快速通道：段有 sidecar 索引时先走索引预筛（summary/key_facts/key_paths/
        content_head 子串匹配）→ 命中行按偏移读全文确认；索引未达 limit 时
        全文补齐该段（保证 content 尾部命中/索引缺失条目不漏），索引缺失/损坏
        直接全文扫描（fail-open）。最终判定始终在全文，limit 截断语义等价。
        """
        try:
            segs = self._segment_paths(session_id)
        except ValueError:
            return []
        if not segs:
            return []
        raw_query = str(query or "").strip()
        lower_query = raw_query.lower()
        if lower_query.startswith("archive:"):
            raw_query = raw_query[len("archive:") :].split(";", 1)[0].strip()
        elif lower_query.startswith("digest:"):
            raw_query = raw_query[len("digest:") :].split(";", 1)[0].strip()
        q = raw_query.lower()
        hits: list[dict] = []
        seen_ids: set[str] = set()
        for p in reversed(segs):  # T3b: 最近段优先
            idx = self._index_path(p)
            if idx.exists():
                # 快速通道：索引预筛（含 role/tool_name 过滤）
                for offset, rec in self._index_scan(idx, q, role, tool_name):
                    line = self._line_at(p, offset)
                    if line is None:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if (
                        str(entry.get("id") or "") != str(rec.get("id") or "")
                        or entry.get("session_id", session_id) != session_id
                    ):
                        # A lagging index offset must never supply another
                        # entry's canonical content or satisfy limit early.
                        continue
                    eid = entry.get("id", "")
                    if eid in seen_ids:
                        continue
                    if self._entry_matches(entry, q, role, tool_name):
                        seen_ids.add(eid)
                        hits.append(self._hit_dict(entry, p))
                        if len(hits) >= limit:
                            return hits
                # 补齐：全文扫描该段（跳过已确认 id，保证索引盲区不漏）
                if len(hits) < limit:
                    self._scan_segment(p, q, role, tool_name, limit, seen_ids, hits)
                    if len(hits) >= limit:
                        return hits
            else:
                # 无索引（存量段）→ 全文扫描（fail-open 兼容）
                self._scan_segment(p, q, role, tool_name, limit, seen_ids, hits)
                if len(hits) >= limit:
                    return hits
        return hits

    # ── T3c 检索辅助 ──

    def _index_scan(self, idx: Path, q: str, role: str | None, tool_name: str | None) -> list:
        """索引预筛（子串匹配 summary/key_facts/key_paths/content_head）→ [(offset, rec)]."""
        out: list[tuple[int, dict]] = []
        try:
            with idx.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # 索引损坏行跳过（全文补齐兜底）
                    if role and rec.get("role") != role:
                        continue
                    if tool_name and rec.get("tool_name") != tool_name:
                        continue
                    hay = " ".join(
                        [
                            str(rec.get("id", "")),
                            str(rec.get("tool_call_id", "") or ""),
                            rec.get("summary", ""),
                            " ".join(rec.get("key_facts", [])),
                            " ".join(rec.get("key_paths", [])),
                            rec.get("content_head", ""),
                        ]
                    ).lower()
                    if q and q not in hay:
                        continue
                    offset = rec.get("offset")
                    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
                        continue  # corrupted derived offset; full scan recovers
                    out.append((offset, rec))
        except OSError:
            return []  # 索引读失败 → 全文补齐兜底
        return out

    @staticmethod
    def _entry_matches(entry: dict, q: str, role: str | None, tool_name: str | None) -> bool:
        """全文匹配判定（与旧实现逐字一致，含思考链检索域）."""
        if role and entry.get("role") != role:
            return False
        if tool_name and entry.get("tool_name") != tool_name:
            return False
        if not q:
            return True
        hay = " ".join(
            [
                str(entry.get("id", "")),
                str(entry.get("tool_call_id", "") or ""),
                entry.get("content", ""),
                entry.get("summary", ""),
                " ".join(entry.get("key_facts", [])),
                " ".join(entry.get("key_paths", [])),
                entry.get("reasoning_content", "") or "",  # P0-2: 思考链可检索
            ]
        ).lower()
        return q in hay

    @staticmethod
    def _hit_dict(entry: dict, p: Path) -> dict:
        """命中结果构造（与旧实现逐字一致）."""
        return {
            "id": entry.get("id"),
            "ts": entry.get("ts"),
            "role": entry.get("role"),
            "source": entry.get("source"),
            "tool_name": entry.get("tool_name"),
            "tool_call_id": entry.get("tool_call_id"),
            "status": entry.get("status"),
            "chars": entry.get("chars"),
            "summary": entry.get("summary", "")[:500],
            "summary_source": entry.get("summary_source", "deterministic"),
            "key_facts": entry.get("key_facts", [])[:5],
            "key_paths": entry.get("key_paths", [])[:5],
            "content_preview": entry.get("content", "")[:800],
            "file": str(p),
        }

    def _scan_segment(
        self,
        p: Path,
        q: str,
        role: str | None,
        tool_name: str | None,
        limit: int,
        seen_ids: set[str],
        hits: list[dict],
    ) -> None:
        """全文扫描一段（跳过已确认 id，命中达 limit 即停）."""
        try:
            with p.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    eid = entry.get("id", "")
                    if eid in seen_ids:
                        continue
                    if self._entry_matches(entry, q, role, tool_name):
                        seen_ids.add(eid)
                        hits.append(self._hit_dict(entry, p))
                        if len(hits) >= limit:
                            return
        except OSError:
            return  # 段读失败 fail-open（跳过该段）

    def get_by_tool_call_id(self, session_id: str, tool_call_id: str) -> dict | None:
        """按 tool_call_id 精确取档案条目（M52: web 端分层截断"展开原文"数据源）.

        返回 None 表示未归档（未截断/归档降级），调用方如实降级。
        T3c: 有索引时按偏移精确定位；无索引回退全文扫描。
        """
        if not tool_call_id:
            return None
        try:
            segs = self._segment_paths(session_id)
        except ValueError:
            return None
        for p in reversed(segs):  # T3b: 最近段优先
            idx = self._index_path(p)
            if idx.exists():
                # 快速通道：索引 tool_call_id 精确匹配 → 偏移定位原文
                try:
                    with idx.open("r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                rec = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            if rec.get("tool_call_id") != tool_call_id:
                                continue
                            raw = self._line_at(p, rec.get("offset", 0))
                            if raw is None:
                                continue
                            try:
                                indexed_entry = json.loads(raw)
                            except json.JSONDecodeError:
                                continue
                            # Sidecar is derived and may lag a segment rewrite.
                            # Its offset must never authorize a different entry.
                            if (
                                indexed_entry.get("tool_call_id") == tool_call_id
                                and indexed_entry.get("session_id", session_id) == session_id
                                and str(indexed_entry.get("id") or "") == str(rec.get("id") or "")
                            ):
                                return indexed_entry
                            # Continue to canonical linear scan on stale offset.
                except OSError:
                    pass  # 索引读失败 → 回退全文扫描
            with p.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("tool_call_id") == tool_call_id:
                        return entry
        return None

    def get_by_id(self, session_id: str, entry_id: str) -> dict | None:
        """按稳定 archive entry id 精确水合当前会话的 canonical hit.

        Semantic retrieval may rank a compact vectorization projection, but that
        projection is never authoritative display data. This method re-reads the
        owned archive entry and returns the same hit shape as keyword search.
        """
        entry_id = str(entry_id or "").strip()
        if not entry_id:
            return None
        try:
            segs = self._segment_paths(session_id)
        except ValueError:
            return None
        for p in reversed(segs):
            try:
                with p.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if str(entry.get("id") or "") == entry_id:
                            return self._hit_dict(entry, p)
            except OSError:
                continue
        return None

    def stats(self, session_id: str) -> dict:
        """压缩档案统计（供 architecture_status 展示，跨段累加）.

        EVO-20260922 增量缓存（P1）: 按 (mtime_ns, size) 记忆每段统计，段未变
        直接复用，仅新增/变更段重读——21GB 全库每次全扫 ~3s 的根因在此，
        调用方 _sum_archive_stats / identity_history_exists 共用本口径同享收益。
        失效键含 mtime_ns+size：append 改 size、update_summary 改 mtime，
        正常写路径不会漏失效；删除段自动清键。段在 stat 时已消失 → 按 0 计
        （不中断余段；旧实现此处 OSError 会让外部汇总 fail-open 截断，语义
        收窄为更合理的部分统计）。T3b 跨段累加、单行损坏 fail-open 跳过均不变。
        """
        try:
            segs = self._segment_paths(session_id)
        except ValueError:
            return {"archived_count": 0, "archived_chars": 0}
        cache = self._stats_cache.setdefault(session_id, {})
        seen: set[str] = set()
        count = 0
        chars = 0
        for p in segs:  # T3b: 跨段累加
            try:
                st = p.stat()
            except OSError:
                continue  # stat 期已消失的段按 0 计（fail-open，不中断余段）
            key = str(p)
            seen.add(key)
            stamp = (st.st_mtime_ns, st.st_size)
            hit = cache.get(key)
            if hit is not None and hit[0] == stamp:
                seg_count, seg_chars = hit[1], hit[2]
            else:
                seg_count, seg_chars = self._scan_segment_stats(p)
                cache[key] = (stamp, seg_count, seg_chars)
            count += seg_count
            chars += seg_chars
        for stale in cache.keys() - seen:
            del cache[stale]  # 段被 GC/重组删除 → 缓存同步丢弃
        return {"archived_count": count, "archived_chars": chars}

    @staticmethod
    def _scan_segment_stats(p: Path) -> tuple[int, int]:
        """单段全量扫描统计（行数 + chars 字段累加；单行损坏 fail-open 跳过）."""
        seg_count = 0
        seg_chars = 0
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                seg_count += 1
                try:
                    entry = json.loads(line)
                    seg_chars += int(entry.get("chars", 0))
                except (json.JSONDecodeError, ValueError) as exc:  # fail-open：单行损坏跳过
                    logging.getLogger(__name__).debug("档案统计单行损坏跳过（fail-open）: %s", exc)
        return seg_count, seg_chars

    def update_summary(self, entry_id: str, summary: str, summary_source: str) -> bool:
        """按 id 回填摘要到档案条目（T28）.

        失败返回 False + 日志（fail-open，不影响已交付档案）。
        P3: 与 append 串行化物理 segment mutation；旧 run 的合法历史回填可以
        继续完成，但绝不能用旧 read snapshot 覆盖新 run 已追加的事实。
        """
        with self._writer_guard():
            p = self._entry_session_path(entry_id)
            if p is None:
                return False
            try:
                lines = p.read_text(encoding="utf-8").splitlines()
                out: list[str] = []
                found = False
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        out.append(line)
                        continue
                    if entry.get("id") == entry_id:
                        # R5: identity_filtered is a sticky derived-state invariant. Normal
                        # semantic backfill must not reintroduce identity/self-description
                        # details. A future reversible migration can explicitly rewrite the
                        # archive outside this generic update path.
                        if entry.get("summary_source") != "identity_filtered":
                            entry["summary"] = summary
                            entry["summary_source"] = summary_source
                        found = True
                    out.append(json.dumps(entry, ensure_ascii=False))
                if found:
                    payload = ("\n".join(out) + "\n").encode("utf-8")
                    _atomic_replace_bytes(p, payload, operation="update_summary")
                    # Index is reconstructible; if its rebuild fails,
                    # canonical source is still usable through full scan.
                    self._rebuild_segment_index_locked(p)
                return found
            except ArchiveCommitUncertainError as exc:
                logging.getLogger(__name__).warning(
                    "档案摘要提交结果不确定，禁止盲重放，先 exact readback: "
                    "path=%s sha256=%s visible=%s",
                    exc.path, exc.expected_sha256, exc.visible_state,
                )
                return False  # existing bool fail-open contract, no false durability claim
            except OSError:
                return False

    def _entry_session_path(self, entry_id: str) -> Path | None:
        """定位条目所在段文件（线性扫描全部段；T3b 返回完整路径，分片正确）."""
        for p in self.all_segment_paths():
            with p.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("id") == entry_id:
                        return p
        return None

    def cleanup(self, *, max_entries: int = 0, ttl_days: int = 0) -> dict:
        """R7: 清理过期/超量档案条目（启动时调用一次，防磁盘膨胀）.

        - max_entries > 0: 单会话（跨全部段）超过 N 条时删除最旧的（保留最近 N 条）
        - ttl_days > 0: 超过 N 天的条目删除（按条目 ts 判断）
        - 两者都为 0: 空操作（零回归）
        - 单文件清理失败 fail-open（warning + 跳过），不阻断其他文件

        Returns:
            {"pruned_files": N, "pruned_entries": N}
        """
        if max_entries <= 0 and ttl_days <= 0:
            return {"pruned_files": 0, "pruned_entries": 0}

        # The complete read/plan/replace cycle must exclude concurrent
        # append and summary backfill, including other service processes.
        with self._writer_guard():
            return self._cleanup_locked(max_entries=max_entries, ttl_days=ttl_days)

    def _cleanup_locked(self, *, max_entries: int, ttl_days: int) -> dict:
        """Best-effort per-file pruning under the store-wide writer lease."""
        import logging

        total_pruned = 0
        pruned_files = 0

        # 按ArchiveStore的真实owner分组，不能再从`sid-N`文件名猜session归属。
        groups: dict[str, list[Path]] = {}
        for sid in self.session_ids():
            try:
                groups[sid] = self._segment_paths(sid)
            except ValueError as exc:
                logging.getLogger(__name__).warning("档案GC owner不可判定（跳过）: %s", exc)

        cutoff_at = None
        if ttl_days > 0:
            cutoff_at = system_local_now() - timedelta(days=ttl_days)

        for sid, segs in groups.items():
            try:
                kept_lines: list[str] = []  # 段内保留行（ttl 过滤后）
                per_seg: dict[Path, list[str]] = {}
                orig_counts: dict[Path, int] = {}
                for p in segs:
                    lines = p.read_text(encoding="utf-8").splitlines()
                    orig_counts[p] = len(lines)
                    kept: list[str] = []
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        if cutoff_at is not None:
                            try:
                                entry = json.loads(line)
                            except json.JSONDecodeError:
                                kept.append(line)  # 无法解析的条目保留（fail-open）
                                continue
                            ts = entry.get("ts", "")
                            try:
                                recorded_at = datetime.fromisoformat(str(ts)) if ts else None
                                if recorded_at is not None and recorded_at.tzinfo is None:
                                    recorded_at = recorded_at.astimezone()
                            except (TypeError, ValueError):
                                recorded_at = None
                            if recorded_at is not None and recorded_at < cutoff_at:
                                continue
                        kept.append(line)
                    per_seg[p] = kept
                    kept_lines.extend(kept)

                if max_entries > 0 and len(kept_lines) > max_entries:
                    # 跨段全局保留最近 max_entries 条（从最后段向前裁剪/删整段）
                    to_drop = len(kept_lines) - max_entries
                    for p in segs:  # seq 升序 → 从最早段开始丢
                        lines = per_seg[p]
                        if to_drop <= 0:
                            break
                        if len(lines) <= to_drop:
                            to_drop -= len(lines)
                            per_seg[p] = []
                        else:
                            per_seg[p] = lines[to_drop:]
                            to_drop = 0
                # 写回/删除空段（与原始行数一致则零改动）
                for p, kept in per_seg.items():
                    if len(kept) == orig_counts[p]:
                        continue
                    if kept:
                        _atomic_replace_bytes(
                            p, ("\n".join(kept) + "\n").encode("utf-8"),
                            operation="cleanup_rewrite",
                        )
                        self._rebuild_segment_index_locked(p)
                    else:
                        self._index_path(p).unlink(missing_ok=True)
                        p.unlink(missing_ok=True)
                        try:
                            _fsync_directory(p.parent)
                        except OSError as exc:
                            raise ArchiveCommitUncertainError(
                                f"Archive cleanup deletion visible but dir fsync unconfirmed: {exc}",
                                path=p, operation="cleanup_delete",
                                expected_sha256="",
                                visible_state="absent" if not p.exists() else "present",
                            ) from exc
                    total_pruned += max(0, orig_counts[p] - len(kept))
                    pruned_files += 1
                seg_dir = self._segments_dir(sid)
                if seg_dir.is_dir() and not any(seg_dir.iterdir()):
                    seg_dir.rmdir()
                    _fsync_directory(self._dir)
            except Exception as exc:  # noqa: BLE001 — 单会话清理失败 fail-open
                logging.getLogger(__name__).warning("档案 GC 失败（fail-open）: %s: %s", sid, exc)
                continue

        return {"pruned_files": pruned_files, "pruned_entries": total_pruned}
