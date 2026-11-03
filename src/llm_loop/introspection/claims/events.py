"""claim / fanout 决策事件流（DESIGN-20261103 §6.6；T-0.6 埋点骨架，阶段 PR-0）.

落盘位置 ``<audit_dir>/claims/events.jsonl``：与将来的 claims 账本同目录、独立文件。
不混进 ``action_trace.jsonl``（2026-11-03 实测 357MB）：一是那里记的是工具调用，混进去
无法区分"哪一行是权威决策"；二是观测写与工具调用抢同一文件，慢 I/O 会传染到工具路径。

三条不变量（§6.6，本模块是它们的唯一执行点）：

1. **观测不阻断**：``write_event`` 只在内部吞异常 + 计数，永不抛给调用方。
2. **事件不伪造**：调用点必须在权威写入（task 账本 fsync）*之后*才调用本模块；
   崩溃只会丢尾行，不会产生一条没发生过的决策。
3. **事件可丢但要标注**：``write_failures() > 0`` 时调用方必须在 ``degraded`` 里
   标注"分母不完整"，比率不得直接对外报数。

与 §6.6 的一处实现偏差（已回写文档）：``fanout_decision`` 的字段采集在
``_children_guard`` 内完成，append 放在锁外同一函数帧内 —— 决策点仍是同一个临界区，
但不在热锁上做文件 I/O。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections import Counter
from pathlib import Path
from typing import Any

from llm_loop.timekeeping import system_local_now

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
CLAIMS_DIRNAME = "claims"
EVENTS_FILENAME = "events.jsonl"
#: 单行上限（§6.6）。超限不写并计入 failures —— 宁可缺一条事件，不写半条超长行。
MAX_LINE_BYTES = 1024
#: 字符串字段超过此长度即截断（保留可读前缀 + 省略号），避免长 goal/task id 撑爆行。
MAX_STR_FIELD = 96

_FAILURES: Counter[str] = Counter()
_FAILURES_GUARD = threading.Lock()
#: 进程内串行化同一路径的 append：POSIX O_APPEND 单次写虽原子，但两个线程
#: 同时 open->write 仍可能出现半行交错（短写）。
_WRITE_GUARD = threading.Lock()


def claims_dir(audit_dir: str | os.PathLike[str]) -> Path:
    """claims 目录（与 claims 账本同目录）。不创建。"""
    return Path(str(audit_dir)) / CLAIMS_DIRNAME


def events_path(audit_dir: str | os.PathLike[str]) -> Path:
    """事件流路径 ``<audit_dir>/claims/events.jsonl``。不创建。"""
    return claims_dir(audit_dir) / EVENTS_FILENAME


def _failure_key(audit_dir: str | os.PathLike[str]) -> str:
    try:
        return os.path.abspath(os.fspath(events_path(audit_dir)))
    except Exception:  # noqa: BLE001 - key 构造失败也不能阻断调用方
        return str(audit_dir)


def write_failures(audit_dir: str | os.PathLike[str]) -> int:
    """本进程内该事件流的 append 失败次数（跨进程不共享，§6.6 口径）。"""
    with _FAILURES_GUARD:
        return int(_FAILURES.get(_failure_key(audit_dir), 0))


def reset_write_failures(audit_dir: str | os.PathLike[str] | None = None) -> None:
    """清零计数（测试用；进程重启天然归零）。None = 全部清零。"""
    with _FAILURES_GUARD:
        if audit_dir is None:
            _FAILURES.clear()
            return
        _FAILURES.pop(_failure_key(audit_dir), None)


def _count_failure(key: str, exc: BaseException | str) -> None:
    with _FAILURES_GUARD:
        _FAILURES[key] += 1
    logger.warning("claims 事件写入失败（fail-open，调用结果不变）: %s", exc)


def _trim_field(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_STR_FIELD:
        return value[: MAX_STR_FIELD - 1] + "…"
    return value


def build_row(kind: str, **fields: Any) -> dict[str, Any]:
    """构造一行事件（字段固定，后续只增不改，§6.6）。

    键顺序固定，便于 diff 与人工抽样；``v``/``ts``/``kind`` 由本函数负责，
    调用方不得覆盖（传了也会被覆盖回权威值）。
    """
    row: dict[str, Any] = {"v": SCHEMA_VERSION, "ts": system_local_now().isoformat()}
    row["kind"] = str(kind)
    for key, value in fields.items():
        if key in ("v", "ts", "kind"):
            continue
        row[key] = _trim_field(value)
    return row


def write_event(audit_dir: str | os.PathLike[str], kind: str, **fields: Any) -> bool:
    """append 一行事件；返回是否真的写成功。**永不抛异常**（不变量 1）。

    不 fsync（§6.6/Q41）：事件的持久性低于权威账本，崩溃丢尾行可接受。
    """
    key = _failure_key(audit_dir)
    try:
        row = build_row(kind, **fields)
        line = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        blob = (line + "\n").encode("utf-8")
        if len(blob) > MAX_LINE_BYTES:
            _count_failure(key, f"line_too_long:{len(blob)}B>{MAX_LINE_BYTES}B")
            return False
        path = events_path(audit_dir)
        with _WRITE_GUARD:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("ab") as handle:
                handle.write(blob)
                handle.flush()
        return True
    except Exception as exc:  # noqa: BLE001 - 不变量 1：观测绝不阻断
        _count_failure(key, f"{type(exc).__name__}: {exc}")
        return False


def read_events_stats(
    audit_dir: str | os.PathLike[str], *, max_scan_bytes: int = 4 * 1024 * 1024
) -> dict[str, Any]:
    """事件流的规模与坏行统计（只读；供 ``coordination_snapshot`` 填 degraded）。

    坏行（半行截断）是**预期**现象：append 不 fsync，崩溃会留半行。这里只如实计数，
    不据此报 degraded —— 丢尾行不是账本损坏（§6.6/F13 同一原则）。

    成本边界：超过 ``max_scan_bytes`` 只回 size，``lines`` 置 None 并标
    ``note=skipped_scan_over_cap``——速率/告警只需要 size 增量，不值得为一次快照
    全量扫（§6.4.2 的 80ms 预算）。
    """
    path = events_path(audit_dir)
    stats: dict[str, Any] = {
        "path": str(path),
        "exists": False,
        "bytes": 0,
        "lines": 0,
        "bad_lines": 0,
    }
    try:
        info = path.stat()
    except FileNotFoundError:
        return stats
    except OSError as exc:
        stats["error"] = f"{type(exc).__name__}: {exc}"
        return stats
    stats["exists"] = True
    stats["bytes"] = int(info.st_size)
    if int(info.st_size) > max_scan_bytes:
        stats["lines"] = None
        stats["note"] = "skipped_scan_over_cap"
        return stats
    lines = bad = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                if not raw.strip():
                    continue
                lines += 1
                try:
                    json.loads(raw)
                except json.JSONDecodeError:
                    bad += 1
    except OSError as exc:
        stats["error"] = f"{type(exc).__name__}: {exc}"
    stats["lines"] = lines
    stats["bad_lines"] = bad
    return stats
