"""EVO-20260814 P1-B: workflow_run 工作流编排（对齐 Harness 多 Agent 编排）.

parallel:  一次派发多个独立子任务 → 聚合结果（顺序执行+聚合，诚实标注并发限制）
pipeline:  步骤串联，上一步 final_answer 自动注入下一步 context
"""

from __future__ import annotations

from dataclasses import dataclass, field

from llm_loop.core.message import ToolResultStatus
from llm_loop.tools.builtin.workflow import WorkflowRunTool


@dataclass
class FakeResult:
    final_answer: str = ""
    refused: bool = False
    truncated: bool = False
    depth: int = 0
    rounds: int = 1
    tool_calls: list = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []  # (task, context)

    def run(self, task: str, context: str = "", depth: int = 0) -> FakeResult:
        self.calls.append((task, context))
        return FakeResult(final_answer=f"result_of:{task[:12]}", depth=depth, rounds=1)


def test_parallel_runs_each_step_and_aggregates():
    """parallel: 每步独立执行，各自结果聚合，不互相注入 context."""
    runner = FakeRunner()
    tool = WorkflowRunTool(runner)
    res = tool.execute(
        mode="parallel",
        steps=[
            {"task": "调研 A 方案", "context": "背景1"},
            {"task": "调研 B 方案", "context": "背景2"},
        ],
    )
    assert res.status == ToolResultStatus.SUCCESS
    assert len(runner.calls) == 2
    # 无跨步注入（parallel 各步 context 独立）
    assert "上一步结果" not in runner.calls[1][1]
    assert "调研 A 方案" in runner.calls[0][0]
    assert "调研 B 方案" in runner.calls[1][0]
    assert "result_of:调研 A" in res.content
    assert "result_of:调研 B" in res.content


def test_pipeline_injects_prev_answer_to_next():
    """pipeline: 上一步 final_answer 自动注入下一步 context."""
    runner = FakeRunner()
    tool = WorkflowRunTool(runner)
    tool.execute(
        mode="pipeline",
        steps=[
            {"task": "步骤一：收集需求"},
            {"task": "步骤二：基于需求设计"},
        ],
    )
    assert len(runner.calls) == 2
    assert "上一步结果" in runner.calls[1][1]
    assert "result_of:步骤一：收集" in runner.calls[1][1]
    # 第一步无上步结果
    assert "上一步结果" not in runner.calls[0][1]


def test_pipeline_merges_user_context_with_prev():
    """pipeline: 用户 context 与上步结果合并注入."""
    runner = FakeRunner()
    tool = WorkflowRunTool(runner)
    tool.execute(
        mode="pipeline",
        steps=[
            {"task": "步骤一"},
            {"task": "步骤二", "context": "用户额外背景"},
        ],
    )
    ctx2 = runner.calls[1][1]
    assert "用户额外背景" in ctx2
    assert "上一步结果" in ctx2


def test_invalid_mode_rejected():
    """非法 mode 拒绝."""
    res = WorkflowRunTool(FakeRunner()).execute(mode="bogus", steps=[{"task": "x"}])
    assert res.status == ToolResultStatus.FAILURE
    assert "mode" in res.content


def test_missing_steps_rejected():
    """缺 steps 拒绝."""
    res = WorkflowRunTool(FakeRunner()).execute(mode="parallel", steps=[])
    assert res.status == ToolResultStatus.FAILURE


def test_too_many_steps_rejected():
    """超过 6 步拒绝（预算边界）."""
    steps = [{"task": f"t{i}"} for i in range(7)]
    res = WorkflowRunTool(FakeRunner()).execute(mode="parallel", steps=steps)
    assert res.status == ToolResultStatus.FAILURE
    assert "最多 6 步" in res.content


def test_failed_step_does_not_block_others():
    """某步失败不阻断后续步骤，整体如实标注 failure."""
    class FlakyRunner(FakeRunner):
        def run(self, task, context="", depth=0):
            if "bad" in task:
                return FakeResult(final_answer="", refused=True, depth=depth)
            return FakeResult(final_answer=f"ok:{task[:8]}", depth=depth)

    tool = WorkflowRunTool(FlakyRunner())
    res = tool.execute(
        mode="parallel",
        steps=[{"task": "good1"}, {"task": "bad"}, {"task": "good2"}],
    )
    assert res.status == ToolResultStatus.FAILURE  # 有失败步 → 整体 failure
    assert "good1" in res.content and "good2" in res.content  # 后续仍执行
    assert "[状态: failure]" in res.content


def test_workflow_tool_registered():
    """workflow_run 已注册进 factory（engine 工具清单）."""
    import tempfile

    from llm_loop.config import Settings
    from llm_loop.factory import build_engine

    tmp = tempfile.mkdtemp()
    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=tmp,
        extract_enabled=False,
        docs_dir="",
    )
    engine = build_engine(settings)  # type: ignore[arg-type]
    names = set(engine.registry._tools.keys())  # noqa: SLF001
    assert "workflow_run" in names
