"""LoopEngine overflow 处理职责——已迁 engine_services/termination_controller.py（R9 B5-W1-02）.

原 _OverflowMixin（M53 拆分 + R8.24-B B-D5 重设计产物）于 R9 Phase 5 退役
（design :475 直接消亡类）：_handle_overflow / _reset_overflow_state 两方法与
_OVERFLOW_SHRINK_FACTOR 常量逐字平移至 TerminationController（行为零变化）。
本文件保留路径占位，防止旧 import 面硬断；内容随 R9 收尾批清理。
"""
