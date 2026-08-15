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


# ── P3-4: dag 模式（拓扑序 + 依赖注入 + 节点预算 + 环检测） ──

def test_dag_topological_order_and_dep_injection():
    """dag: 依赖步骤先执行；依赖 final_answer 注入被依赖步骤 context."""
    runner = FakeRunner()
    tool = WorkflowRunTool(runner)
    res = tool.execute(
        mode="dag",
        steps=[
            {"id": "a", "task": "调研 A"},
            {"id": "b", "task": "基于 A 做 B", "depends_on": ["a"]},
            {"id": "c", "task": "独立 C"},
            {"id": "d", "task": "汇总 B 与 C", "depends_on": ["b", "c"]},
        ],
    )
    assert res.status == ToolResultStatus.SUCCESS
    # 拓扑序：a 与 c 在前（任一），b 在 a 后，d 最后
    order = [t for t, _ in runner.calls]
    assert order.index("调研 A") < order.index("基于 A 做 B")
    assert order.index("独立 C") < order.index("汇总 B 与 C")
    assert order[-1] == "汇总 B 与 C"
    # 依赖注入：b 的 context 含 a 的结果；d 的 context 含 b 和 c 的结果
    ctx_b = runner.calls[order.index("基于 A 做 B")][1]
    ctx_d = runner.calls[order.index("汇总 B 与 C")][1]
    assert "依赖步骤 a 结果" in ctx_b and "result_of:调研 A" in ctx_b
    assert "依赖步骤 b 结果" in ctx_d and "依赖步骤 c 结果" in ctx_d
    # 回执含拓扑序标注
    assert "拓扑序" in res.content


def test_dag_cycle_detected():
    runner = FakeRunner()
    tool = WorkflowRunTool(runner)
    res = tool.execute(
        mode="dag",
        steps=[
            {"id": "a", "task": "A", "depends_on": ["b"]},
            {"id": "b", "task": "B", "depends_on": ["a"]},
        ],
    )
    assert res.status == ToolResultStatus.FAILURE
    assert "循环依赖" in res.content
    assert runner.calls == []  # 环检测在派发前


def test_dag_unknown_dep_rejected():
    tool = WorkflowRunTool(FakeRunner())
    res = tool.execute(
        mode="dag",
        steps=[
            {"id": "a", "task": "A", "depends_on": ["ghost"]},
        ],
    )
    assert res.status == ToolResultStatus.FAILURE
    assert "未知" in res.content and "ghost" in res.content


def test_dag_self_dep_rejected():
    tool = WorkflowRunTool(FakeRunner())
    res = tool.execute(
        mode="dag",
        steps=[
            {"id": "a", "task": "A", "depends_on": ["a"]},
        ],
    )
    assert res.status == ToolResultStatus.FAILURE
    assert "自身" in res.content


def test_dag_duplicate_id_rejected():
    tool = WorkflowRunTool(FakeRunner())
    res = tool.execute(
        mode="dag",
        steps=[
            {"id": "a", "task": "A"},
            {"id": "a", "task": "A2"},
        ],
    )
    assert res.status == ToolResultStatus.FAILURE
    assert "重复" in res.content


def test_dag_budget_rounds_passthrough():
    """节点级预算：budget_rounds 透传子代理 max_rounds（runner 记录 kwargs）."""

    class BudgetRunner:
        def __init__(self) -> None:
            self.max_rounds_calls: list[int | None] = []

        def run(self, task: str, context: str = "", depth: int = 0, max_rounds: int | None = None):
            self.max_rounds_calls.append(max_rounds)
            return FakeResult(final_answer=f"ok:{task[:8]}", rounds=3)

    runner = BudgetRunner()
    tool = WorkflowRunTool(runner)
    res = tool.execute(
        mode="dag",
        steps=[
            {"id": "a", "task": "A", "budget_rounds": 5},
            {"id": "b", "task": "B"},
        ],
    )
    assert res.status == ToolResultStatus.SUCCESS
    assert runner.max_rounds_calls == [5, None]
    assert "budget_rounds=5" in res.content
