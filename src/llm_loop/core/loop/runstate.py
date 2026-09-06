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
from typing import Any


@dataclass
class _RunState:
    """单个会话一次/多次 run 的可变运行状态（按 session_id 分桶，跨会话不共享）.

    - stagnation_state: 历史字段名；仅保存精确工具调用/连续空结果观测，不具终止权
    - overflow_reinject_count: overflow 反馈注入次数（同一 run 最多 1 次）
    - context_warning_injected / round_warning_injected: 预警一次性标志
    - last_breakdown / last_build_info: 上下文占用分解快照（architecture_status 消费）
    """

    stagnation_state: dict = field(
        default_factory=lambda: {
            "fp": None, "count": 0, "reminded": False,
            "empty_count": 0, "empty_reminded": False,
        }
    )
    # P1-B: exact provider-callable surface is a factual per-session snapshot only.
    # It never grants permission or changes future projection; get_tool_schema may use
    # the registry/runtime-health facts directly without a promotion state machine.
    current_provider_callable_tools: set[str] = field(default_factory=set)
    # Current-run emergency fallback fact for user delivery only; never prompt authority.
    fallback_receipt: dict[str, str] | None = None
    overflow_reinject_count: int = 0
    context_warning_injected: bool = False
    round_warning_injected: bool = False
    exhaustion_decision_used: bool = False  # 轮次耗尽决策轮一次性标志（2026-08-15）
    last_breakdown: Any = None
    last_build_info: Any = None
    # 2026-09-03 cache-boundary P1: provider cache window 是跨 run、按 session 的事实。
    # 旧 engine._last_cache_window 为全局单槽，多会话并发会互相覆盖；本桶与现有
    # current_session_id authority 同源，供下一 build 保护上一轮已确认 cached prefix。
    last_cache_window: Any = None
    last_cache_window_model: str = ""
    last_cache_window_turn_ref: int | None = None
    last_cache_window_stable_fp: str = ""
    cache_gate_stable_fp: str = ""
    # Exact fingerprint of the actual projected tool schema array for the current
    # provider attempt. Tool schema bytes are part of the request structure and
    # therefore must participate in cache-prefix stability even though they are
    # not model-visible chat messages.
    cache_gate_tools_fp: str = ""
    # Monotonic provider-prefix epoch for this session. It advances only when an
    # already-observed provider prefix is structurally replaced (model/stable
    # prefix change) or compaction explicitly resets a protected cache boundary.
    cache_prefix_epoch: int = 0
    cache_gate_hint: str | None = None
    # Immediate one-shot continuity for the next genuine human ingress after an
    # interrupted/crashed provider stream.  This is transient provider-view state,
    # never a program-authored conversational message: {text_tail, reasoning_tail,
    # provider, model, source, partial_sha256}.  It is rebuilt from durable storage
    # at run ingress and reset every run.
    interruption_resume: dict[str, Any] | None = None
    # T5(GPT 复审 P0 串台修复): turn 身份与预算归因入 per-session 桶
    # （此前是 Engine 实例全局 self._current_turn_ref/_last_budget_info——
    #   同一 Engine 服务多 session（Web/飞书/Headless）时并发 run 互相覆盖）
    current_turn_ref: int | None = None
    last_budget_info: Any = None
    # Last successful provider request observability. Kept per-session and exposed
    # only through architecture_status/tooling; never injected into model prompts.
    last_request_usage: dict[str, Any] | None = None
    # Physical compaction facts remain independent from ERR1210 recovery.
    compact_event_seq: int = 0
    compact_event_was_compacted: bool = False
    # P2-B: one bounded structural ERR1210 transform opportunity per run.
    err1210_run_seq: int = 0


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
