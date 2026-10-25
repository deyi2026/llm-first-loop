#!/usr/bin/env python3
"""P1-3: 默认工作区迁出代码根（~/lfl-workspace）——三段式迁移脚本.

设计依据 docs/P1-3-实施方案-2026-10-25.md §5。统一入口、五子命令：

  backup    Phase 1 快照（纯读源）：workspaces.json/.lock、sessions/<旧键>/、
            sessions/.identity/、artifacts/records/<旧桶>/ →
            .backup/workspace-migration-<ts>/，逐文件 SHA256SUMS + 计数清单
            （manifest.json 同时记录未复制的其它分区 stats，供 verify 对照）。
  rehearse  Phase 2 镜像演练：同源集合复制到 /tmp/lfl-migration-rehearsal-<ts>/data
            （真实 data/ 只读），在镜像上以与实迁同一核心函数执行迁移并做六项
            校验（分区计数/账本改写/注册表/冲突注入/幂等/current）。未 PASS
            禁止实迁。
  migrate   Phase 3 实迁（仅停机窗口）：建新根(0700) → 分区原子改名 →
            .identity owner 改写 → 工件记录桶复制 → 注册表 register+switch。
            每步独立幂等（§5.6 三态判定），失败可安全重跑。
  rollback  就地逆向：分区改名回退、owner 逆向改写、current 切回旧代码根条目
            （新条目保留不删——store.remove 不删数据；新工件桶保留，旧桶未动）。
  verify    迁移后独立核对：current=新键、新分区计数/字节与备份清单一致、
            账本无残留旧键 owner、新旧桶并存、其它分区 mtime/计数未动、
            新根存在且 0700。

约定：
  - 旧根/新根：默认旧=脚本所在仓库根；新=LFL_DEFAULT_WORKSPACE_ROOT env
    （缺省 ~/lfl-workspace）。分区键/工件桶由 workspace_key/_workspace_bucket
    现算（防手误），不用硬编码常量。
  - 冲突（同名异内容）一律 WorkspaceMigrationConflictError：两份不同内容程序
    不自动裁决，显式报错人工介入（store.py 同语义）。
  - 审计：data/audit/workspace_migration/<ts>.json，每步追加
    {step, ts, 输入/输出/计数/耗时/结果}；--audit-file 显式传路径时同一次
    迁移战役的各阶段可共用一份审计文件。
  - migrate/rollback 需 --yes 显式确认。Phase 0 预检（各阶段共用）：三服务
    manifest pid 不存活、web 端口无监听、feishu 心跳 pid 不存活、旧分区无活跃
    *.run.lock、磁盘余量≥2×源分区、新根存在或可建 0700。
  - rehearse 的唯一非镜像写副作用：ensure_target_root 在真实新根建 0700 空占位
    目录（与 migrate 步骤1同一语义，幂等；register 需目录存在）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import stat as stat_mod
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from llm_loop.workspace.artifacts import _workspace_bucket, workspace_scope  # noqa: E402
from llm_loop.workspace.store import (  # noqa: E402
    WorkspaceMigrationConflictError,
    WorkspaceStore,
    workspace_key,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_NEW_ROOT = "~/lfl-workspace"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _ts_compact() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")


# ── 通用统计/写辅助 ──


def _dir_stats(path: Path) -> dict[str, int]:
    """目录文件数与总字节（rglob 全深度，只计普通文件）."""
    files = 0
    total = 0
    if path.is_dir():
        for p in path.rglob("*"):
            if p.is_file():
                files += 1
                total += p.stat().st_size
    return {"files": files, "bytes": total}


def _file_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write_bytes(p: Path, payload: bytes) -> None:
    tmp = p.with_name(p.name + ".tmp-migrate")
    tmp.write_bytes(payload)
    os.replace(tmp, p)


def _atomic_write_json(p: Path, obj: dict) -> None:
    _atomic_write_bytes(p, json.dumps(obj, ensure_ascii=False).encode("utf-8"))


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # 存在但属他人——按存活计
    except OSError:
        return False
    return True


class AuditLog:
    """data/audit/workspace_migration/<ts>.json 追加式步骤审计（原子写）."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.records: list[dict] = []
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    self.records = loaded
            except (OSError, json.JSONDecodeError):
                self.records = []  # 损坏审计不阻塞迁移；新记录继续追加

    def append(self, step: str, **facts: object) -> None:
        record: dict[str, object] = {"step": step, "ts": _now_iso()}
        record.update(facts)
        self.records.append(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(self.path, self.records)


# ── Phase 0 预检（各阶段共用）──


def _nearest_existing_ancestor(path: Path) -> Path:
    cur = path
    while not cur.exists() and cur.parent != cur:
        cur = cur.parent
    return cur


def phase0_precheck(
    data_dir: Path, old_key: str, new_root: Path, web_port: int, *, online: bool = False
) -> list[str]:
    """停机与前置条件核对；返回失败清单（空=通过）。纯读，不改任何状态.

    online=True（backup/rehearse 专用，R4 2026-10-25）：跳过 1-4 项停机类检查
    （服务存活/端口/心跳/run.lock）——backup 是纯读复制、rehearse 只在镜像上写，
    均可安全运行于服务在线状态（设计 §5.1 backup=纯读；排期计划要求演练在
    停机窗口前完成）。保留磁盘余量与新根检查。migrate/rollback 恒用全检。
    """
    failures: list[str] = []
    # 1) 三服务 manifest pid 不存活
    if not online:
        for svc in ("web", "feishu", "learning"):
            mf = data_dir / "runtime" / f"runtime_manifest.{svc}.json"
            if not mf.exists():
                continue
            try:
                pid = int(json.loads(mf.read_text(encoding="utf-8")).get("pid", 0))
            except (OSError, json.JSONDecodeError, ValueError):
                failures.append(f"{svc} manifest 不可读: {mf}")
                continue
            if pid > 0 and _pid_alive(pid):
                failures.append(f"{svc} 进程仍在运行 (pid {pid})——须停机窗口执行")
        # 2) web 端口无监听
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", web_port)) == 0:
                failures.append(f"端口 {web_port} 有进程监听——web 可能未停")
        # 3) feishu 心跳 pid 不存活
        hb = data_dir / "feishu_heartbeat.json"
        if hb.exists():
            try:
                pid = int(json.loads(hb.read_text(encoding="utf-8")).get("pid", 0))
                if pid > 0 and _pid_alive(pid):
                    failures.append(f"feishu 心跳 pid 仍存活 (pid {pid})")
            except (OSError, json.JSONDecodeError, ValueError):
                pass  # 心跳损坏按无新鲜 pid 处理，manifest/端口双探针兜底
        # 4) 旧分区无活跃 run 锁（正在运行的会话钉住分区；仅停机类操作需要）
        #    R4(P0-1 修复, 2026-10-25): run.lock 文件是稳定墓碑设计（存在≠活跃），
        #    活跃性由 flock 判定——复用权威实现 resources.foreground.active_run_locks
        #    （此前按文件存在计数 1755 个必误拦，见编排审核报告）。
        from llm_loop.resources.foreground import active_run_locks
        old_partition = data_dir / "sessions" / old_key
        if old_partition.is_dir():
            active = active_run_locks(old_partition)
            if active:
                failures.append(
                    f"旧分区存在 {len(active)} 个活跃(flock) *.run.lock（示例 {active[0]}）"
                )
    # 5) 磁盘余量 ≥ 2×源分区（备份+桶复制峰值）
    old_partition = data_dir / "sessions" / old_key
    if old_partition.is_dir():
        need = 2 * _dir_stats(old_partition)["bytes"]
        free = shutil.disk_usage(data_dir).free
        if free < need:
            failures.append(f"磁盘余量不足: free={free} < 2×源分区={need}")
    # 6) 新根存在或可创建（0700）
    if new_root.exists():
        if not new_root.is_dir():
            failures.append(f"新根路径存在但不是目录: {new_root}")
    else:
        ancestor = _nearest_existing_ancestor(new_root)
        if not os.access(ancestor, os.W_OK):
            failures.append(f"新根不可创建（最近存在祖先不可写）: {ancestor}")
    return failures


# ── 核心迁移函数（rehearse/migrate/rollback 复用同一代码路径）──


def ensure_target_root(new_root: Path) -> dict[str, object]:
    """步骤1: 新根存在或创建（0700，幂等；不改动已存在目录权限）."""
    existed = new_root.is_dir()
    if not existed and not new_root.exists():
        new_root.mkdir(parents=True, mode=0o700)
    mode = stat_mod.S_IMODE(new_root.stat().st_mode)
    return {"path": str(new_root), "existed": existed, "mode": oct(mode)}


def rename_sessions_partition(sessions_root: Path, old_key: str, new_key: str) -> dict[str, object]:
    """步骤2: 分区原子改名（同卷 rename，瞬时；幂等三态判定 §5.6）.

    源在目标不在=待办改名；源不在目标在=已完成；都在→逐文件比对（同内容=完成，
    异内容=WorkspaceMigrationConflictError）；都不在=前置状态非法。
    """
    src = sessions_root / old_key
    dst = sessions_root / new_key
    if src.is_dir() and not dst.exists():
        os.rename(src, dst)
        return {"action": "renamed", "from": str(src), "to": str(dst), **_dir_stats(dst)}
    if not src.exists() and dst.is_dir():
        return {"action": "already_done", "from": str(src), "to": str(dst), **_dir_stats(dst)}
    if src.is_dir() and dst.is_dir():
        src_files = {p.relative_to(src): p for p in src.rglob("*") if p.is_file()}
        dst_files = {p.relative_to(dst): p for p in dst.rglob("*") if p.is_file()}
        only_src = sorted(set(src_files) - set(dst_files), key=str)
        only_dst = sorted(set(dst_files) - set(src_files), key=str)
        if only_src or only_dst:
            raise WorkspaceMigrationConflictError(
                f"分区改名冲突: 文件集不一致 only_src={only_src[:5]} only_dst={only_dst[:5]}"
            )
        for rel, sp in src_files.items():
            if sp.read_bytes() != dst_files[rel].read_bytes():
                raise WorkspaceMigrationConflictError(
                    f"分区改名冲突: {sp} 与 {dst / rel} 内容不同"
                )
        return {"action": "already_done", "from": str(src), "to": str(dst), **_dir_stats(dst)}
    raise WorkspaceMigrationConflictError(
        f"分区改名前置状态非法（源/目标均不存在）: src={src} dst={dst}"
    )


def rewrite_identity_owners(identity_root: Path, old_key: str, new_key: str) -> dict[str, object]:
    """步骤3: .identity 账本 owner 改写（保留 claimed_at；幂等按 owner 值判定）."""
    scanned = 0
    rewritten = 0
    others: dict[str, int] = {}
    if not identity_root.is_dir():
        return {"scanned": 0, "rewritten": 0, "other_owners": others,
                "identity_root": str(identity_root)}
    for p in sorted(identity_root.glob("*.json")):
        scanned += 1
        try:
            record = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkspaceMigrationConflictError(f"账本文件不可读/损坏，拒绝改写: {p}: {exc}") from exc
        if not isinstance(record, dict):
            raise WorkspaceMigrationConflictError(f"账本记录非对象，拒绝改写: {p}")
        owner = record.get("owner")
        if owner == old_key:
            record["owner"] = new_key
            _atomic_write_json(p, record)
            rewritten += 1
        else:
            others[str(owner)] = others.get(str(owner), 0) + 1
    return {"scanned": scanned, "rewritten": rewritten, "other_owners": others,
            "identity_root": str(identity_root)}


def copy_artifact_records(records_root: Path, old_bucket: str, new_bucket: str) -> dict[str, object]:
    """步骤4: 工件记录桶复制（record 内 canonical_path 保留旧绝对路径——诚实保留，
    workspace_path_state 如实报 diverged；字节仍在全局 blobs，历史引用不断链）.

    幂等按记录文件存在判定；同名异内容=冲突（不静默覆盖）。
    """
    src = records_root / old_bucket
    dst = records_root / new_bucket
    if not src.is_dir():
        return {"action": "no_source", "copied": 0, "skipped_existing": 0,
                "from": str(src), "to": str(dst)}
    copied = 0
    skipped = 0
    for p in sorted(src.rglob("*")):
        if not p.is_file():
            continue
        target = dst / p.relative_to(src)
        if target.exists():
            if target.read_bytes() != p.read_bytes():
                raise WorkspaceMigrationConflictError(
                    f"工件记录桶冲突: {p} 与 {target} 内容不同"
                )
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
        copied += 1
    return {"action": "copied", "copied": copied, "skipped_existing": skipped,
            "from": str(src), "to": str(dst)}


def switch_registry(data_dir: Path, new_root: Path) -> dict[str, object]:
    """步骤5: 注册表切换（WorkspaceStore.register + switch；幂等按 current 值判定）."""
    store = WorkspaceStore(data_dir)
    ws = store.register(str(new_root))
    current = store.get_current()
    if current is not None and current.id == ws.id:
        return {"action": "already_current", "current": ws.id, "path": ws.path}
    store.switch(ws.id)
    return {"action": "switched", "current": ws.id, "path": ws.path}


def run_core_migration(
    data_dir: Path,
    *,
    old_key: str,
    new_key: str,
    old_bucket: str,
    new_bucket: str,
    new_root: Path,
    audit: AuditLog,
) -> dict[str, dict[str, object]]:
    """按序执行步骤1-5（每步独立计时+审计）；rehearse/migrate 复用本入口."""
    results: dict[str, dict[str, object]] = {}
    sessions_root = data_dir / "sessions"
    steps: list[tuple[str, Callable[..., dict[str, object]], tuple[object, ...]]] = [
        ("ensure_target_root", ensure_target_root, (new_root,)),
        ("rename_sessions_partition", rename_sessions_partition, (sessions_root, old_key, new_key)),
        ("rewrite_identity_owners", rewrite_identity_owners,
         (data_dir / "sessions" / ".identity", old_key, new_key)),
        ("copy_artifact_records", copy_artifact_records,
         (data_dir / "artifacts" / "records", old_bucket, new_bucket)),
        ("switch_registry", switch_registry, (data_dir, new_root)),
    ]
    for step, fn, fargs in steps:
        t0 = time.monotonic()
        outcome = fn(*fargs)
        elapsed = round(time.monotonic() - t0, 3)
        results[step] = outcome
        audit.append(step, result=outcome, elapsed_s=elapsed)
    return results


# ── 源集合（backup/rehearse 共用的复制清单）──


def _backup_items(data_dir: Path, old_key: str, old_bucket: str) -> list[tuple[Path, str]]:
    """(源路径, 目标内相对路径) 清单；源缺失项由调用方如实记录."""
    return [
        (data_dir / "workspaces.json", "workspaces.json"),
        (data_dir / "workspaces.lock", "workspaces.lock"),
        (data_dir / "sessions" / old_key, f"sessions/{old_key}"),
        (data_dir / "sessions" / ".identity", "sessions/.identity"),
        (data_dir / "artifacts" / "records" / old_bucket, f"artifacts/records/{old_bucket}"),
    ]


def _copy_backup_set(data_dir: Path, dest_root: Path, old_key: str, old_bucket: str) -> dict[str, object]:
    """把源集合复制到 dest_root（纯读源）；返回逐项计数（含缺失项）."""
    manifest_items: dict[str, object] = {}
    for src, rel in _backup_items(data_dir, old_key, old_bucket):
        if not src.exists():
            manifest_items[rel] = {"exists": False}
            continue
        target = dest_root / rel
        if src.is_dir():
            shutil.copytree(src, target)
            manifest_items[rel] = {"exists": True, **_dir_stats(src)}
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            manifest_items[rel] = {"exists": True, "bytes": src.stat().st_size}
    return manifest_items


def _write_sha_sums(dest_root: Path) -> dict[str, int]:
    """逐文件 SHA256SUMS（sha256 + 相对路径）；纯读 dest_root."""
    lines: list[str] = []
    total = 0
    for p in sorted(dest_root.rglob("*")):
        if p.is_file() and p.name not in ("SHA256SUMS", "manifest.json"):
            total += 1
            lines.append(f"{_file_sha256(p)}  {p.relative_to(dest_root).as_posix()}")
    (dest_root / "SHA256SUMS").write_text(
        "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
    )
    return {"files_hashed": total}


def _other_partitions_snapshot(data_dir: Path, old_key: str) -> dict[str, dict[str, float]]:
    """sessions/ 下其它分区（research/sy/worktrees 等）的计数/mtime 快照
    （不复制，仅供 verify 对照"未动"）."""
    snapshot: dict[str, dict[str, float]] = {}
    sessions = data_dir / "sessions"
    if not sessions.is_dir():
        return snapshot
    for p in sorted(sessions.iterdir()):
        if p.is_dir() and p.name not in (old_key, ".identity"):
            stats = _dir_stats(p)
            snapshot[p.name] = {
                "files": float(stats["files"]),
                "bytes": float(stats["bytes"]),
                "mtime": p.stat().st_mtime,
            }
    return snapshot


def _owner_distribution(identity_root: Path) -> dict[str, int]:
    dist: dict[str, int] = {}
    if not identity_root.is_dir():
        return dist
    for p in identity_root.glob("*.json"):
        try:
            owner = json.loads(p.read_text(encoding="utf-8")).get("owner")
        except (OSError, json.JSONDecodeError):
            continue
        key = str(owner)
        dist[key] = dist.get(key, 0) + 1
    return dist


def _registry_snapshot(data_dir: Path) -> dict[str, object]:
    try:
        store = WorkspaceStore(data_dir)
        current = store.get_current()
        return {
            "current": current.id if current else None,
            "active": sorted(w.id for w in store.list()),
        }
    except Exception as exc:  # noqa: BLE001 — 快照失败如实记录，不阻塞演练
        return {"error": f"{type(exc).__name__}: {exc}"}


# ── 演练六项校验（§5 Phase 2）──


def run_rehearsal_checks(
    mirror_data: Path,
    *,
    source_partition_stats: dict[str, int],
    old_key: str,
    new_key: str,
    old_bucket: str,
    new_bucket: str,
    new_root: Path,
    probe_root: Path,
    pre_registry_retired: list[str],
) -> tuple[bool, dict[str, object]]:
    """在镜像 data 上执行核心迁移并做六项校验；返回 (PASS, 报告)."""
    checks: dict[str, object] = {}
    identity_root = mirror_data / "sessions" / ".identity"
    pre_owners = _owner_distribution(identity_root)
    pre_registry = _registry_snapshot(mirror_data)
    # R5(2026-10-25 实测): 校验 1 基准=镜像内快照（复制后、迁移前统计），非调用方
    # 复制前统计的源——真实 data/ 是活数据（活跃会话持续写入），源统计与复制
    # 之间存在 TOCTOU 竞态（实测 5320 文件一致但字节差 3058）。镜像内自一致
    # （改名前后镜像统计相等）才是"迁移逻辑保真"的判定；源→镜像复制保真由
    # Phase 1 backup 的逐文件 SHA256SUMS 机制独立保证。
    mirror_pre_stats = _dir_stats(mirror_data / "sessions" / old_key)

    audit_stub = AuditLog(mirror_data.parent / "rehearsal-audit.json")
    results = run_core_migration(
        mirror_data,
        old_key=old_key,
        new_key=new_key,
        old_bucket=old_bucket,
        new_bucket=new_bucket,
        new_root=new_root,
        audit=audit_stub,
    )

    # 1) 分区改名后文件数与总字节与镜像快照一致（源统计仅作参考：活数据有竞态）
    post_stats = _dir_stats(mirror_data / "sessions" / new_key)
    checks["partition_stats_match"] = {
        "pass": post_stats == mirror_pre_stats,
        "baseline": "mirror_snapshot_before_migration",
        "mirror_before": mirror_pre_stats,
        "mirror": post_stats,
        "source_reference": source_partition_stats,
        "source_reference_note": "活数据源，统计时刻≠复制时刻，仅参考不判定",
    }
    # 2) .identity：old_key 全部改写为 new_key；其它 owner 逐一不变
    post_owners = _owner_distribution(identity_root)
    expected = dict(pre_owners)
    expected[new_key] = expected.pop(new_key, 0) + expected.pop(old_key, 0)
    checks["identity_rewrite"] = {
        "pass": post_owners == expected and old_key not in post_owners,
        "pre": pre_owners,
        "post": post_owners,
        "rewritten": results["rewrite_identity_owners"]["rewritten"],
    }
    # 3) 镜像注册表：新条目已注册、current=新键、旧条目仍在 active、retired 不变
    post_registry = _registry_snapshot(mirror_data)
    active = post_registry.get("active", [])
    retired_now: list[str] = []
    try:
        reg = json.loads((mirror_data / "workspaces.json").read_text(encoding="utf-8"))
        retired_now = sorted(str(x) for x in reg.get("retired", []))
    except (OSError, json.JSONDecodeError):
        retired_now = []
    checks["registry_state"] = {
        "pass": (
            post_registry.get("current") == new_key
            and new_key in active
            and old_key in active
            and retired_now == pre_registry_retired
        ),
        "pre": pre_registry,
        "post": post_registry,
        "retired_pre": pre_registry_retired,
        "retired_post": retired_now,
    }
    # 4) 冲突注入：预置同名异内容文件 → 必须 WorkspaceMigrationConflictError
    conflict_ok = False
    conflict_detail: str = ""
    probe_sessions = probe_root / "sessions"
    (probe_sessions / old_key).mkdir(parents=True, exist_ok=True)
    (probe_sessions / new_key).mkdir(parents=True, exist_ok=True)
    (probe_sessions / old_key / "conflict.json").write_text('{"owner":"x"}', encoding="utf-8")
    (probe_sessions / new_key / "conflict.json").write_text('{"owner":"y"}', encoding="utf-8")
    try:
        rename_sessions_partition(probe_sessions, old_key, new_key)
        conflict_detail = "未抛出冲突错误（同名异内容被静默接受）"
    except WorkspaceMigrationConflictError as exc:
        conflict_ok = True
        conflict_detail = str(exc)
    checks["conflict_injection"] = {"pass": conflict_ok, "detail": conflict_detail}
    # 5) 幂等：同一命令连跑两次，第二次改名/改写计数为 0 且无异常
    idem_ok = True
    idem_detail: dict[str, object] = {}
    try:
        second = run_core_migration(
            mirror_data,
            old_key=old_key,
            new_key=new_key,
            old_bucket=old_bucket,
            new_bucket=new_bucket,
            new_root=new_root,
            audit=audit_stub,
        )
        idem_detail = {
            "rename_action": second["rename_sessions_partition"]["action"],
            "identity_rewritten": second["rewrite_identity_owners"]["rewritten"],
            "records_copied": second["copy_artifact_records"]["copied"],
            "registry_action": second["switch_registry"]["action"],
        }
        idem_ok = (
            second["rename_sessions_partition"]["action"] == "already_done"
            and second["rewrite_identity_owners"]["rewritten"] == 0
            and second["copy_artifact_records"]["copied"] == 0
            and second["switch_registry"]["action"] == "already_current"
        )
    except Exception as exc:  # noqa: BLE001 — 演练报告如实记录异常
        idem_ok = False
        idem_detail = {"error": f"{type(exc).__name__}: {exc}"}
    checks["idempotent_rerun"] = {"pass": idem_ok, **idem_detail}
    # 6) WorkspaceStore 断言 get_current().path 指向新根
    store = WorkspaceStore(mirror_data)
    current = store.get_current()
    checks["current_points_to_new_root"] = {
        "pass": current is not None and Path(current.path) == new_root,
        "current_path": current.path if current else None,
        "expect": str(new_root),
    }
    overall = all(
        bool(v.get("pass")) for v in checks.values() if isinstance(v, dict)  # type: ignore[union-attr]
    )
    return overall, {"pass": overall, "checks": checks, "migration_results": results}


# ── 子命令 ──


def cmd_backup(args: argparse.Namespace) -> int:
    data_dir: Path = args.data_dir
    failures = phase0_precheck(data_dir, args.old_key, args.new_root, args.web_port, online=True)
    audit = AuditLog(args.audit_file)
    audit.append("backup.precheck", data_dir=str(data_dir), old_key=args.old_key,
                 failures=failures, result="pass" if not failures else "fail")
    if failures:
        for f in failures:
            print(f"✗ [backup] 预检失败: {f}", file=sys.stderr)
        return 2
    dest_root: Path = args.backup_root / f"workspace-migration-{_ts_compact()}"
    if dest_root.exists():
        print(f"✗ [backup] 备份目录已存在: {dest_root}", file=sys.stderr)
        return 2
    t0 = time.monotonic()
    items = _copy_backup_set(data_dir, dest_root, args.old_key, args.old_bucket)
    sums = _write_sha_sums(dest_root)
    manifest = {
        "ts": _now_iso(),
        "data_dir": str(data_dir),
        "old_key": args.old_key,
        "new_key": args.new_key,
        "old_bucket": args.old_bucket,
        "new_bucket": args.new_bucket,
        "items": items,
        "other_partitions": _other_partitions_snapshot(data_dir, args.old_key),
    }
    _atomic_write_json(dest_root / "manifest.json", manifest)
    elapsed = round(time.monotonic() - t0, 3)
    audit.append("backup.done", dest=str(dest_root), items=items, sha_sums=sums,
                 elapsed_s=elapsed, result="ok")
    print(f"✅ [backup] 快照完成: {dest_root} ({sums['files_hashed']} 文件, {elapsed}s)")
    print(f"   审计: {audit.path}")
    return 0


def cmd_rehearse(args: argparse.Namespace) -> int:
    data_dir: Path = args.data_dir
    # R3(准入审核第九轮 P2-4): 演练按 runbook 在停机窗口前执行（真实 data/ 只读，
    # 仅 backup 副本被复制到镜像），不需要服务全停。R4(2026-10-25): 改用参数化
    # online=True（跳过服务/端口/心跳/run.lock 停机类检查）——原字符串过滤
    # （"服务"/"port" 子串）与实际消息文本（"进程"/"端口"）不匹配，运行态恒误拦。
    # 保留磁盘余量与新根检查。migrate/rollback 仍走完整 Phase 0。
    failures = phase0_precheck(
        data_dir, args.old_key, args.new_root, args.web_port, online=True
    )
    audit = AuditLog(args.audit_file)
    audit.append("rehearse.precheck", data_dir=str(data_dir), failures=failures,
                 result="pass" if not failures else "fail",
                 skipped_service_checks="online=True（1-4 项停机类检查跳过）")
    if failures:
        for f in failures:
            print(f"✗ [rehearse] 预检失败: {f}", file=sys.stderr)
        return 2
    source_stats = _dir_stats(data_dir / "sessions" / args.old_key)
    mirror_root = Path(tempfile.mkdtemp(prefix="lfl-migration-rehearsal-"))
    try:
        mirror_data = mirror_root / "data"
        try:
            reg = json.loads((data_dir / "workspaces.json").read_text(encoding="utf-8"))
            retired = sorted(str(x) for x in reg.get("retired", []))
        except (OSError, json.JSONDecodeError):
            retired = []
        probe_root = mirror_root / "probe"
        probe_root.mkdir()
        _copy_backup_set(data_dir, mirror_data, args.old_key, args.old_bucket)
        overall, report = run_rehearsal_checks(
            mirror_data,
            source_partition_stats=source_stats,
            old_key=args.old_key,
            new_key=args.new_key,
            old_bucket=args.old_bucket,
            new_bucket=args.new_bucket,
            new_root=args.new_root,
            probe_root=probe_root,
            pre_registry_retired=retired,
        )
    finally:
        shutil.rmtree(mirror_root, ignore_errors=True)
    audit.append("rehearse.report", source_partition_stats=source_stats, report=report,
                 result="PASS" if overall else "FAIL")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("✅ [rehearse] 演练 PASS" if overall else "✗ [rehearse] 演练 FAIL——禁止实迁",
          file=sys.stderr)
    return 0 if overall else 1


def cmd_migrate(args: argparse.Namespace) -> int:
    data_dir: Path = args.data_dir
    failures = phase0_precheck(data_dir, args.old_key, args.new_root, args.web_port)
    audit = AuditLog(args.audit_file)
    audit.append("migrate.precheck", data_dir=str(data_dir), failures=failures,
                 result="pass" if not failures else "fail")
    if failures:
        for f in failures:
            print(f"✗ [migrate] 预检失败: {f}", file=sys.stderr)
        return 2
    if not args.yes:
        print("✗ [migrate] 实迁需 --yes 显式确认（停机窗口内执行）", file=sys.stderr)
        return 2
    before = {
        "registry": _registry_snapshot(data_dir),
        "old_partition": _dir_stats(data_dir / "sessions" / args.old_key),
        "owners": _owner_distribution(data_dir / "sessions" / ".identity"),
    }
    audit.append("migrate.before", **before)
    results = run_core_migration(
        data_dir,
        old_key=args.old_key,
        new_key=args.new_key,
        old_bucket=args.old_bucket,
        new_bucket=args.new_bucket,
        new_root=args.new_root,
        audit=audit,
    )
    after = {
        "registry": _registry_snapshot(data_dir),
        "new_partition": _dir_stats(data_dir / "sessions" / args.new_key),
        "owners": _owner_distribution(data_dir / "sessions" / ".identity"),
    }
    audit.append("migrate.after", results=results, **after)
    print(json.dumps({"results": results, "before": before, "after": after},
                     ensure_ascii=False, indent=2))
    print(f"✅ [migrate] 完成（审计: {audit.path}）。请运行 verify 子命令独立核对。")
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    data_dir: Path = args.data_dir
    failures = phase0_precheck(data_dir, args.old_key, args.new_root, args.web_port)
    audit = AuditLog(args.audit_file)
    audit.append("rollback.precheck", data_dir=str(data_dir), failures=failures,
                 result="pass" if not failures else "fail")
    if failures:
        for f in failures:
            print(f"✗ [rollback] 预检失败: {f}", file=sys.stderr)
        return 2
    if not args.yes:
        print("✗ [rollback] 回滚需 --yes 显式确认", file=sys.stderr)
        return 2
    sessions_root = data_dir / "sessions"
    steps: list[tuple[str, dict[str, object], float]] = []

    def _run(step: str, fn: Callable[..., dict[str, object]], *fargs: object) -> None:
        t0 = time.monotonic()
        outcome = fn(*fargs)
        elapsed = round(time.monotonic() - t0, 3)
        steps.append((step, outcome, elapsed))
        audit.append(f"rollback.{step}", result=outcome, elapsed_s=elapsed)

    # 逆向：新键分区 → 旧键分区（幂等三态同语义）
    _run("rename_back", rename_sessions_partition, sessions_root, args.new_key, args.old_key)
    # 账本 owner 逆向改写
    _run("identity_rewrite_back", rewrite_identity_owners,
         data_dir / "sessions" / ".identity", args.new_key, args.old_key)
    # current 切回旧代码根条目（register 幂等；新条目保留不删）
    _run("switch_registry_back", switch_registry, data_dir, args.old_root)
    # 新工件桶保留（旧桶未动；历史引用两侧均可水合）
    summary = {name: {"result": outcome, "elapsed_s": elapsed}
               for name, outcome, elapsed in steps}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"✅ [rollback] 完成（审计: {audit.path}）")
    return 0


def _find_latest_backup(backup_root: Path) -> Path | None:
    if not backup_root.is_dir():
        return None
    candidates = sorted(backup_root.glob("workspace-migration-*"))
    return candidates[-1] if candidates else None


def cmd_verify(args: argparse.Namespace) -> int:
    data_dir: Path = args.data_dir
    audit = AuditLog(args.audit_file)
    backup_dir: Path | None = args.backup_dir or _find_latest_backup(args.backup_root)
    checks: dict[str, object] = {}

    # 1) current = 新键
    current = WorkspaceStore(data_dir).get_current()
    checks["current_is_new_key"] = {
        "pass": current is not None and current.id == args.new_key,
        "current": current.id if current else None,
    }
    # 2) 新分区计数/字节与备份清单一致（有备份清单时）
    new_stats = _dir_stats(data_dir / "sessions" / args.new_key)
    manifest: Any = None
    if backup_dir is not None and (backup_dir / "manifest.json").exists():
        try:
            manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = None
    item = None
    if isinstance(manifest, dict):
        raw = manifest.get("items", {}).get(f"sessions/{args.old_key}", {})
        if isinstance(raw, dict):
            item = {k: v for k, v in raw.items() if k in ("files", "bytes")}
    checks["partition_matches_backup"] = {
        "pass": (new_stats == item) if item is not None else True,
        "backup_dir": str(backup_dir) if backup_dir else None,
        "backup_item": item,
        "current": new_stats,
        "note": "" if item is not None else "无备份清单可比（未跑 backup 或 --backup-dir 未指）；仅记录现状",
    }
    # 3) .identity 无残留旧键 owner
    owners = _owner_distribution(data_dir / "sessions" / ".identity")
    checks["no_residual_old_owner"] = {
        "pass": args.old_key not in owners,
        "residual": owners.get(args.old_key, 0),
    }
    # 4) 新旧工件桶并存
    records_root = data_dir / "artifacts" / "records"
    checks["both_buckets_exist"] = {
        "pass": (records_root / args.old_bucket).is_dir()
        and (records_root / args.new_bucket).is_dir(),
        "old_bucket": (records_root / args.old_bucket).is_dir(),
        "new_bucket": (records_root / args.new_bucket).is_dir(),
    }
    # 5) 其它分区 mtime/计数未动（对照备份清单快照）
    others_ok = True
    others_detail: dict[str, object] = {}
    if isinstance(manifest, dict):
        for key, snap in manifest.get("other_partitions", {}).items():
            now = _dir_stats(data_dir / "sessions" / key)
            try:
                same = (
                    now["files"] == int(snap.get("files", -1))
                    and now["bytes"] == int(snap.get("bytes", -1))
                    and (data_dir / "sessions" / key).stat().st_mtime == snap.get("mtime")
                )
            except (OSError, ValueError, AttributeError):
                same = False
            others_ok = others_ok and same
            others_detail[key] = {"pass": same, "snapshot": snap, "current": now}
    checks["other_partitions_untouched"] = {"pass": others_ok, "detail": others_detail}
    # 6) 新根存在且 0700
    mode_now = stat_mod.S_IMODE(args.new_root.stat().st_mode) if args.new_root.is_dir() else None
    checks["new_root_0700"] = {
        "pass": mode_now is not None and (mode_now & 0o777) == 0o700,
        "path": str(args.new_root),
        "mode": oct(mode_now) if mode_now is not None else None,
    }
    overall = all(
        bool(v.get("pass")) for v in checks.values() if isinstance(v, dict)  # type: ignore[union-attr]
    )
    audit.append("verify.report", checks=checks,
                 backup_dir=str(backup_dir) if backup_dir else None,
                 result="PASS" if overall else "FAIL")
    print(json.dumps({"pass": overall, "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if overall else 1


def _default_new_root() -> Path:
    raw = os.environ.get("LFL_DEFAULT_WORKSPACE_ROOT", "").strip()
    return Path(raw or _DEFAULT_NEW_ROOT).expanduser().resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def _common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data",
                       help="数据根（默认 <repo>/data）")
        p.add_argument("--old-root", type=Path, default=REPO_ROOT,
                       help="旧默认工作区根（默认脚本所在仓库根）")
        p.add_argument("--new-root", type=Path, default=None,
                       help="新默认工作区根（默认 LFL_DEFAULT_WORKSPACE_ROOT env，缺省 ~/lfl-workspace）")
        p.add_argument("--audit-file", type=Path, default=None,
                       help="审计文件路径（默认 data/audit/workspace_migration/<ts>.json；"
                            "同一迁移战役各阶段可显式传同一路径共用）")
        p.add_argument("--web-port", type=int,
                       default=int(os.environ.get("WEB_PORT", "8903")),
                       help="web 端口（Phase 0 监听探针，默认 env WEB_PORT 或 8903）")

    for name, fn in (
        ("backup", cmd_backup),
        ("rehearse", cmd_rehearse),
        ("migrate", cmd_migrate),
        ("rollback", cmd_rollback),
        ("verify", cmd_verify),
    ):
        p = sub.add_parser(name)
        _common(p)
        if name in ("migrate", "rollback"):
            p.add_argument("--yes", action="store_true", help="显式确认执行（停机窗口内）")
        if name == "backup":
            p.add_argument("--backup-root", type=Path, default=REPO_ROOT / ".backup",
                           help="备份落点根（默认 <repo>/.backup）")
        if name == "verify":
            p.add_argument("--backup-dir", type=Path, default=None,
                           help="对照的备份目录（默认自动发现 .backup/workspace-migration-* 最新一份）")
            p.add_argument("--backup-root", type=Path, default=REPO_ROOT / ".backup",
                           help="自动发现备份的根（默认 <repo>/.backup）")
        p.set_defaults(func=fn)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.old_root = args.old_root.expanduser().resolve()
    args.new_root = (args.new_root or _default_new_root()).expanduser().resolve()
    args.data_dir = args.data_dir.expanduser().resolve()
    # 键/桶现算（防手误；与 factory/store/artifacts 同一派生函数）
    args.old_key = workspace_key(args.old_root)
    args.new_key = workspace_key(args.new_root)
    args.old_bucket = _workspace_bucket(workspace_scope(args.old_root))
    args.new_bucket = _workspace_bucket(workspace_scope(args.new_root))
    if args.audit_file is None:
        args.audit_file = (
            args.data_dir / "audit" / "workspace_migration" / f"{_ts_compact()}.json"
        )
    else:
        args.audit_file = args.audit_file.expanduser().resolve()
    print(
        f"[migrate_workspace] old_root={args.old_root} ({args.old_key}, bucket={args.old_bucket})\n"
        f"                  new_root={args.new_root} ({args.new_key}, bucket={args.new_bucket})\n"
        f"                  data_dir={args.data_dir} audit={args.audit_file}"
    )
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
