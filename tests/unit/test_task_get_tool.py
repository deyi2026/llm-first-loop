"""task_get：单任务明细按需读取（TASK-INTELLIGENCE-M0-AUDIT-20261112 M1）.

M0 缺口1复现：blocked_reason>50 字符与 acceptance 全文经既有工具不可达
（task_frontier 截 50 字符、无 acceptance；get_goal 只投影 goal 面）。
本文件锁定修复后的闭合行为与"不应做"的反例。

正例：全文渲染（不截断）/ strict-session 默认解析 / 显式 goal_id。
反例：无写参数（只读 schema）/ 未知 task_id 确定性失败 / 调用零副作用
（任务存储字节不变）/ 不改变 task_frontier 既有图视图渲染。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.core.run_context import current_session_id as _sid
from llm_loop.introspection.goal import GoalStore
from llm_loop.introspection.task_store import TaskStore
from llm_loop.introspection.tools_task import (
    TASK_GET_TOOL_DEF,
    run_task_frontier,
    run_task_get,
)

SID = "sess-task-get"
OTHER_SID = "sess-other-run"

LONG_REASON = (
    "被阻塞的完整原因说明，超过五十个字符的长度限制，用于验证 task_get 返回全文"
    "而 task_frontier 视图会截断到五十个字符以内——这里是第二句，确保长度足够。"
)


@pytest.fixture(autouse=True)
def _bind():
    token = _sid.set(SID)
    yield
    _sid.reset(token)


def _host(tmp_path) -> SimpleNamespace:
    return SimpleNamespace(audit_dir=str(tmp_path), ctx=SimpleNamespace())


def _seed_goal_task(tmp_path, *, session_id=SID):
    gs = GoalStore(str(tmp_path))
    goal = gs.create("task_get 审计目标", session_id=session_id)
    ts = TaskStore(str(tmp_path))
    t = ts.create(
        goal.id,
        "长阻塞原因任务",
        acceptance=["验收标准一：输出包含全文", "验收标准二：不改变既有视图"],
        done_when=["done_when 判据行"],
        evidence_required=True,
    )
    ts.update(goal.id, t.task_id, status="in_progress")
    ts.update(goal.id, t.task_id, status="blocked", blocked_reason=LONG_REASON)
    return goal, t


# ── 正例 ────────────────────────────────────────────────────────────


def test_full_text_reachable_and_frontier_still_truncates(tmp_path):
    """盲区闭合：task_get 返回 blocked_reason/acceptance 全文；frontier 保持既有截断渲染."""
    goal, t = _seed_goal_task(tmp_path)
    host = _host(tmp_path)

    got = run_task_get(host.ctx, host, {"task_id": t.task_id})
    assert got.status == ToolResultStatus.SUCCESS
    assert LONG_REASON in got.content  # 全文（>50 字符）可达
    for acc in ("验收标准一：输出包含全文", "验收标准二：不改变既有视图"):
        assert acc in got.content
    assert "done_when 判据行" in got.content
    assert "evidence_required=true" in got.content  # 空 evidence 但必填时的提示

    fr = run_task_frontier(host.ctx, host, {})
    assert fr.status == ToolResultStatus.SUCCESS
    assert LONG_REASON[:50] in fr.content  # 既有视图行为不变（仍含前缀）
    assert LONG_REASON not in fr.content  # 截断语义保持——修复不改动 frontier


def test_strict_session_default_resolution(tmp_path):
    """goal_id 省略 → 解析当前绑定会话的活动 goal；不泄漏他会的 goal."""
    goal, t = _seed_goal_task(tmp_path)  # 归属 SID
    host = _host(tmp_path)
    got = run_task_get(host.ctx, host, {"task_id": t.task_id})
    assert got.status == ToolResultStatus.SUCCESS
    assert goal.id in got.content

    # 他会话 goal 在 strict-session 默认下不可见（fail-closed）
    other_goal, other_t = _seed_goal_task(tmp_path / "other", session_id=OTHER_SID)
    host2 = SimpleNamespace(audit_dir=str(tmp_path / "other"), ctx=SimpleNamespace())
    got2 = run_task_get(host2.ctx, host2, {"task_id": other_t.task_id})
    assert "[无任务] 当前无活动 goal" in got2.content


def test_cross_session_no_goal_response_guides_explicit_read_without_leak(tmp_path):
    """跨会话冷启动的 task_id 不可误判为不存在或诱导新建 Goal."""
    other_goal, other_t = _seed_goal_task(tmp_path, session_id=OTHER_SID)
    host = _host(tmp_path)
    task_file = Path(tmp_path) / "tasks" / f"{other_goal.id}.jsonl"
    before = task_file.read_bytes()

    missing = run_task_get(host.ctx, host, {"task_id": other_t.task_id})
    assert missing.status == ToolResultStatus.SUCCESS  # 保持既有空视图契约
    assert "[无任务] 当前无活动 goal" in missing.content
    assert "仅当前会话" in missing.content
    assert "跨会话只读恢复" in missing.content
    assert "goal_id + task_id" in missing.content
    assert "无需 create_goal" in missing.content
    assert other_goal.id not in missing.content  # 不枚举/泄漏其他会话 Goal
    assert task_file.read_bytes() == before

    recovered = run_task_get(
        host.ctx, host, {"goal_id": other_goal.id, "task_id": other_t.task_id}
    )
    assert recovered.status == ToolResultStatus.SUCCESS
    assert LONG_REASON in recovered.content
    assert task_file.read_bytes() == before


def test_explicit_goal_id_reads_any_goal(tmp_path):
    """显式 goal_id 可跨会话读取（读取面宽松，与 task_frontier 显式路径一致）."""
    other_goal, other_t = _seed_goal_task(tmp_path, session_id=OTHER_SID)
    host = _host(tmp_path)
    got = run_task_get(host.ctx, host, {"goal_id": other_goal.id, "task_id": other_t.task_id})
    assert got.status == ToolResultStatus.SUCCESS
    assert LONG_REASON in got.content


def test_evidence_and_flags_rendered(tmp_path):
    goal = GoalStore(str(tmp_path)).create("证据任务", session_id=SID)
    ts = TaskStore(str(tmp_path))
    t = ts.create(goal.id, "带证据", acceptance=["a1"])
    ts.update(goal.id, t.task_id, status="in_progress")
    # 非 done 态附加 refs 不触发校验（task_store.py: 仅 done 进入/变更才 verify），
    # verification 如实渲染 not_checked
    ts.update(goal.id, t.task_id, evidence_refs=["evidence://v1/abc123"])
    host = _host(tmp_path)
    got = run_task_get(host.ctx, host, {"task_id": t.task_id})
    assert "evidence://v1/abc123" in got.content
    assert "verification=not_checked" in got.content


# ── 反例（不应做）───────────────────────────────────────────────────


def test_schema_has_no_write_surface():
    """只读工具：参数面仅 goal_id/task_id，无任何写参数."""
    props = TASK_GET_TOOL_DEF["parameters"]["properties"]
    assert set(props) == {"goal_id", "task_id"}
    assert TASK_GET_TOOL_DEF["parameters"]["required"] == ["task_id"]
    assert TASK_GET_TOOL_DEF["name"] == "task_get"
    assert "跨会话只读恢复" in TASK_GET_TOOL_DEF["description"]
    assert "原 goal_id" in props["goal_id"]["description"]


def test_unknown_task_id_deterministic_failure(tmp_path):
    goal, _t = _seed_goal_task(tmp_path)
    host = _host(tmp_path)
    got = run_task_get(host.ctx, host, {"task_id": "T-NOPE"})
    assert got.status == ToolResultStatus.FAILURE
    assert "[任务不存在]" in got.content
    assert goal.id in got.content


def test_missing_task_id_param(tmp_path):
    host = _host(tmp_path)
    got = run_task_get(host.ctx, host, {})
    assert got.status == ToolResultStatus.FAILURE
    assert "[参数错误]" in got.content


def test_read_only_no_storage_mutation(tmp_path):
    """零副作用：调用前后任务存储文件字节不变（只读派生视图）."""
    _goal, t = _seed_goal_task(tmp_path)
    store_file = Path(tmp_path) / "tasks" / (_goal.id + ".jsonl")
    before = store_file.read_bytes()
    host = _host(tmp_path)
    r1 = run_task_get(host.ctx, host, {"task_id": t.task_id})
    r2 = run_task_get(host.ctx, host, {"task_id": t.task_id})
    assert store_file.read_bytes() == before
    assert r1.content == r2.content  # 幂等读取


def test_registered_in_registry_dispatch():
    from llm_loop.introspection import registry_task

    names = [d["name"] for d in registry_task.tool_defs()]
    assert "task_get" in names
