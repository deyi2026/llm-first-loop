"""Issue #73: a green CI run cannot mint the independent Host required check."""
from __future__ import annotations

import copy

# Reuse the full authoritative fake-GitHub fixture without creating a
# second, potentially divergent model of GitHub branch protection.
import importlib.util
from pathlib import Path

import pytest
from host_premerge_check_publisher import publish_verified
from premerge_host import HostHoldError, evaluate_host

_spec = importlib.util.spec_from_file_location(
    "issue73_existing_host_fixtures",
    Path(__file__).with_name("test_premerge_gate_host.py"),
)
assert _spec and _spec.loader
_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixtures)
FakeGitHub, snapshot, sign = (
    _fixtures.FakeGitHub, _fixtures.snapshot, _fixtures.sign,
)
NOW, MAIN, CANDIDATE, MERGE = (
    _fixtures.NOW, _fixtures.MAIN, _fixtures.CANDIDATE, _fixtures.MERGE,
)
PREFIX, PR_NUMBER, RUN_ID, HOST_APP_ID, APP_ID, TEST_PUBLIC = (
    _fixtures.PREFIX, _fixtures.PR_NUMBER, _fixtures.RUN_ID,
    _fixtures.HOST_APP_ID, _fixtures.APP_ID, _fixtures.TEST_PUBLIC,
)


@pytest.fixture
def facts(monkeypatch):
    # The signed test snapshot uses a deterministic timestamp.
    import premerge_host
    monkeypatch.setattr(premerge_host.time, "time", lambda: NOW)
    return [FakeGitHub(), snapshot()]


def publish(facts, *, apply=False, token="", post=None):
    client, envelope = facts
    kwargs = dict(
        repo="o/r", pr_number=PR_NUMBER, main=MAIN, candidate=CANDIDATE,
        run_id=RUN_ID, envelope=envelope, public_key=TEST_PUBLIC,
        app_id=HOST_APP_ID, now=NOW, apply=apply, check_token=token,
        live_state=lambda payload: None,
    )
    if post is not None:
        kwargs["post"] = post
    return publish_verified(client, **kwargs)


def test_green_ci_and_signed_host_pass_is_readonly_without_apply(facts):
    result = publish(facts)
    assert result["decision"] == "ELIGIBLE_TO_PUBLISH"
    assert result["head_sha"] == MERGE
    assert result["app_id"] == HOST_APP_ID
    assert result["read_only"] is True


def test_real_host_app_publishes_only_tested_merge_sha(facts):
    observed = []
    def post(repo, token, body):
        observed.append((repo, token, body))
        return {**body, "id": 37, "app": {"id": HOST_APP_ID}}
    result = publish(facts, apply=True, token="host-app-token" * 3, post=post)
    assert result["decision"] == "PUBLISHED"
    assert result["head_sha"] == MERGE
    assert len(observed) == 1
    repo, token, body = observed[0]
    assert repo == "o/r" and token.startswith("host-app-token")
    assert body["name"] == "lfl-host-premerge"
    assert body["head_sha"] == MERGE != CANDIDATE
    assert body["external_id"].startswith(f"lfl-host:{PR_NUMBER}:{MAIN}:{CANDIDATE}:{MERGE}:")
    assert "signed Host snapshot SHA-256" in body["output"]["summary"]


def test_missing_separate_host_token_cannot_publish(facts):
    called = []
    with pytest.raises(HostHoldError, match="host_check_token_unavailable"):
        publish(facts, apply=True, post=lambda *a: called.append(a))
    assert not called


def test_green_ci_without_required_host_check_cannot_publish(facts):
    checks = facts[0].data[f"{PREFIX}/branches/main/protection/required_status_checks"]["checks"]
    checks.pop()
    with pytest.raises(HostHoldError, match="host_check_not_required"):
        publish(facts)


def test_host_required_wrong_app_id_rejected(facts):
    checks = facts[0].data[f"{PREFIX}/branches/main/protection/required_status_checks"]["checks"]
    checks[-1]["app_id"] = 99999
    with pytest.raises(HostHoldError, match="host_check_not_required"):
        publish(facts)


def test_actions_app_cannot_masquerade_as_independent_host(facts):
    client, envelope = facts
    with pytest.raises(HostHoldError, match="host_check_app_not_independent"):
        evaluate_host(
            client, repo="o/r", pr_number=PR_NUMBER, main=MAIN,
            candidate=CANDIDATE, run_id=RUN_ID, envelope=envelope,
            snapshot_public_key=TEST_PUBLIC, now=NOW, host_app_id=APP_ID,
        )


@pytest.mark.parametrize("mutation,reason", [
    (lambda p: p["review"].update(terminal=False, verdict="pending"), "review_missing_or_stale"),
    (lambda p: p["review"].update(terminal=True, verdict="REVISE"), "review_missing_or_stale"),
    (lambda p: p["queue"].update(slot_held=False), "queue_snapshot_incomplete"),
    (lambda p: p["lane"].update(verify_ref=""), "lane_snapshot_incomplete"),
    (lambda p: p["r9"].update(exit_code=1), "r9_missing_or_stale"),
])
def test_no_host_check_for_cancelled_review_missing_slot_or_failed_r9(facts, mutation, reason):
    payload = copy.deepcopy(facts[1]["payload"])
    mutation(payload)
    facts[1] = sign(payload)
    with pytest.raises(HostHoldError, match=reason):
        publish(facts)


def test_stale_base_or_head_cannot_publish(facts):
    facts[0].data[f"{PREFIX}/pulls/{PR_NUMBER}"]["base"]["sha"] = "d" * 40
    with pytest.raises(HostHoldError, match="pr_identity_changed"):
        publish(facts)


def test_race_after_verified_host_preflight_holds(facts):
    client = facts[0]
    original_get = client.get
    calls = 0
    def drift_on_third_read(path):
        nonlocal calls
        value = original_get(path)
        if path == f"{PREFIX}/branches/main":
            calls += 1
            if calls >= 3:
                value["commit"]["sha"] = "d" * 40
        return value
    client.get = drift_on_third_read
    with pytest.raises(HostHoldError, match="prepublish_identity_changed"):
        publish(facts, apply=True, token="host-app-token" * 3)


def test_existing_conflicting_host_check_must_not_be_replaced(facts):
    key = f"{PREFIX}/commits/{MERGE}/check-runs?per_page=100&filter=all"
    facts[0].data[key]["check_runs"].append({
        "id": 99, "name": "lfl-host-premerge",
        "app": {"id": HOST_APP_ID}, "head_sha": MERGE,
        "status": "completed", "conclusion": "success",
        "external_id": "stale-base-or-forged-snapshot",
    })
    facts[0].data[key]["total_count"] += 1
    with pytest.raises(HostHoldError, match="host_check_existing_conflict"):
        publish(facts, apply=True, token="host-app-token" * 3)


def test_wrong_app_identity_in_write_response_cannot_be_claimed_success(facts):
    def post(_repo, _token, body):
        return {**body, "id": 37, "app": {"id": APP_ID}}
    with pytest.raises(HostHoldError, match="host_check_publish_identity_mismatch"):
        publish(facts, apply=True, token="host-app-token" * 3, post=post)


def test_live_lane_queue_probe_unavailable_blocks_even_with_green_ci(facts):
    client, envelope = facts
    with pytest.raises(HostHoldError, match="host_live_state_unavailable"):
        publish_verified(
            client, repo="o/r", pr_number=PR_NUMBER, main=MAIN,
            candidate=CANDIDATE, run_id=RUN_ID, envelope=envelope,
            public_key=TEST_PUBLIC, app_id=HOST_APP_ID, now=NOW,
            apply=True, check_token="host-app-token" * 3,
            live_state=None,
        )


def test_live_queue_cas_drift_blocks_before_check_write(facts):
    def changed(_payload):
        raise HostHoldError("host_live_state_changed", unavailable=False)
    called = []
    with pytest.raises(HostHoldError, match="host_live_state_changed"):
        publish_verified(
            facts[0], repo="o/r", pr_number=PR_NUMBER,
            main=MAIN, candidate=CANDIDATE, run_id=RUN_ID,
            envelope=facts[1], public_key=TEST_PUBLIC,
            app_id=HOST_APP_ID, now=NOW, apply=True,
            check_token="host-app-token" * 3,
            live_state=changed,
            post=lambda *args: called.append(args),
        )
    assert not called


def test_protection_disabled_after_host_verification_blocks_publication(facts):
    client = facts[0]
    original_get = client.get
    count = 0

    def remove_required_host_check_on_third_read(path):
        nonlocal count
        value = original_get(path)
        if path == f"{PREFIX}/branches/main/protection/required_status_checks":
            count += 1
            if count >= 3:
                value["checks"] = [
                    x for x in value["checks"]
                    if x["context"] != "lfl-host-premerge"
                ]
        return value

    client.get = remove_required_host_check_on_third_read
    called = []
    with pytest.raises(HostHoldError, match="prepublish_protection_changed"):
        publish(
            facts, apply=True, token="host-app-token" * 3,
            post=lambda *args: called.append(args),
        )
    assert not called


def test_web_uid_cannot_run_host_publisher_even_with_apply(tmp_path):
    import subprocess
    import sys

    script = Path(__file__).resolve().parents[2] / "scripts" / "host_premerge_check_publisher.py"
    envelope = tmp_path / "signed.json"
    envelope.write_text("{}", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(script), "--repo", "o/r",
         "--pr", str(PR_NUMBER), "--run-id", str(RUN_ID),
         "--expected-main-sha", MAIN, "--expected-candidate-sha", CANDIDATE,
         "--host-snapshot", str(envelope), "--execution-root", str(tmp_path),
         "--apply"],
        capture_output=True, text=True, timeout=10, env={},
    )
    assert proc.returncode == 3
    assert "host_check_issuer_isolation_required" in proc.stdout
    assert "PUBLISHED" not in proc.stdout
