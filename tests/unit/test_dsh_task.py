"""dsh_task 工具测试（DSH-ORCHESTRATION：调度 DeepSeek Harness headless）.

覆盖：成功回收 / 失败回收 / 超时终止 / dsh 缺失引导 / 参数校验 / 输出截断。
用 fake dsh 脚本模拟 headless 契约（stdout=回答、退出码 0/1）。
"""

from __future__ import annotations

from pathlib import Path

from llm_loop.core.message import ToolResultStatus
from llm_loop.tools.builtin.dsh_task import _MAX_OUTPUT_CHARS, DshTaskTool


def _write_fake_dsh(dirpath: Path, mode: str) -> str:
    """写 fake dsh 脚本（mode: ok / fail / sleep）并返回路径."""
    if mode == "ok":
        body = 'echo "这是 DSH 的最终回答\\n第二行"; exit 0\n'
    elif mode == "fail":
        body = 'echo "部分回答"; echo "dsh: SOME_ERROR: boom" >&2; exit 1\n'
    elif mode == "sleep":
        body = 'sleep 5; echo "迟到回答"\n'
    p = dirpath / "dsh"
    p.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    p.chmod(0o755)
    return str(p)


def _make_tool(monkeypatch, fake_dsh: str) -> DshTaskTool:
    monkeypatch.setattr("shutil.which", lambda _name: fake_dsh)
    return DshTaskTool()
def test_success_receives_answer(monkeypatch, tmp_path):
    """退出码 0 + stdout 回答 → success 回执."""
    fake = _write_fake_dsh(tmp_path, "ok")
    tool = _make_tool(monkeypatch, fake)
    result = tool.execute(task="完成一个任务")
    assert result.status == ToolResultStatus.SUCCESS
    assert "这是 DSH 的最终回答" in result.content
    assert "[状态: success]" in result.content


def test_failure_receives_stderr(monkeypatch, tmp_path):
    """退出码 1 + stderr 错误 → failure 回执（含错误摘要）."""
    fake = _write_fake_dsh(tmp_path, "fail")
    tool = _make_tool(monkeypatch, fake)
    result = tool.execute(task="会失败的任务")
    assert result.status == ToolResultStatus.FAILURE
    assert "退出码 1" in result.content
    assert "SOME_ERROR" in result.content


def test_timeout_kills_process(monkeypatch, tmp_path):
    """超时 → 整树终止 + timeout 回执."""
    fake = _write_fake_dsh(tmp_path, "sleep")
    tool = _make_tool(monkeypatch, fake)
    result = tool.execute(task="长任务", timeout_s=1)
    assert result.status == ToolResultStatus.TIMEOUT
    assert "已整树终止" in result.content


def test_dsh_missing_guidance(monkeypatch):
    """dsh 不在 PATH → failure + 安装引导."""
    monkeypatch.setattr("shutil.which", lambda _name: None)
    tool = DshTaskTool()
    result = tool.execute(task="任务")
    assert result.status == ToolResultStatus.FAILURE
    assert "找不到 dsh 命令" in result.content


def test_missing_task_param(monkeypatch, tmp_path):
    """缺 task 参数 → failure（不 spawn）."""
    fake = _write_fake_dsh(tmp_path, "ok")
    tool = _make_tool(monkeypatch, fake)
    result = tool.execute()
    assert result.status == ToolResultStatus.FAILURE
    assert "缺少必填参数 task" in result.content


def test_output_clipped(monkeypatch, tmp_path):
    """回答超限 → 截断 + 标注."""
    big = "x" * (_MAX_OUTPUT_CHARS + 5000)
    p = tmp_path / "dsh"
    p.write_text(f"#!/bin/sh\necho '{big}'\nexit 0\n", encoding="utf-8")
    p.chmod(0o755)
    tool = _make_tool(monkeypatch, str(p))
    result = tool.execute(task="大输出")
    assert result.status == ToolResultStatus.SUCCESS
    assert "已截断" in result.content
    assert len(result.content) < _MAX_OUTPUT_CHARS + 200


def test_cwd_passed_to_process(monkeypatch, tmp_path):
    """cwd 参数传递给子进程（任务在指定工作区执行）."""
    fake = _write_fake_dsh(tmp_path, "ok")
    monkeypatch.setattr("shutil.which", lambda _name: fake)
    tool = DshTaskTool()
    workdir = tmp_path / "ws"
    workdir.mkdir()
    result = tool.execute(task="任务", cwd=str(workdir))
    assert result.status == ToolResultStatus.SUCCESS


# ── P1（协议 v2）：ctx 引用 / 汇报格式 / 重试 / 脱敏 ──

def test_ctx_path_merged_into_task(monkeypatch, tmp_path):
    """ctx_path 文件内容并入任务文本（上下文通过引用传递）."""
    ctx = tmp_path / "ctx.md"
    ctx.write_text("前情摘要：已完成 A，待做 B", encoding="utf-8")
    captured: dict = {}

    def fake_run_once(task, cwd, timeout_s, dsh_bin, patch_path=''):
        captured["task"] = task
        return 0, "ok", "", 0.1

    tool = DshTaskTool()
    monkeypatch.setattr(tool, "_run_once", fake_run_once)
    monkeypatch.setattr(tool, "_audit", lambda *a: None)
    monkeypatch.setattr("shutil.which", lambda _n: "/fake/dsh")
    r = tool.execute(task="继续做 B", ctx_path=str(ctx))
    assert r.status == ToolResultStatus.SUCCESS
    assert "前情摘要：已完成 A" in captured["task"]
    assert "继续做 B" in captured["task"]


def test_report_format_injected(monkeypatch, tmp_path):
    """report_format=true 注入汇报格式模板；false 不注入."""
    captured: dict = {}

    def fake_run_once(task, cwd, timeout_s, dsh_bin, patch_path=''):
        captured["task"] = task
        return 0, "ok", "", 0.1

    tool = DshTaskTool()
    monkeypatch.setattr(tool, "_run_once", fake_run_once)
    monkeypatch.setattr(tool, "_audit", lambda *a: None)
    monkeypatch.setattr("shutil.which", lambda _n: "/fake/dsh")
    tool.execute(task="做任务")
    assert "汇报格式" in captured["task"]
    assert "## 产物清单" in captured["task"]
    captured.clear()
    tool.execute(task="做任务", report_format=False)
    assert "汇报格式" not in captured["task"]


def test_retry_on_failure(monkeypatch, tmp_path):
    """非 0 退出码 + retry>0 → 新 session 重跑；最终成功."""
    calls: list[int] = []

    def fake_run_once(task, cwd, timeout_s, dsh_bin, patch_path=''):
        calls.append(1)
        if len(calls) < 3:
            return 1, "", "dsh: ERROR: boom", 0.1
        return 0, "第三次成功", "", 0.2

    tool = DshTaskTool()
    monkeypatch.setattr(tool, "_run_once", fake_run_once)
    monkeypatch.setattr(tool, "_audit", lambda *a: None)
    monkeypatch.setattr("shutil.which", lambda _n: "/fake/dsh")
    r = tool.execute(task="任务", retry=2)
    assert r.status == ToolResultStatus.SUCCESS
    assert "第三次成功" in r.content
    assert len(calls) == 3


def test_retry_exhausted_failure(monkeypatch, tmp_path):
    """重试耗尽仍失败 → failure 回执（含重试次数）."""
    calls: list[int] = []

    def fake_run_once(task, cwd, timeout_s, dsh_bin, patch_path=''):
        calls.append(1)
        return 1, "", "dsh: ERROR: boom", 0.1

    tool = DshTaskTool()
    monkeypatch.setattr(tool, "_run_once", fake_run_once)
    monkeypatch.setattr(tool, "_audit", lambda *a: None)
    monkeypatch.setattr("shutil.which", lambda _n: "/fake/dsh")
    r = tool.execute(task="任务", retry=2)
    assert r.status == ToolResultStatus.FAILURE
    assert "重试 2 次" in r.content
    assert len(calls) == 3


def test_timeout_not_retried(monkeypatch, tmp_path):
    """timeout 不重试（防无限超时），直接回 timeout."""
    calls: list[int] = []

    def fake_run_once(task, cwd, timeout_s, dsh_bin, patch_path=''):
        calls.append(1)
        return "timeout", "部分", "", 10.0

    tool = DshTaskTool()
    monkeypatch.setattr(tool, "_run_once", fake_run_once)
    monkeypatch.setattr(tool, "_audit", lambda *a: None)
    monkeypatch.setattr("shutil.which", lambda _n: "/fake/dsh")
    r = tool.execute(task="长任务", retry=2, timeout_s=5)
    assert r.status == ToolResultStatus.TIMEOUT
    assert len(calls) == 1  # 只跑一次


def test_redact_sensitive_env(monkeypatch, tmp_path):
    """任务文本中的敏感 env 值被替换为 ***."""
    monkeypatch.setenv("LLM_API_KEY", "sk-very-secret-key-123456")
    captured: dict = {}

    def fake_run_once(task, cwd, timeout_s, dsh_bin, patch_path=''):
        captured["task"] = task
        return 0, "ok", "", 0.1

    tool = DshTaskTool()
    monkeypatch.setattr(tool, "_run_once", fake_run_once)
    monkeypatch.setattr(tool, "_audit", lambda *a: None)
    monkeypatch.setattr("shutil.which", lambda _n: "/fake/dsh")
    tool.execute(task="用密钥 sk-very-secret-key-123456 配置")
    assert "sk-very-secret-key-123456" not in captured["task"]
    assert "***" in captured["task"]


def test_acceptance_injected(monkeypatch, tmp_path):
    """acceptance 清单注入任务文本（逐项自检输出 完成/未完成/原因）."""
    captured: dict = {}

    def fake_run_once(task, cwd, timeout_s, dsh_bin, patch_path=''):
        captured["task"] = task
        return 0, "ok", "", 0.1

    tool = DshTaskTool()
    monkeypatch.setattr(tool, "_run_once", fake_run_once)
    monkeypatch.setattr(tool, "_audit", lambda *a: None)
    monkeypatch.setattr("shutil.which", lambda _n: "/fake/dsh")
    tool.execute(task="做任务", acceptance=["功能可用", "测试通过"])
    assert "验收清单" in captured["task"]
    assert "1. 功能可用" in captured["task"]
    assert "2. 测试通过" in captured["task"]
    assert "完成 / 未完成 / 原因" in captured["task"]


# ── P2：background 并行 fan-out ──

def test_background_starts_job(monkeypatch, tmp_path):
    """background=true → 立即返回 job_id（不阻塞），输出经 job_output 可见."""
    fake = _write_fake_dsh(tmp_path, "ok")
    tool = _make_tool(monkeypatch, fake)
    r = tool.execute(task="后台任务", background=True)
    assert r.status == ToolResultStatus.SUCCESS
    assert "job_id=" in r.content
    assert "[后台 dsh_task 已启动]" in r.content
    assert "job_output" in r.content
