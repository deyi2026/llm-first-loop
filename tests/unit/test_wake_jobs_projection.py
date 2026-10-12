"""EVO-20260919-eee9d3b8（人工已审）: schedule 唤醒注入后台任务机械现状投影测试.

唤醒 run 看不到沉睡前的终态回执（压缩折叠/跨进程），历史事故为盲目重放已完成的
步骤清单。format_session_jobs_facts 只做 registry 事实的有界机械投影：
active 全列（封顶 8）+ terminal 最近 3 条 + 计数摘要；无推断、无建议、fail-open。
"""

from __future__ import annotations

from llm_loop.tools.builtin.job_registry import JobRegistry, format_session_jobs_facts


class _FakeProc:
    def __init__(self, exit_code: int = 0) -> None:
        self.returncode = exit_code
        self.pid = 4242
        self.stdout = None
        self.stderr = None

    def wait(self) -> int:
        return self.returncode


class _BoomRegistry:
    def snapshots_for_session(self, session_id: str) -> tuple[dict, ...]:
        raise RuntimeError("registry unavailable")


def _fresh_registry() -> JobRegistry:
    JobRegistry._instance = None
    reg = JobRegistry.instance()
    reg.configure(event_store=None, data_dir=None, max_concurrent=8)
    reg._jobs.clear()
    reg._seq = 0
    return reg


def _finish(reg: JobRegistry, job_id: str, exit_code: int, output: list[str]) -> None:
    """白盒模拟 watcher 终态标记（durable 关闭，无 journal 交互）."""
    entry = reg.get(job_id)
    assert entry is not None
    with entry._lock:
        entry.done = True
        entry.exit_code = exit_code
        entry.output = list(output)


def test_empty_session_or_registry_returns_empty() -> None:
    reg = _fresh_registry()
    assert format_session_jobs_facts("") == ""
    assert format_session_jobs_facts("s-no-jobs", registry=reg) == ""


def test_running_job_projected_with_cmd_head() -> None:
    reg = _fresh_registry()
    reg.create(_FakeProc(), "echo 'x' " * 20, session_id="s1")
    facts = format_session_jobs_facts("s1", registry=reg)
    assert "[程序投影·后台任务现状（机械事实" in facts
    assert "state=running" in facts
    assert "executor=execute_command" in facts
    assert "cmd_head=" in facts
    # cmd_head 截断到 60 字符以内
    line = next(ln for ln in facts.splitlines() if "cmd_head=" in ln)
    head = line.split("cmd_head=", 1)[1]
    assert len(head) <= 60
    assert "active=1" in facts


def test_terminal_job_projected_with_exit_and_tail() -> None:
    reg = _fresh_registry()
    job_id = reg.create(_FakeProc(), "gh pr checks 40", session_id="s1")
    _finish(reg, job_id, 0, ["[stdout] A.5 pass", "[stdout] 门禁 pass"])
    facts = format_session_jobs_facts("s1", registry=reg)
    assert "state=completed" in facts
    assert "exit=0" in facts
    assert "output_tail=[stdout] 门禁 pass" in facts
    assert "terminal=1" in facts


def test_terminal_cap_lists_last_three_with_skip_count() -> None:
    reg = _fresh_registry()
    for i in range(5):
        job_id = reg.create(_FakeProc(), f"cmd-{i}", session_id="s1")
        _finish(reg, job_id, 0, [f"[stdout] done-{i}"])
    facts = format_session_jobs_facts("s1", registry=reg)
    body = [ln for ln in facts.splitlines() if "state=" in ln]
    assert len(body) == 3
    assert "done-4" in body[-1]  # 最近终态保留
    assert "done-0" not in facts and "done-1" not in facts
    assert "省略 2" in facts


def test_registry_failure_fails_open_to_empty() -> None:
    assert format_session_jobs_facts("s1", registry=_BoomRegistry()) == ""  # type: ignore[arg-type]


def test_no_cross_session_leak() -> None:
    reg = _fresh_registry()
    reg.create(_FakeProc(), "secret-cmd-other-session", session_id="s-other")
    assert format_session_jobs_facts("s1", registry=reg) == ""
