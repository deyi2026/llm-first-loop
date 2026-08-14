"""单元测试: export-distill CLI 入口（design §2.4.1 用例 19-21）.

- 全部走 `tmp_path` 构造会话目录（M64 防污染真实 data/）；
- `--output`/`--report` 显式指向 tmp_path，避免写入真实 `data/export_distill/`.
"""

from __future__ import annotations

import json

import pytest

from llm_loop.cli import _cmd_export_distill, _dispatch_command


def _write_session(tmp_path, name: str, messages: list) -> None:
    sess = {
        "version": 3,
        "session_id": name.split(".")[0],
        "created_at": "2026-08-14T00:00:00",
        "title": "CLI测试",
        "updated_at": "2026-08-14T00:01:00",
        "status": "active",
        "parent_id": None,
        "branch_id": None,
        "messages": messages,
    }
    (tmp_path / name).write_text(json.dumps(sess, ensure_ascii=False), encoding="utf-8")


def _valid_messages() -> list:
    return [
        {"role": "user", "content": "问题"},
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "思考",
            "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "f1", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "content": "[状态: success] 结果", "tool_call_id": "c1", "status": "success"},
        {"role": "assistant", "content": "最终回答", "tool_calls": None},
    ]


# ── 用例 19: --help ──

def test_cli_export_distill_help(capsys):
    with pytest.raises(SystemExit) as exc:
        _cmd_export_distill(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--input-dir" in out
    assert "--output" in out
    assert "--report" in out
    assert "--force" in out
    assert "data/sessions/" in out


# ── 用例 20: 退出码 ──

def test_cli_export_distill_exit_codes(tmp_path, capsys):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    _write_session(sessions_dir, "s1.json", _valid_messages())
    out = tmp_path / "out.jsonl"
    rep = tmp_path / "rep.json"
    # 正常 → 0
    assert _cmd_export_distill(["--input-dir", str(sessions_dir), "--output", str(out), "--report", str(rep)]) == 0
    stdout = capsys.readouterr().out
    assert "对账 passed+filtered==total: OK" in stdout
    # 目录不存在 → 2
    assert _cmd_export_distill(["--input-dir", str(tmp_path / "nope"), "--output", str(out), "--report", str(rep)]) == 2
    # 输出冲突（非 --force）→ 2
    assert _cmd_export_distill(["--input-dir", str(sessions_dir), "--output", str(out), "--report", str(rep)]) == 2
    err = capsys.readouterr().err
    assert "--force" in err
    # --force 覆盖 → 0
    assert _cmd_export_distill(
        ["--input-dir", str(sessions_dir), "--output", str(out), "--report", str(rep), "--force"]
    ) == 0


# ── 用例 21: 分派注册 + 不触发 engine 装配 ──

def test_cli_dispatch_registered(tmp_path, monkeypatch):
    from llm_loop.introspection import export_distill as ed

    # 构造会话目录
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    _write_session(sessions_dir, "s1.json", _valid_messages())
    out = tmp_path / "out.jsonl"
    rep = tmp_path / "rep.json"

    # export-distill 分派入口特判早于 build_engine：即使 build_engine 被强制失败，
    # export-distill 仍正常导出（证明不装配 engine，对齐程序最小化）
    import llm_loop.factory

    def _boom(settings):
        raise RuntimeError("不应装配 engine")

    monkeypatch.setattr(llm_loop.factory, "build_engine", _boom)
    code = _dispatch_command(
        ["export-distill", "--input-dir", str(sessions_dir), "--output", str(out), "--report", str(rep)]
    )
    assert code == 0
    assert out.exists()
    assert rep.exists()

    # run_export 由 export_distill 模块提供且可调用（核心路径贯通）
    assert callable(ed.run_export)
