"""event_logs 增量扫描缓存（settlement 超时缓解，2026-10-17）。

背景：data/event_logs 已到 GB 级（2k+ 会话目录）。settlement 的规则回执
跨会话查重（P-SET-7）与 RuleFeedbackProjection 此前每次调用都全量重扫，
60s 工具超时会把 settlement_submit 掐断（2026-10-17 10:40 事故：模型侧
timeout×2，服务端实际完成两项落账但回执丢失、krate autorun 钩子未执行）。

可见行为与 settlement._scan_event_files 的全量直读逐字对齐：
- 遍历 root/*.jsonl 与 root/*/*.jsonl（两段均按路径名 sorted），行序 =
  文件序 × 行序；仅返回 type ∈ keep_types 的行（dict 原样返回）。
- indexed_watermark 覆盖本次扫描见到的全部行（含被过滤的行）的 max(ts)。

缓存设计（可删重建的派生物，非真值源；删 .scan_cache 即冷启）：
- 文件 root/.scan_cache/events_<keephash10>.json（keep 集合分桶，互不污染）：
  {"version":1,"keep":[...],"files":{relpath:[mtime_ns,size,offset]},
   "rows_by_file":{relpath:[rows...]},"indexed_watermark":str}
- 续读：size 增大且 mtime 变化 → 从字节 offset 续读（offset 只记行边界）；
  size 变小 / mtime 变而 size 不变（原地改写）→ 整文件重读。
- 并发：更新全程 flock(LOCK_EX)；5s 内抢不到锁则返回进入时加载的快照
  （fail-open 旧数据、水位如实旧，绝不抛错打断调用方）。
- 损坏：缓存 JSON 解析失败/结构异常 → 视为冷缓存全量重建。
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import time

try:  # POSIX 锁；无 fcntl 平台（非本仓运行态）整体退化为全量直读
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_VERSION = 1
_LOCK_WAIT_SECONDS = 5.0
_CACHE_DIRNAME = ".scan_cache"


def _keep_hash(keep_types: Iterable[str]) -> str:
    joined = "|".join(sorted(str(t) for t in keep_types))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:10]


def _empty_snapshot() -> dict:
    return {"files": {}, "rows_by_file": {}, "indexed_watermark": ""}


def _load_cache(cpath: Path) -> dict:
    try:
        data = json.loads(cpath.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty_snapshot()
    if (
        not isinstance(data, dict)
        or data.get("version") != CACHE_VERSION
        or not isinstance(data.get("files"), dict)
        or not isinstance(data.get("rows_by_file"), dict)
    ):
        return _empty_snapshot()
    rows_by_file = data["rows_by_file"]
    if any(
        not isinstance(v, list) or any(not isinstance(r, dict) for r in v)
        for v in rows_by_file.values()
    ):
        # 结构损坏（如值被写成字符串）视为缓存不可用，走重建，
        # 防止垃圾行穿透 fail-open 兜底直达调用方。
        return _empty_snapshot()
    return {
        "files": data["files"],
        "rows_by_file": rows_by_file,
        "indexed_watermark": str(data.get("indexed_watermark") or ""),
    }


def _collect_paths(root: Path) -> list[Path]:
    """与 settlement._scan_event_files 相同的两段式遍历（sorted，缓存目录除外）."""
    paths = sorted(root.glob("*.jsonl"))
    for seg in sorted(
        p for p in root.iterdir() if p.is_dir() and p.name != _CACHE_DIRNAME
    ):
        paths.extend(sorted(seg.glob("*.jsonl")))
    return paths


def _read_rows(
    path: Path, keep: set[str], *, offset: int = 0
) -> tuple[list[dict], str, int]:
    """读单个 jsonl：返回 (keep 行, 本段 max(ts), 读到的字节 offset).

    offset 只在完整行尾记录（readline 循环），续读不会撕开多字节字符。
    单行畸形跳过（与全量直读的 json 容错一致）；OSError 时如实返回已读部分。
    """
    rows: list[dict] = []
    watermark = ""
    pos = offset
    try:
        with path.open("rb") as fh:
            if offset:
                fh.seek(offset)
            while True:
                line = fh.readline()
                if not line:
                    break
                if not line.endswith(b"\n"):
                    # 末尾半行（写入方 mid-flush）：offset 不越过行边界，
                    # 补全后下次续读重拿整行（与全量直读对齐契约）。
                    break
                pos = fh.tell()
                text = line.decode("utf-8", "replace").strip()
                if not text:
                    continue
                try:
                    row = json.loads(text)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                ts = str(row.get("ts") or "")
                if ts > watermark:
                    watermark = ts
                if str(row.get("type") or "") in keep:
                    rows.append(row)
    except OSError:
        logger.debug("增量扫描读文件失败（fail-open 跳过）: %s", path, exc_info=True)
    return rows, watermark, pos


def _update_snapshot(root: Path, snap: dict, keep: set[str]) -> dict:
    files_meta: dict = snap["files"]
    rows_by_file: dict = snap["rows_by_file"]
    watermark = str(snap.get("indexed_watermark") or "")
    new_files: dict[str, list] = {}
    new_rows: dict[str, list] = {}
    for path in _collect_paths(root):
        rel = str(path.relative_to(root))
        try:
            st = path.stat()
        except OSError:
            continue
        meta = files_meta.get(rel)
        cached_rows = rows_by_file.get(rel) or []
        if isinstance(meta, list) and len(meta) == 3 and meta[0] == st.st_mtime_ns and meta[1] == st.st_size:
            rows, new_offset = cached_rows, int(meta[2])
        elif (
            isinstance(meta, list)
            and len(meta) == 3
            and st.st_size > int(meta[1])
            and meta[0] != st.st_mtime_ns
        ):
            appended, wm, pos = _read_rows(path, keep, offset=int(meta[2]))
            rows = list(cached_rows) + appended
            new_offset = pos
            if wm > watermark:
                watermark = wm
        else:
            rows, wm, pos = _read_rows(path, keep, offset=0)
            new_offset = pos
            if wm > watermark:
                watermark = wm
        new_files[rel] = [st.st_mtime_ns, st.st_size, new_offset]
        new_rows[rel] = rows
    return {
        "files": new_files,
        "rows_by_file": new_rows,
        "indexed_watermark": watermark,
    }


def _materialize(root: Path, snap: dict) -> tuple[list[dict], str]:
    rows: list[dict] = []
    for path in _collect_paths(root):
        rel = str(path.relative_to(root))
        rows.extend(snap["rows_by_file"].get(rel) or [])
    return rows, str(snap.get("indexed_watermark") or "")


def _store_cache(cpath: Path, snap: dict, keep: set[str]) -> None:
    payload = {
        "version": CACHE_VERSION,
        "keep": sorted(keep),
        "files": snap["files"],
        "rows_by_file": snap["rows_by_file"],
        "indexed_watermark": snap["indexed_watermark"],
    }
    tmp = cpath.with_name(cpath.name + f".tmp.{os.getpid()}")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, cpath)
    except OSError:
        logger.debug("缓存写回失败（fail-open，下次重建）", exc_info=True)
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


def _full_scan(root: Path, keep: set[str]) -> tuple[list[dict], str]:
    rows: list[dict] = []
    watermark = ""
    for path in _collect_paths(root):
        file_rows, wm, _pos = _read_rows(path, keep, offset=0)
        rows.extend(file_rows)
        if wm > watermark:
            watermark = wm
    return rows, watermark


def scan_event_files(
    root: Path | str,
    *,
    keep_types: Iterable[str],
    cache_dir: Path | str | None = None,
) -> tuple[list[dict], str]:
    """增量扫描 event_logs：返回 (keep 行列表, indexed_watermark).

    fail-open 契约：任何内部异常都不外抛——回退全量直读，行为退化为
    旧实现（慢但正确）。调用方不需要 try/except。
    """
    root = Path(root)
    keep = {str(t) for t in keep_types}
    if not root.is_dir():
        return [], ""
    cdir = Path(cache_dir) if cache_dir is not None else root / _CACHE_DIRNAME
    cpath = cdir / f"events_{_keep_hash(keep)}.json"
    lock_path = cdir / f"events_{_keep_hash(keep)}.lock"
    try:
        cdir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return _full_scan(root, keep)
    if fcntl is None:
        return _full_scan(root, keep)
    snapshot = _load_cache(cpath)
    fd: int | None = None
    deadline = time.monotonic() + _LOCK_WAIT_SECONDS
    try:
        while True:
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    os.close(fd)
                    fd = None
                    if time.monotonic() >= deadline:
                        # 抢不到锁：旧快照结构可用则用旧快照（略旧，水位如实旧）；
                        # 空快照（该桶缓存尚未建成/损坏重建中）回退全量直读，
                        # 绝不返回"缓存不存在"造成的空集（fail-open 契约）。
                        if snapshot.get("files"):
                            return _materialize(root, snapshot)
                        return _full_scan(root, keep)
                    time.sleep(0.05)
            except OSError:
                fd = None
                break
        if fd is not None:
            # 拿到锁后重读最新缓存（他人可能刚写完）
            snapshot = _load_cache(cpath)
            snapshot = _update_snapshot(root, snapshot, keep)
            _store_cache(cpath, snapshot, keep)
        return _materialize(root, snapshot)
    except Exception:  # noqa: BLE001 — 缓存层任何异常回退全量直读
        logger.debug("增量缓存异常，回退全量直读", exc_info=True)
        return _full_scan(root, keep)
    finally:
        if fd is not None:
            os.close(fd)
