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
from dataclasses import dataclass
from typing import Any

# ---- 合同常量 ----
OBSERVATION_TTL_MS = 1000.0  # 观察新鲜半开区间 [acquired, acquired+TTL)；now>=上界即拒（v2.3 §5.2/AT-05）
STOP_CONFIRM_MIN_SAMPLES = 2  # 停止确认最少采样数
STOP_CONFIRM_MAX_WAIT_MS = 500.0  # 确认窗口；超期未确认 fail-closed 保持 UNCONFIRMED
STOP_SAMPLE_INTERVAL_MS = 50.0  # 两次有效采样的最小间隔
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
    oracle_verified: bool = False
    evidence_ref: str | None = None


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

    def __init__(self, clock: SimClock, oracle: StubOracle) -> None:
        self.clock = clock
        self.oracle = oracle
        self._obs_seq = 0
        self._irrelevant_frames = 0
        self._obs_by_ref: dict[str, Observation] = {}
        self.grants: dict[int, dict[str, Any]] = {}
        self._next_grant = 1
        self.ledger: dict[str, LedgerEntry] = {}
        self.intent_index: dict[str, str] = {}
        self.intent_fp: dict[str, str] = {}
        self.intent_semantic: dict[str, str] = {}
        self.unknown_holds: dict[str, str] = {}
        self.in_flight: dict[str, dict[str, Any]] = {}
        self.executed_count = 0
        self.nw_calls = 0  # 双口径之一：真实执行端才会递增；内存双桩恒为 0
        self.hw_calls = 0
        # 故障注入
        self.fault_delay_ms: float = 0.0
        self.fault_drop_receipt: bool = False
        # 停止语义（两段时基）
        self.stop_requested_at_ms: float | None = None
        self.stop_confirmed_at_ms: float | None = None
        self._stop_samples: list[float] = []
        self._stop_window_expired = False

    # ---- 授权 ----
    def issue_grant(self) -> int:
        version = self._next_grant
        self._next_grant += 1
        self.grants[version] = {"robot_id": self.oracle.robot_id, "revoked": False}
        return version

    def revoke_grant(self, version: int) -> None:
        if version in self.grants:
            self.grants[version]["revoked"] = True

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
            raise DeniedError("WRITE_FROZEN_UNKNOWN")
        # 3) grant 校验
        grant = self.grants.get(grant_version)
        if grant is None:
            raise DeniedError("GRANT_UNKNOWN")
        if grant["revoked"]:
            raise DeniedError("GRANT_REVOKED")
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
        # 5) 观察新鲜度：ref 必须存在、属于当前 epoch、落在半开区间
        #    [acquired, acquired+TTL) 内（now >= acquired+TTL 即拒，v2.3 §5.2/AT-05）；显式 scene_epoch 一致
        obs = self._obs_by_ref.get(observation_ref)
        if obs is None:
            raise DeniedError("OBSERVATION_REF_UNKNOWN")
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

    def reconcile_unknown(self, intent_key: str, *, resolved_by: str, release: bool) -> None:
        """只有可信账本/人工能结案；其他来源（如模型自称）一律拒绝。"""
        if resolved_by not in UNKNOWN_RECONCILE_TRUSTED_SOURCES:
            raise DeniedError("RECONCILE_SOURCE_NOT_TRUSTED")
        if release:
            self.unknown_holds.pop(intent_key, None)

    # ---- 崩溃恢复 ----
    def crash_restart(self) -> None:
        """进程崩溃重启：内存态丢失（in-flight、观察缓存、停止采样）；
        持久账本/幂等索引/UNKNOWN 冻结/grant 表保留。停止请求记录保守保留（fail-closed）。"""
        self.in_flight.clear()
        self._obs_by_ref.clear()
        self._stop_samples.clear()
        self._stop_window_expired = False

    # ---- 独立 Oracle 验证通道 ----
    def claim_success(self, action_id: str, *, evidence_ref: str) -> None:
        """执行端宣称成功（不可信声明通道）：只置 claimed_success，不改 oracle_verified。"""
        entry = self.ledger.get(action_id)
        if entry is None:
            raise DeniedError("ACTION_ID_UNKNOWN")
        entry.claimed_success = True
        entry.evidence_ref = evidence_ref

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
        return "STOP_REQUESTED"

    def poll_stop_confirmation(self) -> str:
        """停止确认采样：样本不足或窗口超期 → STOP_UNCONFIRMED（fail-closed 保持 HOLD）。"""
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
        if not self._stop_window_expired and (
            not self._stop_samples or now - self._stop_samples[-1] >= STOP_SAMPLE_INTERVAL_MS
        ):
            self._stop_samples.append(now)
        if len(self._stop_samples) >= STOP_CONFIRM_MIN_SAMPLES:
            if self.stop_confirmed_at_ms is None:
                self.stop_confirmed_at_ms = now
            return "STOPPED_CONFIRMED"
        return "STOP_UNCONFIRMED"

    def stop_state(self) -> str:
        if self.stop_confirmed_at_ms is not None:
            return "STOPPED_CONFIRMED"
        if self.stop_requested_at_ms is not None:
            return "STOP_REQUESTED"
        return "NONE"
