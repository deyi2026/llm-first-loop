"""单元测试: D1 event-* CLI 子命令（tasks §8.2 / design §2.4.1）.

覆盖:
- 非法参数 → argparse 用法提示 + SystemExit 退出码 2
- 编排函数异常 → 打印原因 + 退出码 1（fail-open 如实反馈）
- 正常路径退出码 0 且报告含闭环对账数字
- 分派入口特判早于 build_engine（对齐 export-distill 先例，不装配 engine）
- 全部走 tmp_path（M64 防御，monkeypatch DATA_DIR 隔离真实 data/）
"""

from __future__ import annotations

import json

import pytest

from llm_loop.cli import (
    _cmd_event_inventory,
    _cmd_event_migrate,
    _cmd_event_rollback,
    _cmd_event_verify,
    _dispatch_command,
)


def _write_session(sessions_dir, sid: str, with_compressed: bool = False) -> None:
    sessions_dir.mkdir(parents=True, exist_ok=True)
    messages = [
        {"role": "user", "content": "问题", "source": "user", "tool_call_id": None,
         "status": None, "tool_name": None, "error_detail": None, "tool_calls": None,
         "reasoning_content": None, "metadata": {}},
        {"role": "assistant", "content": "回答", "source": "user", "tool_call_id": None,
         "status": None, "tool_name": None, "error_detail": None, "tool_calls": None,
         "reasoning_content": None, "metadata": {}},
    ]
    if with_compressed:
        messages.append(
            {"role": "tool", "content": "…[本消息已压缩，完整内容已另存]…", "source": "tool",
             "tool_call_id": "c1", "status": "success", "tool_name": "f1",
             "error_detail": None, "tool_calls": None, "reasoning_content": None, "metadata": {}}
        )
    data = {
        "version": 4, "session_id": sid, "created_at": "2026-01-01T00:00:00",
        "title": f"会话{sid}", "updated_at": "2026-01-01T00:01:00", "status": "active",
        "parent_id": None, "branch_id": "", "branch_summary": "", "model_override": None,
        "pinned": False, "channel": "web", "messages": messages,
    }
    (sessions_dir / f"{sid}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _setup_data(tmp_path) -> str:
    """构造含 2 个会话的数据目录，返回 data-dir 字符串."""
    data_dir = tmp_path / "data"
    sessions_dir = data_dir / "sessions"
    _write_session(sessions_dir, "s1")
    _write_session(sessions_dir, "s2", with_compressed=True)
    return str(data_dir)


# ── 非法参数 → 退出码 2 ──

@pytest.mark.parametrize(
    "fn",
    [_cmd_event_inventory, _cmd_event_migrate, _cmd_event_verify, _cmd_event_rollback],
)
def test_event_cmd_invalid_arg_usage_exit2(fn, capsys):
    with pytest.raises(SystemExit) as exc:
        fn(["--bogus-flag", "x"])
    assert exc.value.code == 2
    out = capsys.readouterr()
    assert "usage:" in (out.out + out.err).lower() or "--bogus-flag" in (out.out + out.err)


# ── 编排函数异常 → 退出码 1 ──

def test_event_inventory_orchestration_error_exit1(tmp_path, monkeypatch):
    from llm_loop.event_log import inventory as inv_mod

    def _boom(data_dir):
        raise RuntimeError("盘点故障")

    monkeypatch.setattr(inv_mod, "run_inventory", _boom)
    assert _cmd_event_inventory(["--data-dir", str(tmp_path)]) == 1



def test_event_inventory_error_prints_reason(capsys, monkeypatch):
    from llm_loop.event_log import inventory as inv_mod

    monkeypatch.setattr(inv_mod, "run_inventory", lambda d: (_ for _ in ()).throw(RuntimeError("盘点故障")))
    _cmd_event_inventory(["--data-dir", "/tmp/nonexistent-data-xyz"])
    err = capsys.readouterr().err
    assert "盘点失败" in err
    assert "RuntimeError" in err


def test_event_migrate_error_exit1(tmp_path, monkeypatch, capsys):
    from llm_loop.event_log import migrate as mig_mod

    monkeypatch.setattr(mig_mod, "run_migration", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("迁移故障")))
    assert _cmd_event_migrate(["--data-dir", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "迁移失败" in err


def test_event_verify_error_exit1(tmp_path, monkeypatch, capsys):
    from llm_loop.event_log import replay as rep_mod

    monkeypatch.setattr(rep_mod, "replay_session", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("校验故障")))
    data_dir = _setup_data(tmp_path)
    from llm_loop.event_log.migrate import run_migration
    run_migration(f"{data_dir}/sessions", f"{data_dir}/event_logs")
    assert _cmd_event_verify(["--data-dir", data_dir]) == 1
    out = capsys.readouterr().out
    assert "校验异常" in out  # 单会话校验异常如实标注，不中断整体（fail-open）


def test_event_rollback_error_exit1(tmp_path, monkeypatch, capsys):
    from llm_loop.event_log import migrate as mig_mod

    data_dir = _setup_data(tmp_path)
    # 先迁移生成备份区，再让 run_rollback 抛异常
    assert _cmd_event_migrate(["--data-dir", data_dir]) == 0
    capsys.readouterr()
    monkeypatch.setattr(mig_mod, "run_rollback", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("回滚故障")))
    assert _cmd_event_rollback(["--data-dir", data_dir]) == 1
    err = capsys.readouterr().err
    assert "回滚失败" in err


# ── 正常路径退出码 0 + 闭环对账 ──

def test_event_inventory_normal_exit0(tmp_path, capsys):
    data_dir = _setup_data(tmp_path)
    assert _cmd_event_inventory(["--data-dir", data_dir]) == 0
    out = capsys.readouterr().out
    assert "存量存储盘点" in out
    assert "会话 sessions: 2 个" in out


def test_event_migrate_normal_exit0_with_closed_loop(tmp_path, capsys):
    data_dir = _setup_data(tmp_path)
    assert _cmd_event_migrate(["--data-dir", data_dir]) == 0
    out = capsys.readouterr().out
    assert "会话总数: 2 / 迁移通过: 2 / 幂等跳过: 0 / 失败: 0" in out
    assert (tmp_path / "data" / "event_logs" / "s1.jsonl").is_file()
    # 源文件未被删除
    assert (tmp_path / "data" / "sessions" / "s1.json").is_file()
    # 备份区生成
    backups = list((tmp_path / "data" / "event_logs" / "_backup").glob("*"))
    assert len(backups) == 1


def test_event_verify_normal_exit0_with_closed_loop(tmp_path, capsys):
    data_dir = _setup_data(tmp_path)
    assert _cmd_event_migrate(["--data-dir", data_dir]) == 0
    capsys.readouterr()
    assert _cmd_event_verify(["--data-dir", data_dir]) == 0
    out = capsys.readouterr().out
    assert "通过: 2 / 失败: 0" in out


def test_event_verify_specific_session(tmp_path, capsys):
    data_dir = _setup_data(tmp_path)
    assert _cmd_event_migrate(["--data-dir", data_dir]) == 0
    capsys.readouterr()
    assert _cmd_event_verify(["--data-dir", data_dir, "--session", "s1"]) == 0
    out = capsys.readouterr().out
    assert "通过: 1 / 失败: 0" in out


def test_event_rollback_normal_exit0(tmp_path, capsys):
    data_dir = _setup_data(tmp_path)
    assert _cmd_event_migrate(["--data-dir", data_dir]) == 0
    capsys.readouterr()
    assert _cmd_event_rollback(["--data-dir", data_dir]) == 0
    out = capsys.readouterr().out
    assert "恢复会话" in out
    assert "备份区" in out
    # 恢复后源仍在（备份恢复为同内容覆盖）
    assert (tmp_path / "data" / "sessions" / "s1.json").is_file()


def test_event_rollback_no_backup_exit1(tmp_path, capsys):
    data_dir = _setup_data(tmp_path)
    assert _cmd_event_rollback(["--data-dir", data_dir]) == 1
    err = capsys.readouterr().err
    assert "无备份区可回滚" in err


# ── 分派注册 + 不触发 engine 装配 ──

def test_event_cmd_dispatch_registered_without_engine(tmp_path, monkeypatch):
    import llm_loop.factory

    def _boom(settings):
        raise RuntimeError("不应装配 engine")

    monkeypatch.setattr(llm_loop.factory, "build_engine", _boom)
    data_dir = _setup_data(tmp_path)
    # event-inventory 入口特判早于 build_engine
    assert _dispatch_command(["event-inventory", "--data-dir", data_dir]) == 0
