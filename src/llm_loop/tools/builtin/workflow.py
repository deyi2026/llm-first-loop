"""基础工具: workflow_run 工作流编排（EVO-20260814 P1-B，对齐 Harness 文章③多 Agent 编排）.

parallel:  一次派发多个独立子任务 → 聚合结果（编排语义 = 一次调用多个子代理，
            结果统一回传整合；当前为顺序执行，原因见下"并发说明"）。
pipeline:  步骤串联，上一步 final_answer 自动注入下一步 context（依赖链编排）。
dag:       有向无环图编排（P3-4）——步骤可声明 depends_on（id 或 0 起下标）依赖，
            按拓扑序执行；依赖步骤的 final_answer 自动注入被依赖步骤的 context；
            支持节点级轮次预算 budget_rounds（max_rounds 透传子代理）。无 graph DSL。

并发说明（诚实标注）: SubAgentRunner 共享 ToolRegistry（有状态，set_session_id 会
互相覆盖），真并发执行有竞态风险。故 parallel 当前为顺序执行 + 聚合——结果等价于
并行（各子代理独立会话互不依赖），但规避 registry 竞态；dag 亦按拓扑序顺序执行
（满足依赖即运行，不做真并发）。如后续需要真并发，须先让 registry 无状态化（演进候选）。
"""

from __future__ import annotations

from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus

MAX_STEPS = 6


def _topo_order(deps: list[list[int]], n: int) -> list[int] | None:
    """Kahn 拓扑排序；有环返回 None（调用方如实报环）."""
    indeg = [0] * n
    adj: list[list[int]] = [[] for _ in range(n)]
    for i in range(n):
        for d in deps[i]:
            indeg[i] += 1
            adj[d].append(i)
    order: list[int] = []
    queue = [i for i in range(n) if indeg[i] == 0]
    while queue:
        u = queue.pop(0)
        order.append(u)
        for v in adj[u]:
            indeg[v] -= 1
            if indeg[v] == 0:
                queue.append(v)
    return order if len(order) == n else None


class WorkflowRunTool:
    name = "workflow_run"
    description = (
        "工作流编排（EVO-20260814 P1-B，对齐 Harness 多 Agent 编排）。何时用: 需要一次派发多个"
        "子代理任务（parallel 模式：独立调研/独立计算/并行验证）、依赖链编排（pipeline 模式："
        "上一步结果自动传给下一步）或有向无环图编排（dag 模式：步骤声明 depends_on 依赖，"
        "按拓扑序执行，依赖结果自动注入；支持节点级 budget_rounds 轮次预算）时。"
        "何时不用: 单个子任务用 spawn_subagent；任务简单直接处理。"
        "注意: 子代理可用工具受限（read_file/execute_command/web_fetch/web_search/get_tool_schema/edit_file），"
        "不可改文件/改架构；递归深度上限 3。parallel/dag 当前为顺序执行+聚合（registry 有状态，"
        "真并发有竞态风险——结果等价，如实标注）。"
        "失败对策: 某步失败不阻断后续步骤，每步状态如实标注，请在父级整合。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["parallel", "pipeline", "dag"],
                "description": "编排模式: parallel=多独立子任务聚合; pipeline=步骤串联（上步结果注入下步）; "
                               "dag=有向无环图（步骤 depends_on 声明依赖，拓扑序执行，依赖结果注入，支持 budget_rounds 节点预算）",
            },
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "子任务描述（明确目标/约束/期望产出）",
                        },
                        "context": {
                            "type": "string",
                            "description": "该步额外上下文（可选；pipeline 自动追加结果；dag 自动注入依赖步骤结果）",
                        },
                        "id": {
                            "type": "string",
                            "description": "步骤唯一标识（可选；dag 模式 depends_on 引用；缺省用 0 起下标）",
                        },
                        "depends_on": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "dag 模式依赖列表（id 或 0 起下标字符串）；拓扑序保证先执行依赖",
                        },
                        "budget_rounds": {
                            "type": "integer",
                            "description": "dag/parallel/pipeline 通用节点级轮次预算（可选；透传子代理 max_rounds）",
                        },
                        "executor": {
                            "type": "string",
                            "enum": ["local", "codearts"],
                            "description": "执行器（可选；local=本地 SubAgentRunner（缺省零回归）；"
                                           "codearts=经 CodeArtsScheduler 委派远端子 Agent 执行）",
                        },
                    },
                    "required": ["task"],
                },
                "description": "子任务列表（parallel: 每项独立; pipeline: 按序串联; dag: 按依赖拓扑序）",
            },
        },
        "required": ["mode", "steps"],
    }

    def __init__(self, runner, codearts_scheduler: Any = None) -> None:
        self._runner = runner
        self._codearts_scheduler = codearts_scheduler

    def execute(self, **kwargs) -> ToolResult:
        mode = str(kwargs.get("mode", "")).strip().lower()
        steps = kwargs.get("steps") or []

        if mode not in {"parallel", "pipeline", "dag"}:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[参数错误] mode 必须是 'parallel'/'pipeline'/'dag'（收到: '{mode}'）",
                tool_call_id="",
                tool_name=self.name,
            )
        if not isinstance(steps, list) or not steps:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 缺少必填参数 'steps'（非空子任务列表）",
                tool_call_id="",
                tool_name=self.name,
            )
        if len(steps) > MAX_STEPS:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[参数错误] steps 最多 {MAX_STEPS} 步（收到 {len(steps)} 步），请在父级分批编排",
                tool_call_id="",
                tool_name=self.name,
            )

        if mode == "dag":
            return self._execute_dag(steps)
        return self._execute_linear(mode, steps)

    # ── pipeline / parallel ──
    def _execute_linear(self, mode: str, steps: list) -> ToolResult:
        prev_answer = ""  # pipeline: 上一步结果
        parts = [f"[workflow_run] mode={mode}, steps={len(steps)}（顺序执行+聚合，registry 有状态故不真并发）"]
        all_ok = True
        for i, step in enumerate(steps, start=1):
            extra = ""
            if mode == "pipeline" and prev_answer:
                extra = f"【上一步结果（步骤 {i - 1}）】\n{prev_answer}"
            result_line, refused, truncated, answer, budget_rounds = self._run_step(
                i, len(steps), step, extra
            )
            parts.append(result_line)
            if refused or truncated:
                all_ok = False
            prev_answer = answer
        return ToolResult(
            status=ToolResultStatus.SUCCESS if all_ok else ToolResultStatus.FAILURE,
            content="\n".join(parts),
            tool_call_id="",
            tool_name=self.name,
        )

    # ── dag（P3-4）：拓扑序 + 依赖注入 + 节点预算 ──
    def _execute_dag(self, steps: list) -> ToolResult:
        n = len(steps)
        ids: list[str] = []
        id_index: dict[str, int] = {}
        for i, step in enumerate(steps):
            sid = str(step.get("id", "")).strip() if isinstance(step, dict) else ""
            if sid:
                if sid in id_index:
                    return ToolResult(
                        status=ToolResultStatus.FAILURE,
                        content=f"[参数错误] dag 步骤 id 重复: '{sid}'",
                        tool_call_id="",
                        tool_name=self.name,
                    )
                id_index[sid] = i
            ids.append(sid or str(i))

        # 依赖解析：id 或 0 起下标字符串 → 索引
        deps: list[list[int]] = []
        for i, step in enumerate(steps):
            raw = step.get("depends_on") if isinstance(step, dict) else None
            resolved: list[int] = []
            if raw is not None:
                if not isinstance(raw, list):
                    return ToolResult(
                        status=ToolResultStatus.FAILURE,
                        content=f"[参数错误] 步骤 {ids[i]} 的 depends_on 必须为数组",
                        tool_call_id="",
                        tool_name=self.name,
                    )
                for d in raw:
                    dstr = str(d)
                    if dstr in id_index:
                        resolved.append(id_index[dstr])
                    elif dstr.isdigit() and 0 <= int(dstr) < n and int(dstr) != i:
                        resolved.append(int(dstr))
                    else:
                        return ToolResult(
                            status=ToolResultStatus.FAILURE,
                            content=f"[参数错误] 步骤 {ids[i]} 的 depends_on 引用未知: '{dstr}'",
                            tool_call_id="",
                            tool_name=self.name,
                        )
            # 去重 + 自依赖拒绝
            if i in resolved:
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content=f"[参数错误] 步骤 {ids[i]} 不能依赖自身",
                    tool_call_id="",
                    tool_name=self.name,
                )
            resolved = list(dict.fromkeys(resolved))
            deps.append(resolved)

        order = _topo_order(deps, n)
        if order is None:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] dag 存在循环依赖（无法拓扑排序），请检查 depends_on",
                tool_call_id="",
                tool_name=self.name,
            )

        order_str = " → ".join(ids[i] for i in order)
        parts = [f"[workflow_run] mode=dag, steps={n}（拓扑序: {order_str}；顺序执行+聚合，registry 有状态故不真并发）"]
        answers: list[str] = [""] * n
        all_ok = True
        for i in order:
            step = steps[i]
            # 依赖结果注入（与 pipeline 同款格式）
            dep_ctx = ""
            for d in deps[i]:
                if answers[d]:
                    dep_ctx += (dep_ctx and "\n\n") + f"【依赖步骤 {ids[d]} 结果】\n{answers[d]}"
            result_line, refused, truncated, answer, budget = self._run_step(
                i + 1, n, step, dep_ctx
            )
            parts.append(f"[步骤 {ids[i]}（拓扑第 {order.index(i) + 1} 位）] {result_line}")
            if refused or truncated:
                all_ok = False
            answers[i] = answer
        return ToolResult(
            status=ToolResultStatus.SUCCESS if all_ok else ToolResultStatus.FAILURE,
            content="\n".join(parts),
            tool_call_id="",
            tool_name=self.name,
        )

    # ── 单步执行（含 budget_rounds 透传；返回 行文本/refused/truncated/answer/budget） ──
    def _run_step(self, i: int, total: int, step, extra_ctx: str):
        if not isinstance(step, dict):
            return f"[步骤 {i}/{total}] [状态: failure] 步骤非对象（跳过）", True, False, "", None
        task = str(step.get("task", "")).strip()
        ctx = str(step.get("context", "")).strip()
        if not task:
            return f"[步骤 {i}/{total}] [状态: failure] 缺少 task（跳过）", True, False, "", None
        if extra_ctx:
            ctx = (ctx + "\n\n" if ctx else "") + extra_ctx
        budget: int | None = None
        raw_budget = step.get("budget_rounds")
        if raw_budget is not None:
            try:
                budget = max(1, int(raw_budget))
            except (ValueError, TypeError):
                budget = None  # 非法预算如实忽略（用默认）
        executor = str(step.get("executor", "local")).strip().lower()
        if executor == "codearts":
            return self._run_step_codearts(i, total, task, ctx, budget)
        try:
            if budget is not None:
                result = self._runner.run(task=task, context=ctx, depth=0, max_rounds=budget)
            else:
                result = self._runner.run(task=task, context=ctx, depth=0)
        except Exception as exc:  # noqa: BLE001 — 子代理异常如实标注，不阻断后续步骤
            return (
                f"[步骤 {i}/{total}] [状态: error] 子代理异常: {type(exc).__name__}: {exc}",
                True,
                False,
                "",
                budget,
            )
        st = "failure" if result.refused else "success"
        refused = result.refused
        if result.truncated:
            st += "+truncated"
        budget_note = f" budget_rounds={budget}" if budget else ""
        line = (
            f"[步骤 {i}/{total}] [状态: {st}] depth={result.depth} rounds={result.rounds}"
            f" tools={len(result.tool_calls)} tokens_in={result.tokens_in} tokens_out={result.tokens_out}{budget_note}"
        )
        if result.tool_calls:
            trace = ", ".join(f"{t['name']}:{t['status']}" for t in result.tool_calls[:6])
            line += f"\n  [工具轨迹] {trace}"
        line += f"\n  [回答] {result.final_answer[:300]}"
        line += f"\n  [回答全文 {len(result.final_answer)} 字符，如需完整见上文]"
        return line, refused, result.truncated, result.final_answer, budget

    def _run_step_codearts(self, i: int, total: int, task: str, ctx: str, budget: int | None):
        """经 CodeArtsScheduler 委派远端子 Agent 执行步骤."""
        if self._codearts_scheduler is None:
            return (
                f"[步骤 {i}/{total}] [状态: failure] CodeArts 集成未装配，无法执行远端步骤",
                True,
                False,
                "",
                budget,
            )
        try:
            import uuid as _uuid

            from llm_loop.codearts.models import DispatchTask, TimeoutBudget

            dispatch_task = DispatchTask(
                task_description=task,
                trace_id=str(_uuid.uuid4()),
                context_summary=ctx,
                timeout_budget=TimeoutBudget(exec_s=budget * 60 if budget else 1800),
            )
            session_id = ""
            try:
                from llm_loop.core.run_context import current_session_id

                session_id = current_session_id.get() or ""
            except Exception:  # noqa: BLE001
                pass
            result = self._codearts_scheduler.dispatch(dispatch_task, session_id=session_id)
        except Exception as exc:  # noqa: BLE001 — 委派异常如实标注
            return (
                f"[步骤 {i}/{total}] [状态: error] CodeArts 委派异常: {type(exc).__name__}: {exc}",
                True,
                False,
                "",
                budget,
            )
        st = result.status.value
        refused = result.status.value != "success"
        answer = result.content
        budget_note = f" budget_rounds={budget}" if budget else ""
        line = f"[步骤 {i}/{total}] [状态: {st}] executor=codearts{budget_note}"
        line += f"\n  [回答] {answer[:300]}"
        line += f"\n  [回答全文 {len(answer)} 字符]"
        return line, refused, False, answer, budget
