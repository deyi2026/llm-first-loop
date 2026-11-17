"""M0-A 内存双桩（DESIGN-20261116 embodied v2.3 §11.1.1 双桩合同；仅标准库）。

- StubExecutor：可信执行端。observe / execute_skill / get_action_status / stop 四个入口，
  另含独立 Oracle 验证通道与编排层 UNKNOWN 冻结/结案入口。
  账本、幂等索引、grant 表、UNKNOWN 写权冻结为持久语义（crash_restart 后保留）；
  in-flight 完成时刻、观察缓存、停止采样为内存语义（crash_restart 后丢失）。
- StubOracle：独立环境 Oracle。特权真值绝不进入模型可见观察；verify 只依据隐藏世界
  状态判定，不受执行端声明（含宣称成功）影响。
- 全部状态仅存内存；无 socket / subprocess / 文件 / 真机 / 外网调用（conftest 哨兵强制）。
- 模型侧只能选高层技能（ALLOWED_SKILLS + 参数键白名单）；低层指令字段一律拒绝。

故障注入面（§11.1）：fault_delay_ms / fault_drop_receipt / crash_restart / 无关帧 bump。
时钟为注入式 SimClock（不读 wall time，支持偏移推进与偏斜演练）。
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

# ---- 合同常量 ----
OBSERVATION_TTL_MS = 1000.0  # 观察新鲜半开区间 [acquired, acquired+TTL)；now>=上界即拒（v2.3 §5.2/AT-05）
STOP_CONFIRM_MIN_SAMPLES = 2  # 停止确认最少采样数
STOP_CONFIRM_MAX_WAIT_MS = 500.0  # 确认窗口；超期未确认 fail-closed 保持 UNCONFIRMED
STOP_SAMPLE_INTERVAL_MS = 50.0  # 两次有效采样的最小间隔
STOP_VELOCITY_EPS_MM_S = 0.5  # 运动证据容差（双桩固定合同，不是实机测量）
STOP_POSE_EPS_MM = 0.5
ALLOWED_SKILLS = frozenset({"pick", "place", "move_home", "open_gripper", "close_gripper"})
ALLOWED_PARAM_KEYS = frozenset({"target_id", "tray_id", "pose_name"})
FORBIDDEN_LOW_LEVEL_KEYS = frozenset(
    {"joint", "joints", "torque", "speed", "velocity", "effort", "trajectory"}
)
UNKNOWN_RECONCILE_TRUSTED_SOURCES = frozenset({"trusted_ledger", "human"})


class DeniedError(Exception):
    """合同拒绝（fail-closed）。调用方必须断言 .code 与动作计数，不得只看消息文本。"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class SimClock:
    """可注入单调时钟（毫秒）；支持显式推进，供 TTL / 停止窗口 / 时钟边界演练。"""

    now_ms: float = 0.0

    def advance(self, dt_ms: float) -> None:
        self.now_ms += dt_ms


@dataclass
class Observation:
    """模型可见观察。visible 不得包含 Oracle 特权键（由测试负向断言）。"""

    robot_id: str
    scene_epoch: int
    observation_ref: str
    acquired_ms: float
    visible: dict[str, Any]


@dataclass
class Receipt:
    action_id: str
    status: str
    intent_key: str
    evidence_ref: str | None = None


@dataclass
class LedgerEntry:
    """动作账本条目（持久语义）。status ∈ RUNNING/SUCCEEDED/UNKNOWN/INTERRUPTED/
    VERIFIED/EXECUTED_UNVERIFIED。oracle_verified 仅独立 Oracle 通道可置位。"""

    action_id: str
    intent_key: str
    params_fp: str
    semantic_fingerprint: str
    grant_version: int
    scene_epoch: int
    skill: str
    status: str = "RUNNING"
    claimed_success: bool = False
    claimed_evidence_ref: str | None = None
    oracle_verified: bool = False
    evidence_ref: str | None = None
    resolved_by: str | None = None
    resolved_at_ms: float | None = None
    reconcile_evidence_ref: str | None = None


@dataclass(frozen=True, eq=False)
class ReconcileProof:
    """One-shot, identity-bound capability issued outside the model-facing executor.

    This is an in-memory contract stub, NOT a production cryptographic attestation.
    """

    action_id: str
    intent_key: str
    resolved_by: str
    terminal_status: str
    evidence_ref: str


class TrustedReconcileAuthority:
    """Independent test actor for trusted-ledger/human reconciliation.

    The model-facing executor has no proof-minting API. A separate actor must
    attest a specific UNKNOWN ledger entry; forged, cross-entry and replayed
    proof objects are rejected. Production must isolate this actor out of process.
    """

    def __init__(self) -> None:
        self._issued: set[ReconcileProof] = set()

    def attest(
        self,
        entry: LedgerEntry,
        *,
        resolved_by: str,
        terminal_status: str,
        evidence_ref: str,
    ) -> ReconcileProof:
        if resolved_by not in UNKNOWN_RECONCILE_TRUSTED_SOURCES:
            raise DeniedError("RECONCILE_SOURCE_NOT_TRUSTED")
        if entry.status != "UNKNOWN" or terminal_status not in {"SUCCEEDED", "FAILED"}:
            raise DeniedError("RECONCILE_TERMINAL_EVIDENCE_REQUIRED")
        if not evidence_ref or not evidence_ref.startswith(f"{resolved_by}:"):
            raise DeniedError("RECONCILE_EVIDENCE_INVALID")
        proof = ReconcileProof(
            entry.action_id, entry.intent_key, resolved_by, terminal_status, evidence_ref
        )
        self._issued.add(proof)
        return proof

    def consume(self, proof: ReconcileProof, entry: LedgerEntry) -> None:
        if (
            proof not in self._issued
            or proof.action_id != entry.action_id
            or proof.intent_key != entry.intent_key
            or entry.status != "UNKNOWN"
        ):
            raise DeniedError("RECONCILE_PROOF_INVALID")
        self._issued.remove(proof)


class StubOracle:
    """独立环境 Oracle：持有特权真值（目标位姿/隐藏对象），模型可见观察不含这些键。"""

    ORACLE_PRIVILEGED_KEYS = ("oracle_target_pose", "oracle_hidden_objects", "oracle_success_rule")

    def __init__(self, robot_id: str = "sim-arm-01") -> None:
        self.robot_id = robot_id
        self._epoch = 1
        self._target_pose = {"target_id": "cube-red", "pose_name": "tray-A"}
        self._hidden_objects = frozenset({"cube-red"})
        self._known_trays = frozenset({"tray-A", "tray-B"})
        self._held: str | None = None
        # Picking does not mean placing: the held object and its last completed
        # placement are mutually exclusive, and only a valid place updates the latter.
        self._placed_at: dict[str, str] = {}
        self._effects: dict[str, dict[str, Any]] = {}  # action_id -> 该动作效果记录（逐动作验收依据）

    @property
    def scene_epoch(self) -> int:
        return self._epoch

    def bump_scene(self) -> None:
        """关键场景状态变化：推进 scene_epoch，使既有观察整体失效。"""
        self._epoch += 1

    def apply_pick(self, action_id: str, target_id: str | None) -> None:
        """执行端技能的世界效果，按 action_id 留验收依据。
        未知对象：世界不变，但效果记录仍登记 world_changed=False（执行端可能仍自报成功）。"""
        world_changed = target_id in self._hidden_objects and self._held is None
        if world_changed and target_id is not None:
            self._held = target_id
            self._placed_at.pop(target_id, None)
        self._effects[action_id] = {
            "skill": "pick",
            "target": target_id,
            "world_changed": world_changed,
        }

    def apply_place(self, action_id: str, tray_id: str | None) -> None:
        # Unknown/missing trays are never silently mapped to the goal tray.
        # A valid place releases the object; an invalid place preserves the held state.
        target_id = self._held
        world_changed = target_id is not None and tray_id in self._known_trays
        if world_changed and target_id is not None and tray_id is not None:
            self._placed_at[target_id] = tray_id
            self._held = None
        self._effects[action_id] = {
            "skill": "place",
            "target": target_id,
            "tray": tray_id,
            "world_changed": world_changed,
        }

    def effect_of(self, action_id: str) -> dict[str, Any] | None:
        return self._effects.get(action_id)

    def verify_effect(self, action_id: str) -> bool:
        """逐动作后置条件判定：只依据隐藏世界状态与该动作的效果记录，与执行端声明无关。
        无效果记录的动作（未被执行端应用）一律不满足。"""
        effect = self._effects.get(action_id)
        if effect is None:
            return False
        if effect["skill"] == "pick":
            return (
                bool(effect["world_changed"])
                and effect["target"] in self._hidden_objects
                and self._held == effect["target"]
                and effect["target"] not in self._placed_at
            )
        if effect["skill"] == "place":
            goal_target = self._target_pose["target_id"]
            goal_tray = self._target_pose["pose_name"]
            return (
                bool(effect["world_changed"])
                and effect["target"] == goal_target
                and effect["tray"] == goal_tray
                and self._held != goal_target
                and self._placed_at.get(goal_target) == goal_tray
            )
        return False

    def verify(self) -> bool:
        """全局目标判定：目标对象已放入目标托盘且不再被夹持。
        与逐动作 verify_effect 独立；抓住物体或放错托盘均不算完成。"""
        target = self._target_pose["target_id"]
        tray = self._target_pose["pose_name"]
        return self._held != target and self._placed_at.get(target) == tray

    def privileged_view(self) -> dict[str, Any]:
        """特权视图：仅供验收通道；绝不进入 Observation.visible。"""
        return {
            "oracle_target_pose": dict(self._target_pose),
            "oracle_hidden_objects": sorted(self._hidden_objects),
            "oracle_success_rule": {"pick": {"target_id": "cube-red", "at": "tray-A"}},
        }


class StubExecutor:
    """可信执行端双桩（内存）。拒绝顺序固定（fail-closed）：

    1 STOP_PENDING_HOLD → 2 WRITE_FROZEN_UNKNOWN → 3 GRANT_* → 4 幂等
    → 5 OBSERVATION_* → 6 技能/参数白名单
    """

    def __init__(
        self,
        clock: SimClock,
        oracle: StubOracle,
        reconcile_authority: TrustedReconcileAuthority | None = None,
        max_grant_epoch_age_ms: float | None = None,
    ) -> None:
        self.clock = clock
        self.oracle = oracle
        self._reconcile_authority = reconcile_authority
        self._obs_seq = 0
        self._irrelevant_frames = 0
        self._obs_by_ref: dict[str, Observation] = {}
        self.grants: dict[int, dict[str, Any]] = {}
        self._next_grant = 1
        self._current_grant_version: int | None = None
        self._max_grant_epoch_age_ms = max_grant_epoch_age_ms
        self._last_grant_verified_at_ms: float | None = None
        self._grant_freshness_hold = False
        self._clock_untrusted = False
        self._host_connected = True
        self.ledger: dict[str, LedgerEntry] = {}
        self.intent_index: dict[str, str] = {}
        self.intent_fp: dict[str, str] = {}
        self.intent_semantic: dict[str, str] = {}
        self.semantic_index: dict[str, str] = {}  # scene-independent pending-action identity
        self.unknown_holds: dict[str, str] = {}
        self.in_flight: dict[str, dict[str, Any]] = {}
        self.executed_count = 0
        # 故障注入
        self.fault_delay_ms: float = 0.0
        self.fault_drop_receipt: bool = False
        # 停止语义（两段时基）
        self.stop_requested_at_ms: float | None = None
        self.stop_boundary_at_ms: float | None = None
        self.stop_confirmed_at_ms: float | None = None
        self.stop_evidence_ref: str | None = None
        self._stop_samples: list[float] = []
        self._stop_window_expired = False

    # ---- 授权 ----
    def issue_grant(self) -> int:
        version = self._next_grant
        self._next_grant += 1
        self.grants[version] = {"robot_id": self.oracle.robot_id, "revoked": False}
        self._current_grant_version = version  # 新授权自动取代未撤销的旧版本
        self._last_grant_verified_at_ms = self.clock.now_ms
        self._grant_freshness_hold = False
        self._clock_untrusted = False
        return version

    def revoke_grant(self, version: int) -> None:
        if version in self.grants:
            self.grants[version]["revoked"] = True

    def set_host_connected(self, connected: bool) -> None:
        """Partition does not instantly revoke, but prevents refreshing stale grants."""
        self._host_connected = connected

    def mark_wake_clock_untrusted(self) -> None:
        """A wake/migration event requires new Host confirmation even if age is small."""
        self._clock_untrusted = True

    def refresh_grant_epoch(self, version: int, *, host_verified: bool) -> None:
        """Only explicit Host confirmation can clear a grant-freshness HOLD."""
        grant = self.grants.get(version)
        if (
            not host_verified or not self._host_connected or grant is None
            or grant["revoked"] or version != self._current_grant_version
        ):
            raise DeniedError("GRANT_REFRESH_UNVERIFIED")
        self._last_grant_verified_at_ms = self.clock.now_ms
        self._grant_freshness_hold = False
        self._clock_untrusted = False

    # ---- 观察 ----
    def observe(self) -> Observation:
        """无关帧只推进观察序号，不推进 scene_epoch（无关变化不活锁的机械保证）。"""
        self._obs_seq += 1
        obs = Observation(
            robot_id=self.oracle.robot_id,
            scene_epoch=self.oracle.scene_epoch,
            observation_ref=f"obs:{self.oracle.scene_epoch}:{self._obs_seq}",
            acquired_ms=self.clock.now_ms,
            visible={
                "robot_id": self.oracle.robot_id,
                "scene_epoch": self.oracle.scene_epoch,
                "held_visible": None,
                "known_targets": ["cube-red"],
            },
        )
        self._obs_by_ref[obs.observation_ref] = obs
        return obs

    def bump_irrelevant_frame(self) -> None:
        """无关观察帧变化（噪声/遥测抖动）：不影响 scene_epoch 与既有观察有效性。"""
        self._irrelevant_frames += 1

    # ---- 执行 ----
    def _canonical_fp(self, skill: str, params: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps({"skill": skill, "params": params}, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def execute_skill(
        self,
        *,
        grant_version: int,
        scene_epoch: int,
        observation_ref: str,
        intent_key: str,
        semantic_fingerprint: str,
        skill: str,
        params: dict[str, Any],
    ) -> Receipt:
        # 1) 停止请求后 fail-closed：新动作一律拒绝，直到 STOPPED_CONFIRMED 或人工重置
        if self.stop_requested_at_ms is not None:
            raise DeniedError("STOP_PENDING_HOLD")
        # 2) UNKNOWN 写权冻结：新 key 与同语义重发均拒（未结案不解除）
        if self.unknown_holds:
            prior_id = self.semantic_index.get(semantic_fingerprint)
            if (
                prior_id is not None
                and self.ledger[prior_id].intent_key != intent_key
                and scene_epoch != self.ledger[prior_id].scene_epoch
            ):
                raise DeniedError("DUPLICATE_SEMANTIC_INFLIGHT")
            raise DeniedError("WRITE_FROZEN_UNKNOWN")
        # 3) grant 校验
        grant = self.grants.get(grant_version)
        if grant is None:
            raise DeniedError("GRANT_UNKNOWN")
        if grant["revoked"]:
            raise DeniedError("GRANT_REVOKED")
        if grant_version != self._current_grant_version:
            raise DeniedError("GRANT_STALE")
        if grant["robot_id"] != self.oracle.robot_id:
            raise DeniedError("GRANT_ROBOT_MISMATCH")
        if self._max_grant_epoch_age_ms is not None:
            last_verified = self._last_grant_verified_at_ms
            age = None if last_verified is None else self.clock.now_ms - last_verified
            if (
                self._grant_freshness_hold or self._clock_untrusted or age is None
                or age < 0 or age >= self._max_grant_epoch_age_ms
            ):
                self._grant_freshness_hold = True
                raise DeniedError("GRANT_EPOCH_UNVERIFIED")
        # 4) 幂等：同键同参同语义 → 原样返回原 action_id（重放为查询性质，先于观察
        #    新鲜度检查——crash 后观察缓存已清也不阻断账本重放；绝不重复执行）
        prev_action_id = self.intent_index.get(intent_key)
        params_fp = self._canonical_fp(skill, params)
        if prev_action_id is not None:
            if (
                self.intent_fp.get(intent_key) == params_fp
                and self.intent_semantic.get(intent_key) == semantic_fingerprint
            ):
                entry = self.ledger[prev_action_id]
                return Receipt(prev_action_id, entry.status, intent_key, entry.evidence_ref)
            raise DeniedError("INTENT_CONFLICT")
        # New intent keys cannot bypass a still-pending physical action by
        # changing the scene epoch, retry key or wording. The fingerprint is
        # intentionally scene-independent and survives crash_restart.
        prior_id = self.semantic_index.get(semantic_fingerprint)
        if prior_id is not None and self.ledger[prior_id].status in {
            "RUNNING", "UNKNOWN", "INTERRUPTED"
        }:
            raise DeniedError("DUPLICATE_SEMANTIC_INFLIGHT")
        # 5) 观察新鲜度：ref 必须存在、属于当前 epoch、落在半开区间
        #    [acquired, acquired+TTL) 内（now >= acquired+TTL 即拒，v2.3 §5.2/AT-05）；显式 scene_epoch 一致
        obs = self._obs_by_ref.get(observation_ref)
        if obs is None:
            raise DeniedError("OBSERVATION_REF_UNKNOWN")
        if obs.robot_id != grant["robot_id"]:
            raise DeniedError("GRANT_ROBOT_MISMATCH")
        if obs.scene_epoch != self.oracle.scene_epoch or scene_epoch != self.oracle.scene_epoch:
            raise DeniedError("OBSERVATION_STALE_SCENE")
        if self.clock.now_ms - obs.acquired_ms >= OBSERVATION_TTL_MS:
            raise DeniedError("OBSERVATION_STALE_TTL")
        # 6) 高层技能白名单：模型不得发关节/扭矩/速度类低层指令
        if skill not in ALLOWED_SKILLS:
            raise DeniedError("SKILL_NOT_ALLOWED")
        if any(key in params for key in FORBIDDEN_LOW_LEVEL_KEYS):
            raise DeniedError("ILLEGAL_LOW_LEVEL_COMMAND")
        if not set(params) <= ALLOWED_PARAM_KEYS:
            raise DeniedError("PARAM_KEY_NOT_ALLOWED")

        action_id = f"act-{len(self.ledger) + 1:04d}"
        entry = LedgerEntry(
            action_id=action_id,
            intent_key=intent_key,
            params_fp=params_fp,
            semantic_fingerprint=semantic_fingerprint,
            grant_version=grant_version,
            scene_epoch=scene_epoch,
            skill=skill,
        )
        self.ledger[action_id] = entry
        self.intent_index[intent_key] = action_id
        self.intent_fp[intent_key] = params_fp
        self.intent_semantic[intent_key] = semantic_fingerprint
        self.semantic_index[semantic_fingerprint] = action_id
        self.executed_count += 1
        # 世界效果（经 Oracle 持有的隐藏状态，按 action_id 留逐动作验收依据）
        if skill == "pick":
            self.oracle.apply_pick(action_id, params.get("target_id"))
        elif skill == "place":
            self.oracle.apply_place(action_id, params.get("tray_id"))
        # 故障注入
        self.in_flight[action_id] = {
            "done_at_ms": self.clock.now_ms + self.fault_delay_ms,
            "receipt_lost": self.fault_drop_receipt,
        }
        if self.fault_drop_receipt:
            # 回执丢失 → UNKNOWN 且机械冻结写权（合同 2：超时进入 UNKNOWN/HOLD_WRITE；
            # 冻结是执行端/编排的机械行为，不依赖调用方显式登记）
            self.unknown_holds.setdefault(intent_key, "UNKNOWN_RECEIPT")
            return Receipt(action_id, "UNKNOWN", intent_key, None)
        return Receipt(action_id, "RUNNING", intent_key, None)

    def get_action_status(self, action_id: str) -> Receipt:
        """只读账本查询；不重发、不补发任何动作。crash 后 RUNNING 无终态 → INTERRUPTED。"""
        entry = self.ledger.get(action_id)
        if entry is None:
            raise DeniedError("ACTION_ID_UNKNOWN")
        if entry.status == "RUNNING":
            flight = self.in_flight.get(action_id)
            if flight is None:
                entry.status = "INTERRUPTED"  # 崩溃后对账：不假装成功
            elif flight.get("receipt_lost"):
                entry.status = "UNKNOWN"
            elif self.clock.now_ms >= flight["done_at_ms"]:
                entry.status = "SUCCEEDED"
                entry.evidence_ref = f"ev:{action_id}:exec"
        return Receipt(entry.action_id, entry.status, entry.intent_key, entry.evidence_ref)

    # ---- UNKNOWN 冻结与结案 ----
    def mark_unknown(self, intent_key: str, reason: str = "UNKNOWN_RECEIPT") -> None:
        """编排层在回执丢失/超时后的机械冻结：全局写权 HOLD，直到可信结案。"""
        self.unknown_holds.setdefault(intent_key, reason)

    def reconcile_unknown(self, intent_key: str, *, proof: ReconcileProof, release: bool) -> None:
        """Only one-shot trusted proof can settle an UNKNOWN and release HOLD_WRITE."""
        if not release or intent_key not in self.unknown_holds:
            raise DeniedError("RECONCILE_HOLD_REQUIRED")
        action_id = self.intent_index.get(intent_key)
        entry = self.ledger.get(action_id or "")
        if entry is None or self._reconcile_authority is None:
            raise DeniedError("RECONCILE_AUTHORITY_REQUIRED")
        if not isinstance(proof, ReconcileProof):
            raise DeniedError("RECONCILE_PROOF_INVALID")
        self._reconcile_authority.consume(proof, entry)
        entry.status = proof.terminal_status
        entry.resolved_by = proof.resolved_by
        entry.resolved_at_ms = self.clock.now_ms
        entry.reconcile_evidence_ref = proof.evidence_ref
        entry.evidence_ref = proof.evidence_ref
        self.unknown_holds.pop(intent_key)

    # ---- 崩溃恢复 ----
    def crash_restart(self) -> None:
        """进程崩溃重启：内存态丢失（in-flight、观察缓存、停止采样）；
        持久账本/幂等索引/UNKNOWN 冻结/grant 表保留。停止请求记录保守保留（fail-closed）。"""
        self.in_flight.clear()
        self._obs_by_ref.clear()
        self._stop_samples.clear()
        self._stop_window_expired = False
        if self._max_grant_epoch_age_ms is not None:
            # Strict M0-B contract: restart invalidates old execution grants.
            # Existing ledger remains queryable through get_action_status.
            self._current_grant_version = None
            self._grant_freshness_hold = True

    # ---- 独立 Oracle 验证通道 ----
    def claim_success(self, action_id: str, *, evidence_ref: str) -> None:
        """Untrusted claim is kept separate from independent Oracle/ledger evidence."""
        entry = self.ledger.get(action_id)
        if entry is None:
            raise DeniedError("ACTION_ID_UNKNOWN")
        entry.claimed_success = True
        entry.claimed_evidence_ref = evidence_ref

    def verify_with_oracle(self, action_id: str) -> str:
        """独立验收（逐动作后置条件）：仅终态动作可验收；Oracle 不满足 →
        EXECUTED_UNVERIFIED（绝不进 VERIFIED）。未定态（RUNNING/UNKNOWN/INTERRUPTED）
        一律拒绝验收（§6.6：未定态期间验收层不得写 VERIFIED）。"""
        entry = self.ledger.get(action_id)
        if entry is None:
            raise DeniedError("ACTION_ID_UNKNOWN")
        # Historical action acceptance is immutable. Re-verification must not
        # turn a rejected action into success after a different action moves the world.
        if entry.status in ("VERIFIED", "EXECUTED_UNVERIFIED"):
            return entry.status
        if entry.status != "SUCCEEDED":
            raise DeniedError("VERIFY_NOT_TERMINAL")
        if self.oracle.verify_effect(action_id):
            entry.oracle_verified = True
            entry.status = "VERIFIED"
            entry.evidence_ref = f"ev:{action_id}:oracle"
        else:
            entry.oracle_verified = False
            entry.status = "EXECUTED_UNVERIFIED"
            entry.evidence_ref = f"ev:{action_id}:oracle_refused"
        return entry.status

    # ---- 停止语义（两段时基：requested_at 与 confirmed_at 分别记录）----
    def stop(self, reason: str = "operator") -> str:
        if self.stop_requested_at_ms is None:
            self.stop_requested_at_ms = self.clock.now_ms
            # The in-memory executor has no atomic motion stage: the safe
            # boundary is reached immediately. A real simulator must measure it.
            self.stop_boundary_at_ms = self.clock.now_ms
        return "STOP_REQUESTED"

    def poll_stop_confirmation(
        self, *, motion_mm_s: float = 0.0, pose_delta_mm: float = 0.0
    ) -> str:
        """Two independent zero-motion samples are needed to confirm stopping.

        Motion, nonfinite readings, missing samples or timeout are fail-closed.
        The default zero readings preserve M0-A's static-arm contract only.
        """
        if self.stop_requested_at_ms is None:
            raise DeniedError("STOP_NOT_REQUESTED")
        now = self.clock.now_ms
        if (
            not self._stop_window_expired
            and now - self.stop_requested_at_ms > STOP_CONFIRM_MAX_WAIT_MS
            and self.stop_confirmed_at_ms is None
        ):
            # 确认窗口超期且从未确认：sticky fail-closed（需要人工重新发起/重置）
            self._stop_window_expired = True
        if (
            not math.isfinite(motion_mm_s) or not math.isfinite(pose_delta_mm)
            or abs(motion_mm_s) > STOP_VELOCITY_EPS_MM_S
            or abs(pose_delta_mm) > STOP_POSE_EPS_MM
        ):
            self._stop_samples.clear()
            return "STOP_UNCONFIRMED"
        if not self._stop_window_expired and (
            not self._stop_samples or now - self._stop_samples[-1] >= STOP_SAMPLE_INTERVAL_MS
        ):
            self._stop_samples.append(now)
        if len(self._stop_samples) >= STOP_CONFIRM_MIN_SAMPLES:
            if self.stop_confirmed_at_ms is None:
                self.stop_confirmed_at_ms = now
                self.stop_evidence_ref = f"ev:stop:{now}:zero_motion"
            return "STOPPED_CONFIRMED"
        return "STOP_UNCONFIRMED"

    def stop_state(self) -> str:
        if self.stop_confirmed_at_ms is not None:
            return "STOPPED_CONFIRMED"
        if self.stop_requested_at_ms is not None:
            return "STOP_REQUESTED"
        return "NONE"
