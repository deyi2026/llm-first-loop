"""err1210 P2 oracle CLI 测试（tasks 7.1；spec 5.2.1-3、design 2.2.2-⑧）.

覆盖: 参数解析（env ORACLE_1210_BUDGET/QPS 默认值）、dry-run 零发送、
单轨 dry-run 只构造该轨变体、快照缺失错误退出、工单例外条款
（spec 5.2.1-5b）在 dry-run 下的跳过骨架轨标记。零真实网络
（live 发送路径由 test_oracle_1210.TestRunOracle 的 mock client 覆盖）。
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.oracle_1210_replay import main, parse_args

_SNAPSHOT = {
    "schema": 1,
    "ts_utc": "2026-08-27T11:02:30.370547+00:00",
    "session_id": "sess-cli-test-00000000",
    "model": "glm-5.3",
    "is_compact_first": True,
    "messages": [
        {"role": "system", "content": "S" * 50},
        {"role": "user", "content": "hist-" + "x" * 80},
        {"role": "assistant", "content": "hist-" + "x" * 80},
        {"role": "user", "content": "inj-0-" + "y" * 60},
    ],
    "tools": [],
    "params": {"timeout_s": 30},
    "injection_span": [{"msg_idx": 3, "slot_kind": "INTEROP", "prefix_sha": "sha0"}],
    "trace_key": {"session_id": "sess-cli-test-00000000", "local_ts": "2026-08-27T19:02:30"},
}


def _write_snapshot(tmp_path: Path) -> Path:
    p = tmp_path / "snap.json"
    p.write_text(json.dumps(_SNAPSHOT, ensure_ascii=False), encoding="utf-8")
    return p


def test_env_budget_qps_defaults(monkeypatch):
    monkeypatch.setenv("ORACLE_1210_BUDGET", "7")
    monkeypatch.setenv("ORACLE_1210_QPS", "1.0")
    ns = parse_args(["--snapshot", "x.json"])
    assert ns.budget == 7
    assert ns.qps == 1.0


def test_env_defaults_fallback(monkeypatch):
    monkeypatch.delenv("ORACLE_1210_BUDGET", raising=False)
    monkeypatch.delenv("ORACLE_1210_QPS", raising=False)
    ns = parse_args(["--snapshot", "x.json"])
    assert ns.budget == 20
    assert ns.qps == 0.5


def test_env_bad_value_falls_back(monkeypatch):
    monkeypatch.setenv("ORACLE_1210_BUDGET", "abc")
    ns = parse_args(["--snapshot", "x.json"])
    assert ns.budget == 20


def test_dry_run_no_send(tmp_path, capsys):
    p = _write_snapshot(tmp_path)
    code = main(["--snapshot", str(p), "--dry-run", "--data-dir", str(tmp_path / "data")])
    out = capsys.readouterr().out
    assert code == 0
    assert "dry-run 完成" in out and "未发送任何请求" in out
    assert "skel-000" in out and "bis-r0-keep-all" in out


def test_single_track_dry_run(tmp_path, capsys):
    p = _write_snapshot(tmp_path)
    code = main(["--snapshot", str(p), "--track", "skeleton", "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0
    assert "skel-000" in out
    assert "bis-r0" not in out, "单轨 dry-run 只构造该轨道变体"


def test_missing_snapshot_exit_1(tmp_path, capsys):
    code = main(["--snapshot", str(tmp_path / "nope.json"), "--dry-run"])
    err = capsys.readouterr().err
    assert code == 1
    assert "快照不存在" in err


def test_ticket_evidence_skips_skeleton(tmp_path, capsys):
    """spec 5.2.1-5b: 工单证据下骨架轨记 skipped_ticket（dry-run 不发送）. """
    p = _write_snapshot(tmp_path)
    code = main(
        ["--snapshot", str(p), "--dry-run", "--ticket-ref", "T-20260827-01",
         "--ticket-note", "官方确认连续 user 条数上限", "--data-dir", str(tmp_path / "d")]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "工单证据: #T-20260827-01" in out
    assert "skipped_ticket" in out
    assert "跳过骨架轨" in out
