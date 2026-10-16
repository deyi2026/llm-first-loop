"""EVO-20261016-ac47e850: spawn_subagent 声明式 git worktree 文件系统隔离。

约定（非默认开启；requires.fs_isolation=true 才生效）：
- worktree 建在 <parent>/.worktrees/lfl-child-<sid8>/，与既有 drill 施工惯例同目录；
- 子代理运行期 current_workspace_root 指向 worktree，fs 工具面（edit_file/
  execute_command/path registry）落在隔离树内；journal/session 落盘位置不受影响
  （由 session_store 决定，见 ToolExecutionJournal 构造）；
- 终态：干净树删除；脏树保守保留并报告，绝不自动删除未合并改动；
- 孤儿回收：仅"过期且干净"的树可 prune；脏树（含未过期）一律保守保留并计入
  上限，超上限拒绝新的隔离申请（防敏感跟踪文件明文副本无限堆积）；
- "干净"= 工作区无未提交/未跟踪/ignored 文件且 HEAD 仍等于创建时 base commit；
  child 已 commit 的产出（detached HEAD 上新提交）与 ignored 文件均判脏保留，
  保留树报告附当前 HEAD hash 供父会话显式合并；
- 不做自动合并：合并回父工作区是父会话的显式动作，走既有提交队列。

失败即拒绝（fail-fast），绝不降级到共享工作区——无声丢隔离比失败更糟。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

WORKTREE_PREFIX = "lfl-child-"
META_FILENAME = ".lfl-worktree.json"
# 默认值：孤儿 TTL 取 child 租约上限（600s）的量级放大，运行中的树不会被判孤儿。
ORPHAN_TTL_S = 24 * 3600
MIN_FREE_BYTES = 512 * 1024 * 1024  # 512MB
MAX_KEPT_DIRTY = 8
_GIT_TIMEOUT_S = 30


class WorktreeIsolationError(Exception):
    """prepare 阶段失败。reason_code 供上层原样透出，绝不降级。"""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)
        self.reason_code = reason_code
        self.detail = detail


@dataclass
class WorktreeLease:
    path: str
    child_id: str
    parent_root: str = ""
    created_at: float = field(default_factory=time.time)


@dataclass
class ReleaseReport:
    state: str  # "removed" | "kept_dirty" | "remove_failed" | "missing"
    dirty_files: int = 0
    head: str = ""  # kept_dirty 时的当前 HEAD（父会话据此显式合并）
    detail: str = ""


def _git(cwd: str, *args: str, timeout: int = _GIT_TIMEOUT_S) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        # git 异常不向外抛：调用方 rc!=0 分支均已按保守方向处理。
        return 127, "", f"{type(exc).__name__}: {exc}"
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _meta_path(worktree_dir: Path) -> Path:
    return worktree_dir / META_FILENAME


def _read_meta(worktree_dir: Path) -> dict[str, Any] | None:
    try:
        return json.loads(_meta_path(worktree_dir).read_text("utf-8"))
    except (OSError, ValueError):
        return None


def _latest_touch(worktree_dir: Path) -> float:
    """树内最近文件修改时间（活性代理）：活跃 child 持续写文件 → 近；
    崩溃孤儿死树停止写入 → 过期。O(树内文件数)，仅惰性 sweep 时调用。"""
    latest = 0.0
    for p in worktree_dir.rglob("*"):
        try:
            m = p.stat().st_mtime
        except OSError:
            continue
        if m > latest:
            latest = m
    return latest


def _ensure_worktrees_excluded(parent: Path) -> None:
    """.worktrees/ 未被任何 ignore 机制覆盖时，幂等补一行 .git/info/exclude。
    不动用户的 .gitignore（本地仓库级 exclude，作用等同且无共享副作用）。"""
    marker = ".worktrees/"
    try:
        rc, _out, _err = _git(str(parent), "check-ignore", "-q", marker)
        if rc == 0:
            return  # 已被 .gitignore/.gitignore_global/exclude 覆盖
    except Exception:  # noqa: BLE001 — check-ignore 失败继续走 exclude 兜底
        pass
    # 嵌套隔离（父自身是 linked worktree 再派子代）时 --git-dir 指向 per-worktree
    # 目录，而 exclude 实际读取在 common dir → 必须用 --git-common-dir 定位。
    rc, common_dir, _ = _git(str(parent), "rev-parse", "--git-common-dir")
    if rc != 0:
        return
    cd = Path(common_dir)
    if not cd.is_absolute():
        cd = (parent / cd).resolve()
    exclude = cd / "info" / "exclude"
    try:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude.read_text("utf-8") if exclude.exists() else ""
        if marker not in existing.splitlines():
            with exclude.open("a", encoding="utf-8") as fh:
                if existing and not existing.endswith("\n"):
                    fh.write("\n")
                fh.write(f"{marker}\n")
    except OSError:
        # exclude 写失败不阻塞 prepare：gitlink 污染风险留给上层 reason_code 已有路径
        return


def _tree_has_changes(worktree_dir: Path) -> bool:
    """"干净"谓词（P1 修复）: base_head 变化（已 commit 产出）或存在
    未提交/未跟踪/ignored 文件（机制 meta 除外）均判脏，保守保留。"""
    meta = _read_meta(worktree_dir) or {}
    base = str(meta.get("base_head") or "")
    if not base:
        # meta 缺失/损坏/base_head 为空（如 child git clean 删掉了未跟踪 meta、
        # 或 prepare 时 rev-parse 失败写入空串）：HEAD 漂移检查不可执行，
        # 已提交产出无法证明安全 → 一律判脏保守保留。
        return True
    rc, head, _ = _git(str(worktree_dir), "rev-parse", "HEAD")
    if rc != 0 or head != base:
        return True
    rc, out, _ = _git(
        str(worktree_dir),
        "status",
        "--porcelain",
        "--ignored=matching",
        "--",
        ".",
        f":!{META_FILENAME}",
    )
    if rc != 0:
        # 状态不可判定时按脏处理（保守：不删）。
        return True
    return bool(out)


def _sweep_orphans(parent_root: Path, *, ttl_s: float) -> tuple[int, int]:
    """回收孤儿树。返回 (kept_dirty, pruned)。

    - 仅"过期且干净"的树可删；
    - 脏树保守保留。上限只统计"非活跃"树（最近写入早于 TTL 或 meta 缺失且目录
      mtime 过期）：活跃 child 的进行中树不计数（避免并发误拒），崩溃孤儿死树
      停止写入后自然计入（防 TTL 内不可见堆积）；
    - 无 meta 且目录 mtime 未过期的 lfl-child-*（worktree add 成功但 meta 写入
      前崩溃）计入 orphaned_nometa 报警值，不删不计数上限外的动作；
    - 无 meta 且不匹配本机制命名前缀的目录是既有 drill 树等非托管目录，不碰。
    """
    kept_dirty = 0
    pruned = 0
    nometa_stale = 0
    base = parent_root / ".worktrees"
    if not base.is_dir():
        return 0, 0
    now = time.time()
    for entry in sorted(base.iterdir()):
        if not entry.is_dir() or not entry.name.startswith(WORKTREE_PREFIX):
            continue
        meta = _read_meta(entry)
        if meta is None:
            # add 成功但 meta 写入前崩溃的残留：不删（无 base_head 无法证明
            # 安全）；过期才计数（未过期可能是刚 prepare 的进行中树）。
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                mtime = 0
            if now - mtime >= ttl_s:
                nometa_stale += 1
            continue
        active = now - _latest_touch(entry) < ttl_s
        if _tree_has_changes(entry):
            if not active:
                kept_dirty += 1
            continue
        created_at = float(meta.get("created_at", 0) or 0)
        if now - created_at < ttl_s:
            continue
        rc, _, _err = _git(str(parent_root), "worktree", "remove", "--force", str(entry))
        if rc == 0:
            pruned += 1
        else:
            # remove 失败（如锁）按脏保留，交给下次或人工。
            kept_dirty += 1
    return kept_dirty + nometa_stale, pruned


def prepare_worktree(
    child_id: str,
    *,
    parent_root: str,
    min_free_bytes: int = MIN_FREE_BYTES,
    max_kept_dirty: int = MAX_KEPT_DIRTY,
    orphan_ttl_s: float = ORPHAN_TTL_S,
) -> WorktreeLease:
    """创建隔离 worktree。任何前置条件不满足即抛 WorktreeIsolationError。"""
    if not parent_root:
        # contextvar 未设时空值绝不静默落到 CWD（会建错仓库的隔离树）。
        raise WorktreeIsolationError(
            "NO_WORKSPACE_ROOT", "parent_root 为空（current_workspace_root 未设置）"
        )
    parent = Path(parent_root).resolve()

    rc, out, err = _git(str(parent), "rev-parse", "--is-inside-work-tree")
    if rc != 0 or out != "true":
        raise WorktreeIsolationError(
            "NOT_GIT_WORKSPACE", f"parent_root 不是 git 工作树: {err or out or parent}"
        )

    try:
        free = shutil.disk_usage(parent).free
    except OSError as exc:  # 磁盘状态不可读时保守拒绝
        raise WorktreeIsolationError("DISK_LOW", f"disk_usage 失败: {exc}") from exc
    if free < min_free_bytes:
        raise WorktreeIsolationError(
            "DISK_LOW", f"可用 {free // (1024 * 1024)}MB < 阈值 {min_free_bytes // (1024 * 1024)}MB"
        )

    kept_dirty, _pruned = _sweep_orphans(parent, ttl_s=orphan_ttl_s)
    if kept_dirty >= max_kept_dirty:
        raise WorktreeIsolationError(
            "WORKTREE_LIMIT",
            f"非活跃孤儿树 {kept_dirty} >= 上限 {max_kept_dirty}；请人工核对 "
            f".worktrees/ 下 lfl-child-*（注意：最近仍在写入的树可能是运行中的 "
            f"child，不要删除）后重试",
        )

    # 保障 .worktrees/ 不进父提交（gitlink 污染）：若未被既有 ignore 覆盖，
    # 幂等写入 .git/info/exclude（本地仓库级，不动用户的 .gitignore）。
    _ensure_worktrees_excluded(parent)

    # tag 取 child_id 尾段（不截断，避免前缀相似目录名碰撞）；非白名单字符
    # 或超长时退哈希，杜绝路径注入。
    tail = child_id.rsplit("-", 1)[-1] or "x"
    if len(tail) <= 24 and re.fullmatch(r"[A-Za-z0-9_-]+", tail):
        tag = tail
    else:
        tag = hashlib.sha256(child_id.encode()).hexdigest()[:24]
    worktree_dir = parent / ".worktrees" / f"{WORKTREE_PREFIX}{tag}"
    if worktree_dir.exists():
        raise WorktreeIsolationError(
            "WORKTREE_LIMIT", f"目标目录已存在: {worktree_dir}"
        )

    rc, out, err = _git(
        str(parent), "worktree", "add", "--detach", str(worktree_dir), "HEAD"
    )
    if rc != 0:
        raise WorktreeIsolationError("GIT_ERROR", f"git worktree add 失败: {err or out}")

    rc, base_head, _ = _git(str(worktree_dir), "rev-parse", "HEAD")
    lease = WorktreeLease(
        path=str(worktree_dir), child_id=child_id, parent_root=str(parent)
    )
    # 原子写 meta（tmp + os.replace）：崩溃不留半写文件。写入失败则回滚已建树
    # 后以 GIT_ERROR 拒绝（无 meta 的树后续无法证明安全，不留半成品）。
    try:
        meta_tmp = worktree_dir / f"{META_FILENAME}.tmp"
        meta_tmp.write_text(
            json.dumps(
                {
                    "child_id": child_id,
                    "created_at": lease.created_at,
                    "parent_root": str(parent),
                    "base_head": base_head if rc == 0 else "",
                },
                ensure_ascii=False,
                indent=2,
            ),
            "utf-8",
        )
        os.replace(meta_tmp, _meta_path(worktree_dir))
    except OSError as exc:
        _git(str(parent), "worktree", "remove", "--force", str(worktree_dir))
        raise WorktreeIsolationError(
            "GIT_ERROR", f"meta 写入失败（已回滚 worktree）: {exc}"
        ) from exc
    return lease


def release_worktree(parent_root: str, worktree_path: str) -> ReleaseReport:
    """终态释放。脏树保守保留；任何失败如实报告，绝不影响既有终态传播。"""
    parent = Path(parent_root).resolve()
    wt = Path(worktree_path)
    if not wt.is_dir():
        return ReleaseReport(state="missing")
    rc, head, _ = _git(str(wt), "rev-parse", "HEAD")
    if _tree_has_changes(wt):
        # 保守保留：改动未合并（含已 commit 的 detached 产出），删除责任在父会话/人工。
        _rc, out, _ = _git(
            str(wt),
            "status",
            "--porcelain",
            "--ignored=matching",
            "--",
            ".",
            f":!{META_FILENAME}",
        )
        n = len(out.splitlines()) if _rc == 0 else -1
        return ReleaseReport(
            state="kept_dirty",
            dirty_files=n,
            head=head if rc == 0 else "",
        )
    # --force 仅删除机制自身留下的 untracked meta；用户改动已在上面被判脏并保留，
    # 不会因此被吞。
    rc, _out, err = _git(str(parent), "worktree", "remove", "--force", str(wt))
    if rc != 0:
        return ReleaseReport(
            state="remove_failed", detail=f"git worktree remove: {err}"
        )
    return ReleaseReport(state="removed")


def format_release_note(report: ReleaseReport, worktree_path: str) -> str:
    """生成附加到 child 终态报告的一行摘要（父会话据此决定是否人工合并）。"""
    if report.state == "removed":
        return f"[worktree] 已清理隔离树（干净）: {worktree_path}"
    if report.state == "kept_dirty":
        head_part = f"，HEAD={report.head}" if report.head else ""
        return (
            f"[worktree] 隔离树保留（{report.dirty_files} 个未提交/未跟踪/ignored 文件"
            f"或新提交{head_part}，未自动合并，需父会话显式处理）: {worktree_path}"
        )
    if report.state == "remove_failed":
        return f"[worktree] 清理失败（{report.detail}），树保留: {worktree_path}"
    return f"[worktree] 树不存在: {worktree_path}"
