"""EVO-20261002-daa84575 §3: update_goal(complete) spec 吸收归档门（G5，可见性轴）.

门语义（complete 专用；blocked 不走门）:
  - goal 声明 spec_change_ref 且未带 spec_archive → BLOCKED spec_archive_missing
    （出口: 补归档清单 / 声明不适用 / 人工 waive——防死锁指路）
  - 归档清单形态: result_doc + merged_docs 引用真实性机械核验（路径存在 /
    evidence:// 过 verifier），不做语义判定; 引用缺失 → BLOCKED spec_archive_missing
  - 不适用形态: applicable=false + 非空 reason → 记录后放行
  - 旧 Goal 未声明 spec_change_ref: 零行为变化（SUCCESS + 一次性提示补充）
  - §4.3 fail-open: 校验器不可用/探针故障 → pending_verification 标记放行
    （区别于终局证据门 fail-closed——可见性轴 ≠ 终局真实性轴）
"""

from __future__ import annotations

from types import SimpleNamespace

from llm_loop.core.message import ToolResultStatus
from llm_loop.introspection.goal import GoalStore
from llm_loop.introspection.task_store import TaskStore
from llm_loop.introspection.tools_goal import run_get_goal, run_update_goal


class _FakeVerifier:
    """轻量 verifier: 只暴露 verify(refs) -> report(status)."""

    def __init__(self, status: str = "verified") -> None:
        self.status = status
        self.calls: list[list[str]] = []

    def verify(self, refs) -> SimpleNamespace:  # noqa: ANN001
        self.calls.append(list(refs))
        return SimpleNamespace(
            status=self.status,
            failing_ref="",
            checked_at="2026-10-02T07:00:00+08:00",
            refs_digest="digest0",
        )


def _host(tmp_path, verifier=None):
    ctx = SimpleNamespace(task_evidence_verifier=verifier)
    return SimpleNamespace(audit_dir=str(tmp_path), ctx=ctx, session_id="s-spec")


def _goal(tmp_path, title="spec 归档门测试目标", spec_change_ref="") -> str:
    store = GoalStore(str(tmp_path))
    g = store.create(title, session_id="s-spec", spec_change_ref=spec_change_ref)
    return g.id


def _complete(host, gid, evidence_refs=None, spec_archive=None):
    args = {"goal_id": gid, "status": "complete"}
    if evidence_refs is not None:
        args["evidence_refs"] = evidence_refs
    if spec_archive is not None:
        args["spec_archive"] = spec_archive
    return run_update_goal(None, host, args)


# ---------- 声明了 spec_change_ref 的 Goal ----------

def test_spec_goal_complete_without_declaration_blocked(tmp_path):
    host = _host(tmp_path, verifier=_FakeVerifier())
    gid = _goal(tmp_path, spec_change_ref=".codeartsdoer/specs/20261002/")
    result = _complete(host, gid, evidence_refs=["evidence://v1/abc"])
    assert result.status == ToolResultStatus.BLOCKED
    assert "reason_code=spec_archive_missing" in result.content
    # 防死锁: 出口指路（补清单 / 不适用 / 人工 waive）
    assert "spec_change_ref=.codeartsdoer/specs/20261002/" in result.content
    assert "waive" in result.content or "人工" in result.content


def test_spec_goal_checklist_with_real_paths_passes_and_records(tmp_path):
    host = _host(tmp_path, verifier=_FakeVerifier())
    gid = _goal(tmp_path, spec_change_ref=".codeartsdoer/specs/20261002/")
    result_doc = tmp_path / "result.md"
    result_doc.write_text("# 结果清单", encoding="utf-8")
    merged = tmp_path / "analysis" / "SPEC-ABSORB.md"
    merged.parent.mkdir(parents=True, exist_ok=True)
    merged.write_text("吸收后文档", encoding="utf-8")
    result = _complete(
        host,
        gid,
        evidence_refs=["evidence://v1/abc"],
        spec_archive={"result_doc": str(result_doc), "merged_docs": [str(merged)]},
    )
    assert result.status == ToolResultStatus.SUCCESS
    rec = GoalStore(str(tmp_path)).get(gid)
    sa = rec.get("spec_archive")
    assert isinstance(sa, dict) and sa["applicable"] is True
    assert sa["result_doc"] == str(result_doc)
    assert sa["merged_docs"] == [str(merged)]
    assert sa.get("pending_verification") is False


def test_spec_goal_checklist_with_missing_path_blocked(tmp_path):
    host = _host(tmp_path, verifier=_FakeVerifier())
    gid = _goal(tmp_path, spec_change_ref=".codeartsdoer/specs/20261002/")
    result = _complete(
        host,
        gid,
        evidence_refs=["evidence://v1/abc"],
        spec_archive={
            "result_doc": str(tmp_path / "nope.md"),
            "merged_docs": [str(tmp_path / "docs" / "gone.md")],
        },
    )
    assert result.status == ToolResultStatus.BLOCKED
    assert "reason_code=spec_archive_missing" in result.content
    assert "nope.md" in result.content
    # 拒绝的是书写: goal 未被写成终态
    assert GoalStore(str(tmp_path)).get(gid).get("status") == "active"


def test_spec_goal_not_applicable_declaration_passes(tmp_path):
    host = _host(tmp_path, verifier=_FakeVerifier())
    gid = _goal(tmp_path, spec_change_ref=".codeartsdoer/specs/20261002/")
    result = _complete(
        host,
        gid,
        evidence_refs=["evidence://v1/abc"],
        spec_archive={"applicable": False, "reason": "纯分析类 Goal，无 spec 吸收"},
    )
    assert result.status == ToolResultStatus.SUCCESS
    sa = GoalStore(str(tmp_path)).get(gid).get("spec_archive")
    assert sa["applicable"] is False
    assert sa["reason"] == "纯分析类 Goal，无 spec 吸收"


def test_spec_goal_malformed_declaration_blocked(tmp_path):
    host = _host(tmp_path, verifier=_FakeVerifier())
    gid = _goal(tmp_path, spec_change_ref=".codeartsdoer/specs/20261002/")
    result = _complete(
        host,
        gid,
        evidence_refs=["evidence://v1/abc"],
        spec_archive={"result_doc": str(tmp_path)},  # 缺 merged_docs
    )
    assert result.status == ToolResultStatus.BLOCKED
    assert "reason_code=spec_archive_missing" in result.content
    assert "声明形态无效" in result.content


# ---------- 旧 Goal（未声明 spec_change_ref）: 零行为变化 ----------

def test_old_goal_complete_zero_behavior_change_with_hint(tmp_path):
    verifier = _FakeVerifier("verified")
    host = _host(tmp_path, verifier=verifier)
    gid = _goal(tmp_path)  # 未声明 spec_change_ref
    result = _complete(host, gid, evidence_refs=["evidence://v1/abc"])
    assert result.status == ToolResultStatus.SUCCESS  # 不阻断（红线: 零行为变化）
    assert "spec_change_ref" in result.content  # 一次性提示补充
    assert GoalStore(str(tmp_path)).get(gid).get("spec_archive") is None


def test_old_goal_supplementary_declaration_recorded(tmp_path):
    verifier = _FakeVerifier("verified")
    host = _host(tmp_path, verifier=verifier)
    gid = _goal(tmp_path)
    result = _complete(
        host,
        gid,
        evidence_refs=["evidence://v1/abc"],
        spec_archive={"applicable": False, "reason": "收口时补账: 纯分析任务"},
    )
    assert result.status == ToolResultStatus.SUCCESS
    sa = GoalStore(str(tmp_path)).get(gid).get("spec_archive")
    assert sa and sa["applicable"] is False


# ---------- §4.3 fail-open: 校验器不可用/探针故障 ----------

def test_checklist_evidence_ref_no_verifier_fail_open(tmp_path):
    # done 任务依托 → G4 无需 verifier；G5 的 evidence:// 引用无校验器 → pending 放行
    verifier = _FakeVerifier("verified")
    gid = _goal(tmp_path, spec_change_ref=".codeartsdoer/specs/20261002/")
    ts = TaskStore(str(tmp_path), evidence_verifier=verifier)
    t = ts.create(gid, "吸收任务", acceptance=["验收1"], evidence_required=True)
    ts.update(gid, t.task_id, status="in_progress")
    ts.update(gid, t.task_id, status="done", evidence_refs=["evidence://v1/x"])
    host2 = _host(tmp_path, verifier=None)  # G5 时校验器未装配
    merged = tmp_path / "docs" / "x.md"
    merged.parent.mkdir(parents=True, exist_ok=True)
    merged.write_text("吸收后文档", encoding="utf-8")
    result = _complete(
        host2,
        gid,
        spec_archive={"result_doc": "evidence://v1/result0", "merged_docs": [str(merged), "evidence://v1/m0"]},
    )
    assert result.status == ToolResultStatus.SUCCESS
    sa = GoalStore(str(tmp_path)).get(gid).get("spec_archive")
    assert sa.get("pending_verification") is True


def test_checklist_probe_failure_fail_open(tmp_path, monkeypatch):
    # 探针故障（Path.exists 抛 OSError）→ pending 标记放行（区别于终局证据门 fail-closed）
    verifier = _FakeVerifier("verified")
    host = _host(tmp_path, verifier=verifier)
    gid = _goal(tmp_path, spec_change_ref=".codeartsdoer/specs/20261002/")

    class _BrokenPath(type(tmp_path)):  # noqa: N801
        def exists(self):  # noqa: N802
            raise OSError("probe down")

    import llm_loop.introspection.tools_goal as tg

    monkeypatch.setattr(tg, "Path", _BrokenPath)
    result_doc = tmp_path / "result.md"
    result_doc.write_text("x", encoding="utf-8")
    result = _complete(
        host,
        gid,
        evidence_refs=["evidence://v1/abc"],
        spec_archive={"result_doc": str(result_doc), "merged_docs": [str(tmp_path / "m.md")]},
    )
    assert result.status == ToolResultStatus.SUCCESS
    assert "pending_verification" in result.content
    sa = GoalStore(str(tmp_path)).get(gid).get("spec_archive")
    assert sa.get("pending_verification") is True


# ---------- 检索侧可见性 ----------

def test_get_goal_surfaces_spec_change_ref_states(tmp_path):
    host = _host(tmp_path, verifier=_FakeVerifier())
    gid = _goal(tmp_path, spec_change_ref=".codeartsdoer/specs/20261002/")
    result = run_get_goal(None, host, {"goal_id": gid})
    assert result.status == ToolResultStatus.SUCCESS
    assert "spec_change_ref: .codeartsdoer/specs/20261002/" in result.content
    assert "complete 时需 spec_archive 声明" in result.content
