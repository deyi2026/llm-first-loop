"""P0-5(2026-08-15): per-run 状态分桶 mixin（审计发现 #7 —— LoopEngine 可重入修复）.

从 engine.py 拆出（对齐 M53 职责 mixin 拆分纪律，守卫 engine.py 体量）：

- ``_RunState``: 单个会话的可变运行状态（停滞指纹/overflow 计数/预警标志/
  快照节流/breakdown/build_info），按 session_id 分桶，跨会话并发 run 不共享。
- 桶解析与一致性锁已对象化为 ``engine_services/run_state.RunStateManager``
  （B5-W4-03：_RunStateMixin 属性 shim 退役，读写触点直迁
  ``self._run_state().<field>`` 显式形态；guard 同时保护桶表与 run 绑定表）。

本模块只保留两个显式 dataclass（B5-W4-03 任务口径：runstate.py 留显式 dataclass）：
``_RunState``（per-session 桶）/ ``RunState``（单次 run 显式状态对象）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from llm_loop.core.loop.err1210 import InjectedEntry, SlotKind
    from llm_loop.core.message import Message


@dataclass
class _RunState:
    """单个会话一次/多次 run 的可变运行状态（按 session_id 分桶，跨会话不共享）.

    - stagnation_state: 实时停滞指纹追踪（engine/tool_exec 共用）
    - overflow_reinject_count: overflow 反馈注入次数（同一 run 最多 1 次）
    - context_warning_injected / round_warning_injected: 预警一次性标志
    - last_snapshot_count: 会话状态快照节流（跨 run 保留——同会话多次 run 共享节流语义）
    - last_breakdown / last_build_info: 上下文占用分解快照（architecture_status 消费）
    """

    stagnation_state: dict = field(
        default_factory=lambda: {
            "fp": None, "count": 0, "reminded": False,
            "empty_count": 0, "empty_reminded": False,
        }
    )
    overflow_reinject_count: int = 0
    context_warning_injected: bool = False
    round_warning_injected: bool = False
    exhaustion_decision_used: bool = False  # 轮次耗尽决策轮一次性标志（2026-08-15）
    last_snapshot_count: int = 0
    last_breakdown: Any = None
    last_build_info: Any = None
    # T5(GPT 复审 P0 串台修复): turn 身份与预算归因入 per-session 桶
    # （此前是 Engine 实例全局 self._current_turn_ref/_last_budget_info——
    #   同一 Engine 服务多 session（Web/飞书/Headless）时并发 run 互相覆盖）
    current_turn_ref: int | None = None
    last_budget_info: Any = None
    # err1210 P0-A(2026-08-28) + Injection Governance R4: 恢复状态字段入
    # per-session 桶（此前 Engine 实例全局 self._xxx——同一 Engine 服务多 session
    # 时并发 run 互相覆盖；property shim 保旧名，读写落当前会话桶）。
    last_build_injections: list[InjectedEntry] = field(default_factory=list)
    compact_event_seq: int = 0
    compact_event_was_compacted: bool = False
    last_build_defer_replayed: bool = False
    deferred_replay_refs: list[tuple[SlotKind, Message]] = field(default_factory=list)
    deferred_replay_slots: set[str] = field(default_factory=set)
    # INJECTION-GOVERNANCE R4: recovery lifecycle is session-scoped.  These were
    # previously Engine-global, which allowed concurrent sessions to share the one-shot
    # counter/sequence/pending recovery slot.
    err1210_run_seq: int = 0
    auto_continue_1210: int = 0
    program_recovery_tail_message: Message | None = None


@dataclass
class RunState:
    """单次 run 的显式状态对象（R9-P5-03 显式状态流；B5-W1-01 冻结字段面）.

    与 per-session 桶 ``_RunState`` 的生命周期区分：桶字段跨 run 保留
    （快照节流/恢复序号/turn 身份——P0-5/T5 串台修复语义），本对象随单次
    run 创建销毁（design §T6-A/创建销毁策略）。七 service（RunCoordinator/
    TerminationController/ToolCycle/RunFinalizer…）组件间通信一律经此对象，
    禁止直接读写 engine 实例属性（design §469 拦截判据）。

    字段面 = ``_run_stream_inner`` 前段 :310-:497 局部态收编（B5-W1-01 冻结；
    切换渐进：tool_trace 可变对象先行真绑定，其余字段随波次 W1-02+ 逐项接管，
    接管前函数内裸局部仍是真相源——本对象持同值初值镜像）。
    """

    # ── 轮次与终止（TerminationController authority 面，W1-02 接管）──
    rounds: int = 0
    run_end_reason: str = "completed"  # 各结束分支标记；统一出口 run.end 事件用
    cancel_reason: str = ""  # ""=未取消；user_stop/runner_stop（结构化可审计）
    # ── 停滞与预警（:328-:338 run 开始重置语义；W1-02 经 TerminationController 消费；
    #    接管前桶（shim）为真相源，本字段仅持同值初值）──
    stagnation_state: dict = field(
        default_factory=lambda: {
            "fp": None,
            "count": 0,
            "reminded": False,
            "empty_count": 0,
            "empty_reminded": False,
        }
    )
    context_warning_injected: bool = False
    # ── 工具循环（ToolCycle authority 面；W1-01 即真绑定——list 可变对象同源）──
    tool_trace: list[dict] = field(default_factory=list)
    # ── 收尾产出（RunFinalizer authority 面，W4-01 接管）──
    final_answer: str = ""
    verification_note: str | None = None
    truncation_noted: bool = False
    resp: Any = None  # M20 THK-04: 最终回答轮思考链来源（异常/停滞路径 None）
    # ── KPI 观测（_KpiMixin 消费面，W5-02 评估裁决时接管）──
    run_started_at: float = 0.0
    model_used: str = ""  # M51: 本轮实际使用的模型标签（每轮 LLM 调用时刷新）
    tokens_in: int = 0  # M52
    tokens_out: int = 0
    tokens_cache_hit: int = 0  # M58: 前缀缓存命中 token（省钱可观测）
    llm_ms_total: float = 0.0  # M59: LLM 调用总耗时（首 token 埋点聚合）
    ttft_first_ms: float | None = None  # M59: 首个 token 延迟
