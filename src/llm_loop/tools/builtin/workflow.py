"""基础工具: workflow_run 工作流编排（EVO-20260814 P1-B，对齐 Harness 文章③多 Agent 编排）.

parallel:  一次派发多个独立子任务 → 聚合结果（编排语义 = 一次调用多个子代理，
           结果统一回传整合；当前为顺序执行，原因见下"并发说明"）。
pipeline:  步骤串联，上一步 final_answer 自动注入下一步 context（依赖链编排）。

并发说明（诚实标注）: SubAgentRunner 共享 ToolRegistry（有状态，set_session_id 会
互相覆盖），真并发执行有竞态风险。故 parallel 当前为顺序执行 + 聚合——结果等价于
并行（各子代理独立会话互不依赖），但规避 registry 竞态。如后续需要真并发，
须先让 registry 无状态化（演进候选）。
"""

from __future__ import annotations

from llm_loop.core.message import ToolResult, ToolResultStatus


class WorkflowRunTool:
    name = "workflow_run"
    description = (
        "工作流编排（EVO-20260814 P1-B，对齐 Harness 多 Agent 编排）。何时用: 需要一次派发多个"
        "子代理任务（parallel 模式：独立调研/独立计算/并行验证）或依赖链编排（pipeline 模式："
        "上一步结果自动传给下一步）时。何时不用: 单个子任务用 spawn_subagent；任务简单直接处理。"
        "注意: 子代理可用工具受限（read_file/execute_command/web_fetch/web_search/get_tool_schema），"
        "不可改文件/改架构；递归深度上限 3。parallel 当前为顺序执行+聚合（registry 有状态，"
        "真并发有竞态风险——结果等价，如实标注）。"
        "失败对策: 某步失败不阻断后续步骤，每步状态如实标注，请在父级整合。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["parallel", "pipeline"],
                "description": "编排模式: parallel=多独立子任务聚合; pipeline=步骤串联（上步结果注入下步）",
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
                            "description": "该步额外上下文（可选；pipeline 模式会自动追加上一步结果）",
                        },
                    },
                    "required": ["task"],
                },
                "description": "子任务列表（parallel: 每项独立; pipeline: 按序串联）",
            },
        },
        "required": ["mode", "steps"],
    }

    def __init__(self, runner) -> None:
        self._runner = runner

    def execute(self, **kwargs) -> ToolResult:
        mode = str(kwargs.get("mode", "")).strip().lower()
        steps = kwargs.get("steps") or []

        if mode not in {"parallel", "pipeline"}:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[参数错误] mode 必须是 'parallel' 或 'pipeline'（收到: '{mode}'）",
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
        if len(steps) > 6:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[参数错误] steps 最多 6 步（收到 {len(steps)} 步），请在父级分批编排",
                tool_call_id="",
                tool_name=self.name,
            )

        prev_answer = ""  # pipeline: 上一步结果
        parts = [f"[workflow_run] mode={mode}, steps={len(steps)}（顺序执行+聚合，registry 有状态故不真并发）"]
        all_ok = True
        for i, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                parts.append(f"[步骤 {i}/{len(steps)}] [状态: failure] 步骤非对象（跳过）")
                all_ok = False
                continue
            task = str(step.get("task", "")).strip()
            ctx = str(step.get("context", "")).strip()
            if not task:
                parts.append(f"[步骤 {i}/{len(steps)}] [状态: failure] 缺少 task（跳过）")
                all_ok = False
                continue
            # pipeline: 上一步结果自动注入 context
            if mode == "pipeline" and prev_answer:
                ctx = (ctx + "\n\n" if ctx else "") + f"【上一步结果（步骤 {i-1}）】\n{prev_answer}"
            try:
                result = self._runner.run(task=task, context=ctx, depth=0)
            except Exception as exc:  # noqa: BLE001 — 子代理异常如实标注，不阻断后续步骤
                parts.append(f"[步骤 {i}/{len(steps)}] [状态: error] 子代理异常: {type(exc).__name__}: {exc}")
                all_ok = False
                continue
            st = "failure" if result.refused else "success"
            if result.refused:
                all_ok = False
            if result.truncated:
                st += "+truncated"
                all_ok = False
            prev_answer = result.final_answer
            parts.append(
                f"[步骤 {i}/{len(steps)}] [状态: {st}] depth={result.depth} rounds={result.rounds} "
                f"tools={len(result.tool_calls)} tokens_in={result.tokens_in} tokens_out={result.tokens_out}"
            )
            if result.tool_calls:
                trace = ", ".join(f"{t['name']}:{t['status']}" for t in result.tool_calls[:6])
                parts.append(f"  [工具轨迹] {trace}")
            parts.append(f"  [回答] {result.final_answer[:300]}")
            parts.append(f"  [回答全文 {len(result.final_answer)} 字符，如需完整见上文]")

        return ToolResult(
            status=ToolResultStatus.SUCCESS if all_ok else ToolResultStatus.FAILURE,
            content="\n".join(parts),
            tool_call_id="",
            tool_name=self.name,
        )
