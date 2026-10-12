from llm_loop.introspection.registry_introspection import (
    _ARCHITECTURE_STATUS_TOOL_DEF,
    _SEARCH_RECORDS_TOOL_DEF,
)
from llm_loop.introspection.tools_goal import GET_GOAL_TOOL_DEF
from llm_loop.introspection.tools_task import TASK_FRONTIER_TOOL_DEF


def test_task_recovery_tools_have_non_overlapping_fact_boundaries():
    search = _SEARCH_RECORDS_TOOL_DEF["description"]
    goal = GET_GOAL_TOOL_DEF["description"]
    frontier = TASK_FRONTIER_TOOL_DEF["description"]
    arch = _ARCHITECTURE_STATUS_TOOL_DEF["description"]

    assert "继续/上次/之前那个问题" not in search
    assert "当前 Goal/Task 状态用 get_goal/task_frontier" in search
    assert "episode 表示已解决/退休的对话片段，不代表当前活动任务" in search

    assert "worktree" not in goal and "git status" not in goal
    assert "durable Goal 事实源" in goal
    assert "task_frontier" in goal

    assert "durable Task 图事实源" in frontier
    assert "current/active" in frontier
    assert "不替模型制定下一步" in frontier

    assert "不是用户任务 Goal/Task 的事实源" in arch
    assert "get_goal" in arch and "task_frontier" in arch


def test_correction_schema_order_prefers_read_only_task_state_without_moving_writes():
    from llm_loop.introspection.corrections import CorrectionContext, CorrectionToolRegistry

    names = [row["name"] for row in CorrectionToolRegistry(CorrectionContext()).tool_defs()]
    assert names[:2] == ["get_goal", "task_frontier"]
    assert names.index("get_goal") < names.index("architecture_status")
    assert names.index("task_frontier") < names.index("search_archive")
    assert names.index("task_frontier") < names.index("search_records")
    # Write-capable Goal/Task tools retain their historical relative order; they are not
    # promoted merely because their read-only siblings are more discoverable.
    assert names.index("create_goal") < names.index("update_goal")
    assert names.index("task_create") < names.index("task_update")
    assert names.index("update_goal") < names.index("task_create")
