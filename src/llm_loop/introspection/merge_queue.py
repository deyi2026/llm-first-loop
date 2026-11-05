"""合并队列（P2a·S0）：main 合入串行化 + 合并建议卡.

设计依据: docs/design/DESIGN-20261105-main-lane-parallel-delivery-v1.md §4.4 / §4.4.1 / §5 / §8-P2a

范围裁定（S0 = human_confirm，三级授权中唯一默认开闸级）:
- 本模块只做「排队 → 串行闸 → 四条机检 → 合并建议卡」，**不执行任何 git merge/push**;
  即使配置 lane_auto_merge=true，attempt_auto_merge 也一律抛 MergeNotSupportedError
  ——S1/S2 执行器属 P2b 未交付，绝不允许调用方误以为"已自动化"。

== 双账本与一致性依据（当前态为何不靠事件重放）==
- merge_queue.jsonl:        当前态，一行一条队列项，last-write-wins + version CAS，**读的唯一权威源**;
- merge_queue_events.jsonl: 只追加事件，仅供审计回放。

一致性依据:
1. 两份文件的每次变更都在同一把 flock 临界区内完成: 先原子重写 state（tmp + os.replace），
   再 append 事件，不存在两文件并发交错的窗口;
2. 事件写失败只告警不回滚 state（与 lane.py / goal.py 同口径）——最坏分歧是
   「state 已推进、审计缺一条」，绝无「事件领先 state」的中间态;
3. state 出现不可解析行一律 fail-closed 抛 MergeQueueCorruptionError，
   绝不从事件回放"猜"当前态（事件不参与正确性判定）。

== 串行化（验收 A4）==
同一时刻全局至多一条队列项处于 preflight|merging:
- check-and-set（"是否已有 slot 占用" + 改状态）在 flock 内原子完成;
- 持有者落盘 = state 文件里 status ∈ {preflight, merging} 的那条记录
  （含 slot_acquired_at / slot_owner），跨进程可见，不依赖任何进程内内存;
- 第二个请求回执 ok=False + reason_code=merge_slot_busy + holder 详情，其队列项保持 queued 不降级。

== main 前进语义（§5 时序代价的 S0 处置）==
note_main_advanced(new_sha) 只把 **status=queued** 的项标 stale（保留在队列）;
已进入 preflight/merging 的项不动（合并临界区自会二次比对 sha），终态项不动。
绝不静默删除、绝不直接判 failed——stale 项刷新 base 后 requeue + 再次 preflight 可继续。

== slot 生命周期 ==
占用: request_preflight 成功、request_merge 成功; 释放: run_preflight 判 fail（自动转
failed）、run_preflight 判 pass（转 ready_for_confirm，交还 slot）、abort（人工）、
mark_merged（登记完成）。ready_for_confirm 不占槽是 S0 的关键设计：无执行器推进时，
若机检全过项继续持槽，人不在场就会用一条项卡死整个队列。

== 可一步 revert 性（§4.4.1 机检第 10 条，父代理补充要求）==
S0 阶段 merge commit 尚不存在，无法对真实提交做事后核对，因此建议卡按政策**预判**:
合并临界区规定 --no-ff 且父即当前 main head（§4.4），故 revertible=true +
revert_blocker="predicted_from_no_ff_policy"。P2b 执行器落地后应改为对真实 merge commit
判定 not_no_ff / parent_not_main_head；**不把未知当 false**。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from llm_loop.introspection.lane import _normalize_paths
from llm_loop.introspection.task_claim import overlapping_paths
from llm_loop.timekeeping import system_local_now

logger = logging.getLogger(__name__)

_FALLBACK_LOCK = threading.Lock()

QUEUE_STATUSES = ("queued", "preflight", "ready_for_confirm", "merging", "merged", "failed", "aborted")
QUEUE_TERMINAL_STATUSES = ("merged", "failed", "aborted")
# 全局串行：同一时刻至多一条。ready_for_confirm 不占槽——S0 无执行器推进，
# 若让"机检全过待人工确认"继续持槽，人不在场时整个队列会被一个项卡死。
SLOT_STATUSES = ("preflight", "merging")

# 四条机检的 check 名（run_preflight 逐项返回 {check, verdict, reason_code, evidence}）
CHECK_BASE = "base_main_current"
CHECK_MERGE_TREE = "merge_tree_clean"
CHECK_PATHS = "paths_disjoint"
CHECK_VERIFY = "verify_covers_base"

_TRUTHY = {"1", "true", "yes", "on"}


class MergeQueueCorruptionError(RuntimeError):
    """merge_queue.jsonl 存在损坏记录，当前查询无法安全判定。"""


class MergeQueueVersionConflictError(RuntimeError):
    """expected_version CAS 冲突：在 flock 内检出，写入未发生（与 A9 同款语义）。"""

    def __init__(self, *, lane_id: str, expected: int, current: int) -> None:
        self.lane_id = lane_id
        self.expected = expected
        self.current = current
        super().__init__(f"version_conflict lane={lane_id} expected={expected} current={current}")


class MergeQueueConstraintError(RuntimeError):
    """违反硬约束（重复入队 / 非法迁移 / 缺必填字段 / 终态不可逆）。"""


class MergeNotSupportedError(RuntimeError):
    """S0 阶段本模块不执行 git merge/push；显式未实现，防止误以为已自动化。"""


@dataclass
class QueueEntry:
    """一条等待合入 main 的队列项（lane 快照 + 队列自身状态）."""

    queue_id: str
    lane_id: str
    branch: str
    head_sha: str
    base_main_sha: str
    paths: list[str] = field(default_factory=list)
    verify_ref: str = ""
    status: str = "queued"  # queued|preflight|ready_for_confirm|merging|merged|failed|aborted
    stale: bool = False
    stale_reasons: list[str] = field(default_factory=list)
    stale_since_main: str = ""
    last_preflight: dict[str, Any] = field(default_factory=dict)
    failure_reasons: list[str] = field(default_factory=list)
    close_reason: str = ""
    slot_acquired_at: str = ""
    slot_owner: str = ""  # 显示用，不作鉴权（与 lane 口径一致）
    version: int = 1
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------- 机检（纯函数，供 run_preflight 与建议卡复用） ----------------


_GIT_READ_ONLY = ("rev-parse", "merge-tree", "log", "show")

# 与 lane_gate._run_git_readonly 同一口径：head_sha / base_main_sha 等是模型可控
# 输入（lane_queue_submit 可传），以 "-" 开头的一律拒绝，避免被 git 解析成选项。
_GIT_ALLOWED_FLAGS = frozenset({"--write-tree", "--name-only", "--no-commit-id", "-n", "-z"})
_GIT_ALLOWED_FLAG_PREFIXES = ("--format=", "--pretty=")


def _git(repo_root: str, *args: str, timeout: int = 15) -> tuple[int, str, str]:
    """只读 git 调用（rev-parse / merge-tree / log / show 白名单内）。失败不抛，回执交调用方判定。"""
    if not repo_root:
        return -1, "", "repo_root 未配置"
    if not args or args[0] not in _GIT_READ_ONLY:
        return -1, "", f"git 子命令超出只读白名单: {list(args)[:1]}"
    for raw in args[1:]:
        arg = str(raw)
        if arg.startswith("-") and not (
            arg in _GIT_ALLOWED_FLAGS
            or any(arg.startswith(prefix) for prefix in _GIT_ALLOWED_FLAG_PREFIXES)
        ):
            return -1, "", f"git 参数含不允许的选项: {arg!r}"
    try:
        proc = subprocess.run(
            ["git", "-C", repo_root, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, "", f"{type(exc).__name__}: {exc}"
    return proc.returncode, proc.stdout, proc.stderr


def _check(check: str, ok: bool, reason_code: str, evidence: dict) -> dict:
    return {
        "check": check,
        "verdict": "pass" if ok else "fail",
        "reason_code": "" if ok else reason_code,
        "evidence": evidence,
    }


def check_base_main_current(entry: dict, main_head: str) -> dict:
    """机检 a: lane.base_main_sha 是否为当前 main head。不是则 stale（fail-closed，未知也算不通过）。"""
    base = str(entry.get("base_main_sha") or "").strip()
    if not main_head:
        return _check(CHECK_BASE, False, "main_head_unknown", {"entry_base": base})
    if base != main_head:
        return _check(
            CHECK_BASE, False, "base_stale", {"entry_base": base, "main_head": main_head}
        )
    return _check(CHECK_BASE, True, "", {"entry_base": base, "main_head": main_head})


def merge_tree_conflicts(repo_root: str, main_head: str, head_sha: str) -> tuple[list[str], bool]:
    """git merge-tree --write-tree --name-only 零副作用预检（不建 worktree、不动 index、不写 ref）。

    返回 (conflicts, available): available=False 表示 git 不可用/语法不支持（fail-closed，
    调用方按"预检不可用"处理，不得当作无冲突）。
    """
    if not head_sha:
        return [], False
    if not main_head:
        return [], False
    rc, out, err = _git(
        repo_root, "merge-tree", "--write-tree", "--name-only", main_head, head_sha
    )
    if rc == 0:
        return [], True
    if rc == 1:  # 有冲突: 首行是 tree oid，其后为冲突文件名
        conflicts = [ln.strip() for ln in out.splitlines()[1:] if ln.strip()]
        return conflicts, True
    logger.warning("merge-tree 预检不可用: rc=%s stderr=%s", rc, (err or "")[:200])
    return [], False


def check_merge_tree_clean(repo_root: str, entry: dict, main_head: str) -> dict:
    """机检 b: 该 lane 与当前 main 是否冲突（真实树级预检，独立于 paths 声明）。"""
    theirs = str(entry.get("head_sha") or "").strip()
    if not theirs:
        return _check(CHECK_MERGE_TREE, False, "head_missing", {"head_sha": ""})
    conflicts, available = merge_tree_conflicts(repo_root, main_head, theirs)
    if not available:
        return _check(
            CHECK_MERGE_TREE,
            False,
            "merge_tree_unavailable",
            {"command": "git merge-tree --write-tree --name-only", "main_head": main_head},
        )
    if conflicts:
        return _check(CHECK_MERGE_TREE, False, "merge_conflict", {"conflicts": conflicts})
    return _check(CHECK_MERGE_TREE, True, "", {"main_head": main_head, "head_sha": theirs})


def check_paths_disjoint(entry: dict, others: list[dict]) -> dict:
    """机检 c: lane 声明 paths 与其他在途队列项的 paths 是否交叉（复用 task_claim.overlapping_paths）。"""
    mine = [str(p) for p in entry.get("paths") or []]
    overlaps: list[dict] = []
    for other in others:
        hits = overlapping_paths(mine, [str(p) for p in other.get("paths") or []])
        if hits:
            shared = sorted({a for a, _ in hits} | {b for _, b in hits})
            overlaps.append({"lane_id": other.get("lane_id"), "shared_paths": shared})
    if overlaps:
        return _check(CHECK_PATHS, False, "paths_overlap", {"overlaps": overlaps})
    checked = [str(o.get("lane_id")) for o in others]
    return _check(CHECK_PATHS, True, "", {"checked_against": checked})


def _parse_iso(raw: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


def check_verify_covers_base(entry: dict, receipts: dict[str, dict]) -> dict:
    """机检 d: 验证凭证 verify_ref 是否覆盖当前 base_main_sha（不覆盖则要求重验，fail-closed）。"""
    ref = str(entry.get("verify_ref") or "").strip()
    if not ref:
        return _check(CHECK_VERIFY, False, "verify_required", {"detail": "lane 未携带验证凭证"})
    receipt = receipts.get(ref)
    if receipt is None:
        return _check(
            CHECK_VERIFY, False, "verify_required", {"verify_ref": ref, "detail": "凭证未找到"}
        )
    if str(receipt.get("lane_id") or "") != str(entry.get("lane_id") or ""):
        return _check(
            CHECK_VERIFY,
            False,
            "verify_invalid",
            {"verify_ref": ref, "detail": "凭证不属于该 lane"},
        )
    if str(receipt.get("result") or "").strip().lower() != "pass":
        return _check(
            CHECK_VERIFY,
            False,
            "verify_invalid",
            {"verify_ref": ref, "result": receipt.get("result")},
        )
    created = _parse_iso(receipt.get("created_at"))
    if created is None:
        return _check(
            CHECK_VERIFY, False, "verify_invalid", {"verify_ref": ref, "detail": "created_at 不可解析"}
        )
    ttl = receipt.get("ttl_s")
    if not ttl:
        # 无 ttl_s 不等于「永不过期」：有效期不可判定时按无效处理（fail-closed，
        # 与 lane_gate._within_ttl 的 D3/F8 口径一致）。
        return _check(
            CHECK_VERIFY,
            False,
            "verify_invalid",
            {"verify_ref": ref, "detail": "ttl_s 缺失（有效期不可判定，按无效处理）"},
        )
    try:
        if system_local_now() > created + timedelta(seconds=int(ttl)):
            return _check(CHECK_VERIFY, False, "verify_expired", {"verify_ref": ref})
    except (TypeError, ValueError, OverflowError):
        return _check(
            CHECK_VERIFY, False, "verify_invalid", {"verify_ref": ref, "detail": "ttl 不可解析"}
        )
    rbase = str(receipt.get("base_sha") or "").strip()
    base = str(entry.get("base_main_sha") or "").strip()
    if rbase != base:
        return _check(
            CHECK_VERIFY,
            False,
            "verify_stale",
            {"verify_ref": ref, "receipt_base": rbase, "entry_base": base},
        )
    return _check(
        CHECK_VERIFY, True, "", {"verify_ref": ref, "base_sha": rbase, "scope": receipt.get("scope", "")}
    )


def load_receipts(path: Path) -> dict[str, dict]:
    """加载验证凭证（receipt_id → 行）。文件缺失/行损坏按"凭证不存在"处理（fail-closed 落到 verify_required）。"""
    out: dict[str, dict] = {}
    if not path or not path.exists():
        return out
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("verify_receipts 存在不可解析行（按凭证缺失处理）: %s", path)
                    continue
                if isinstance(row, dict) and row.get("receipt_id"):
                    out[str(row["receipt_id"])] = row
    except OSError:
        logger.warning("verify_receipts 读取失败（按凭证缺失处理）: %s", path, exc_info=True)
    return out


# ---------------- 存储 ----------------


class MergeQueueStore:
    """merge_queue.jsonl 当前态 + merge_queue_events.jsonl 事件的存储层（与 LaneStore 同构）."""

    def __init__(
        self,
        audit_dir: str | Path,
        *,
        repo_root: str = "",
        main_ref: str = "main",
        receipts_path: str | Path | None = None,
        create: bool = True,
    ) -> None:
        self._dir = Path(audit_dir)
        # 只读消费者（lane_queue_status / lane_merge_advice / lane_gate_check）
        # 传 create=False：目录不存在也不建，保持「只读工具零写副作用」。
        if create:
            self._dir.mkdir(parents=True, exist_ok=True)
        # 命名与 lanes 账本一致：无后缀 = 当前态（读的唯一权威源），_events = 只追加事件。
        self._state_path = self._dir / "merge_queue.jsonl"
        self._event_path = self._dir / "merge_queue_events.jsonl"
        self.repo_root = str(repo_root or "")
        self.main_ref = str(main_ref or "main")
        self.receipts_path = (
            Path(receipts_path) if receipts_path is not None else self._dir / "verify_receipts.jsonl"
        )

    # ---------------- 写入 ----------------

    def enqueue(
        self,
        *,
        lane_id: str,
        branch: str = "",
        head_sha: str = "",
        base_main_sha: str = "",
        paths: list[str] | None = None,
        verify_ref: str = "",
        slot_owner: str = "",
        lane_record: dict | None = None,
    ) -> dict:
        """入队（lane 快照落账）。lane_record 可传 LaneStore.get() 的行，显式 kwargs 优先。"""
        rec = lane_record or {}
        lane_id = str(lane_id or rec.get("lane_id") or "").strip()
        branch = str(branch or rec.get("branch") or "").strip()
        head_sha = str(head_sha or rec.get("head_sha") or "").strip()
        base = str(base_main_sha or rec.get("base_main_sha") or "").strip()
        paths = paths if paths is not None else (rec.get("paths") or [])
        verify_ref = str(verify_ref or rec.get("verify_ref") or "").strip()
        if not lane_id:
            raise MergeQueueConstraintError("lane_id 必填")
        if not branch:
            raise MergeQueueConstraintError("branch 必填")
        if not head_sha:
            raise MergeQueueConstraintError("head_sha 必填（无 head 无法预检）")
        if not base:
            raise MergeQueueConstraintError("base_main_sha 必填（无法判定 stale）")

        now = system_local_now().isoformat()
        entry = QueueEntry(
            queue_id=f"mq-{uuid.uuid4().hex[:8]}",
            lane_id=lane_id,
            branch=branch,
            head_sha=head_sha,
            base_main_sha=base,
            paths=_normalize_paths(paths),
            verify_ref=verify_ref,
            slot_owner=str(slot_owner or "").strip(),
            version=1,
            created_at=now,
            updated_at=now,
        )
        with self._file_lock():
            rows = self._read_rows()
            for row in rows:
                if row.get("lane_id") == lane_id and str(row.get("status")) not in QUEUE_TERMINAL_STATUSES:
                    raise MergeQueueConstraintError(
                        f"lane 已在队列中（非终态）: {lane_id} → {row.get('queue_id')} status={row.get('status')}"
                    )
            rows.append(entry.to_dict())
            self._atomic_rewrite([json.dumps(r, ensure_ascii=False) for r in rows])
            self._append_event(
                {"event": "queue.enqueued", "queue_id": entry.queue_id, "lane_id": lane_id,
                 "ts": now, "snapshot": entry.to_dict()}
            )
        return entry.to_dict()

    def request_preflight(self, lane_id: str, *, expected_version: int, slot_owner: str = "") -> dict:
        """申请进入 preflight（串行闸）。回执 {ok, reason_code, entry, holder}，拒绝时队列项保持 queued。"""
        with self._file_lock():
            rows = self._read_rows()
            idx = self._find_index(rows, lane_id)
            entry = rows[idx]
            self._assert_version(entry, expected_version)
            if str(entry.get("status")) != "queued":
                return {
                    "ok": False,
                    "reason_code": "not_queued",
                    "entry": entry,
                    "holder": self._holder_view(self._holder_row(rows)),
                    "detail": f"当前 status={entry.get('status')}（仅 queued 可申请）",
                }
            holder = self._holder_row(rows)
            if holder is not None:
                return {
                    "ok": False,
                    "reason_code": "merge_slot_busy",
                    "entry": entry,
                    "holder": self._holder_view(holder),
                    "detail": "全局串行：已有队列项处于 preflight|merging",
                }
            now = system_local_now().isoformat()
            entry["status"] = "preflight"
            entry["slot_acquired_at"] = now
            if slot_owner:
                entry["slot_owner"] = str(slot_owner).strip()
            entry["version"] = self.version_of(entry) + 1
            entry["updated_at"] = now
            rows[idx] = entry
            self._atomic_rewrite([json.dumps(r, ensure_ascii=False) for r in rows])
            self._append_event(
                {"event": "queue.preflight_started", "queue_id": entry.get("queue_id"),
                 "lane_id": lane_id, "ts": now, "version": entry["version"]}
            )
            return {"ok": True, "reason_code": "", "entry": entry, "holder": self._holder_view(entry)}

    def run_preflight(self, lane_id: str, *, expected_version: int, main_head: str = "") -> dict:
        """执行四条机检并落账。全过 → ready_for_confirm（交还 slot，等人工确认）;
        任一不过 → failed（释放 slot，requeue 可重试）。paths 交叉以请求时点的队列快照为准。"""
        with self._file_lock():
            rows = self._read_rows()
            idx = self._find_index(rows, lane_id)
            entry = rows[idx]
            self._assert_version(entry, expected_version)
            if str(entry.get("status")) != "preflight":
                raise MergeQueueConstraintError(
                    f"run_preflight 仅接受 preflight 态（当前 {entry.get('status')}）"
                )
            snapshot_entry = dict(entry)
            others = [
                dict(r) for r in rows
                if r is not entry
                and str(r.get("status")) not in QUEUE_TERMINAL_STATUSES
            ]
        # ——锁外执行机检（含 git 子进程，不阻塞账本读写）——
        head = str(main_head or "").strip() or self.probe_main_head()
        receipts = load_receipts(self.receipts_path)
        checks = [
            check_base_main_current(snapshot_entry, head),
            check_merge_tree_clean(self.repo_root, snapshot_entry, head),
            check_paths_disjoint(snapshot_entry, others),
            check_verify_covers_base(snapshot_entry, receipts),
        ]
        verdict = "pass" if all(c["verdict"] == "pass" for c in checks) else "fail"
        codes = [c["reason_code"] for c in checks if c["verdict"] == "fail"]

        with self._file_lock():
            rows = self._read_rows()
            idx = self._find_index(rows, lane_id)
            entry = rows[idx]
            self._assert_version(entry, expected_version)  # 机检期间被并发改动则拒绝落账
            now = system_local_now().isoformat()
            entry["last_preflight"] = {
                "ts": now, "main_head": head, "verdict": verdict,
                "checks": checks, "reason_codes": codes,
            }
            if verdict == "pass":
                # S0 无执行器推进：全过即交还 slot，转 ready_for_confirm 等人工确认，
                # 让后续 lane 能进队列；确认入口是 request_merge（确认时重新抢槽）。
                entry["status"] = "ready_for_confirm"
                entry["slot_acquired_at"] = ""
                event_name = "queue.preflight_passed"
            else:
                entry["status"] = "failed"
                entry["failure_reasons"] = codes
                entry["close_reason"] = "preflight_failed"
                entry["slot_acquired_at"] = ""
                event_name = "queue.preflight_failed"
            entry["version"] = self.version_of(entry) + 1
            entry["updated_at"] = now
            rows[idx] = entry
            self._atomic_rewrite([json.dumps(r, ensure_ascii=False) for r in rows])
            self._append_event(
                {"event": event_name, "queue_id": entry.get("queue_id"), "lane_id": lane_id,
                 "ts": now, "verdict": verdict, "reason_codes": codes, "version": entry["version"]}
            )
            return {
                "lane_id": lane_id,
                "queue_id": entry.get("queue_id"),
                "verdict": verdict,
                "status": entry["status"],
                "reason_codes": codes,
                "checks": checks,
                "version": entry["version"],
            }

    def note_main_advanced(self, new_main_sha: str) -> list[dict]:
        """main 前进：仅把 queued 项标 stale 并保留在队列（不删、不直接判 failed）。幂等（同 sha 不重复标）。"""
        sha = str(new_main_sha or "").strip()
        if not sha:
            raise MergeQueueConstraintError("new_main_sha 必填")
        staled: list[dict] = []
        with self._file_lock():
            rows = self._read_rows()
            now = system_local_now().isoformat()
            touched = False
            for entry in rows:
                if str(entry.get("status")) != "queued":
                    continue
                reasons = list(entry.get("stale_reasons") or [])
                if entry.get("stale") and entry.get("stale_since_main") == sha and "main_advanced" in reasons:
                    continue  # 幂等
                if "main_advanced" not in reasons:
                    reasons.append("main_advanced")
                entry["stale"] = True
                entry["stale_reasons"] = reasons
                entry["stale_since_main"] = sha
                entry["version"] = self.version_of(entry) + 1
                entry["updated_at"] = now
                touched = True
                staled.append(dict(entry))
            if touched:
                self._atomic_rewrite([json.dumps(r, ensure_ascii=False) for r in rows])
                for entry in staled:
                    self._append_event(
                        {"event": "queue.staled", "queue_id": entry.get("queue_id"),
                         "lane_id": entry.get("lane_id"), "ts": now, "since_main": sha}
                    )
        return staled

    def requeue(
        self,
        lane_id: str,
        *,
        expected_version: int,
        head_sha: str | None = None,
        base_main_sha: str | None = None,
        verify_ref: str | None = None,
        paths: list[str] | None = None,
    ) -> dict:
        """failed → queued（可顺带刷新 lane 快照字段）。aborted 是人工终态，重新入队请走 enqueue。"""
        with self._file_lock():
            rows = self._read_rows()
            idx = self._find_index(rows, lane_id)
            entry = rows[idx]
            self._assert_version(entry, expected_version)
            if str(entry.get("status")) != "failed":
                raise MergeQueueConstraintError(
                    f"requeue 仅接受 failed 态（当前 {entry.get('status')}）"
                )
            refreshed = []
            if head_sha is not None and str(head_sha).strip():
                entry["head_sha"] = str(head_sha).strip()
                refreshed.append("head_sha")
            if base_main_sha is not None and str(base_main_sha).strip():
                entry["base_main_sha"] = str(base_main_sha).strip()
                refreshed.append("base_main_sha")
            if verify_ref is not None and str(verify_ref).strip():
                entry["verify_ref"] = str(verify_ref).strip()
                refreshed.append("verify_ref")
            if paths is not None:
                entry["paths"] = _normalize_paths(paths)
                refreshed.append("paths")
            now = system_local_now().isoformat()
            entry["status"] = "queued"
            entry["stale"] = False
            entry["stale_reasons"] = []
            entry["stale_since_main"] = ""
            entry["failure_reasons"] = []
            entry["close_reason"] = ""
            entry["version"] = self.version_of(entry) + 1
            entry["updated_at"] = now
            rows[idx] = entry
            self._atomic_rewrite([json.dumps(r, ensure_ascii=False) for r in rows])
            self._append_event(
                {"event": "queue.requeued", "queue_id": entry.get("queue_id"), "lane_id": lane_id,
                 "ts": now, "refreshed": refreshed, "version": entry["version"]}
            )
            return entry

    def request_merge(self, lane_id: str, *, expected_version: int, slot_owner: str = "") -> dict:
        """人工确认合并入口：ready_for_confirm → merging（重新抢全局串行槽）。

        S0 阶段只推进队列状态，不执行任何 git 操作。抢槽失败时保持 ready_for_confirm
        并返回 merge_slot_busy，不降级、不丢项（人可稍后重试）。
        """
        with self._file_lock():
            rows = self._read_rows()
            idx = self._find_index(rows, lane_id)
            entry = rows[idx]
            self._assert_version(entry, expected_version)
            if str(entry.get("status")) != "ready_for_confirm":
                return {
                    "ok": False,
                    "reason_code": "not_ready_for_confirm",
                    "entry": entry,
                    "holder": self._holder_view(self._holder_row(rows)),
                    "detail": (
                        f"当前 status={entry.get('status')}"
                        "（仅 ready_for_confirm 可确认合并）"
                    ),
                }
            holder = self._holder_row(rows)
            if holder is not None:
                return {
                    "ok": False,
                    "reason_code": "merge_slot_busy",
                    "entry": entry,
                    "holder": self._holder_view(holder),
                    "detail": "全局串行：已有队列项处于 preflight|merging",
                }
            now = system_local_now().isoformat()
            entry["status"] = "merging"
            entry["slot_acquired_at"] = now
            if slot_owner:
                entry["slot_owner"] = str(slot_owner).strip()
            entry["version"] = self.version_of(entry) + 1
            entry["updated_at"] = now
            rows[idx] = entry
            self._atomic_rewrite([json.dumps(r, ensure_ascii=False) for r in rows])
            self._append_event(
                {"event": "queue.merge_confirmed", "queue_id": entry.get("queue_id"),
                 "lane_id": lane_id, "ts": now, "version": entry["version"]}
            )
            return {"ok": True, "reason_code": "", "entry": entry,
                    "holder": self._holder_view(entry)}

    def mark_merged(
        self, lane_id: str, *, expected_version: int, merge_commit: str = ""
    ) -> dict:
        """人工登记合并完成：merging → merged，释放 slot。merge_commit 可留空但会如实记账。"""
        with self._file_lock():
            rows = self._read_rows()
            idx = self._find_index(rows, lane_id)
            entry = rows[idx]
            self._assert_version(entry, expected_version)
            if str(entry.get("status")) != "merging":
                raise MergeQueueConstraintError(
                    f"mark_merged 仅接受 merging 态（当前 {entry.get('status')}）"
                )
            now = system_local_now().isoformat()
            entry["status"] = "merged"
            entry["slot_acquired_at"] = ""
            entry["close_reason"] = "merged"
            entry["merge_commit"] = str(merge_commit or "").strip()
            entry["version"] = self.version_of(entry) + 1
            entry["updated_at"] = now
            rows[idx] = entry
            self._atomic_rewrite([json.dumps(r, ensure_ascii=False) for r in rows])
            self._append_event(
                {"event": "queue.merged", "queue_id": entry.get("queue_id"), "lane_id": lane_id,
                 "ts": now, "merge_commit": entry["merge_commit"], "version": entry["version"]}
            )
            return entry

    def abort(self, lane_id: str, *, expected_version: int, reason: str) -> dict:
        """人工中止（queued/preflight/ready_for_confirm/merging → aborted），释放 slot。终态需要非空 reason（可归因）。"""
        reason = str(reason or "").strip()
        if not reason:
            raise MergeQueueConstraintError("abort 必须提供非空 reason（终态可归因）")
        with self._file_lock():
            rows = self._read_rows()
            idx = self._find_index(rows, lane_id)
            entry = rows[idx]
            self._assert_version(entry, expected_version)
            if str(entry.get("status")) in QUEUE_TERMINAL_STATUSES:
                raise MergeQueueConstraintError(f"终态不可逆: {entry.get('status')} → aborted")
            now = system_local_now().isoformat()
            entry["status"] = "aborted"
            entry["close_reason"] = reason
            entry["slot_acquired_at"] = ""
            entry["version"] = self.version_of(entry) + 1
            entry["updated_at"] = now
            rows[idx] = entry
            self._atomic_rewrite([json.dumps(r, ensure_ascii=False) for r in rows])
            self._append_event(
                {"event": "queue.aborted", "queue_id": entry.get("queue_id"), "lane_id": lane_id,
                 "ts": now, "reason": reason, "version": entry["version"]}
            )
            return entry

    def enter_merging(self, lane_id: str, *, expected_version: int) -> dict:
        """preflight → merging（P2b 执行器钩子；S0 无调用方，本模块不执行 merge 本身）。"""
        with self._file_lock():
            rows = self._read_rows()
            idx = self._find_index(rows, lane_id)
            entry = rows[idx]
            self._assert_version(entry, expected_version)
            if str(entry.get("status")) != "preflight":
                raise MergeQueueConstraintError(
                    f"enter_merging 仅接受 preflight 态（当前 {entry.get('status')}）"
                )
            now = system_local_now().isoformat()
            entry["status"] = "merging"
            entry["version"] = self.version_of(entry) + 1
            entry["updated_at"] = now
            rows[idx] = entry
            self._atomic_rewrite([json.dumps(r, ensure_ascii=False) for r in rows])
            self._append_event(
                {"event": "queue.merging", "queue_id": entry.get("queue_id"), "lane_id": lane_id,
                 "ts": now, "version": entry["version"]}
            )
            return entry

    def complete_merged(self, lane_id: str, *, expected_version: int, merge_sha: str) -> dict:
        """preflight|merging → merged（P2b 执行器在真实 merge 后回写；merge_sha 必填以便一步 revert）。"""
        merge_sha = str(merge_sha or "").strip()
        if not merge_sha:
            raise MergeQueueConstraintError("complete_merged 必须提供 merge_sha（可归因/可 revert）")
        with self._file_lock():
            rows = self._read_rows()
            idx = self._find_index(rows, lane_id)
            entry = rows[idx]
            self._assert_version(entry, expected_version)
            if str(entry.get("status")) not in ("preflight", "merging"):
                raise MergeQueueConstraintError(
                    f"complete_merged 仅接受 preflight|merging 态（当前 {entry.get('status')}）"
                )
            now = system_local_now().isoformat()
            entry["status"] = "merged"
            entry["close_reason"] = f"merged as {merge_sha[:12]}"
            entry["slot_acquired_at"] = ""
            entry["version"] = self.version_of(entry) + 1
            entry["updated_at"] = now
            rows[idx] = entry
            self._atomic_rewrite([json.dumps(r, ensure_ascii=False) for r in rows])
            self._append_event(
                {"event": "queue.merged", "queue_id": entry.get("queue_id"), "lane_id": lane_id,
                 "ts": now, "merge_sha": merge_sha, "version": entry["version"]}
            )
            return entry

    # ---------------- 读取（零写副作用） ----------------

    @staticmethod
    def version_of(entry: dict) -> int:
        raw = (entry or {}).get("version", 1)
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return 1

    def probe_main_head(self) -> str:
        """探测当前 main head（git rev-parse）。失败返回空串（fail-closed 交给机检判定）。"""
        rc, out, _ = _git(self.repo_root, "rev-parse", self.main_ref)
        return out.strip() if rc == 0 else ""

    def get(self, lane_id: str) -> dict | None:
        if not self._state_path.exists():
            return None
        malformed: list[int] = []
        with self._state_path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                raw = line.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    malformed.append(line_no)
                    continue
                if entry.get("lane_id") == lane_id:
                    return entry
        if malformed:
            raise self._corruption_error(malformed, "显式 lane_id 未命中")
        return None

    def list(
        self,
        statuses: tuple[str, ...] | list[str] | None = None,
        *,
        include_terminal: bool = False,
    ) -> list[dict]:
        """列出队列项；默认隐藏终态。损坏记录 fail-closed。按入队时间升序（队列语义）。"""
        if not self._state_path.exists():
            return []
        wanted = set(statuses) if statuses else None
        out: list[dict] = []
        malformed: list[int] = []
        with self._state_path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                raw = line.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    malformed.append(line_no)
                    continue
                status = str(entry.get("status") or "")
                if wanted is not None and status not in wanted:
                    continue
                if wanted is None and not include_terminal and status in QUEUE_TERMINAL_STATUSES:
                    continue
                out.append(entry)
        if malformed:
            raise self._corruption_error(malformed, "列表读取")
        out.sort(key=lambda e: (str(e.get("created_at") or ""), str(e.get("queue_id") or "")))
        return out

    @staticmethod
    def _holder_row(rows: list[dict]) -> dict | None:
        for row in rows:
            if str(row.get("status")) in SLOT_STATUSES:
                return row
        return None

    @classmethod
    def _holder_view(cls, row: dict | None) -> dict | None:
        if row is None:
            return None
        return {
            "queue_id": row.get("queue_id"),
            "lane_id": row.get("lane_id"),
            "branch": row.get("branch"),
            "status": row.get("status"),
            "slot_acquired_at": row.get("slot_acquired_at"),
            "slot_owner": row.get("slot_owner"),
        }

    def slot_holder(self) -> dict | None:
        """当前 slot 持有者视图（由 state 文件推导，无第二份存储）。"""
        return self._holder_view(self._holder_row(self.list(include_terminal=True)))

    def snapshot(self, *, include_terminal: bool = True) -> dict:
        """队列快照: 在途项 + slot 持有者 + 计数（只读）。"""
        entries = self.list(include_terminal=include_terminal)
        counts: dict[str, int] = {}
        for row in entries:
            status = str(row.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
        return {
            "generated_at": system_local_now().isoformat(),
            "entries": entries,
            "slot": self.slot_holder(),
            "counts": counts,
        }

    # ---------------- 内部 ----------------

    def _assert_version(self, entry: dict, expected_version: int) -> None:
        current = self.version_of(entry)
        if current != int(expected_version):
            raise MergeQueueVersionConflictError(
                lane_id=str(entry.get("lane_id") or ""),
                expected=int(expected_version),
                current=current,
            )

    @staticmethod
    def _find_index(rows: list[dict], lane_id: str) -> int:
        # 取最后一条匹配：enqueue 允许在上一项终态后重新入队（abort→re-enqueue），
        # 若返回首个匹配，旧终态行会遮蔽新行，get()/confirm 会作用在已死条目上。
        for idx in range(len(rows) - 1, -1, -1):
            if rows[idx].get("lane_id") == lane_id:
                return idx
        raise MergeQueueConstraintError(f"队列项不存在: {lane_id}")

    def _read_rows(self) -> list[dict]:
        if not self._state_path.exists():
            return []
        rows: list[dict] = []
        malformed: list[int] = []
        with self._state_path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                raw = line.strip()
                if not raw:
                    continue
                try:
                    rows.append(json.loads(raw))
                except json.JSONDecodeError:
                    malformed.append(line_no)
        if malformed:
            raise self._corruption_error(malformed, "写入前读取")
        return rows

    def _append_event(self, event: dict) -> None:
        """只追加审计历史; 写失败只告警不吞主写结果（与 lane.py 同口径，见模块 docstring 一致性依据）。"""
        try:
            with self._event_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        except OSError:
            logger.warning("merge_queue 事件写入失败（state 已提交）: %s", self._event_path, exc_info=True)

    def _corruption_error(self, lines: list[int], reason: str) -> MergeQueueCorruptionError:
        shown = ",".join(str(n) for n in lines[:8])
        suffix = "..." if len(lines) > 8 else ""
        return MergeQueueCorruptionError(
            f"merge_queue 存储损坏: {self._state_path} 存在不可解析 JSONL 行 {shown}{suffix}（{reason}）"
        )

    def _atomic_rewrite(self, lines: list[str]) -> None:
        tmp = self._state_path.with_suffix(self._state_path.suffix + ".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                if lines:
                    fh.write("\n".join(lines) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self._state_path)
            dir_fd: int | None = None
            try:
                flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                dir_fd = os.open(self._dir, flags)
                os.fsync(dir_fd)
            except OSError:
                logger.warning("merge_queue 目录 fsync 失败（写入已完成）: %s", self._dir, exc_info=True)
            finally:
                if dir_fd is not None:
                    os.close(dir_fd)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                logger.debug("merge_queue 临时文件清理失败: %s", tmp, exc_info=True)

    @contextmanager
    def _file_lock(self) -> Iterator[None]:
        """merge_queue 跨进程写锁; 仅锁获取失败时 fail-open，业务 I/O 异常原样传播（与 lane.py 同构）。"""
        lock_path = self._state_path.with_suffix(self._state_path.suffix + ".lock")
        try:
            import fcntl
        except ImportError:
            with _FALLBACK_LOCK:
                yield
            return

        lock_file = None
        try:
            lock_file = lock_path.open("a", encoding="utf-8")
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        except OSError as exc:
            if lock_file is not None:
                lock_file.close()
            logger.warning("merge_queue 存储锁不可用（fail-open，并发保护降级）: %s: %s", lock_path, exc)
            yield
            return

        try:
            yield
        finally:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except OSError:
                logger.warning("merge_queue 存储解锁失败: %s", lock_path, exc_info=True)
            finally:
                lock_file.close()


# ---------------- S0 合并建议卡（只读，仅建议不执行） ----------------


def _advice_order_key(card: dict) -> tuple:
    return (
        0 if card["_disjoint"] else 1,
        len(card.get("conflicts") or []),
        str(card.get("created_at") or ""),
        str(card.get("queue_id") or ""),
    )


def build_merge_advice(store: MergeQueueStore, *, main_head: str = "") -> dict:
    """S0 合并建议卡（DESIGN §4.4.1 / §5 D2）。纯只读: 不改账本、不执行 merge。

    排序规则: 无冲突且 paths 与其他在途项不相交者优先，有交叉者后置;
    组内按冲突面升序、入队时间升序。suggested_order 从 1 起，仅建议不执行。
    """
    entries = store.list(include_terminal=False)
    head = str(main_head or "").strip() or store.probe_main_head()
    receipts = load_receipts(store.receipts_path)

    cards: list[dict] = []
    for entry in entries:
        conflicts, available = merge_tree_conflicts(
            store.repo_root, head, str(entry.get("head_sha") or "")
        )
        needs_reverify: list[str] = []
        if not head:
            needs_reverify.append("main_head_unknown")
        elif str(entry.get("base_main_sha") or "") != head:
            needs_reverify.append("base_stale")
        if not available:
            needs_reverify.append("merge_tree_unavailable")
        vcheck = check_verify_covers_base(entry, receipts)
        if vcheck["verdict"] == "fail":
            needs_reverify.append(vcheck["reason_code"])
        overlaps_with = [
            str(other.get("lane_id"))
            for other in entries
            if other is not entry
            and overlapping_paths(
                [str(p) for p in entry.get("paths") or []],
                [str(p) for p in other.get("paths") or []],
            )
        ]
        cards.append(
            {
                "lane_id": entry.get("lane_id"),
                "queue_id": entry.get("queue_id"),
                "branch": entry.get("branch"),
                "status": entry.get("status"),
                "head_sha": entry.get("head_sha"),
                "base_main_sha": entry.get("base_main_sha"),
                "paths": list(entry.get("paths") or []),
                "conflicts": conflicts,
                "needs_reverify": needs_reverify,
                "overlaps_with": sorted(overlaps_with),
                # S0 无 merge commit，按 §4.4 临界区政策预判（不把未知当 false）
                "revertible": True,
                "revert_blocker": "predicted_from_no_ff_policy",
                "created_at": entry.get("created_at"),
                "_disjoint": bool(available) and not conflicts and not overlaps_with,
            }
        )

    cards.sort(key=_advice_order_key)
    reason_codes: set[str] = set()
    for pos, card in enumerate(cards, start=1):
        card["suggested_order"] = pos
        for code in card["needs_reverify"]:
            reason_codes.add(f"{card['lane_id']}:{code}")
        if card["overlaps_with"]:
            reason_codes.add(f"{card['lane_id']}:paths_overlap")
        del card["_disjoint"]

    return {
        "generated_at": system_local_now().isoformat(),
        "main_head": head,
        "lanes": cards,
        "reason_codes": sorted(reason_codes),
    }


# ---------------- 自动化开关（S0 显式不执行） ----------------


def auto_merge_enabled(config: object = None) -> bool:
    """lane_auto_merge 开关（默认 false）；由调用方显式注入，本模块不直接读环境。

    设计 §11.1: 配置默认关; "实现了自动" ≠ "默认自动"。本开关现阶段只影响回执文案，
    不解锁任何 merge 执行（见 attempt_auto_merge）。
    不直接用 os.environ 是本仓库 runtime_env_access_gate 的单向棘轮要求（新增直接环境
    访问须显式审查 baseline），也避免"队列认为开了、机检认为关"的两处口径。
    """
    if config is None:
        return False
    return bool(getattr(config, "auto_merge", False))


def automation_status(config: object = None) -> dict:
    """当前自动化档位（供 Board/工具回执展示）。"""
    return {
        "level": "S0",
        "lane_auto_merge": auto_merge_enabled(config),
        "executor": "not_implemented",
        "note": "S0 仅产出合并建议卡（build_merge_advice）; S1/S2 执行器属 P2b。",
    }


def attempt_auto_merge(config: object = None, *_args: object, **_kwargs: object) -> None:
    """显式未实现闸: S0 阶段任何自动合并请求都抛错，绝不执行 git merge/push。"""
    raise MergeNotSupportedError(
        "S0 阶段不执行 git merge/push（lane_auto_merge="
        f"{auto_merge_enabled(config)}）; 自动执行属 P2b 未交付。合并建议见 build_merge_advice。"
    )

