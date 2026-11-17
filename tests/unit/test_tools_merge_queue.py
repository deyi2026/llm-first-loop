"""merge queue / S1 gate 工具面的失败口径与纯函数边界（RULE-AI-35 实测应拦输入）."""

from __future__ import annotations

from pathlib import Path

from llm_loop.core.message import ToolResultStatus
from llm_loop.introspection import registry_merge_queue
from llm_loop.introspection.tools_merge_queue import (
    run_lane_gate_check,
    run_lane_queue_confirm,
    run_lane_queue_status,
)


class _Host:
    def __init__(self, audit_dir: Path | None) -> None:
        self.audit_dir = str(audit_dir) if audit_dir is not None else None
        self.ctx = None


def test_tool_defs_exposed() -> None:
    names = [d["name"] for d in registry_merge_queue.tool_defs()]
    assert names == [
        "lane_queue_submit",
        "lane_queue_status",
        "lane_merge_advice",
        "lane_queue_confirm",
        "lane_gate_check",
    ]


def test_unknown_tool_returns_none() -> None:
    assert registry_merge_queue.execute("nope", {}, _Host(None)) is None


def test_queue_status_without_audit_dir_degraded() -> None:
    result = run_lane_queue_status(None, _Host(None), {})
    assert result.status is ToolResultStatus.FAILURE
    assert "store_unavailable" in result.content


def test_gate_check_requires_evidence() -> None:
    result = run_lane_gate_check(None, _Host(None), {})
    assert result.status is ToolResultStatus.FAILURE
    assert "missing_param" in result.content


def test_gate_check_blocks_when_main_broken() -> None:
    """应拦输入被拦: main broken 必须 verdict=fail 并指名 s1_01。"""
    evidence = {
        "lane": {"lane_id": "lane-x", "paths": ["src/x.py"]},
        "main": {"head_sha": "a" * 40, "broken": True},
        "now_iso": "2026-11-05T10:00:00",
    }
    result = run_lane_gate_check(None, _Host(None), {"evidence": evidence})
    assert result.status is ToolResultStatus.SUCCESS
    assert '"verdict": "fail"' in result.content
    assert "s1_01" in result.content


def test_gate_check_rollback_denied_by_default() -> None:
    """开关默认关: 即使部署 sha 与 main head 一致也不放行自动回滚。"""
    evidence = {
        "lane": {"lane_id": "lane-x"},
        "main": {"head_sha": "a" * 40},
        "deployment": {"target_sha": "a" * 40},
    }
    result = run_lane_gate_check(
        None, _Host(None), {"evidence": evidence, "rollback": True}
    )
    assert result.status is ToolResultStatus.SUCCESS
    assert '"allow": false' in result.content


def test_confirm_rejects_bad_action() -> None:
    result = run_lane_queue_confirm(
        None, _Host(None), {"lane_id": "lane-x", "action": "bogus"}
    )
    assert result.status is ToolResultStatus.FAILURE
    assert "missing_param" in result.content


def test_status_impact_opt_in_keeps_legacy_fields(monkeypatch, tmp_path: Path) -> None:
    """B2: default off; opt-in is advisory and leaves legacy payload intact."""
    import json
    from types import SimpleNamespace

    from llm_loop.introspection import baseline_impact, tools_merge_queue

    class FakeStore:
        def list(self, *, include_terminal: bool = False) -> list[dict]:
            return [{"lane_id": "lane-1", "status": "queued", "base_main_sha": "a" * 40,
                     "head_sha": "b" * 40, "version": 1}]

        def slot_holder(self) -> None:
            return None

        def probe_main_head(self) -> str:
            return "a" * 40

    host = SimpleNamespace(audit_dir=str(tmp_path), workspace_root=str(tmp_path))
    lane = {"lane_id": "lane-1", "version": 1, "worktree": str(tmp_path)}
    (tmp_path / "lanes.jsonl").write_text(json.dumps(lane) + "\n")
    monkeypatch.setattr(tools_merge_queue, "_store", lambda *_a, **_k: FakeStore())
    monkeypatch.setattr(baseline_impact, "project_baseline_impact", lambda *_a, **_k: {
        "lane_id": "lane-1", "impact": {"status": "stale_needs_refresh",
                                       "reason_codes": ["main_advanced"],
                                       "recommended_next_step": "refresh_base"},
        "evidence": {"projection_is_authoritative": False},
    })
    plain = run_lane_queue_status(None, host, {})
    extra = run_lane_queue_status(None, host, {"with_impact": True})
    plain_json = json.loads(plain.content.split("\n", 1)[1])
    extra_json = json.loads(extra.content.split("\n", 1)[1])
    assert "impact_projection" not in plain_json
    assert {k: v for k, v in extra_json.items() if k != "impact_projection"} == plain_json
    impact = extra_json["impact_projection"]
    assert impact["groups"]["stale_needs_refresh"] == ["lane-1"]
    assert impact["merge_permission"] == "not_granted"
    assert impact["projection_is_authoritative"] is False


def test_status_impact_corrupt_lane_source_fail_closed(monkeypatch, tmp_path: Path) -> None:
    import json
    from types import SimpleNamespace

    from llm_loop.introspection import tools_merge_queue

    class FakeStore:
        def list(self, *, include_terminal: bool = False) -> list[dict]:
            return [{"lane_id": "lane-1", "status": "queued"}]

        def slot_holder(self) -> None:
            return None

        def probe_main_head(self) -> str:
            return "a" * 40

    host = SimpleNamespace(audit_dir=str(tmp_path), workspace_root=str(tmp_path))
    (tmp_path / "lanes.jsonl").write_text(
        '{"lane_id":"lane-1"}\n{"lane_id":"lane-1"}\n'
    )
    monkeypatch.setattr(tools_merge_queue, "_store", lambda *_a, **_k: FakeStore())
    result = run_lane_queue_status(None, host, {"with_impact": True})
    doc = json.loads(result.content.split("\n", 1)[1])["impact_projection"]
    assert doc["source_complete"] is False
    assert doc["items"][0]["impact"]["reason_codes"] == ["lane_snapshot_degraded"]
    assert doc["groups"]["unknown"] == ["lane-1"]
