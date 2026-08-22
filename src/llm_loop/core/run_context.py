"""P0-5(2026-08-15): 每会话运行上下文（审计发现 #7 —— LoopEngine 可重入修复）.

背景：Web 端"同会话串行、不同会话并行"，FastAPI 同步端点在线程池中并发执行
engine.run。引擎/注册表/修正上下文的 per-run 可变状态（停滞指纹、overflow 计数、
registry._session_id 等）原是实例属性，跨会话并发 run 互相污染（串台熔断、
预警互吞、归档/变更日志归错会话）。

机制：contextvars 承载"当前执行上下文属于哪个会话的 run"；execute_many 的
只读线程池经 ``contextvars.copy_context().run`` 逐任务显式传播，跨线程可见性
精确到会话级。无上下文的老调用方（CLI 直跑/测试桩）读到默认空串，走既有
显式字段回退——零回归。
"""

from __future__ import annotations

import contextvars

# 当前执行上下文所属的会话 id（run_stream 入口 set；只读工具池经 copy_context 传播）
current_session_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "llm_loop_current_session_id", default=""
)

# 当前工作区根目录（工作区管理：工具相对路径/命令默认 cwd 跟随；无工作区 → 空串走进程 cwd）
current_workspace_root: contextvars.ContextVar[str] = contextvars.ContextVar(
    "llm_loop_current_workspace_root", default=""
)

# EVO-20260822-b3e7105e: 当前执行上下文所属的模型标签（engine 每轮按 planned_label 设置；
# 工具输出分层按模型预算联动——local 收紧摘要阈值/首尾窗口，云端维持全局配置零回归。
# 无上下文的老调用方（CLI 直跑/测试桩）读到空串 → 走全局配置回退）
current_model_label: contextvars.ContextVar[str] = contextvars.ContextVar(
    "llm_loop_current_model_label", default=""
)


def workspace_base() -> str:
    """工具相对路径/命令默认 cwd 的基准目录（工作区根优先，空则进程 cwd）."""
    root = current_workspace_root.get()
    if root:
        return root
    import os

    return os.getcwd()
