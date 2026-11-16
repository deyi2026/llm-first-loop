"""Host gate T07/T21-T25: authoritative sources, identity, and trust failures."""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from premerge_host import HostHoldError, _blob_sha, evaluate_host

MAIN = "a" * 40
CANDIDATE = "b" * 40
MERGE = "c" * 40
TOKEN = "x" * 48
NOW = 1000.0
PREFIX = "repos/o/r"
RUN_ID = 12345
PR_NUMBER = 42
APP_ID = 15368
GATE_PATHS = (
    "scripts/premerge_gate.py",
    "scripts/ci_gate.sh",
    ".github/workflows/ci.yml",
)
POLICY = "docs/governance/required-ci-checks.json"


def sign(payload: dict) -> dict:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False).encode()
    return {
        "payload": payload,
        "hmac_sha256": hmac.new(TOKEN.encode(), canonical, hashlib.sha256).hexdigest(),
    }


def snapshot() -> dict:
    return sign({
        "checked_at": NOW - 2, "main_sha": MAIN, "candidate_sha": CANDIDATE,
        "lane": {"lane_id": "lane-1", "version": 4, "head_sha": CANDIDATE,
                 "base_main_sha": MAIN, "verify_ref": "verify-1"},
        "queue": {"queue_id": "queue-1", "version": 2, "lane_id": "lane-1",
                  "status": "ready_for_confirm",
                  "last_preflight_main_sha": MAIN, "slot_held": True},
        "review": {"terminal": True, "verdict": "PASS", "p0": 0, "p1": 0,
                   "candidate_sha": CANDIDATE, "reviewer_model": "independent-reviewer"},
        "r9": {"full": True, "exit_code": 0, "candidate_sha": CANDIDATE,
               "receipt": "r9-sha"},
        "integration": {"clean": True, "contracts_verified": True,
                        "merge_tree_clean": True},
    })


def runcheck(name: str, sha: str, *, result: str = "success",
             run_id: int = RUN_ID) -> dict:
    return {"name": name, "app": {"id": APP_ID}, "head_sha": sha,
            "status": "completed", "conclusion": result,
            "details_url": f"https://github.com/o/r/actions/runs/{run_id}/job/77"}


class FakeGitHub:
    def __init__(self):
        self.data: dict[str, object] = {}
        self.blobs: dict[tuple[str, str], bytes] = {}
        self.artifact_value = {
            "mode": "ci", "verdict": "pass", "event": "pull_request",
            "run_id": RUN_ID, "same_run": True, "all_success": True,
            "identity": {"pr_head_sha": CANDIDATE, "pr_base_sha": MAIN,
                         "pr_merge_sha": MERGE},
        }
        workflows = {
            ".github/workflows/ci.yml": b"name: CI\non: [push, pull_request]\n",
            ".github/workflows/architecture-review.yml":
                b"name: Architecture\non: [pull_request]\n",
        }
        names = [
            ("CI / test", "test", ".github/workflows/ci.yml", "push_and_pr"),
            ("CI / security", "security_scan", ".github/workflows/ci.yml", "push_and_pr"),
            ("managed-premerge-evidence", "managed_evidence",
             ".github/workflows/ci.yml", "push_and_pr"),
            ("A.5 architecture", "architecture", ".github/workflows/architecture-review.yml",
             "pr_only"),
        ]
        checks = [
            {"context": context, "app_id": APP_ID, "purpose": purpose,
             "event_scope": scope, "workflow_path": path,
             "workflow_blob_sha": _blob_sha(workflows[path])}
            for context, purpose, path, scope in names
        ]
        policy = json.dumps({"schema": "lfl.required_checks.v1", "checks": checks}).encode()
        for path, data in {
            "scripts/premerge_gate.py": b"gate-code\n",
            "scripts/ci_gate.sh": b"gate-shell\n",
            **workflows,
            POLICY: policy,
        }.items():
            self.blobs[path, MAIN] = data
            self.blobs[path, CANDIDATE] = data
        self.artifact_value["gate_blobs"] = {
            path: _blob_sha(self.blobs[path, MAIN]) for path in GATE_PATHS
        }
        self.data = {
            f"{PREFIX}/branches/main": {"commit": {"sha": MAIN}},
            f"{PREFIX}/pulls/{PR_NUMBER}": {
                "state": "open", "base": {"ref": "main", "sha": MAIN},
                "head": {"sha": CANDIDATE}, "merge_commit_sha": MERGE,
            },
            f"{PREFIX}/branches/main/protection/required_status_checks": {
                "strict": True, "checks": [
                    {"context": c["context"], "app_id": c["app_id"]} for c in checks
                ],
            },
            f"{PREFIX}/rulesets?includes_parents=true": [],
            f"{PREFIX}/commits/{MAIN}/check-runs?per_page=100": {
                "total_count": 3, "check_runs": [
                    runcheck(c["context"], MAIN, run_id=2000) for c in checks
                    if c["event_scope"] == "push_and_pr"
                ],
            },
            f"{PREFIX}/commits/{MERGE}/check-runs?per_page=100": {
                "total_count": 4, "check_runs": [
                    runcheck(c["context"], MERGE,
                             run_id=33333 if c["event_scope"] == "pr_only" else RUN_ID)
                    for c in checks
                ],
            },
            f"{PREFIX}/commits/{CANDIDATE}/check-runs?per_page=100": {
                "total_count": 0, "check_runs": [],
            },
            f"{PREFIX}/actions/runs/2000": {
                "id": 2000, "event": "push", "status": "completed",
                "conclusion": "success", "head_sha": MAIN,
                "pull_requests": [],
            },
            f"{PREFIX}/actions/runs/33333": {
                "id": 33333, "event": "pull_request", "status": "completed",
                "conclusion": "success", "head_sha": CANDIDATE,
                "pull_requests": [{"number": PR_NUMBER, "head": {"sha": CANDIDATE},
                                   "base": {"sha": MAIN}}],
            },
            f"{PREFIX}/actions/runs/{RUN_ID}": {
                "id": RUN_ID, "event": "pull_request", "status": "completed",
                "conclusion": "success", "head_sha": CANDIDATE,
                "pull_requests": [{"number": PR_NUMBER, "head": {"sha": CANDIDATE},
                                   "base": {"sha": MAIN}}],
            },
            f"{PREFIX}/actions/runs/{RUN_ID}/artifacts?per_page=100": {
                "total_count": 1, "artifacts": [
                    {"name": "premerge-gate-receipt", "id": 987, "expired": False}
                ],
            },
        }

    def get(self, path: str):
        if path not in self.data:
            raise HostHoldError("github_api_unavailable")
        return copy.deepcopy(self.data[path])

    def blob(self, path: str, ref: str) -> tuple[str, bytes]:
        if (path, ref) not in self.blobs:
            raise HostHoldError("github_blob_unavailable")
        data = self.blobs[path, ref]
        return _blob_sha(data), data

    def artifact(self, artifact_id: int) -> dict:
        if artifact_id != 987:
            raise HostHoldError("artifact_unavailable")
        return copy.deepcopy(self.artifact_value)


@pytest.fixture
def fixture() -> tuple[FakeGitHub, dict]:
    return FakeGitHub(), snapshot()


def evaluate(fixture: tuple[FakeGitHub, dict]) -> dict:
    client, envelope = fixture
    return evaluate_host(
        client, repo="o/r", pr_number=PR_NUMBER, main=MAIN,
        candidate=CANDIDATE, run_id=RUN_ID, envelope=envelope,
        snapshot_key=TOKEN, now=NOW,
    )


def holds(fixture: tuple[FakeGitHub, dict], reason: str) -> None:
    with pytest.raises(HostHoldError) as error:
        evaluate(fixture)
    assert error.value.reason == reason


def test_host_full_authoritative_success(fixture):
    result = evaluate(fixture)
    assert result["decision"] == "ELIGIBLE_FOR_MANAGED_MERGE"
    assert result["read_only"] is True
    assert result["remote_main_cas"] is False
    assert result["required_checked"] == 4
    assert result["trusted_gate_blobs"]["scripts/ci_gate.sh"]


def test_t25_candidate_gate_self_upgrade_cannot_self_approve(fixture):
    fixture[0].blobs["scripts/ci_gate.sh", CANDIDATE] = b"exit 0\n"
    holds(fixture, "gate_version_untrusted")


def test_t25_candidate_workflow_self_upgrade_cannot_self_approve(fixture):
    fixture[0].blobs[".github/workflows/ci.yml", CANDIDATE] = b"on: [push]\n"
    holds(fixture, "gate_version_untrusted")


def test_t25_candidate_policy_cannot_self_approve(fixture):
    fixture[0].blobs[POLICY, CANDIDATE] = b'{"schema":"lfl.required_checks.v1"}'
    holds(fixture, "gate_version_untrusted")


def test_t21_main_test_red_even_if_security_green(fixture):
    fixture[0].data[f"{PREFIX}/commits/{MAIN}/check-runs?per_page=100"]["check_runs"][0]["conclusion"] = "failure"
    holds(fixture, "main_ci_red")


def test_t22_pr_only_required_absent_on_main_is_not_main_red(fixture):
    assert evaluate(fixture)["decision"] == "ELIGIBLE_FOR_MANAGED_MERGE"
    fixture[0].blobs[".github/workflows/architecture-review.yml", MAIN] = (
        b"on: [push, pull_request]\n"
    )
    holds(fixture, "policy_workflow_untrusted")


def test_t23_required_app_id_mismatch_holds(fixture):
    fixture[0].data[f"{PREFIX}/branches/main/protection/required_status_checks"]["checks"][0]["app_id"] = 999
    holds(fixture, "required_checks_source_inadequate")


def test_t23_legacy_required_context_without_app_id_holds(fixture):
    del fixture[0].data[f"{PREFIX}/branches/main/protection/required_status_checks"]["checks"][0]["app_id"]
    holds(fixture, "required_checks_unavailable")


def test_t21_missing_managed_required_pin_holds(fixture):
    fixture[0].data[f"{PREFIX}/branches/main/protection/required_status_checks"]["checks"].pop(2)
    holds(fixture, "required_checks_source_inadequate")


def test_t25_pr_only_architecture_pending_holds(fixture):
    fixture[0].data[f"{PREFIX}/commits/{MERGE}/check-runs?per_page=100"]["check_runs"][3]["status"] = "in_progress"
    holds(fixture, "pr_required_checks_incomplete")


def test_t24_pr_run_association_wrong_head_holds(fixture):
    fixture[0].data[f"{PREFIX}/actions/runs/{RUN_ID}"]["pull_requests"][0]["head"]["sha"] = MAIN
    holds(fixture, "pr_check_run_identity_mismatch")


def test_t24_pr_run_head_sha_is_merge_ref_allowed(fixture):
    fixture[0].data[f"{PREFIX}/actions/runs/{RUN_ID}"]["head_sha"] = MERGE
    assert evaluate(fixture)["decision"] == "ELIGIBLE_FOR_MANAGED_MERGE"


def test_t21_main_check_run_is_not_push_event_holds(fixture):
    fixture[0].data[f"{PREFIX}/actions/runs/2000"]["event"] = "pull_request"
    holds(fixture, "check_run_event_mismatch")


def test_t25_pr_required_check_wrong_event_holds(fixture):
    fixture[0].data[f"{PREFIX}/actions/runs/33333"]["event"] = "push"
    holds(fixture, "check_run_event_mismatch")


def test_t23_required_check_origin_url_untrusted_holds(fixture):
    fixture[0].data[f"{PREFIX}/commits/{MAIN}/check-runs?per_page=100"]["check_runs"][0]["details_url"] = (
        "https://evil.example/actions/runs/2000"
    )
    holds(fixture, "check_run_origin_unverifiable")


def test_t24_managed_check_run_other_run_id_holds(fixture):
    fixture[0].data[f"{PREFIX}/commits/{MERGE}/check-runs?per_page=100"]["check_runs"][2]["details_url"] = (
        "https://github.com/o/r/actions/runs/33333/job/77"
    )
    holds(fixture, "managed_run_identity_mismatch")


def test_t25_artifact_gate_blob_tampering_holds(fixture):
    fixture[0].artifact_value["gate_blobs"]["scripts/ci_gate.sh"] = "0" * 40
    holds(fixture, "artifact_gate_blob_mismatch")


def test_t25_artifact_run_id_mismatch_holds(fixture):
    fixture[0].artifact_value["run_id"] = RUN_ID + 1
    holds(fixture, "artifact_identity_mismatch")


def test_t25_artifact_missing_holds(fixture):
    fixture[0].data[f"{PREFIX}/actions/runs/{RUN_ID}/artifacts?per_page=100"] = {
        "total_count": 0, "artifacts": [],
    }
    holds(fixture, "artifact_unavailable")


def test_t25_artifact_wrong_tested_merge_holds(fixture):
    fixture[0].artifact_value["identity"]["pr_merge_sha"] = CANDIDATE
    holds(fixture, "artifact_identity_mismatch")


def test_t24_merge_queue_ruleset_holds(fixture):
    fixture[0].data[f"{PREFIX}/rulesets?includes_parents=true"] = [
        {"name": "queue", "enforcement": "active"}
    ]
    holds(fixture, "rulesets_unverified")


def test_t07_branch_protection_not_strict_holds(fixture):
    fixture[0].data[f"{PREFIX}/branches/main/protection/required_status_checks"]["strict"] = False
    holds(fixture, "base_guard_unavailable")


def test_t07_main_advances_during_host_check_holds(fixture):
    client = fixture[0]
    original_get = client.get
    count = 0

    def advance_on_second_read(path: str):
        nonlocal count
        value = original_get(path)
        if path == f"{PREFIX}/branches/main":
            count += 1
            if count >= 2:
                value["commit"]["sha"] = "d" * 40
        return value

    client.get = advance_on_second_read
    holds(fixture, "premerge_race_detected")


def test_t07_main_advances_holds(fixture):
    fixture[0].data[f"{PREFIX}/branches/main"]["commit"]["sha"] = "d" * 40
    holds(fixture, "main_advanced")


def test_t07_queue_cas_drift_holds(fixture):
    fixture[1]["payload"]["queue"]["version"] = 3
    holds(fixture, "host_snapshot_signature_invalid")


def test_t07_host_snapshot_stale_holds(fixture):
    fixture[1].update(sign({**fixture[1]["payload"], "checked_at": NOW - 100}))
    holds(fixture, "host_snapshot_stale")


def test_t25_main_check_run_pagination_holds(fixture):
    fixture[0].data[f"{PREFIX}/commits/{MAIN}/check-runs?per_page=100"]["total_count"] = 120
    holds(fixture, "check_runs_incomplete")


def test_t25_host_api_403_holds(fixture):
    del fixture[0].data[f"{PREFIX}/branches/main/protection/required_status_checks"]
    holds(fixture, "github_api_unavailable")


def test_t25_no_snapshot_secret_holds(fixture):
    with pytest.raises(HostHoldError, match="host_snapshot_key_unavailable"):
        evaluate_host(fixture[0], repo="o/r", pr_number=PR_NUMBER, main=MAIN,
                      candidate=CANDIDATE, run_id=RUN_ID, envelope=fixture[1],
                      snapshot_key="", now=NOW)


def test_cli_host_missing_credentials_returns_hold_without_git_writes(tmp_path: Path):
    script = Path(__file__).resolve().parents[2] / "scripts" / "premerge_gate.py"
    snap = tmp_path / "host.json"
    snap.write_text(json.dumps(snapshot()))
    proc = subprocess.run(
        [sys.executable, str(script), "--mode", "host", "--repo", "o/r",
         "--pr", str(PR_NUMBER), "--run-id", str(RUN_ID),
         "--expected-main-sha", MAIN, "--expected-candidate-sha", CANDIDATE,
         "--host-snapshot", str(snap)],
        capture_output=True, text=True, timeout=15, env={},
    )
    assert proc.returncode == 3
    assert json.loads(proc.stdout)["decision"] == "HOLD"
    assert json.loads(proc.stdout)["reason"] == "host_credential_unavailable"
