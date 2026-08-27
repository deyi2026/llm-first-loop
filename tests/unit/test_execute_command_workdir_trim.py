"""execute_command 增强测试：workdir 支持 / 裁剪可配化 / 环境事实注入.

覆盖:
- workdir 指定后子进程 cwd 生效（pwd 输出 = workdir）
- workdir 不存在 → 失败回执（如实）
- workdir 为空 → 默认当前目录（零回归）
- TOOL_TRIM_MAX/HEAD/TAIL 环境变量生效（裁剪阈值可配）
- LLM_EXEC_CWD 环境事实注入子进程
- 裁剪默认值（未配置环境变量）不变（零回归）
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from llm_loop.tools.builtin.execute_command import ExecuteCommandTool


def _tool() -> ExecuteCommandTool:
    return ExecuteCommandTool(timeout_s=15)


def test_workdir_applies_to_subprocess():
    """指定 workdir 后 pwd 输出 = workdir."""
    with tempfile.TemporaryDirectory() as d:
        r = _tool().execute(command="pwd", workdir=d)
        assert r.status.name == "SUCCESS", f"status={r.status}, content={r.content}"
        # 2026-08-21 摘要前置: 输出 = 元信息行 + 实际输出（取末行）
        out = r.content.strip().splitlines()[-1]
        # macOS /var → /private/var 符号链接，用 resolve 归一
        assert Path(out) == Path(d).resolve(), f"pwd 应为 {d}, 实际 {r.content}"


def test_workdir_missing_returns_failure():
    """workdir 不存在 → 如实失败回执."""
    r = _tool().execute(command="pwd", workdir="/nonexistent/definitely-not-here")
    assert r.status.name == "FAILURE", f"应失败, 实际 {r.status}"
    assert "不是有效目录" in r.content


def test_no_workdir_defaults_cwd():
    """未指定 workdir → 继承进程 cwd（零回归）."""
    r = _tool().execute(command="pwd")
    assert r.status.name == "SUCCESS"
    out = r.content.strip().splitlines()[-1]
    assert out == os.getcwd()


def test_llm_exec_cwd_injected():
    """LLM_EXEC_CWD 环境事实注入子进程."""
    r = _tool().execute(command="echo $LLM_EXEC_CWD")
    assert r.status.name == "SUCCESS"
    # 2026-08-21 摘要前置: 元信息行后为实际输出
    assert os.getcwd() in r.content


def test_trim_config_env_override():
    """TOOL_TRIM_MAX 可配：小阈值触发截断."""
    os.environ["TOOL_TRIM_MAX"] = "10"
    os.environ["TOOL_TRIM_HEAD"] = "5"
    os.environ["TOOL_TRIM_TAIL"] = "5"
    try:
        # 长输出（20 个 a）应触发截断（max=10）
        r = _tool().execute(command="printf 'aaaaaaaaaaaaaaaaaaaa'")
        assert "[输出已截断]" in r.content, f"应截断, 实际: {r.content}"
    finally:
        os.environ.pop("TOOL_TRIM_MAX", None)
        os.environ.pop("TOOL_TRIM_HEAD", None)
        os.environ.pop("TOOL_TRIM_TAIL", None)


def test_trim_config_default_no_truncate():
    """默认阈值（3000）下正常输出不截断（零回归）."""
    os.environ.pop("TOOL_TRIM_MAX", None)
    os.environ.pop("TOOL_TRIM_HEAD", None)
    os.environ.pop("TOOL_TRIM_TAIL", None)
    r = _tool().execute(command="printf 'hello'")
    assert "[输出已截断]" not in r.content
    # 2026-08-21 摘要前置: 输出含 [命令] 元信息行 + 原始内容（行为变更）
    assert "[命令]" in r.content
    assert "hello" in r.content


def test_trim_config_invalid_falls_back():
    """非法环境变量值回退默认（不报错）."""
    os.environ["TOOL_TRIM_MAX"] = "abc"
    try:
        r = _tool().execute(command="printf 'ok'")
        assert r.status.name == "SUCCESS"
        assert "ok" in r.content
    finally:
        os.environ.pop("TOOL_TRIM_MAX", None)


def test_dump_path_content_hash_deterministic(tmp_path, monkeypatch):
    """EVO-20260824 Q1.3: 落盘路径用内容哈希——同输出→同路径（前缀稳定），不同输出→不同路径（不误读）.

    修复前 execute_command 落盘含时间戳 → 同命令重跑路径每轮变 → 回执字节变 → 缓存全 miss。
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from llm_loop.tools.builtin.execute_command import _truncate_output

    out_dir = tmp_path / "audit" / "cmd_outputs"
    # 同内容两次 → 覆盖写同一路径 → 目录仅 1 个文件
    _truncate_output("x" * 5000, command="printf")
    _truncate_output("x" * 5000, command="printf")
    files = list(out_dir.glob("*.log"))
    assert len(files) == 1, f"同输出应同路径, 实际 {len(files)} 个文件"
    # 不同内容 → 不同路径 → 2 个文件
    _truncate_output("y" * 5000, command="printf")
    files = list(out_dir.glob("*.log"))
    assert len(files) == 2
    # 文件名不再含时间戳模式（确定性路径）——覆盖全部已生成路径（刷新后断言，勿漏第三次落盘）
    import re

    for f in files:
        assert not re.search(r"\d{8}-\d{6}", f.name), f"路径不应含时间戳: {f.name}"


def test_truncation_marker_no_search_archive_hint():
    """EVO-20260824 Q4.4: 截断标记不再提示 search_archive（落盘文件不在 ArchiveStore，提示=名不副实）."""
    from llm_loop.tools.trim import truncation_marker

    m = truncation_marker(1000, 100, 100, 300, "kw", "/tmp/xxx.log")
    assert "search_archive" not in m  # 如实化：落盘是显式文件，read_file 路径取全文
    assert "/tmp/xxx.log" in m
