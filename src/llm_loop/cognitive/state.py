"""语义任务状态（Cognitive Runtime 5.1，v0.1 形态）.

对应: `.codeartsdoer/specs/cognitive_runtime/spec.md` §5.1 + design 2.1.3.1 / 2.2.2.1 / 2.3。

设计约束（design 1.2.1 / 1.2.2）:
- Durable/Ephemeral 分层: 仅 Durable 层落盘（跨压缩/重启/切换可恢复）；Ephemeral 每轮丢弃。
- 单一数据源: 状态只读 GoalStore（active goal + checkpoint 四要素），不另起第二套 goal 持久化。
- fail-closed 损坏语义: 继承 GoalStore.get() 的 GoalStoreCorruptionError——不得猜测当前目标。
- v0.1 指针起步: 仅 objective + checkpoint 指针两行；hard_constraints / confirmed_facts 为 v0.2
  预留（缺省空列表，未晋级时永不落盘非空）。
- 持久化格式: 本模块用 JSON 序列化（JSON 为 YAML 1.2 子集；项目无 pyyaml 依赖，不新增依赖），
  文件路径对齐 design 冻结的 ``audit/cognitive/state.yaml``；原子写复用 GoalStore 模式
  （tmp+fsync+rename + flock，goal.py:272-329）。
- confirmed_facts.provenance 优先携带 evidence://v1 引用而非文字重述，避免证据层双写。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from llm_loop.memory.evidence import _EVIDENCE_PREFIX, EvidenceRef

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

_FALLBACK_LOCK = threading.Lock()

# 粗略 token 估算: 中英混合文本约 4 字符/ token（仅用于缩略度量，非精确计费口径）。
_TOKEN_CHARS_PER_ESTIMATE = 4


class SemanticStateVersion(StrEnum):
    """状态字段分级路线（design 2.1.3.3 冻结点③）。"""

    V0_1 = "v0.1"  # objective + checkpoint 指针两行
    V0_2 = "v0.2"  # 追加 hard_constraints + confirmed_facts

    @classmethod
    def parse(cls, raw: str) -> SemanticStateVersion:
        if raw == cls.V0_2.value:
            return cls.V0_2
        return cls.V0_1


class ConfirmedFactFreshness(StrEnum):
    """confirmed_facts.freshness——语义对齐 Manifest 的 currentness（evidence.py:1067-1077）.

    映射（spec 6.1-3b / design 1.2.2）:
    CURRENT    → Manifest currentness = current（对应 FreshnessState.VERIFIED_CURRENT）
    RECENT     → Manifest currentness = unverified（其它状态）
    HISTORICAL → Manifest currentness = historical_only（对应 FreshnessState.STALE）
    """

    CURRENT = "current"
    RECENT = "recent"
    HISTORICAL = "historical"


@dataclass
class CheckpointPointer:
    """最近 checkpoint 的 what+next 两行指针（不携带 evidence/path，保持指针式而非全文）。"""

    what: str
    next: str = ""

    def __post_init__(self) -> None:
        self.what = self.what.strip()
        if not self.what:
            raise ValueError("CheckpointPointer.what 必填非空（spec 5.1.3-2 空 what 回退）")


@dataclass
class EphemeralState:
    """本轮临时状态（不持久化，每次压缩边界丢弃，design 2.3.2）。"""

    hypotheses: list[str] = field(default_factory=list)


@dataclass
class ConfirmedFact:
    """已确认事实（v0.2 预留；未晋级时恒为空列表）。"""

    claim: str
    provenance: EvidenceRef | None = None  # 优先 evidence://v1 引用（避免证据层双写）
    authority: str = ""  # 对齐 Provenance.authority（evidence.py:274）
    freshness: ConfirmedFactFreshness = ConfirmedFactFreshness.CURRENT
    scope: str = ""  # 对齐 Provenance.scope（evidence.py:275）
    confidence: str = ""  # 本层补充维度（不与 Manifest 冲突）

    def to_dict(self) -> dict:
        return {
            "claim": self.claim,
            "provenance": self.provenance.ref if self.provenance else None,
            "authority": self.authority,
            "freshness": self.freshness.value,
            "scope": self.scope,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ConfirmedFact:
        provenance: EvidenceRef | None = None
        ref = data.get("provenance")
        if ref:
            try:
                provenance = EvidenceRef(str(ref))
            except ValueError:
                logger.warning("confirmed_facts.provenance 非有效 evidence://v1 引用，置空: %r", ref)
        freshness_raw = str(data.get("freshness", ""))
        try:
            freshness = ConfirmedFactFreshness(freshness_raw) if freshness_raw else ConfirmedFactFreshness.CURRENT
        except ValueError:
            freshness = ConfirmedFactFreshness.CURRENT
        return cls(
            claim=str(data.get("claim", "")),
            provenance=provenance,
            authority=str(data.get("authority", "")),
            freshness=freshness,
            scope=str(data.get("scope", "")),
            confidence=str(data.get("confidence", "")),
        )


@dataclass
class SemanticTaskState:
    """语义任务状态（单一事实来源，design 2.3.2）。

    v0.1 仅 objective + checkpoint 指针可为非空；hard_constraints / confirmed_facts 为 v0.2 预留
    （缺省空列表，未晋级时永不落盘非空）；Ephemeral 不持久化。
    """

    objective: str
    checkpoint: CheckpointPointer | None = None
    version: SemanticStateVersion = SemanticStateVersion.V0_1
    hard_constraints: list[str] = field(default_factory=list)  # spec 6.1-2（v0.2）
    confirmed_facts: list[ConfirmedFact] = field(default_factory=list)  # spec 6.1-3（v0.2）
    ephemeral: EphemeralState = field(default_factory=EphemeralState)

    def __post_init__(self) -> None:
        self.objective = self.objective.strip()
        if not self.objective:
            raise ValueError("SemanticTaskState.objective 必填且非空（spec 6.1-1）")

    def to_dict(self) -> dict:
        """仅 Durable 层序列化（Ephemeral 不落盘，design 2.3.2）。"""
        return {
            "objective": self.objective,
            "checkpoint": (
                {"what": self.checkpoint.what, "next": self.checkpoint.next}
                if self.checkpoint
                else None
            ),
            "version": self.version.value,
            "hard_constraints": list(self.hard_constraints),
            "confirmed_facts": [f.to_dict() for f in self.confirmed_facts],
        }

    @classmethod
    def from_dict(cls, data: dict) -> SemanticTaskState:
        cp = data.get("checkpoint")
        checkpoint: CheckpointPointer | None = None
        if cp:
            try:
                checkpoint = CheckpointPointer(what=str(cp.get("what", "")), next=str(cp.get("next", "")))
            except ValueError:
                checkpoint = None  # 空 what：回退（spec 5.1.3-2）
        return cls(
            objective=str(data.get("objective", "")),
            checkpoint=checkpoint,
            version=SemanticStateVersion.parse(str(data.get("version", ""))),
            hard_constraints=[str(x) for x in data.get("hard_constraints", [])],
            confirmed_facts=[ConfirmedFact.from_dict(f) for f in data.get("confirmed_facts", [])],
        )


def _is_durable(
    *,
    survives_boundary: bool = False,
    is_hard_constraint: bool = False,
    is_decision_basis: bool = False,
    high_recover_cost: bool = False,
    stable_reusable_fact: bool = False,
) -> bool:
    """Durable Admission 门槛（spec 5.1.1-2 / design 2.1.3.1）：任一信号满足即入 Durable。

    5 条判定（任一成立）:
    1. survives_boundary    跨边界后仍影响决策
    2. is_hard_constraint   是硬约束或硬约束的解释依据
    3. is_decision_basis    是已关闭决策的 based_on / reopen_if
    4. high_recover_cost    丢失会显著增加重复调查或高成本风险
    5. stable_reusable_fact 是后续任务高概率复用的稳定技术事实
    """
    return any(
        (survives_boundary, is_hard_constraint, is_decision_basis, high_recover_cost, stable_reusable_fact)
    )


def promote_ephemeral(state: SemanticTaskState) -> list[str]:
    """压缩前：晋级 Ephemeral 中仍具决策相关性的最小恢复信息（spec 5.1.3-3，v0.1 记录行为）。

    v0.1 字段预留——假设即使满足 Durable 门槛，hard_constraints/confirmed_facts 仍不真正落盘
    （晋级由 v0.2 的 COG_RUNTIME_STATE_VERSION + 晋级触发条件驱动），本函数只识别并 WARN 记录。
    """
    durable: list[str] = []
    for h in state.ephemeral.hypotheses:
        if _is_durable(survives_boundary=True):
            durable.append(h)
    if durable:
        logger.warning("v0.1 Ephemeral 假设具备 Durable 信号但字段预留，暂不持久化: %r", durable)
    return durable


@dataclass
class Tombstone:
    """终态退役标记（spec 4.1-3）：goal complete/blocked 后禁止任何投影复活。"""

    reason: str
    ts: str

    def to_dict(self) -> dict:
        return {"reason": self.reason, "ts": self.ts}

    @classmethod
    def from_dict(cls, data: dict) -> Tombstone:
        return cls(reason=str(data.get("reason", "")), ts=str(data.get("ts", "")))


def _source_digest(goal_id: str, goal_updated_at: str, checkpoint_ts: str) -> str:
    """identity 源摘要（sha256 前 12 位）：goal + checkpoint 变更即变（design §2.1）。"""
    payload = f"{goal_id}|{goal_updated_at}|{checkpoint_ts}".encode()
    return hashlib.sha256(payload).hexdigest()[:12]


@dataclass
class StateIdentity:
    """state schema v2 身份头（spec 4.1-1）：会话隔离 + Read Barrier 比对键。"""

    session_id: str
    goal_id: str
    goal_updated_at: str
    checkpoint_ts: str
    state_revision: int = 1
    source_digest: str = ""

    def __post_init__(self) -> None:
        if not self.source_digest:
            self.source_digest = _source_digest(self.goal_id, self.goal_updated_at, self.checkpoint_ts)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "goal_id": self.goal_id,
            "goal_updated_at": self.goal_updated_at,
            "checkpoint_ts": self.checkpoint_ts,
            "state_revision": self.state_revision,
            "source_digest": self.source_digest,
        }

    @classmethod
    def from_dict(cls, data: dict) -> StateIdentity:
        return cls(
            session_id=str(data.get("session_id", "")),
            goal_id=str(data.get("goal_id", "")),
            goal_updated_at=str(data.get("goal_updated_at", "")),
            checkpoint_ts=str(data.get("checkpoint_ts", "")),
            state_revision=int(data.get("state_revision", 1) or 1),
            source_digest=str(data.get("source_digest", "")),
        )

    def matches(self, goal: dict) -> bool:
        """Read Barrier 一致性键：session + goal.id + goal.updated_at + 最新 checkpoint ts.

        CR-R1.1: 补 session_id 比对——不变量①要求信封与 goal 同会话；goal 缺
        session_id 字段（旧格式）视为不匹配，触发一次 rebuild 后回到稳态。
        """
        if not goal:
            return False
        if str(goal.get("session_id", "")) != self.session_id:
            return False
        if str(goal.get("id", "")) != self.goal_id:
            return False
        if str(goal.get("updated_at", "")) != self.goal_updated_at:
            return False
        cps = goal.get("checkpoints") or []
        latest_ts = str((cps[-1] or {}).get("ts", "")) if cps else ""
        return latest_ts == self.checkpoint_ts


@dataclass
class StateEnvelope:
    """state schema v2 信封：identity 头 + 墓碑 + 语义状态体（design §2.1）。"""

    identity: StateIdentity
    tombstone: Tombstone | None = None
    state: SemanticTaskState | None = None

    def to_dict(self) -> dict:
        return {
            "identity": self.identity.to_dict(),
            "tombstone": self.tombstone.to_dict() if self.tombstone else None,
            "state": self.state.to_dict() if self.state else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> StateEnvelope:
        identity_raw = data.get("identity")
        if not isinstance(identity_raw, dict):
            raise ValueError("envelope missing identity header")
        tombstone_raw = data.get("tombstone")
        state_raw = data.get("state")
        return cls(
            identity=StateIdentity.from_dict(identity_raw),
            tombstone=Tombstone.from_dict(tombstone_raw) if isinstance(tombstone_raw, dict) else None,
            state=SemanticTaskState.from_dict(state_raw) if isinstance(state_raw, dict) else None,
        )


class _StaleUntrusted:
    """旧无头 state.yaml 的哨兵标记：不可信 → 调用方应 rebuild（design §2.1 迁移）。"""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover
        return "STALE_UNTRUSTED"


STALE_UNTRUSTED = _StaleUntrusted()


def rebuild_state(goal: dict | None, version: SemanticStateVersion | None = None) -> SemanticTaskState | None:
    """从 GoalStore.get() 返回的 goal dict 派生 SemanticTaskState（design 2.1.3.1）。

    - Goal 为空/**非 active（complete/blocked 终态）** → None（spec 4.1-3 墓碑前置检查）。
    - fail-closed: 调用方应先经 GoalStore.get() 读取——其抛出的 GoalStoreCorruptionError
      已含损坏文件路径+行范围，本函数不吞该异常（调用方据此保留既有状态）。
    - 空 what checkpoint 回退上一有效 checkpoint + warn（spec 5.1.3-2）。
    """
    if not goal:
        return None
    if str(goal.get("status", "")) in ("complete", "blocked"):
        return None
    objective = str(goal.get("objective", "")).strip()
    if not objective:
        return None
    cps = goal.get("checkpoints") or []
    checkpoint: CheckpointPointer | None = None
    skipped_empty = 0
    for cp in reversed(cps):
        what = str((cp or {}).get("what", "")).strip()
        nxt = str((cp or {}).get("next", "")).strip()
        if what:
            checkpoint = CheckpointPointer(what=what, next=nxt)
            break
        skipped_empty += 1
    if skipped_empty:
        logger.warning("rebuild_state: %d 条空 what checkpoint 已跳过，回退上一有效 checkpoint", skipped_empty)
    return SemanticTaskState(
        objective=objective,
        checkpoint=checkpoint,
        version=version or SemanticStateVersion.V0_1,
    )


class SemanticStateStore:
    """语义状态 YAML(JSON) 持久化（schema v2，按会话分片；原子写 + flock，复用 GoalStore 模式）。

    分片路径 = ``<audit_dir>/cognitive/state.<sha16>.yaml``（sha16=sha256(session_id)[:16]，CR-R1.1 升级 64-bit 碰撞域）——
    会话写竞争隔离，Session A 物理上读不到 B 的分片（spec 4.1-1 不变量①）。
    旧全局 ``state.yaml``（无 identity 头）→ load 返回 STALE_UNTRUSTED，调用方 rebuild 后
    写入新分片（零手工迁移；旧文件留存不再读，供审计）。
    无分片且无遗留 → load 返回 None，由 rebuild_state 派生初始化。
    """

    def __init__(self, audit_dir: str | Path) -> None:
        self._dir = Path(audit_dir) / "cognitive"
        self._legacy_path = self._dir / "state.yaml"

    def path_for(self, session_id: str) -> Path:
        """会话分片路径（不变量①：按 sid 分片隔离）。"""
        # CR-R1.1: 分片键改 sha256[:16]（64-bit）——sid8 仅 32-bit 碰撞域，前缀相同
        # 的不同会话会共享分片文件（审查实测可互读）。旧 sid8 路径不再读取，
        # 缺失走 rebuild 派生（安全方向：宁缺勿错）。
        shard = hashlib.sha256((session_id or "_").encode("utf-8")).hexdigest()[:16]
        return self._dir / f"state.{shard}.yaml"

    @property
    def path(self) -> Path:
        """向后兼容诊断入口：无会话语义的默认分片。"""
        return self.path_for("")

    def load(self, session_id: str) -> StateEnvelope | None | _StaleUntrusted:
        """按会话读取语义状态信封（schema v2）。

        返回三态：StateEnvelope（含墓碑标记时由调用方决定不投影）/ None（无状态）/
        STALE_UNTRUSTED（旧无头遗留不可信 → 调用方 rebuild）。
        """
        p = self.path_for(session_id)
        if not p.exists():
            if self._legacy_path.exists():
                raw_legacy = self._legacy_path.read_text(encoding="utf-8").strip()
                if raw_legacy:
                    logger.info(
                        "检测到旧全局语义状态（无 identity 头），视为不可信触发 rebuild: %s",
                        self._legacy_path,
                    )
                    return STALE_UNTRUSTED
            return None
        raw = p.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("语义状态分片损坏，load 返回 None（由 rebuild 派生）: %s", p)
            return None
        try:
            env = StateEnvelope.from_dict(data)
        except ValueError:
            logger.warning("语义状态分片缺 identity 头，视为不可信（STALE_UNTRUSTED）: %s", p)
            return STALE_UNTRUSTED
        if env.identity.session_id != (session_id or ""):
            # CR-R1.1: 分片身份校验——shard 碰撞/污染（读到他会的 state）不得直接
            # 返回，降级 STALE_UNTRUSTED 走 rebuild 派生（宁缺勿错）。
            logger.warning(
                "语义状态分片会话身份不匹配（shard 污染/碰撞）→ STALE_UNTRUSTED: %s "
                "envelope_sid=%r requested=%r",
                p,
                env.identity.session_id,
                session_id,
            )
            return STALE_UNTRUSTED
        return env

    def save(self, session_id: str, envelope: StateEnvelope) -> None:
        p = self.path_for(session_id)
        self._dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(envelope.to_dict(), ensure_ascii=False)
        with self._file_lock(p):
            self._atomic_rewrite(payload, p)

    def _atomic_rewrite(self, payload: str, path: Path) -> None:
        """原子提交（tmp+fsync+rename，对齐 goal.py:272-297）；reader 只见旧/新，不见半写。"""
        tmp = self._dir / f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        try:
            with tmp.open("w", encoding="utf-8") as f:
                f.write(payload + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            dir_fd: int | None = None
            try:
                flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                dir_fd = os.open(self._dir, flags)
                os.fsync(dir_fd)
            except OSError:
                logger.warning("语义状态目录 fsync 失败（写入已完成）: %s", self._dir, exc_info=True)
            finally:
                if dir_fd is not None:
                    os.close(dir_fd)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                logger.debug("语义状态临时文件清理失败: %s", tmp, exc_info=True)

    @contextmanager
    def _file_lock(self, path: Path) -> Iterator[None]:
        """跨进程写锁（flock），对齐 goal.py:299-329；仅锁获取失败时 fail-open。"""
        lock_path = path.with_suffix(path.suffix + ".lock")
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
            logger.warning("语义状态锁不可用（fail-open）: %s: %s", lock_path, exc)
            yield
            return
        try:
            yield
        finally:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except OSError:
                logger.warning("语义状态解锁失败: %s", lock_path, exc_info=True)
            finally:
                lock_file.close()


def _count_state_fields(state: SemanticTaskState) -> int:
    """reset 前后缩略度量：Durable + Ephemeral 字段计数。"""
    n = 1  # objective
    if state.checkpoint is not None:
        n += 1
    n += len(state.hard_constraints) + len(state.confirmed_facts) + len(state.ephemeral.hypotheses)
    return n


def _estimate_tokens(text: str) -> int:
    return len(text) // _TOKEN_CHARS_PER_ESTIMATE


@dataclass
class ResetResult:
    """受控清空重载返回（design 2.2.2.3）。"""

    ok: bool = False
    failed: bool = False
    need_confirmation: bool = False  # enforce 语境需操作者确认
    metric_before: int = 0  # reset 前字段数
    metric_after: int = 0  # reset 后字段数
    estimated_token_delta: int = 0  # 估算清除 token（缩略度量）
    first_miss_expected: bool = False  # 清空会触发缓存前缀重建 → 预期首 miss
    # Cognitive Runtime（tasks 3.3）: 清空后的最小 Durable 状态（供 A/B 编排 reset 组
    # 重建会话使用；字段只增不改，design 2.3.1 兼容策略）
    cleared: SemanticTaskState | None = None


class SemanticResetController:
    """受控清空重载（spec 4.2-2 / 4.3-2 / design 2.1.4）。

    reset 清空累积认知负担（Ephemeral 假设等），保留最小必要 Durable：
    objective + checkpoint 指针 + 硬约束 + 已确认事实（spec 4.2-1「不因 reset
    丢失已确认事实与硬约束」/ 4.3-1「硬约束不可被优化掉」）；
    先写内存快照，清空失败回滚（不产生半清空态）。
    """

    def reset(self, state: SemanticTaskState, *, require_confirmation: bool = False) -> ResetResult:
        metric_before = _count_state_fields(state)
        if require_confirmation:
            return ResetResult(
                failed=True,
                need_confirmation=True,
                metric_before=metric_before,
                metric_after=metric_before,
            )
        try:
            # spec 4.2-1/4.3-1/5.1.1-5a: 不因 reset 丢失已确认事实与硬约束——
            # 清空的是累积认知负担（Ephemeral 假设等），硬约束/已确认事实属"不丢"半边
            cleared = SemanticTaskState(
                objective=state.objective,
                checkpoint=state.checkpoint,
                version=state.version,
                hard_constraints=list(state.hard_constraints),
                confirmed_facts=list(state.confirmed_facts),
            )
        except Exception:
            logger.warning("语义 reset 清空失败，回滚快照", exc_info=True)
            return ResetResult(failed=True, metric_before=metric_before, metric_after=metric_before)
        removed_texts = list(state.ephemeral.hypotheses)
        return ResetResult(
            ok=True,
            metric_before=metric_before,
            metric_after=_count_state_fields(cleared),
            estimated_token_delta=_estimate_tokens("".join(removed_texts)),
            first_miss_expected=True,
            cleared=cleared,
        )


__all__ = [
    "SemanticStateVersion",
    "ConfirmedFactFreshness",
    "CheckpointPointer",
    "EphemeralState",
    "ConfirmedFact",
    "SemanticTaskState",
    "SemanticStateStore",
    "SemanticResetController",
    "ResetResult",
    "rebuild_state",
    "promote_ephemeral",
    "_EVIDENCE_PREFIX",
]
