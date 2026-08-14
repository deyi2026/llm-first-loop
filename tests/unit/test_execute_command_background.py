"""execute_command run_in_background + job_output/job_kill 测试（EVO-20260814）.

覆盖:
- run_in_background=true 立即返回 job_id（不阻塞），状态 running
- job_output 在运行中查询 → running
- 任务完成后 job_output → done + exit_code + 输出内容
- job_kill 终止运行中任务 → killed
- job_kill/job_output 不存在 job_id → 如实失败
- job_kill 已完成任务 → 如实失败
"""

from __future__ import annotations

import time

from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.builtin.job_kill import JobKillTool
from llm_loop.tools.builtin.job_output import JobOutputTool


def _cmd_tool():
    return ExecuteCommandTool(timeout_s=15)


def test_background_starts_immediately():
    """后台启动长任务：立即返回 job_id（不阻塞 3 秒）."""
    t0 = time.time()
    r = _cmd_tool().execute(command="sleep 3; echo done", run_in_background=True)
    elapsed = time.time() - t0
    assert r.status.name == "SUCCESS", f"status={r.status}, content={r.content}"
    assert elapsed < 2, f"不应阻塞 3 秒, 实际耗时 {elapsed:.1f}s"
    assert "job_id=job-" in r.content
    assert "running" in r.content


def test_job_output_running_then_done():
    """job_output 查询：运行中→running，完成后→done + exit_code + 输出."""
    r = _cmd_tool().execute(command="sleep 1; echo hello", run_in_background=True)
    assert r.status.name == "SUCCESS"
    job_id = r.content.split("job_id=")[1].split()[0]
    # 立即查询 → running（sleep 1 未完成）
    q = JobOutputTool().execute(job_id=job_id)
    assert q.status.name == "SUCCESS"
    assert "状态=running" in q.content
    # 等完成再查 → done + 输出
    time.sleep(2)
    q2 = JobOutputTool().execute(job_id=job_id)
    assert q2.status.name == "SUCCESS"
    assert "状态=done" in q2.content, f"实际: {q2.content}"
    assert "exit=0" in q2.content
    assert "hello" in q2.content


def test_job_kill_terminates():
    """job_kill 终止运行中的长任务."""
    r = _cmd_tool().execute(command="sleep 100", run_in_background=True)
    assert r.status.name == "SUCCESS"
    job_id = r.content.split("job_id=")[1].split()[0]
    k = JobKillTool().execute(job_id=job_id)
    assert k.status.name == "SUCCESS", f"kill 应成功, 实际: {k.content}"
    assert "已终止" in k.content
    # 终止后再查 → killed
    time.sleep(0.5)
    q = JobOutputTool().execute(job_id=job_id)
    assert "killed" in q.content, f"应标记 killed, 实际: {q.content}"


def test_job_output_missing_id():
    """job_output 不存在 job_id → 如实失败."""
    r = JobOutputTool().execute(job_id="job-999999")
    assert r.status.name == "FAILURE"
    assert "任务不存在" in r.content


def test_job_kill_missing_id():
    """job_kill 不存在 job_id → 如实失败."""
    r = JobKillTool().execute(job_id="job-999999")
    assert r.status.name == "FAILURE"
    assert "任务不存在" in r.content


def test_job_kill_completed_job_fails():
    """job_kill 已完成任务 → 如实失败."""
    r = _cmd_tool().execute(command="echo quick", run_in_background=True)
    assert r.status.name == "SUCCESS"
    job_id = r.content.split("job_id=")[1].split()[0]
    time.sleep(1.5)  # 等完成
    k = JobKillTool().execute(job_id=job_id)
    assert k.status.name == "FAILURE", f"已完成任务 kill 应失败, 实际: {k.content}"
    assert "已结束" in k.content
