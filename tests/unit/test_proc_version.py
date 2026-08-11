"""进程版本一致性 + 变更通告测试（EVO-20260811-f94e5306）."""

import json

from llm_loop.introspection import proc_version
from llm_loop.introspection.proc_version import (
    get_process_versions,
    git_head,
    record_change_log,
    record_process_start,
)


def test_record_and_get_process_versions(tmp_path, monkeypatch):
    """记录启动版本 → 读取返回服务/pid/git_head，与当前 HEAD 对照 code_current."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    record_process_start("test-svc")
    result = get_process_versions()
    assert result["current_git_head"]  # 非空（git 仓库或 no-git）
    svc = [s for s in result["services"] if s["service"] == "test-svc"]
    assert len(svc) == 1
    assert svc[0]["pid"]  # pid 有值
    assert "started_at" in svc[0]
    # code_current = 记录时 git head 与当前一致（同一进程内调用 → True）
    assert svc[0]["git_head"] == result["current_git_head"]
    assert svc[0]["code_current"] is True


def test_process_versions_old_code_flagged(tmp_path, monkeypatch):
    """旧代码进程（git_head 与当前不一致）→ code_current=False + 建议重启提示."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # 手工写入一条旧版本记录（git_head 与当前不一致）
    path = tmp_path / "audit" / "proc_versions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    current = git_head()
    old_head = "deadbeef" if current != "deadbeef" else "cafebabe"
    path.write_text(json.dumps({
        "ts": "2026-08-11T00:00:00+00:00",
        "pid": 9999,
        "service": "old-svc",
        "git_head": old_head,
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    result = get_process_versions()
    old = [s for s in result["services"] if s["service"] == "old-svc"]
    assert len(old) == 1
    assert old[0]["code_current"] is False
    assert "建议重启" in old[0]["note"]


def test_record_change_log(tmp_path, monkeypatch):
    """变更通告落盘 change_log.jsonl（工具/明细/pid 可检索）."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    record_change_log("execute_command", "echo test", session_id="s1")
    path = tmp_path / "audit" / "change_log.jsonl"
    assert path.exists()
    records = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(records) == 1
    assert records[0]["tool"] == "execute_command"
    assert records[0]["session_id"] == "s1"
    assert records[0]["detail"] == "echo test"


def test_fail_open_on_bad_env(tmp_path, monkeypatch):
    """DATA_DIR 不可写 → 记录 fail-open（不抛异常）."""
    import os

    monkeypatch.setenv("DATA_DIR", str(tmp_path / "nonexistent" / "deep"))
    record_process_start("svc")  # 不应抛异常
    record_change_log("execute_command", "x")  # 不应抛异常
    # 子目录不存在时 _audit_dir().mkdir(parents=True) 会创建 → 仍写入
    assert (tmp_path / "nonexistent" / "deep" / "audit").exists()
