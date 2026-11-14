"""M5-E actual OS SIGKILL + dual-worker negative matrix, strictly offline.

The worker uses the production EventStore, TaskBudgetStore, T1 admission,
SessionStore lease and FileService. Provider and Tool transport are NEVER
executed: synthetic local events cannot prove remote Provider settlement or
file-effect causation. These tests MUST NOT be interpreted as auto-resume.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from llm_loop.core.durable_effect_evidence import inspect_run_effect_evidence
from llm_loop.core.durable_run_recovery import (
    COMPLETED,
    FENCED,
    HOLD,
    OPENED,
    assess_durable_run,
)
from llm_loop.core.trace_leak.ingress_token import issue_ingress
from llm_loop.event_log.model import build_message_payload
from llm_loop.event_log.store import EventStore
from llm_loop.resources.task_budget_dispatch import exact_workspace_scope
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError, TaskBudgetStore
from llm_loop.resources.task_budget_t1_web_profile import (
    T1WebEventPlan,
    prepare_t1_web_event_budget,
)

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or not hasattr(signal, "SIGKILL"),
    reason="real POSIX SIGKILL and flock required",
)

AUTH = "a" * 32
GEN = "b" * 32
SID = "m5e-offline-process"
BID = "webt1-" + AUTH
WORKER = Path(__file__).resolve().parents[1] / "fixtures" / "m5e_fault_worker.py"


def _setup(tmp_path: Path, *, operator: bool = False) -> Path:
    root = tmp_path / "m5e-sandbox"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "target.md").write_text("# Offline\nOLD\n", encoding="utf-8")
    events = EventStore(root / "events")
    user_text = "offline crash matrix; no Provider call"
    events.append_durable_human_message(
        SID,
        build_message_payload(
            index=0, role="user", source="user", content=user_text,
            metadata={"origin_layer": "user_instruction", "program_origin": False},
        ),
    )
    config = {
        "session_id": SID,
        "authorization_id": AUTH,
        "run_generation": GEN,
        "target_sha256": hashlib.sha256(
            (root / "docs" / "target.md").read_bytes()
        ).hexdigest(),
        "user_text": user_text,
        "valid_from_epoch_s": time.time() - 20,
        "valid_until_epoch_s": time.time() + 3500,
    }
    if operator:
        operator_file = root / "operator-config.json"
        operator_file.write_text('{"test":"authorized"}', encoding="utf-8")
        operator_file.chmod(0o600)
        config["operator_config_path"] = str(operator_file.resolve())
        config["operator_config_sha256"] = hashlib.sha256(
            operator_file.read_bytes()
        ).hexdigest()
    (root / "plan.json").write_text(
        json.dumps(config, sort_keys=True), encoding="utf-8"
    )
    return root


def _stores(root: Path):
    return EventStore(root / "events"), TaskBudgetStore(root / "ledger")


def _plan(root: Path) -> T1WebEventPlan:
    cfg = json.loads((root / "plan.json").read_text(encoding="utf-8"))
    events, budget = _stores(root)
    return T1WebEventPlan(
        session_id=SID, workspace_scope=exact_workspace_scope(str(root)),
        authorization_id=AUTH, target_path="docs/target.md",
        prepared_target_sha256=cfg["target_sha256"],
        valid_from_epoch_s=cfg["valid_from_epoch_s"],
        valid_until_epoch_s=cfg["valid_until_epoch_s"],
        event_store=events, budget_store=budget,
        durable_run_admission_required=True,
        operator_config_path=cfg.get("operator_config_path", ""),
        operator_config_sha256=cfg.get("operator_config_sha256", ""),
    )


def _prepare(root: Path) -> None:
    plan = _plan(root)
    event = next(e for e in plan.event_store.read(SID) if e.type == "message.appended")
    prepare_t1_web_event_budget(
        plan=plan, event=event, session_id=SID,
        workspace_root=str(root), run_generation=GEN,
        user_text="offline crash matrix; no Provider call",
        ingress=issue_ingress("web"),
    )
    row = plan.budget_store.read(BID)
    cfg_path = root / "plan.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["admission_revision"] = row["revision"]
    cfg_path.write_text(json.dumps(cfg, sort_keys=True), encoding="utf-8")


def _assess(root: Path):
    events, budget = _stores(root)
    return assess_durable_run(
        event_store=events, budget_store=budget,
        session_id=SID, run_generation=GEN, authorization_id=AUTH,
    )


def _effects(root: Path):
    events, budget = _stores(root)
    return inspect_run_effect_evidence(
        event_store=events, budget_store=budget,
        session_id=SID, run_generation=GEN, authorization_id=AUTH,
    )


def _spawn(
    root: Path, mode: str, stage: str, marker: Path, release: Path | None = None,
) -> subprocess.Popen[bytes]:
    source_root = Path(__file__).resolve().parents[2] / "src"
    env = {
        **os.environ,
        "PYTHONPATH": str(source_root),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    args = [sys.executable, str(WORKER), mode, str(root), stage, str(marker)]
    if release is not None:
        args.append(str(release))
    return subprocess.Popen(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _await_marker(proc: subprocess.Popen[bytes], marker: Path) -> None:
    deadline = time.monotonic() + 15
    while not marker.exists():
        if proc.poll() is not None:
            _out, err = proc.communicate(timeout=1)
            pytest.fail(f"worker exited before {marker.name}: {proc.returncode}: {err[-1500:]!r}")
        if time.monotonic() >= deadline:
            proc.kill()
            _out, err = proc.communicate(timeout=3)
            pytest.fail(f"worker timed out at {marker.name}: {err[-1500:]!r}")
        time.sleep(0.01)


def _kill_at(root: Path, mode: str, stage: str) -> None:
    marker = root / (mode + "-" + stage + ".marker")
    proc = _spawn(root, mode, stage, marker)
    try:
        _await_marker(proc, marker)
        proc.kill()  # real OS SIGKILL, not os._exit or a mocked exception
        _out, err = proc.communicate(timeout=5)
        assert proc.returncode == -signal.SIGKILL, err[-1200:]
        assert marker.read_text(encoding="utf-8") == stage
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=3)


def _probe(root: Path, mode: str, stage: str) -> dict:
    marker = root / (mode + "-" + stage + ".marker")
    proc = _spawn(root, mode, stage, marker)
    out, err = proc.communicate(timeout=15)
    assert proc.returncode == 0, (out[-500:], err[-1500:])
    return json.loads((marker.parent / (marker.name + ".result")).read_text())


@pytest.mark.parametrize(
    ("stage", "expected_facts"),
    [("before_open", []), ("after_open", [OPENED]), ("after_fence", [OPENED, FENCED])],
)
def test_m5e_sigkill_real_t1_admission_never_replays_old_auth(
    tmp_path: Path, stage: str, expected_facts: list[str],
) -> None:
    root = _setup(tmp_path)
    before = (root / "docs" / "target.md").read_bytes()
    _kill_at(root, "admission", stage)
    events, budget = _stores(root)
    facts = [e.type for e in events.read(SID) if e.type.startswith("run.durable.")]
    assert facts == expected_facts
    assert budget.read(BID)["phase"] == "active"
    assert budget.read(BID)["reservations"] == {}
    verdict = _assess(root)
    assert verdict.decision == HOLD
    assert not verdict.auto_resume_allowed and not verdict.old_run_replay_allowed
    assert (root / "docs" / "target.md").read_bytes() == before
    plan = _plan(root)
    event = next(e for e in events.read(SID) if e.type == "message.appended")
    with pytest.raises(TaskBudgetDeniedError):
        prepare_t1_web_event_budget(
            plan=replace(plan, event_store=events, budget_store=budget),
            event=event, session_id=SID, workspace_root=str(root),
            run_generation="f" * 32,
            user_text="offline crash matrix; no Provider call",
            ingress=issue_ingress("web"),
        )


@pytest.mark.parametrize(
    ("stage", "phase", "transport_opened", "transport_settled"),
    [
        ("before_dispatch", "reserved", 0, 0),
        ("after_dispatch", "dispatched", 0, 0),
        ("transport_opened", "dispatched", 1, 0),
        ("transport_settled", "dispatched", 1, 1),
    ],
)
def test_m5e_sigkill_provider_local_windows_preserve_unknown_liability(
    tmp_path: Path, stage: str, phase: str, transport_opened: int,
    transport_settled: int,
) -> None:
    root = _setup(tmp_path)
    _prepare(root)
    _kill_at(root, "provider", stage)
    events, budget = _stores(root)
    row = budget.read(BID)
    assert len(row["reservations"]) == 1
    reservation = next(iter(row["reservations"].values()))
    assert reservation["kind"] == "physical_attempts"
    assert reservation["phase"] == phase
    assert _assess(root).decision == HOLD
    effect = _effects(root)
    assert effect.decision == HOLD
    assert effect.provider_transport_opened == transport_opened
    assert effect.provider_transport_settled == transport_settled
    assert effect.provider_budget_unsettled == 1
    assert not effect.remote_provider_settlement_proven
    assert not effect.auto_resume_allowed
    probe = _probe(root, "replay_probe", stage)
    assert probe == {"outcome": "denied", "exception": "TaskBudgetDeniedError"}
    assert len(budget.read(BID)["reservations"]) == 1


@pytest.mark.parametrize(
    ("stage", "mutated", "observed"),
    [
        ("effect_prepared", False, 0),
        ("effect_replaced", True, 0),
        ("effect_observed", True, 1),
    ],
)
def test_m5e_sigkill_real_file_service_effect_window_never_proves_causation(
    tmp_path: Path, stage: str, mutated: bool, observed: int,
) -> None:
    root = _setup(tmp_path)
    _prepare(root)
    before = (root / "docs" / "target.md").read_bytes()
    _kill_at(root, "tool", stage)
    after = (root / "docs" / "target.md").read_bytes()
    assert (after != before) is mutated
    assert after.count(b"NEW") == (1 if mutated else 0)
    assert after.count(b"OLD") == (0 if mutated else 1)
    row = _stores(root)[1].read(BID)
    assert len(row["reservations"]) == 1
    assert next(iter(row["reservations"].values()))["phase"] == "dispatched"
    assert _assess(root).decision == HOLD
    effect = _effects(root)
    assert effect.tool_effect_prepared == 1
    assert effect.tool_effect_observed == observed
    assert effect.tool_effect_unresolved >= 1
    assert not effect.tool_effect_causation_proven
    assert not effect.auto_resume_allowed
    probe = _probe(root, "replay_probe", stage)
    assert probe == {"outcome": "denied", "exception": "TaskBudgetDeniedError"}
    assert (root / "docs" / "target.md").read_bytes() == after


@pytest.mark.parametrize(
    ("stage", "expected_decision"),
    [("after_run_end", HOLD), ("after_terminal", COMPLETED)],
)
def test_m5e_sigkill_finalizer_terminal_window_is_not_replay_authority(
    tmp_path: Path, stage: str, expected_decision: str,
) -> None:
    root = _setup(tmp_path)
    _prepare(root)
    _kill_at(root, "finalizer", stage)
    verdict = _assess(root)
    assert verdict.decision == expected_decision
    assert not verdict.auto_resume_allowed
    assert not verdict.old_run_replay_allowed
    assert _effects(root).decision == HOLD
    assert _stores(root)[1].read(BID)["phase"] == "stop_requested"


def test_m5e_two_process_session_lease_exclusive_and_kill_releases(
    tmp_path: Path,
) -> None:
    root = _setup(tmp_path)
    marker = root / "lease-owner.marker"
    owner = _spawn(root, "lease_hold", "holding", marker)
    try:
        _await_marker(owner, marker)
        assert _probe(root, "lease_probe", "contended")["acquired"] is False
        owner.kill()
        owner.communicate(timeout=5)
        assert owner.returncode == -signal.SIGKILL
        assert _probe(root, "lease_probe", "released")["acquired"] is True
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.communicate(timeout=3)


def test_m5e_two_process_budget_cas_only_one_wins(
    tmp_path: Path,
) -> None:
    root = _setup(tmp_path)
    _prepare(root)
    release = root / "cas-release"
    markers = [root / "cas-one.marker", root / "cas-two.marker"]
    workers = [
        _spawn(root, "budget_cas", stage, marker, release)
        for stage, marker in zip(("one", "two"), markers, strict=True)
    ]
    try:
        for worker, marker in zip(workers, markers, strict=True):
            _await_marker(worker, marker)
        release.write_text("go", encoding="utf-8")
        for worker in workers:
            out, err = worker.communicate(timeout=10)
            assert worker.returncode == 0, (out[-500:], err[-1200:])
        results = [
            json.loads((root / (m.name + ".result")).read_text())
            for m in markers
        ]
        assert sorted(r["outcome"] for r in results) == ["denied", "reserved"]
        denied = next(r for r in results if r["outcome"] == "denied")
        assert denied["exception"] == "TaskBudgetConflictError"
        assert "stale budget revision CAS" in denied["reason"]
        row = _stores(root)[1].read(BID)
        assert len(row["reservations"]) == 1
        assert next(iter(row["reservations"].values()))["phase"] == "reserved"
        assert _assess(root).decision == HOLD
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
                worker.communicate(timeout=3)


def test_m5e_cross_process_operator_revocation_denies_next_action(
    tmp_path: Path,
) -> None:
    root = _setup(tmp_path, operator=True)
    _prepare(root)
    marker = root / "revoke-ready.marker"
    release = root / "revoke-release"
    worker = _spawn(root, "revoke", "waiting", marker, release)
    try:
        _await_marker(worker, marker)
        operator_file = root / "operator-config.json"
        operator_file.write_text('{"test":"revoked"}', encoding="utf-8")
        release.write_text("go", encoding="utf-8")
        out, err = worker.communicate(timeout=10)
        assert worker.returncode == 0, (out[-500:], err[-1200:])
        result = json.loads((root / (marker.name + ".result")).read_text())
        assert result["outcome"] == "denied"
        assert result["exception"] == "TaskBudgetDeniedError"
        row = _stores(root)[1].read(BID)
        assert row["phase"] == "stop_requested"
        assert row["reservations"] == {}
        assert _assess(root).decision == HOLD
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.communicate(timeout=3)
