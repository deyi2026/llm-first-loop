"""Real Host-only CLI path: no Engine, no Provider, no Goal/Task mutation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.introspection.goal import GoalStore
from llm_loop.introspection.owner_finality_host import check_completed_goal
from llm_loop.introspection.task_evidence import TaskEvidenceVerifier
from llm_loop.introspection.task_store import TaskStore
from llm_loop.memory.evidence import (
    BlobStore,
    Coverage,
    EvidenceCapture,
    EvidenceLedgerStore,
    OwnerScope,
    Provenance,
    SourceIdentity,
    SourceKind,
    SourceVersionPolicy,
    make_capture_request,
)
from llm_loop.skills.loader import write_manifest
from llm_loop.terminal.queries import dispatch_query

REPO = Path(__file__).resolve().parents[2]
SID = "owner-verified-1"


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assets = tmp_path / "assets"
    (assets / "docs").mkdir(parents=True)
    (assets / "docs" / "ai_rules.md").write_bytes((REPO / "docs" / "ai_rules.md").read_bytes())
    target = assets / "skills" / "owner-finality-verify"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_bytes(
        (REPO / "skills" / "owner-finality-verify" / "SKILL.md").read_bytes()
    )
    write_manifest(assets / "skills")
    monkeypatch.setenv("LFL_SKILLS_REQUIRE_MANIFEST", "1")

    audit = data / "audit"
    goal = GoalStore(audit).create("Trusted Host finality fixture", session_id=SID)
    owner = OwnerScope(workspace_id=str(workspace.resolve()), session_id=SID)
    blobs = BlobStore(data / "evidence" / "blobs")
    ledger = EvidenceLedgerStore(data / "evidence" / "ledger")
    verifier = TaskEvidenceVerifier(blobs, ledger, owner_resolver=lambda: owner)
    tasks = TaskStore(audit, evidence_verifier=verifier)
    task = tasks.create(goal.id, "Check durable evidence",
                        acceptance=["exact owner EvidenceRef is valid"],
                        evidence_required=True)
    return SimpleNamespace(
        data=data, workspace=workspace, assets=assets, audit=audit,
        goal=goal, task=task, tasks=tasks, blobs=blobs, ledger=ledger,
        owner=owner, verifier=verifier,
    )


def _complete(fx):
    ref = EvidenceCapture(fx.blobs, fx.ledger).capture(make_capture_request(
        owner=fx.owner, stable_capture_id="host-finality-positive",
        raw_observation="trusted fixture observation",
        acquired_at=datetime.now(UTC),
        tool_name="read_file", tool_call_id="call-finality",
        source=SourceIdentity(kind=SourceKind.FILE,
                              locator="fixture/result.txt",
                              version_policy=SourceVersionPolicy.SNAPSHOT_ONLY),
        coverage=Coverage(unit="line", start=0, end_exclusive=1,
                          source_complete=True),
        provenance=Provenance(producer="isolated_test"),
    )).evidence_ref.ref
    fx.tasks.update(fx.goal.id, fx.task.task_id, status="in_progress")
    fx.tasks.update(fx.goal.id, fx.task.task_id, status="done", evidence_refs=[ref])
    GoalStore(fx.audit).update(fx.goal.id, "complete", reason="fixture only")
    return ref


def _check(fx, **kwargs):
    return check_completed_goal(
        data_dir=kwargs.get("data_dir", fx.data),
        workspace=kwargs.get("workspace", fx.workspace),
        asset_root=kwargs.get("asset_root", fx.assets),
        goal_id=kwargs.get("goal_id", fx.goal.id),
        session_id=kwargs.get("session_id", SID),
    )


def _ledgers(fx):
    return (
        (fx.audit / "goals.jsonl").read_bytes(),
        (fx.audit / "tasks" / f"{fx.goal.id}.jsonl").read_bytes(),
        *(
            (p.relative_to(fx.data).as_posix(), p.read_bytes())
            for p in sorted((fx.data / "evidence").rglob("*"))
            if p.is_file()
        ),
    )


def test_host_completed_goal_verifies_exact_evidence_and_never_calls_provider(
    tmp_path, monkeypatch
):
    fx = _fixture(tmp_path, monkeypatch)
    _complete(fx)
    # The Host-only path must never import or build a model engine.
    import llm_loop.factory as factory

    monkeypatch.setattr(factory, "build_engine", lambda *_a, **_kw: pytest.fail("engine called"))
    before = _ledgers(fx)
    before_tree = sorted(
        (str(f.relative_to(fx.data)), f.read_bytes())
        for f in fx.data.rglob("*") if f.is_file()
    )
    for _ in range(3):
        r = _check(fx)
        assert r["decision"] == "NO_WRITE_VERIFIED", r
        assert r["reason"] == "goal_already_complete_with_verified_refs"
        assert r["evidence_status"] == "verified"
        assert r["tasks_checked"] == r["evidence_refs_checked"] == 1
        assert r["model_calls"] == 0
        assert r["no_write"] is True and r["host_permission_granted"] is False
    assert _ledgers(fx) == before
    assert sorted(
        (str(f.relative_to(fx.data)), f.read_bytes())
        for f in fx.data.rglob("*") if f.is_file()
    ) == before_tree


def test_host_active_or_missing_evidence_cannot_skip(tmp_path, monkeypatch):
    fx = _fixture(tmp_path, monkeypatch)
    assert _check(fx)["reason"] == "goal_not_complete"
    GoalStore(fx.audit).update(fx.goal.id, "complete", reason="bad historical flag")
    r = _check(fx)
    assert r["decision"] == "HOLD"
    assert r["reason"] in {"evidence_ref_missing", "required_knowledge_not_verified", "evidence_lock_unavailable"}
    assert r["model_calls"] == 0


def test_host_missing_blob_or_cross_owner_fails_closed(tmp_path, monkeypatch):
    fx = _fixture(tmp_path, monkeypatch)
    ref = _complete(fx)
    assert _check(fx)["decision"] == "NO_WRITE_VERIFIED"
    wrong = tmp_path / "other-workspace"
    wrong.mkdir()
    assert _check(fx, workspace=wrong)["decision"] == "HOLD"
    assert _check(fx, session_id="other-owner")["reason"] == "goal_owner_scope_mismatch"
    from llm_loop.memory.evidence import EvidenceRef
    record = fx.ledger.require_authorized(fx.owner, EvidenceRef(ref))
    assert fx.blobs.delete(record.blob_ref)
    r = _check(fx)
    assert r["decision"] == "HOLD"
    assert r["evidence_status"] != "verified"


def test_host_corrupt_ledger_or_tampered_skill_fails_closed(tmp_path, monkeypatch):
    fx = _fixture(tmp_path, monkeypatch)
    _complete(fx)
    skill = fx.assets / "skills" / "owner-finality-verify" / "SKILL.md"
    skill.write_text(skill.read_text() + "\nInjected new instruction\n")
    assert _check(fx)["decision"] == "HOLD"
    assert _check(fx)["knowledge_gaps"]
    skill.write_bytes((REPO / "skills" / "owner-finality-verify" / "SKILL.md").read_bytes())
    assert _check(fx)["decision"] == "NO_WRITE_VERIFIED"
    with (fx.audit / "tasks" / f"{fx.goal.id}.jsonl").open("ab") as fh:
        fh.write(b"invalid-json\n")
    assert _check(fx)["reason"] == "task_ledger_corrupt"


def test_host_missing_evidence_lock_never_creates_one(tmp_path, monkeypatch):
    fx = _fixture(tmp_path, monkeypatch)
    _complete(fx)
    lock = fx.data / "evidence" / "ledger" / ".gc.lock"
    assert lock.is_file()
    lock.unlink()
    before = _ledgers(fx)
    assert _check(fx)["reason"] == "evidence_lock_unavailable"
    assert not lock.exists()
    assert _ledgers(fx) == before


def test_host_missing_roots_and_traversal_never_create_files(tmp_path, monkeypatch):
    fx = _fixture(tmp_path, monkeypatch)
    missing = tmp_path / "does-not-exist"
    assert _check(fx, data_dir=missing)["decision"] == "HOLD"
    assert not missing.exists()
    assert _check(fx, goal_id="../../outside")["reason"] == "invalid_goal_or_session_id"
    assert _check(fx, session_id="../other")["reason"] == "invalid_goal_or_session_id"
    _complete(fx)
    (fx.assets / "docs" / "ai_rules.md").unlink()
    assert _check(fx)["reason"] == "required_rule_or_skill_unavailable"


def test_real_cli_query_dispatch_with_bound_host_roots(tmp_path, monkeypatch, capsys):
    fx = _fixture(tmp_path, monkeypatch)
    _complete(fx)
    options = SimpleNamespace(
        data_dir=str(fx.data), workspace=str(fx.workspace),
        config=str(tmp_path / "empty.env"), _query_home=str(fx.assets),
    )
    before = _ledgers(fx)
    assert dispatch_query(
        ["owner-finality", "--goal-id", fx.goal.id, "--session", SID, "--json"],
        options,
    ) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "NO_WRITE_VERIFIED" and out["model_calls"] == 0
    assert _ledgers(fx) == before

    # No implicit production/workspace lookup is ever accepted.
    options.workspace = None
    assert dispatch_query(
        ["owner-finality", "--goal-id", fx.goal.id, "--session", SID],
        options,
    ) == 3
    assert json.loads(capsys.readouterr().out)["reason"] == "explicit_host_roots_required"


def test_wheel_resource_list_includes_skill_manifest_without_other_dotfiles(
    tmp_path, monkeypatch
):
    import runpy
    from unittest.mock import patch

    with patch("setuptools.setup"):
        scope = runpy.run_path(str(REPO / "setup.py"))
    bundle = tmp_path / "fake-source"
    for name in ("skills/owner-finality-verify", "methods", "webui/dist", "docs"):
        (bundle / name).mkdir(parents=True, exist_ok=True)
    (bundle / "skills" / ".manifest.json").write_text("{}")
    (bundle / "skills" / ".secret").write_text("not a package resource")
    (bundle / "skills" / "owner-finality-verify" / "SKILL.md").write_text("steps")
    (bundle / "webui" / "dist" / "index.html").write_text("html")
    (bundle / "webui" / "dist" / ".hidden").write_text("hidden")
    scope["resource_files"].__globals__["ROOT"] = bundle
    names = [str(relative) for _source, relative in scope["resource_files"]()]
    assert "skills/.manifest.json" in names
    assert "skills/owner-finality-verify/SKILL.md" in names
    assert "skills/.secret" not in names
    assert "webui/dist/.hidden" not in names


def test_installed_bundle_assets_take_priority_over_mutable_home(
    tmp_path, monkeypatch, capsys
):
    fx = _fixture(tmp_path, monkeypatch)
    _complete(fx)
    from llm_loop.runtime import installation

    monkeypatch.setattr(installation, "bundle_root", lambda: fx.assets)
    options = SimpleNamespace(
        data_dir=str(fx.data), workspace=str(fx.workspace),
        config=str(tmp_path / "empty.env"),
        _query_home=str(tmp_path / "mutable-home"),
    )
    assert dispatch_query(
        ["owner-finality", "--goal-id", fx.goal.id, "--session", SID],
        options,
    ) == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "NO_WRITE_VERIFIED"


def test_real_lfl_executable_process_has_zero_provider_and_zero_writes(
    tmp_path, monkeypatch
):
    fx = _fixture(tmp_path, monkeypatch)
    _complete(fx)
    before = _ledgers(fx)
    # Use the actual installed console entrypoint and source assets, not
    # a mocked Host function. No API key is available to the subprocess.
    env = dict(os.environ)
    for name in ("LLM_API_KEY", "OPENAI_API_KEY", "MODEL_PROVIDERS"):
        env.pop(name, None)
    env["PYTHONPATH"] = str(REPO / "src")
    env["LFL_SKILLS_REQUIRE_MANIFEST"] = "1"
    exe = Path(sys.executable).parent / "lfl"
    proc = subprocess.run(
        [str(exe), "--data-dir", str(fx.data), "--workspace", str(fx.workspace),
         "owner-finality", "--goal-id", fx.goal.id, "--session", SID, "--json"],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=25,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    out = json.loads(proc.stdout)
    assert out["decision"] == "NO_WRITE_VERIFIED" and out["model_calls"] == 0
    assert out["host_permission_granted"] is False
    assert _ledgers(fx) == before

    # Same real CLI must fail closed on a different session ID.
    bad = subprocess.run(
        [str(exe), "--data-dir", str(fx.data), "--workspace", str(fx.workspace),
         "owner-finality", "--goal-id", fx.goal.id,
         "--session", "wrong-owner", "--json"],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=25,
        check=False,
    )
    assert bad.returncode == 3
    assert json.loads(bad.stdout)["decision"] == "HOLD"
    assert _ledgers(fx) == before
