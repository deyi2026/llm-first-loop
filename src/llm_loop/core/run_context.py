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

# P3 Same-Session Cross-Run ownership: exact execution generation for the active run.
# BackgroundRunner seeds this with RunHandle.run_generation; direct/synchronous Engine runs
# mint one generation at admission.  Worker pools use copy_context(), so late callbacks can
# retain their *origin* generation instead of borrowing whichever run is current later.
current_run_generation: contextvars.ContextVar[str] = contextvars.ContextVar(
    "llm_loop_current_run_generation", default=""
)

# CR-R1.1（审查项7）: 当前 LLM 轮次（engine run 循环每轮 set；cognitive
# telemetry 归因用——此前 packet_compile 事件的 round 恒 0，attribution 断裂）
current_round_no: contextvars.ContextVar[int] = contextvars.ContextVar(
    "llm_loop_current_round_no", default=0
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

# 当前请求推理等级 override。只存 request-local 值，不写共享 LLMClient 实例属性；
# 空串表示使用该 provider client 自身的装配默认。
current_reasoning_effort: contextvars.ContextVar[str] = contextvars.ContextVar(
    "llm_loop_current_reasoning_effort", default=""
)

# 当前请求 reasoning 模式 override。值域: auto/off/on；空串表示调用方未显式指定，
# 等价于 auto（保留 provider/operator 默认，不做内容启发式判断）。
current_reasoning_mode: contextvars.ContextVar[str] = contextvars.ContextVar(
    "llm_loop_current_reasoning_mode", default=""
)

# 当前工具发现作用域。None 表示完整 registry；子代理等受限执行域可设置为
# frozenset(tool_names)，确保 provider 投影与 get_tool_schema 发现面一致。
current_tool_discovery_scope: contextvars.ContextVar[frozenset[str] | None] = (
    contextvars.ContextVar("llm_loop_current_tool_discovery_scope", default=None)
)

# EVO-20261012-65475c5a (E5): child 会话内的取消事件与等待预算。
# runner 在 child context 内注入（父会话保持 None，互不影响）；
# wait 工具读取它们实现「可取消的只读等待 + 每 child 累计上限」。
child_cancel_event: contextvars.ContextVar[object | None] = (
    contextvars.ContextVar("llm_loop_child_cancel_event", default=None)
)
# EVO-20261012-32e89b46: 累计预算改为共享可变载体。旧实现 ContextVar[float] 的
# set() 写入 registry 每次派发 copy_context() 拍出的副本即弃（live 实测：连续
# wait 回执累计恒为单次值，600s 累计上限形同虚设）。与 cancel_event 同模式：
# contextvar 只携带对象引用（引用跨副本共享），本体跨调用持久，wait 原位累加。
child_wait_budget_used: contextvars.ContextVar[object | None] = (
    contextvars.ContextVar("llm_loop_child_wait_budget_used", default=None)
)


class WaitBudget:
    """每 child 会话一个的 wait 累计预算载体（runner 注入，wait 原位累加）."""

    __slots__ = ("used",)

    def __init__(self, used: float = 0.0) -> None:
        self.used = float(used)

# ERC R0/Phase2 shadow only: tools preserve their pre-trim observation only when an explicit
# registry shadow hook is installed. Default false keeps legacy memory/runtime behavior unchanged.
current_evidence_shadow_enabled: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "llm_loop_current_evidence_shadow_enabled", default=False
)

# ERC Phase3 enforce only: when true, participating tools must return the unprojected
# observation to ToolRegistry and skip their legacy internal trim.  Registry captures it
# durably before any model-visible projection.
current_evidence_enforce_enabled: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "llm_loop_current_evidence_enforce_enabled", default=False
)


def workspace_base() -> str:
    """工具相对路径/命令默认 cwd 的基准目录（工作区根优先，空则进程 cwd）."""
    root = current_workspace_root.get()
    if root:
        return root
    import os

    return os.getcwd()
