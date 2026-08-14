"""每轮末信号检测统一壳（M17 FR-REVIEW-AI-02/03 / design §8.2/8.3; M18 AA1 收敛）.

M18 审计（FR-AUDIT3-AI-01）: 参数信号检测（check_param_signal）已移除并移交 RULE-AI-02
"主动管理自查"（AI 经 architecture_status 自查 + adjust_strategy 调整通道）——
程序不再推送参数调整建议。本模块收敛为 eval_trigger + evolution_executing 二合一壳。

消费注入的 eval_trigger_detector/status/settings，显式传参可单测；
依赖 events.py（ArchitectureEvent）/ evaluator.py（EvalTrigger），无环依赖。
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from llm_loop.introspection.events import ArchitectureEvent, ArchitectureEventType
from llm_loop.notify import confirm  # EVO-20260810-86e777d1: 系统通知/授权确认（fail-open）

logger = logging.getLogger(__name__)


class LoopSignalDetector:
    """每轮末检测注入统一壳（eval_trigger / evolution_executing，零 LLM 往返）."""

    def __init__(
        self,
        *,
        eval_trigger_detector: Any | None = None,  # EvalTriggerDetector
        status: Any | None = None,  # ArchitectureStatusProvider
        settings: Any | None = None,  # Settings（self_eval_remind_enabled 等）
        popup_pending_review: bool = False,  # M49 RULE-AI-00: 默认不弹窗，仅 CLI 交互开启
    ) -> None:
        self._eval_trigger_detector = eval_trigger_detector
        self._status = status
        self._settings = settings
        # M49 弹窗开关: True 时 check_pending_review 保留 osascript 授权确认（仅有人值守 CLI 交互）;
        # False（默认）时仅文本事件注入（web/feishu/测试/单条 CLI 无人值守路径不阻塞循环）。
        self.popup_pending_review = popup_pending_review
        # EVO-20260810-86e777d1 缺陷修复: 已弹窗提示过的建议 ID（确认或拒绝后不再重复弹）
        self._prompted_ids: set[str] = set()

    # ── T63/T65 自我评估触发检测（逐字搬移自 loop.py:362-389，M16 收敛语义不变）──
    def check_eval_trigger(
        self,
        sess,
        rounds: int,
        *,
        milestone: bool = False,
    ) -> ArchitectureEvent | None:
        """自我评估触发检测（periodic/milestone 两个确定性触发；命中返回事件）.

        异常触发时机交 AI 自主（RULE-AI-06 子规则 3）；仅提示不强制。
        """
        if self._eval_trigger_detector is None or self._status is None or not self._status.enabled:
            logger.debug(
                "check_eval_trigger 前置条件不满足: detector=%s status=%s enabled=%s",
                self._eval_trigger_detector is not None,
                self._status is not None,
                getattr(self._status, "enabled", None),
            )
            return None
        if not getattr(self._settings, "self_eval_remind_enabled", True):
            logger.debug("check_eval_trigger: self_eval_remind_enabled=False")
            return None
        try:
            trigger = self._eval_trigger_detector.check(
                rounds=rounds,
                task_completed=milestone,
            )
            if trigger is None:
                logger.debug("check_eval_trigger: trigger=None (rounds=%s milestone=%s)", rounds, milestone)
                return None
            logger.debug("check_eval_trigger: trigger=%s (rounds=%s milestone=%s)", trigger.trigger, rounds, milestone)
            return ArchitectureEvent(
                event_type=ArchitectureEventType.DEGRADATION,
                fact=trigger.fact,
                reason=trigger.reason,
                suggestion=trigger.suggestion,
            )
        except Exception:
            logger.warning("自我评估触发检测异常（fail-open）", exc_info=True)
            return None

    # ── G2 executing 演进待办检测（design 8.2.2）──
    def check_evolution_executing(self, store) -> ArchitectureEvent | None:
        """executing 演进待办检测（读取失败 fail-open → None，不阻断）.

        有 executing 演进 → 返回 DEVIATION 事件（含 id + evolution_complete 引导）。
        """
        try:
            if store is None:
                return None
            items = store.list(status="executing")
        except OSError:
            return None  # 读取失败 → 不注入提醒（fail-open，DFX-REL-08）
        if not items:
            return None
        first = items[0]
        return ArchitectureEvent(
            event_type=ArchitectureEventType.DEVIATION,
            fact=f"存在 executing 演进建议（{first.get('id', '?')}）",
            reason="已 accepted 且权限允许自动执行，等待落地修正动作",
            suggestion=(
                "可经修正工具落地执行，完成后调用 evolution_complete 登记'已完成 + 验证结论'"
                "（RULE-AI-06 子规则 4）；不执行不阻断本循环。"
            ),
        )

    # ── EVO-20260810-86e777d1: pending_review 演进授权确认弹窗 ──
    def check_pending_review(self, store) -> ArchitectureEvent | None:
        """pending_review 演进检测（授权确认弹窗；确认即自动审阅 accepted）.

        有 pending_review 演进 → 弹授权窗（确认/拒绝）：
        - 用户点确认 → 调 store.review(id, accepted) 自动审阅（无需复制命令到终端）
        - 用户点拒绝 / 弹窗不可用 → 降级为事件（文本注入引导），不阻断循环
        """
        try:
            if store is None:
                return None
            items = store.list(status="pending_review")
        except OSError:
            return None  # 读取失败 → 不注入提醒（fail-open，DFX-REL-08）
        if not items:
            return None
        first = items[0]
        sid = str(first.get("id", "?"))
        content_preview = str(first.get("content", ""))[:60]
        # 缺陷修复: 已提示过 或 已忽略（幽灵）的建议不再重复弹窗
        # EVO-20260811-f94e5306 补丁: 幽灵建议（确认后存储不存在）持久化忽略，防反复弹
        if sid in self._prompted_ids or self._is_ghost_ignored(store, sid, content_preview):
            return None
        # M49 RULE-AI-00: 默认不弹窗（web/feishu/测试/单条 CLI 无人值守路径）。
        # 仅文本事件注入待审事实（AI 可见，不静默丢失），不阻塞循环、不自动审阅、不写忽略清单。
        if not self.popup_pending_review:
            return ArchitectureEvent(
                event_type=ArchitectureEventType.DEVIATION,
                fact=f"存在待审阅演进建议（{sid}）",
                reason="未启用弹窗授权（非交互路径），等待人工审阅",
                suggestion=(
                    "可执行 CLI: evolve-review <id> accepted|rejected；"
                    "多条待审阅可逐条处理（不审阅不阻断本循环）。"
                ),
            )
        # 授权确认弹窗（阻塞等待用户选择；失败/超时 → False → 降级引导）
        try:
            granted = confirm(
                "LLM-First Loop: 演进审阅授权",
                f"待审阅建议: {sid}\n{content_preview}\n\n是否授权 accepted 审阅？",
            )
        except Exception:  # noqa: BLE001 — 弹窗异常降级，不阻断
            logger.warning("演进审阅授权弹窗异常（fail-open）", exc_info=True)
            granted = False
        self._prompted_ids.add(sid)  # 记录已提示（确认或拒绝均不重复弹）
        if granted and store is not None:
            try:
                target = store.review(sid, "accepted")
                if target is None:
                    # EVO-20260811-f94e5306 补丁: 幽灵建议（确认但存储不存在）→ 持久化忽略防反复弹
                    self._ignore_ghost(store, sid, content_preview)
                    return ArchitectureEvent(
                        event_type=ArchitectureEventType.DEVIATION,
                        fact=f"幽灵建议 {sid} 已确认但存储层不存在，已加入忽略清单（防反复弹窗）",
                        reason="store.review 返回 None（建议未落盘）",
                        suggestion="该建议未落盘，无需人工审阅；后续不再弹窗。",
                    )
                return ArchitectureEvent(
                    event_type=ArchitectureEventType.DEVIATION,
                    fact=f"演进建议 {sid} 已经授权弹窗审阅为 accepted",
                    reason="用户在授权弹窗点击确认",
                    suggestion="已自动 accepted；如权限允许将触发执行（EVOLVE-05）。",
                )
            except Exception as exc:  # noqa: BLE001
                # 审阅异常 → 持久化忽略（防幽灵反复弹），如实标注
                self._ignore_ghost(store, sid, content_preview)
                logger.warning("授权后自动审阅失败（fail-open）: %s", exc)
                return ArchitectureEvent(
                    event_type=ArchitectureEventType.DEVIATION,
                    fact=f"演进建议 {sid} 授权确认但自动审阅失败: {exc}（已加入忽略清单防反复弹）",
                    reason="store.review 执行异常",
                    suggestion="可执行 CLI: evolve-review <id> accepted 人工补审。",
                )
        # 拒绝/降级 → 文本引导（不重复弹窗；下次仅静默，如需审阅走 CLI）
        return ArchitectureEvent(
            event_type=ArchitectureEventType.DEVIATION,
            fact=f"存在待审阅演进建议（{sid}）",
            reason="未获授权弹窗确认（拒绝/不可用），等待人工审阅",
            suggestion=(
                "可执行 CLI: evolve-review <id> accepted|rejected；"
                "多条待审阅可逐条处理（不审阅不阻断本循环）。"
            ),
        )


    # ── EVO-20260811-f94e5306 补丁: 幽灵建议防御（确认后存储不存在的建议持久化忽略）──
    @staticmethod
    def _ghost_ignore_path(store) -> Path:
        """忽略清单路径（与 store 同目录；store 无 _path 时用 DATA_DIR/audit 兜底）."""
        p = getattr(store, "_path", None)
        if p:
            return Path(p).parent / "pending_ignored.jsonl"
        return Path(os.environ.get("DATA_DIR", "./data")) / "audit" / "pending_ignored.jsonl"

    def _is_ghost_ignored(self, store, sid: str, content_preview: str = "") -> bool:
        """是否在忽略清单（按 id 或内容指纹匹配；fail-open: 读取失败视为未忽略）.

        内容指纹匹配（EVO-20260811 升级）: 并行会话换 ID 重复提交同主题建议时，
        以忽略清单中记录的内容前 20 字符为指纹（如"启用语义检索能力以提升"），
        该指纹命中当前建议内容 → 视为同主题幽灵 → 不再反复弹窗。
        """
        try:
            path = self._ghost_ignore_path(store)
            if not path.exists():
                return False
            import json as _json

            for line in path.read_text(encoding="utf-8").splitlines():
                if sid in line:
                    return True
                if not content_preview:
                    continue
                try:
                    rec = _json.loads(line)
                except Exception:  # noqa: BLE001 — 单行损坏跳过
                    rec = {}
                ign_content = str(rec.get("content", ""))
                # 指纹：忽略内容的开头 20 字符（足够独特且避免长度差导致的子串失配）
                if ign_content[:20] and ign_content[:20] in content_preview:
                    return True
        except OSError as exc:  # fail-open：读忽略清单失败视为无
            logger.debug("读忽略清单失败（fail-open）: %s", exc)
        return False

    def _ignore_ghost(self, store, sid: str, content_preview: str = "") -> None:
        """写入忽略清单（含内容指纹；fail-open: 记录失败不阻断循环）."""
        try:
            path = self._ghost_ignore_path(store)
            path.parent.mkdir(parents=True, exist_ok=True)
            import json as _json

            record = {
                "ts": datetime.now(UTC).isoformat(),
                "sid": sid,
                "reason": "ghost",
                "content": content_preview[:60],
            }
            with open(path, "a", encoding="utf-8") as f:
                f.write(_json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:  # fail-open：写忽略清单失败不阻断循环
            logger.debug("写忽略清单失败（fail-open）: %s", exc)
