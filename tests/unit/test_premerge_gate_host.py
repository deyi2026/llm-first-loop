"""Host gate T07/T21-T25: authoritative sources, identity, and trust failures."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from premerge_host import _GATE_PATHS, HostHoldError, _blob_sha, _trusted_policy, evaluate_host

MAIN = "a" * 40
CANDIDATE = "b" * 40
MERGE = "c" * 40
TEST_PRIVATE = ECC.generate(curve="Ed25519")
TEST_PUBLIC = TEST_PRIVATE.public_key().export_key(format="PEM")
NOW = 1000.0
PREFIX = "repos/o/r"
RUN_ID = 12345
PR_NUMBER = 42
APP_ID = 15368
GATE_PATHS = _GATE_PATHS
POLICY = "docs/governance/required-ci-checks.json"


def sign(payload: dict) -> dict:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    signature = eddsa.new(TEST_PRIVATE, "rfc8032").sign(canonical)
    return {
        "payload": payload,
        "key_id": hashlib.sha256(TEST_PUBLIC.encode()).hexdigest()[:16],
        "signature_ed25519": base64.b64encode(signature).decode(),
    }

def snapshot() -> dict:
    return sign({
        "checked_at": NOW - 2, "main_sha": MAIN, "candidate_sha": CANDIDATE,
        "repo": "o/r", "pr_number": PR_NUMBER, "run_id": RUN_ID,
        "lane": {"lane_id": "lane-1", "version": 4, "head_sha": CANDIDATE,
                 "base_main_sha": MAIN, "verify_ref": "verify-1", "status": "merging"},
        "queue": {"queue_id": "queue-1", "version": 2, "lane_id": "lane-1",
                  "status": "merging",
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
             "workflow_blob_sha": _blob_sha(workflows[path]),
             "workflow_id": 1002 if scope == "pr_only" else 1001}
            for context, purpose, path, scope in names
        ]
        policy = json.dumps({"schema": "lfl.required_checks.v1", "checks": checks}).encode()
        for path, data in {
            "scripts/premerge_gate.py": b"gate-code\n",
            "scripts/premerge_host.py": b"host-verifier\n",
            "scripts/integration_writer_lock.py": b"integration-lock\n",
            "scripts/ci_gate.sh": b"gate-shell\n",
            "scripts/git_security_scan.sh": b"scan-shell\n",
            "scripts/verify_linux_installer.py": b"installer-py\n",
            "pyproject.toml": b"project-toml\n",
            "scripts/check_static_diagnostics.py": b"static-py\n",
            "scripts/check_test_env_pins.py": b"env-pin-py\n",
            "scripts/check_architecture_submission.py": b"a5-py\n",
            **workflows,
            POLICY: policy,
        }.items():
            self.blobs[path, MAIN] = data
            self.blobs[path, CANDIDATE] = data
        # Test fixture includes every trust-closure path; individual negative
        # tests mutate only one candidate blob to verify fail-closed behavior.
        for path in GATE_PATHS:
            if (path, MAIN) not in self.blobs:
                self.blobs[path, MAIN] = path.encode() + b"\n"
                self.blobs[path, CANDIDATE] = path.encode() + b"\n"
        self.artifact_value["gate_blobs"] = {
            path: _blob_sha(self.blobs[path, MAIN]) for path in GATE_PATHS
        }
        self.data = {
            f"{PREFIX}/branches/main": {"commit": {"sha": MAIN}},
            f"{PREFIX}/pulls/{PR_NUMBER}": {
                "state": "open", "base": {"ref": "main", "sha": MAIN},
                "head": {"sha": CANDIDATE}, "merge_commit_sha": MERGE,
            },
            f"{PREFIX}/commits/{MERGE}": {
                "sha": MERGE, "parents": [{"sha": MAIN}, {"sha": CANDIDATE}],
            },
            f"{PREFIX}/branches/main/protection/required_status_checks": {
                "strict": True, "checks": [
                    {"context": c["context"], "app_id": c["app_id"]} for c in checks
                ],
            },
            f"{PREFIX}/rulesets?includes_parents=true": [],
            f"{PREFIX}/commits/{MAIN}/check-runs?per_page=100&filter=all": {
                "total_count": 3, "check_runs": [
                    runcheck(c["context"], MAIN, run_id=2000) for c in checks
                    if c["event_scope"] == "push_and_pr"
                ],
            },
            f"{PREFIX}/commits/{MERGE}/check-runs?per_page=100&filter=all": {
                "total_count": 4, "check_runs": [
                    runcheck(c["context"], MERGE,
                             run_id=33333 if c["event_scope"] == "pr_only" else RUN_ID)
                    for c in checks
                ],
            },
            f"{PREFIX}/commits/{CANDIDATE}/check-runs?per_page=100&filter=all": {
                "total_count": 0, "check_runs": [],
            },
            f"{PREFIX}/actions/runs/2000": {
                "id": 2000, "event": "push", "status": "completed",
                "conclusion": "success", "head_sha": MAIN,
                "workflow_id": 1001, "path": ".github/workflows/ci.yml@main",
                "pull_requests": [],
            },
            f"{PREFIX}/actions/runs/33333": {
                "id": 33333, "event": "pull_request", "status": "completed",
                "conclusion": "success", "head_sha": CANDIDATE,
                "workflow_id": 1002, "path": ".github/workflows/architecture-review.yml@refs/pull/42/merge",
                "pull_requests": [{"number": PR_NUMBER, "head": {"sha": CANDIDATE},
                                   "base": {"sha": MAIN}}],
            },
            f"{PREFIX}/actions/runs/{RUN_ID}": {
                "id": RUN_ID, "event": "pull_request", "status": "completed",
                "conclusion": "success", "head_sha": CANDIDATE,
                "workflow_id": 1001, "path": ".github/workflows/ci.yml@refs/pull/42/merge",
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


def evaluate(fixture: tuple[FakeGitHub, dict], *, final_now: float = NOW) -> dict:
    client, envelope = fixture
    return evaluate_host(
        client, repo="o/r", pr_number=PR_NUMBER, main=MAIN,
        candidate=CANDIDATE, run_id=RUN_ID, envelope=envelope,
        snapshot_public_key=TEST_PUBLIC, now=NOW, final_now=final_now,
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


def test_ready_for_confirm_cannot_claim_exclusive_merge_slot(fixture):
    """The queue releases its slot at ready_for_confirm, before request_merge."""
    from llm_loop.introspection.merge_queue import SLOT_STATUSES

    assert "ready_for_confirm" not in SLOT_STATUSES
    assert "merging" in SLOT_STATUSES
    payload = fixture[1]["payload"]
    payload["queue"]["status"] = "ready_for_confirm"
    payload["queue"]["slot_held"] = True  # forged impossible combination
    fixture[1].update(sign(payload))
    holds(fixture, "queue_snapshot_incomplete")


def test_merging_without_slot_is_not_merge_eligible(fixture):
    payload = fixture[1]["payload"]
    payload["queue"]["status"] = "merging"
    payload["queue"]["slot_held"] = False
    fixture[1].update(sign(payload))
    holds(fixture, "queue_snapshot_incomplete")


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
    fixture[0].data[f"{PREFIX}/commits/{MAIN}/check-runs?per_page=100&filter=all"]["check_runs"][0]["conclusion"] = "failure"
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
    fixture[0].data[f"{PREFIX}/commits/{MERGE}/check-runs?per_page=100&filter=all"]["check_runs"][3]["status"] = "in_progress"
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
    fixture[0].data[f"{PREFIX}/commits/{MAIN}/check-runs?per_page=100&filter=all"]["check_runs"][0]["details_url"] = (
        "https://evil.example/actions/runs/2000"
    )
    holds(fixture, "check_run_origin_unverifiable")


def test_t24_managed_check_run_other_run_id_holds(fixture):
    fixture[0].data[f"{PREFIX}/commits/{MERGE}/check-runs?per_page=100&filter=all"]["check_runs"][2]["details_url"] = (
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
    fixture[0].data[f"{PREFIX}/commits/{MAIN}/check-runs?per_page=100&filter=all"]["total_count"] = 120
    holds(fixture, "check_runs_incomplete")


def test_t25_host_api_403_holds(fixture):
    del fixture[0].data[f"{PREFIX}/branches/main/protection/required_status_checks"]
    holds(fixture, "github_api_unavailable")


def test_t25_no_snapshot_secret_holds(fixture):
    with pytest.raises(HostHoldError, match="host_snapshot_public_key_unavailable"):
        evaluate_host(fixture[0], repo="o/r", pr_number=PR_NUMBER, main=MAIN,
                      candidate=CANDIDATE, run_id=RUN_ID, envelope=fixture[1],
                      snapshot_public_key="", now=NOW)


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


def test_p0_same_context_fake_workflow_cannot_override_red_check(fixture):
    client = fixture[0]
    key = f"{PREFIX}/commits/{MERGE}/check-runs?per_page=100&filter=all"
    client.data[key]["check_runs"][0]["conclusion"] = "failure"
    client.data[key]["check_runs"].append(
        runcheck("CI / test", MERGE, run_id=44444)
    )
    client.data[key]["total_count"] = 5
    holds(fixture, "check_context_ambiguous")


def test_p0_single_fake_workflow_same_context_rejected_by_run_path(fixture):
    client = fixture[0]
    client.data[f"{PREFIX}/actions/runs/{RUN_ID}"]["path"] = (
        ".github/workflows/zz.yml@refs/pull/42/merge"
    )
    holds(fixture, "check_run_workflow_mismatch")


def test_p0_same_context_wrong_workflow_id_rejected(fixture):
    client = fixture[0]
    client.data[f"{PREFIX}/actions/runs/33333"]["workflow_id"] = 9999
    holds(fixture, "check_run_workflow_mismatch")


@pytest.mark.parametrize(
    "path",
    ["scripts/premerge_host.py", "scripts/integration_writer_lock.py",
     "scripts/git_security_scan.sh", "scripts/verify_linux_installer.py",
     "pyproject.toml", "scripts/check_architecture_submission.py",
     "scripts/check_static_diagnostics.py", "scripts/check_test_env_pins.py"],
)
def test_p1_candidate_gate_dependency_self_upgrade_rejected(fixture, path):
    fixture[0].blobs[path, CANDIDATE] = b"exit 0\n"
    holds(fixture, "gate_version_untrusted")


def test_p2_head_only_green_does_not_override_tested_merge_red(fixture):
    client = fixture[0]
    key = f"{PREFIX}/commits/{MERGE}/check-runs?per_page=100&filter=all"
    client.data[key]["check_runs"][0]["conclusion"] = "failure"
    client.data[f"{PREFIX}/commits/{CANDIDATE}/check-runs?per_page=100&filter=all"] = {
        "total_count": 1,
        "check_runs": [runcheck("CI / test", CANDIDATE)],
    }
    holds(fixture, "pr_required_checks_incomplete")


def test_p2_tested_merge_wrong_parents_holds(fixture):
    fixture[0].data[f"{PREFIX}/commits/{MERGE}"]["parents"][0]["sha"] = "d" * 40
    holds(fixture, "tested_merge_parents_mismatch")


def test_p1_snapshot_signed_by_other_private_key_rejected(fixture):
    other = ECC.generate(curve="Ed25519")
    canonical = json.dumps(
        fixture[1]["payload"], sort_keys=True, separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    fixture[1]["signature_ed25519"] = base64.b64encode(
        eddsa.new(other, "rfc8032").sign(canonical)
    ).decode()
    holds(fixture, "host_snapshot_signature_invalid")


def test_p1_verifier_rejects_private_key_instead_of_public(fixture):
    private_pem = TEST_PRIVATE.export_key(format="PEM")
    fixture[1]["key_id"] = hashlib.sha256(private_pem.encode()).hexdigest()[:16]
    with pytest.raises(HostHoldError, match="host_snapshot_public_key_invalid"):
        evaluate_host(
            fixture[0], repo="o/r", pr_number=PR_NUMBER, main=MAIN,
            candidate=CANDIDATE, run_id=RUN_ID, envelope=fixture[1],
            snapshot_public_key=private_pem, now=NOW,
        )


@pytest.mark.parametrize(
    ("path", "code", "reason"),
    [
        ("branches/main/protection/required_status_checks", 404, "protection_not_installed"),
        (f"{PREFIX}/branches/main/protection/required_status_checks", 404,
         "protection_not_installed"),
        ("contents/docs/governance/required-ci-checks.json?ref=" + MAIN, 404, "policy_missing"),
        ("branches/main/protection/required_status_checks", 403, "host_credential_scope_missing"),
    ],
)
def test_p2_http_error_classification(monkeypatch, path, code, reason):
    import urllib.error
    import urllib.request

    from premerge_host import GitHubReadOnly

    class DenyOpener:
        def open(self, request, timeout):
            raise urllib.error.HTTPError(request.full_url, code, "denied", {}, None)

    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: DenyOpener())
    client = GitHubReadOnly("o/r", "x" * 30)
    with pytest.raises(HostHoldError, match=reason):
        client.get(path)


def test_api_redirect_cannot_forward_host_authorization():
    import urllib.request

    from premerge_host import _NoRedirect

    request = urllib.request.Request(
        "https://api.github.com/repos/o/r/branches/main",
        headers={"Authorization": "Bearer test-secret"},
    )
    assert _NoRedirect().redirect_request(
        request, None, 302, "redirect", {"Location": "https://evil.invalid/"},
        "https://evil.invalid/",
    ) is None


def test_p2_check_run_turns_red_during_final_recheck_holds(fixture):
    client = fixture[0]
    original_get = client.get
    calls = 0
    target = f"{PREFIX}/commits/{MERGE}/check-runs?per_page=100&filter=all"

    def flip_after_first_read(path: str):
        nonlocal calls
        value = original_get(path)
        if path == target:
            calls += 1
            if calls == 2:
                value["check_runs"][0]["conclusion"] = "failure"
        return value

    client.get = flip_after_first_read
    holds(fixture, "premerge_race_detected")


def test_candidate_cannot_modify_additional_policy_workflow(fixture):
    """Policy-controlled workflows must be pinned even outside _GATE_PATHS."""
    client = fixture[0]
    extra = ".github/workflows/privacy-scan.yml"
    trusted = b"on: [push, pull_request]\n"
    client.blobs[extra, MAIN] = trusted
    client.blobs[extra, CANDIDATE] = b"on: [pull_request]\n"
    policy = json.loads(client.blobs[POLICY, MAIN])
    policy["checks"].append({
        "context": "privacy-gate", "app_id": APP_ID, "purpose": "privacy",
        "event_scope": "push_and_pr", "workflow_path": extra,
        "workflow_blob_sha": _blob_sha(trusted), "workflow_id": 999,
    })
    raw = json.dumps(policy).encode()
    client.blobs[POLICY, MAIN] = raw
    client.blobs[POLICY, CANDIDATE] = raw
    required = [{"context": item["context"], "app_id": item["app_id"]}
                for item in policy["checks"]]
    with pytest.raises(HostHoldError, match="gate_version_untrusted"):
        _trusted_policy(client, PREFIX, MAIN, CANDIDATE, required)


@pytest.mark.parametrize("field,value", [
    ("repo", "another/repo"), ("pr_number", PR_NUMBER + 1),
    ("run_id", RUN_ID + 1),
])
def test_signed_snapshot_must_bind_exact_request(fixture, field, value):
    payload = fixture[1]["payload"]
    payload[field] = value
    fixture[1].update(sign(payload))
    holds(fixture, "host_snapshot_identity_changed")


def test_abandoned_lane_cannot_reuse_signed_merge_snapshot(fixture):
    payload = fixture[1]["payload"]
    payload["lane"]["status"] = "abandoned"
    fixture[1].update(sign(payload))
    holds(fixture, "lane_snapshot_incomplete")


def test_draft_pr_cannot_be_eligible(fixture):
    fixture[0].data[f"{PREFIX}/pulls/{PR_NUMBER}"]["draft"] = True
    holds(fixture, "pr_identity_changed")


def test_snapshot_expires_during_host_recheck(fixture):
    with pytest.raises(HostHoldError, match="host_snapshot_stale"):
        evaluate(fixture, final_now=NOW + 91)


@pytest.mark.parametrize("path", [
    "tests/conftest.py", "uv.lock", "scripts/run_eval.py",
    "scripts/verify_serial_signal_stability.sh",
    ".github/workflows/privacy-scan.yml",
])
def test_v19_p1_candidate_auxiliary_gate_mutation_holds(fixture, path):
    """The candidate may not neuter a supporting gate script/config."""
    fixture[0].blobs[path, CANDIDATE] = b"exit 0\n"
    holds(fixture, "gate_version_untrusted")


def test_v19_p1_new_direct_ci_script_outside_closure_holds(fixture):
    from premerge_host import _verify_gate_closure

    client = fixture[0]
    client.blobs["scripts/ci_gate.sh", MAIN] = b"python scripts/hidden_skip.py\n"
    client.blobs["scripts/ci_gate.sh", CANDIDATE] = b"python scripts/hidden_skip.py\n"
    with pytest.raises(HostHoldError, match="gate_closure_incomplete"):
        _verify_gate_closure(client, MAIN)


def test_v19_p1_host_executed_root_sha_and_blob_must_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    from premerge_host import _verify_host_execution

    root = tmp_path / "clean-main"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-b", "main"], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"],
                   check=True)
    for name in ("scripts/premerge_host.py", "scripts/premerge_gate.py"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# reviewed host code\n")
    (root / "README.md").write_text("base\n")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "base"],
                   check=True, capture_output=True)
    main = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"],
                                   text=True).strip()

    class TrustedClient:
        def blob(self, name: str, _ref: str) -> tuple[str, bytes]:
            data = (root / name).read_bytes()
            return _blob_sha(data), data

    client = TrustedClient()
    with monkeypatch.context() as env:
        # Caller-controlled Git environment must never redirect Host identity.
        env.setenv("GIT_DIR", str(root / "invalid-gitdir"))
        env.setenv("GIT_WORK_TREE", str(root / "invalid-worktree"))
        env.setenv("GIT_INDEX_FILE", str(root / "invalid-index"))
        _verify_host_execution(client, main, execution_root=root)
    (root / "README.md").write_text("dirty\n")
    with pytest.raises(HostHoldError, match="gate_execution_root_untrusted"):
        _verify_host_execution(client, main, execution_root=root)
    subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "advanced"],
                   check=True, capture_output=True)
    with pytest.raises(HostHoldError, match="gate_execution_root_untrusted"):
        _verify_host_execution(client, main, execution_root=root)

    current = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"],
                                      text=True).strip()

    class WrongBlob(TrustedClient):
        def blob(self, name: str, ref: str) -> tuple[str, bytes]:
            sha, data = super().blob(name, ref)
            return "0" * 40, data

    with pytest.raises(HostHoldError, match="gate_execution_blob_untrusted"):
        _verify_host_execution(WrongBlob(), current, execution_root=root)


def test_v19_p2_dynamic_script_reference_fails_closed(fixture):
    from premerge_host import _verify_gate_closure

    client = fixture[0]
    client.blobs["scripts/ci_gate.sh", MAIN] = b'"$PY" "scripts/${TARGET}.py"\n'
    with pytest.raises(HostHoldError, match="gate_closure_incomplete"):
        _verify_gate_closure(client, MAIN)


def test_v19_p2_mixed_literal_and_dynamic_script_reference_holds(fixture):
    from premerge_host import _verify_gate_closure

    client = fixture[0]
    client.blobs["scripts/ci_gate.sh", MAIN] = (
        b'bash scripts/ci_gate.sh; "$PY" "scripts/${TARGET}.py"\n'
    )
    with pytest.raises(HostHoldError, match="gate_closure_incomplete"):
        _verify_gate_closure(client, MAIN)


def test_v19_p2_case_variant_dynamic_script_reference_holds(fixture):
    from premerge_host import _verify_gate_closure

    client = fixture[0]
    client.blobs["scripts/ci_gate.sh", MAIN] = b'"$PY" "Scripts/${TARGET}.py"\n'
    with pytest.raises(HostHoldError, match="gate_closure_incomplete"):
        _verify_gate_closure(client, MAIN)


def test_v19_p2_mixed_case_dynamic_reference_cannot_hide_after_literal(fixture):
    from premerge_host import _verify_gate_closure

    client = fixture[0]
    client.blobs["scripts/ci_gate.sh", MAIN] = (
        b'bash scripts/ci_gate.sh; "$PY" "Scripts/${TARGET}.py"\n'
    )
    with pytest.raises(HostHoldError, match="gate_closure_incomplete"):
        _verify_gate_closure(client, MAIN)
