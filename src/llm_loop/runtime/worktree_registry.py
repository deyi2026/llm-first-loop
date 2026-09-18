"""T0-A1/A2（2026-09-16）: worktree registry + 嵌套禁令.

背景（同日两起运维事故）:
- 会话环境残留 LFL_RESTART_CODE_ROOT 指向旧 worktree，重启脚本静默加载旧代码
  （防护见 restart_mirror.sh 的 CODE_ROOT 来源判定）；
- 在现役 code root 内部创建判基线 worktree，弄脏目录并阻断 dual-root clean 校验
  （本模块的嵌套检测）。

registry 是运维辅助事实源，不是承重墙：缺失/损坏时消费方一律 fail-open 降级到
既有校验并大声告警，绝不阻断重启。GC 策略（A4，9/19 再议）：registry 只标记
status，永不自动删除任何 worktree；删除始终是人工动作。
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

REGISTRY_RELPATH = Path("data/audit/worktree_registry.json")
GUARD_LOG_RELPATH = Path("data/audit/worktree_guard.log")


@dataclass
class WorktreeEntry:
    """单个 worktree 的注册表条目."""

    path: str
    head: str = ""
    branch: str = ""
    status: str = "legacy"  # legacy | active | retired（A4: 只标记不删除）
    protected: bool = False
    protected_reason: str = ""


def parse_worktrees(repo: Path) -> list[WorktreeEntry]:
    """解析 `git worktree list --porcelain`（主 worktree 恒为第一条）."""
    proc = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git worktree list 失败: {proc.stderr.strip()[:200]}")
    entries: list[WorktreeEntry] = []
    cur: dict = {}
    for line in proc.stdout.splitlines():
        if line.startswith("worktree "):
            if cur:
                entries.append(WorktreeEntry(**cur))
            cur = {"path": line.split(" ", 1)[1]}
        elif line.startswith("HEAD ") and cur:
            cur["head"] = line.split(" ", 1)[1]
        elif line.startswith("branch ") and cur:
            cur["branch"] = line.split(" ", 1)[1]
    if cur:
        entries.append(WorktreeEntry(**cur))
    return entries


def find_nested(entries: list[WorktreeEntry]) -> list[tuple[WorktreeEntry, WorktreeEntry]]:
    """返回 (outer, inner) 嵌套对.

    仅 linked worktree 作为 outer（主 worktree 下挂 .worktrees/ 是既定布局，
    不算嵌套）；inner 是严格位于 outer 目录内部的另一 worktree。
    """
    pairs: list[tuple[WorktreeEntry, WorktreeEntry]] = []
    for outer in entries[1:]:
        op = Path(outer.path)
        for inner in entries:
            if inner is outer or inner.path == outer.path:
                continue
            ip = Path(inner.path)
            if op in ip.parents:
                pairs.append((outer, inner))
    return pairs


def load_registry(runtime_root: Path) -> dict | None:
    """fail-open 读取 registry：缺失/损坏返回 None（消费方降级既有校验）."""
    path = Path(runtime_root) / REGISTRY_RELPATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("[worktree-registry] registry 损坏，fail-open 忽略: %s", exc)
        return None
    return data if isinstance(data, dict) else None


def save_registry(runtime_root: Path, registry: dict) -> None:
    """原子写（tmp + os.replace）；失败仅告警不抛（registry 非承重）."""
    path = Path(runtime_root) / REGISTRY_RELPATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning("[worktree-registry] registry 写失败（不阻断）: %s", exc)


def append_guard_log(runtime_root: Path, event: dict) -> None:
    """A2 审计：嵌套拒绝/检测事件落 data/audit/worktree_guard.log（best-effort）."""
    path = Path(runtime_root) / GUARD_LOG_RELPATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        event = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **event}
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("[worktree-registry] guard 审计写失败（不阻断）: %s", exc)


def production_code_root(runtime_root: Path) -> str | None:
    """以 runtime_manifest.json 的 workspace_root 为现役 code root 事实源."""
    try:
        manifest = json.loads(
            (Path(runtime_root) / "data/runtime/runtime_manifest.json").read_text(encoding="utf-8")
        )
        root = manifest.get("workspace_root")
        return str(root) if root else None
    except (OSError, json.JSONDecodeError):
        return None


def bootstrap(
    runtime_root: Path,
    repo: Path,
    *,
    protected_paths: list[str] | None = None,
    rollback_candidates: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """初始化/刷新 registry：全部 worktree 落表，默认标 legacy；protected 只来自
    显式参数 + 现役 code root（runtime_manifest）；回滚候选单列。保留旧表中
    retired 状态（A4 人工标记不被 bootstrap 覆盖）。
    """
    entries = parse_worktrees(Path(repo))
    prev = load_registry(Path(runtime_root)) or {}
    prev_status = {
        str(e.get("path")): str(e.get("status"))
        for e in prev.get("entries", [])
        if isinstance(e, dict)
    }
    if protected_paths is None:
        manifest_root = production_code_root(Path(runtime_root))
        protected_paths = [manifest_root] if manifest_root else []
    protected_set = {str(Path(p).resolve()) for p in protected_paths if p}
    rollback_set = {str(Path(p).resolve()) for p in (rollback_candidates or []) if p}

    out: list[WorktreeEntry] = []
    for e in entries:
        rp = str(Path(e.path).resolve())
        if rp in protected_set:
            e.status, e.protected, e.protected_reason = "active", True, "production code root"
        elif rp in rollback_set:
            e.status, e.protected, e.protected_reason = "active", True, "rollback candidate"
        elif prev_status.get(e.path) == "retired":
            e.status = "retired"
        out.append(e)

    nested = find_nested(out)
    registry = {
        "version": 1,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "repo": str(Path(repo).resolve()),
        "counts": {
            "total": len(out),
            "protected": sum(1 for x in out if x.protected),
            "legacy": sum(1 for x in out if x.status == "legacy"),
            "retired": sum(1 for x in out if x.status == "retired"),
            "nested_pairs": len(nested),
        },
        "entries": [asdict(x) for x in out],
    }
    if nested:
        registry["nested"] = [
            {"outer": o.path, "inner": i.path} for o, i in nested
        ]
        append_guard_log(
            Path(runtime_root),
            {"event": "bootstrap_detected_nested", "pairs": registry["nested"]},
        )
    if not dry_run:
        save_registry(Path(runtime_root), registry)
    return registry


def check_add_target(
    repo: Path, target: Path, runtime_root: Path | None = None
) -> tuple[bool, str]:
    """A2 嵌套禁令：拟创建的 worktree 路径不得位于任何既有 linked worktree 内，
    也不得把既有 worktree 包进自己内部。拒绝时写审计并返回 (False, reason)。
    """
    try:
        entries = parse_worktrees(Path(repo))
    except RuntimeError as exc:
        return True, f"worktree 枚举失败，放行（fail-open）: {exc}"
    tp = Path(target).resolve()
    for outer in entries[1:]:
        op = Path(outer.path)
        if op in tp.parents:
            reason = f"嵌套禁令: {tp} 位于 linked worktree {op} 内部（2026-09-16 事故形态）"
            if runtime_root is not None:
                append_guard_log(
                    Path(runtime_root),
                    {"event": "nested_add_rejected", "target": str(tp), "outer": str(op)},
                )
            return False, reason
    for e in entries:
        ep = Path(e.path)
        if tp != ep and tp in ep.parents:
            reason = f"嵌套禁令: {tp} 会包裹既有 worktree {ep}"
            if runtime_root is not None:
                append_guard_log(
                    Path(runtime_root),
                    {"event": "wrapping_add_rejected", "target": str(tp), "inner": str(ep)},
                )
            return False, reason
    return True, "ok"
