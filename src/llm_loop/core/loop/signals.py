"""LoopEngine 信号检查职责——已迁 engine_services/termination_controller.py（R9 B5-W1-02）.

原 _SignalsMixin（M53 拆分产物）于 R9 Phase 5 退役（design :475 直接消亡类）：
_append_report_once / _check_loop_signals / _check_proc_stale / _check_eval_trigger /
_check_evolution_executing / _check_pending_review 六方法逐字平移至
TerminationController（行为零变化，宿主依赖经 self._host 转发）。
本文件保留路径占位，防止旧 import 面硬断；内容随 R9 收尾批清理。
"""
