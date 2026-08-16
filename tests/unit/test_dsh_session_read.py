"""dsh_session_read 工具测试（P2：DSH session 日志回放检索）.

用 zstandard 压缩的临时 session 文件模拟 DSH 事件日志，验证：
读取/最终回答提取/工具轨迹/关键词过滤/session 选择/缺失容错。
"""

from __future__ import annotations

import json
from pathlib import Path

import zstandard

from llm_loop.core.message import ToolResultStatus
from llm_loop.tools.builtin.dsh_session_read import DshSessionReadTool
from llm_loop.workspace.store import workspace_key


def _write_session(dirpath: Path, session_name: str, events: list[dict]) -> Path:
    """写 zstd 压缩的 session.jsonl 到 dirpath 下 session 目录，返回该目录."""
    d = dirpath / session_name
    d.mkdir(parents=True)
    payload = "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n"
    cctx = zstandard.ZstdCompressor()
    with (d / "session.jsonl.zstd").open("wb") as f:
        f.write(cctx.compress(payload.encode("utf-8")))
    return d


def _events() -> list[dict]:
    return [
        {"type": "session", "version": 1, "id": "s1", "createdAt": "t", "cwd": "/tmp"},
        {"type": "agent/inbox/spliced", "seq": 0, "time": 0, "data": {}},
        {"type": "turn/start", "seq": 1, "time": 0, "data": {"turn": 1}},
        {
            "type": "assistant/message",
            "seq": 2,
            "time": 0,
            "data": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "reasoning", "text": "思考过程 A"},
                        {"type": "text", "text": "最终回答：任务完成"},
                    ],
                }
            },
        },
        {
            "type": "tool/call",
            "seq": 3,
            "time": 0,
            "data": {"call": {"name": "execute_command", "arguments": {"command": "ls"}}},
        },
        {"type": "tool/result", "seq": 4, "time": 0, "data": {"status": "success"}},
        {"type": "turn/end", "seq": 5, "time": 0, "data": {"reason": {"kind": "completed"}}},
    ]


def _make(monkeypatch, tmp_path, root: Path) -> DshSessionReadTool:
    monkeypatch.delenv("DSH_HOME", raising=False)  # 隔离本机 DSH_HOME 残留
    monkeypatch.setattr(
        "llm_loop.tools.builtin.dsh_session_read._DSH_SESSIONS_ROOT", root
    )
    return DshSessionReadTool()


def test_read_latest_session(monkeypatch, tmp_path):
    """读最新 session：提取最终回答 + 工具轨迹 + turn 结果."""
    root = tmp_path / "dsh"
    key = workspace_key("/fake/ws")
    base = root / key
    base.mkdir(parents=True)
    _write_session(base, "session-old", _events())
    _write_session(base, "session-new", _events())
    # 让 session-new 更新（mtime 决定最新）
    (base / "session-new" / "session.jsonl.zstd").touch()
    tool = _make(monkeypatch, tmp_path, root)
    r = tool.execute(workspace="/fake/ws")
    assert r.status == ToolResultStatus.SUCCESS
    assert "最终回答：任务完成" in r.content
    assert "execute_command" in r.content
    assert "completed" in r.content
    assert "session-new" in r.content


def test_keyword_filter(monkeypatch, tmp_path):
    """关键词过滤：只回显匹配段."""
    root = tmp_path / "dsh"
    key = workspace_key("/fake/ws")
    base = root / key
    base.mkdir(parents=True)
    _write_session(base, "session-k", _events())
    tool = _make(monkeypatch, tmp_path, root)
    r = tool.execute(workspace="/fake/ws", keyword="execute_command")
    assert r.status == ToolResultStatus.SUCCESS
    assert "execute_command" in r.content
    assert "最终回答" not in r.content  # 不含关键词的段被过滤


def test_specific_session_id(monkeypatch, tmp_path):
    """指定 session_id 精确读取."""
    root = tmp_path / "dsh"
    key = workspace_key("/fake/ws")
    base = root / key
    base.mkdir(parents=True)
    _write_session(base, "session-abc123", _events())
    tool = _make(monkeypatch, tmp_path, root)
    r = tool.execute(workspace="/fake/ws", session_id="session-abc123")
    assert r.status == ToolResultStatus.SUCCESS
    assert "session-abc123" in r.content


def test_no_sessions_failure(monkeypatch, tmp_path):
    """工作区无 session 目录 → failure 如实标注."""
    root = tmp_path / "dsh"
    tool = _make(monkeypatch, tmp_path, root)
    r = tool.execute(workspace="/fake/ws")
    assert r.status == ToolResultStatus.FAILURE
    assert "session 目录不存在" in r.content


def test_corrupt_log_failure(monkeypatch, tmp_path):
    """日志损坏不可读 → failure 如实标注（fail-open 不抛异常）."""
    root = tmp_path / "dsh"
    key = workspace_key("/fake/ws")
    base = root / key
    d = base / "session-bad"
    d.mkdir(parents=True)
    (d / "session.jsonl.zstd").write_bytes(b"not zstd data at all")
    tool = _make(monkeypatch, tmp_path, root)
    r = tool.execute(workspace="/fake/ws")
    assert r.status == ToolResultStatus.FAILURE
    assert "不可读" in r.content


def test_dsh_home_redirect(monkeypatch, tmp_path):
    """DSH_HOME 设置时 session 根跟随 DSH_HOME/sessions（服务进程重定向场景）."""
    monkeypatch.delenv("DSH_HOME", raising=False)
    root = tmp_path / "project" / "data" / "dsh-home"
    base = root / "sessions" / workspace_key("/fake/ws")
    _write_session(base, "session-h", _events())
    monkeypatch.setenv("DSH_HOME", str(root))
    tool = DshSessionReadTool()
    r = tool.execute(workspace="/fake/ws")
    assert r.status == ToolResultStatus.SUCCESS
    assert "session-h" in r.content
