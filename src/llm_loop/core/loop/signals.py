"""LoopEngine 信号检查 mixin（M53 拆分: loop.py 1087 行→按职责分文件，纯重构行为零变化）.

合并自评触发 / executing 演进待办 / pending_review 待审三项检测为一次调用；
均仅"事实提醒"不强制，触发判断与决策权归 AI（RULE-AI-10 每轮自主检查清单）。
"""

# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
# (mixin 模式: self 属性来自混入类 LoopEngine.__init__，pyright 无法静态解析，故文件级关闭这两条；参数/返回类型等其余检查保留)


from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llm_loop.core.loop.engine import LoopEngine


class _SignalsMixin:
    def _append_report_once(self: LoopEngine, sess, msg) -> bool:
        """EVO-20260827-f42496bc: 上报注入内容级幂等 append（去重兜底）.

        实证 02:35:21 同轮 flush 7 条架构上报、其中 4 条内容完全相同（冷却 key
        变化/多路径调用穿透 60s 冷却）→ 存储层每轮膨胀重复 system 消息 → 加速
        触顶压缩（压缩轮必 miss）。兜底: 尾部 12 条内已有相同 role+content 的
        注入则跳过 append（首条保留，信息零丢失）。
        """
        if msg is None:
            return False
        msg.metadata = {**(msg.metadata or {}), "injected_system": True}
        _content = msg.content or ""
        for _pm in sess.messages[-12:]:
            _meta = getattr(_pm, "metadata", None) or {}
            if (
                getattr(_pm, "role", "") == "system"
                and _meta.get("injected_system")
                and (getattr(_pm, "content", "") or "") == _content
            ):
                return False
        sess.messages.append(msg)
        return True

    def _check_loop_signals(self: LoopEngine, sess, rounds: int) -> None:
        """每轮末信号检测统一入口（M56 收敛，ANALYSIS-20260811）.

        合并自评触发 / executing 演进待办 / pending_review 待审三项检测为一次调用；
        均仅"事实提醒"不强制，触发判断与决策权归 AI（RULE-AI-10 每轮自主检查清单）。
        """
        self._check_eval_trigger(sess, rounds)
        self._check_evolution_executing(sess)
        self._check_pending_review(sess)
        self._check_proc_stale(sess)  # EVO-20260815-69ac0bd0

    def _check_proc_stale(self: LoopEngine, sess) -> None:
        """EVO-20260815-69ac0bd0: 进程代码时效提醒（每轮末，仅提示不强制）.

        复用 LoopSignalDetector 冷却（每进程仅提示一次）；无 stale/检测关闭 → 不注入。
        """
        if self.loop_signal_detector is None:
            return
        event = self.loop_signal_detector.check_proc_stale()
        if event is None:
            return
        msg = self._report(
            event.event_type, fact=event.fact, reason=event.reason, suggestion=event.suggestion
        )
        if msg is not None:
            self._append_report_once(sess, msg)  # EVO-20260827-f42496bc: 内容级幂等 append

    def _check_eval_trigger(self: LoopEngine, sess, rounds: int, *, milestone: bool = False) -> None:
        """自我评估触发检测（T63/T65: 每轮末 + run 完成里程碑）.

        M16 审计（FR-AUDIT-AI-04/08）: 只保留 periodic/milestone 两个确定性触发；
        M17 FR-REVIEW-AI-03: 检测逻辑搬移至 introspection/loop_signals.py（薄壳委托）。
        命中且冷却通过 → 注入 [自我评估提醒]（仅提示不强制，EVAL-03；决策权归 LLM）。
        """
        if self.loop_signal_detector is None:
            return
        event = self.loop_signal_detector.check_eval_trigger(sess, rounds, milestone=milestone)
        if event is None:
            return
        msg = self._report(
            event.event_type, fact=event.fact, reason=event.reason, suggestion=event.suggestion
        )
        if msg is not None:
            self._append_report_once(sess, msg)  # EVO-20260827-f42496bc: 内容级幂等 append

    def _check_evolution_executing(self: LoopEngine, sess) -> None:
        """M17 FR-REVIEW-AI-02: executing 演进待办提醒（每轮末，仅提示不强制）.

        复用 EventReporter 冷却（key 含 fact 前缀去重）；无 executing / 读取失败 → 不注入。
        """
        if self.loop_signal_detector is None or self.status is None or not self.status.enabled:
            return
        event = self.loop_signal_detector.check_evolution_executing(self.evolution_store)
        if event is None:
            return
        msg = self._report(
            event.event_type, fact=event.fact, reason=event.reason, suggestion=event.suggestion
        )
        if msg is not None:
            self._append_report_once(sess, msg)  # EVO-20260827-f42496bc: 内容级幂等 append

    def _check_pending_review(self: LoopEngine, sess) -> None:
        """EVO-20260810-86e777d1: pending_review 演进弹窗提醒（每轮末，仅提示不强制）.

        复用 EventReporter 冷却；无 pending_review / 读取失败 → 不注入。
        """
        if self.loop_signal_detector is None or self.status is None or not self.status.enabled:
            return
        event = self.loop_signal_detector.check_pending_review(self.evolution_store)
        if event is None:
            return
        msg = self._report(
            event.event_type, fact=event.fact, reason=event.reason, suggestion=event.suggestion
        )
        if msg is not None:
            self._append_report_once(sess, msg)  # EVO-20260827-f42496bc: 内容级幂等 append
