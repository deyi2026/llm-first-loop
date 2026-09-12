"""EVO-20260912-10818cb5 胶水层测试: smx_perceive 三面（wait/snapshot-diff/receipt）+ 安全拒绝.

冻结实现 tools/smx/smx.py 不改；本文件只测胶水层:
- wait 满足/超时语义（超时=正常观测 satisfied=false，非工具故障）
- loopback 与 run_id 白名单的胶水层预拒绝（smx 内部还有第二道）
- snapshot/diff 净变更（复用冻结 take_snapshot/diff_pair）
- 回执摘要查询 + 路径穿越拒绝
- opt-in 默认关闭（config 字段默认空）
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from llm_loop.config import Settings
from llm_loop.core.message import ToolResultStatus
from llm_loop.tools.builtin.smx_perceive import SmxPerceiveTool

SMX_PATH = Path(__file__).resolve().parents[1] / "tools" / "smx" / "smx.py"


@pytest.fixture()
def tool(tmp_path):
    return SmxPerceiveTool(smx_path=str(SMX_PATH), data_dir=str(tmp_path / "data"), max_wait_s=5.0)


def _payload(res):
    return json.loads(res.content)


# ---------- wait ----------
def test_wait_file_exists_satisfied(tool, tmp_path):
    flag = tmp_path / "done.flag"
    flag.write_text("ok")
    res = tool.execute(action="wait", file_exists=str(flag), timeout=3, root=str(tmp_path))
    assert res.status == ToolResultStatus.SUCCESS
    p = _payload(res)
    assert p["satisfied"] is True and p["kind"] == "wait"
    assert p["run_id"]


def test_wait_timeout_is_observation_not_failure(tool, tmp_path):
    res = tool.execute(action="wait", file_exists=str(tmp_path / "never.flag"),
                       timeout=0.6, interval=0.2, root=str(tmp_path))
    assert res.status == ToolResultStatus.SUCCESS  # 超时=正常观测
    p = _payload(res)
    assert p["satisfied"] is False and p.get("waited_ms", 0) >= 500


def test_wait_nonloopback_host_rejected(tool):
    res = tool.execute(action="wait", port_open=80, host="example.com", timeout=1)
    assert res.status == ToolResultStatus.FAILURE and "安全拒绝" in res.content


def test_wait_two_predicates_rejected(tool, tmp_path):
    res = tool.execute(action="wait", file_exists=str(tmp_path), file_gone=str(tmp_path / "x"))
    assert res.status == ToolResultStatus.FAILURE and "恰好一个谓词" in res.content


def test_wait_no_command_surface(tool):
    assert "command" not in json.dumps(tool.parameters["properties"])
    assert "cmd" not in tool.parameters["properties"]


# ---------- snapshot / diff ----------
def test_snapshot_then_diff_shows_created(tool, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    snap = _payload(tool.execute(action="snapshot", roots=[str(work)], depth=2))
    assert snap["entries"] == 1  # 冻结行为: 空目录计根条目
    (work / "new.txt").write_text("hi")
    d = _payload(tool.execute(action="diff", since=snap["snapshot_id"]))
    assert d["created"] == 1 and d["deleted"] == 0  # modified=1 为根目录 mtime，属冻结语义
    assert any("+new.txt" in r for r in d["display_rows"])


def test_diff_between_two_snapshots_shows_deleted(tool, tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    victim = work / "old.txt"
    victim.write_text("x")
    s1 = _payload(tool.execute(action="snapshot", roots=[str(work)]))["snapshot_id"]
    victim.unlink()
    s2 = _payload(tool.execute(action="snapshot", roots=[str(work)]))["snapshot_id"]
    d = _payload(tool.execute(action="diff", since=s1, current=s2))
    assert d["deleted"] == 1 and any("-old.txt" in r for r in d["display_rows"])


def test_diff_truncated_budget_never_reports_deleted(tool, tmp_path):
    # P1 回归: budget 截断侧的 ±差集不可判（110 文件 + 根 = 111 条目 > budget 100）。
    # 旧行为会把 11 个被预算裁剪掉的文件误报为 deleted；修复后必须降级为 null(unknown)。
    work = tmp_path / "w"
    work.mkdir()
    for i in range(110):
        (work / f"f{i:03d}.txt").write_text("x")
    s1 = _payload(tool.execute(action="snapshot", roots=[str(work)], budget=5000))["snapshot_id"]
    s2 = _payload(tool.execute(action="snapshot", roots=[str(work)], budget=100))["snapshot_id"]
    d = _payload(tool.execute(action="diff", since=s1, current=s2))
    assert d["diff_complete"] is False
    assert d["deleted"] is None and d["created"] is None and d["total_changes"] is None
    assert not any(r.startswith(("+", "-")) for r in d["display_rows"])
    assert any(m.get("truncated") for m in d["meta"]["current"])
    assert "warning" in d


def test_diff_live_truncated_baseline_also_downgrades(tool, tmp_path):
    # 现场(现拍)分支同样受完整性纪律约束: 基线截断即降级，磁盘无删除就不得报 deleted。
    work = tmp_path / "w"
    work.mkdir()
    for i in range(110):
        (work / f"g{i:03d}.txt").write_text("x")
    s1 = _payload(tool.execute(action="snapshot", roots=[str(work)], budget=100))["snapshot_id"]
    d = _payload(tool.execute(action="diff", since=s1))  # live 现拍按基线 budget=100，同样截断
    assert d["diff_complete"] is False
    assert d["deleted"] is None and d["created"] is None
    assert d["meta"]["baseline"] and "warning" in d


def test_diff_bad_snapshot_id_rejected(tool):
    res = tool.execute(action="diff", since="../evil")
    assert res.status == ToolResultStatus.FAILURE


# ---------- receipt ----------
def test_receipt_summary_and_traversal_rejected(tool, tmp_path):
    flag = tmp_path / "done.flag"
    flag.write_text("ok")
    w = _payload(tool.execute(action="wait", file_exists=str(flag), timeout=3, root=str(tmp_path)))
    rid = w["run_id"]
    r = _payload(tool.execute(action="receipt", run_id=rid, root=str(tmp_path)))
    assert r["kind"] == "wait" and r["satisfied"] is True and "hint" in r
    full = _payload(tool.execute(action="receipt", run_id=rid, root=str(tmp_path), full=True))
    assert full["run_id"] == rid and "_receipt_path" in full
    for bad in ("../evil", "a/b", "", "a..b"):
        res = tool.execute(action="receipt", run_id=bad, root=str(tmp_path))
        assert res.status == ToolResultStatus.FAILURE, bad


def test_receipt_missing_run(tool, tmp_path):
    res = tool.execute(action="receipt", run_id="no-such-run", root=str(tmp_path))
    assert res.status == ToolResultStatus.FAILURE and "回执不存在" in res.content


# ---------- opt-in ----------
def test_opt_in_default_off():
    f = next(f for f in dataclasses.fields(Settings) if f.name == "smx_perceive_path")
    assert f.default == ""
