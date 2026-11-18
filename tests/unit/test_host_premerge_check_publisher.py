"""Issue #73: a green CI run cannot mint the independent Host required check."""
from __future__ import annotations

import copy

# Reuse the full authoritative fake-GitHub fixture without creating a
# second, potentially divergent model of GitHub branch protection.
import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from datetime import UTC

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
        app_id=HOST_APP_ID, now=NOW, apply=apply,
        token_supplier=lambda: token, live_state=lambda payload: None,
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
            apply=True, token_supplier=lambda: "host-app-token" * 3,
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
            token_supplier=lambda: "host-app-token" * 3,
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


def test_ci_required_check_removed_after_host_preflight_blocks_publish(facts):
    client = facts[0]
    original_get = client.get
    calls = 0

    def remove_ci_check_on_third_read(path):
        nonlocal calls
        value = original_get(path)
        if path == f"{PREFIX}/branches/main/protection/required_status_checks":
            calls += 1
            if calls >= 3:
                value["checks"] = [
                    item for item in value["checks"]
                    if item["context"] != "CI / test"
                ]
        return value

    client.get = remove_ci_check_on_third_read
    with pytest.raises(HostHoldError, match="prepublish_protection_changed"):
        publish(facts, apply=True, token="host-app-token" * 3)


def test_ruleset_added_after_host_preflight_blocks_publish(facts):
    client = facts[0]
    original_get = client.get
    calls = 0

    def ruleset_on_third_read(path):
        nonlocal calls
        value = original_get(path)
        if path == f"{PREFIX}/rulesets?includes_parents=true":
            calls += 1
            if calls >= 3:
                value = [{"name": "bypass", "enforcement": "active"}]
        return value

    client.get = ruleset_on_third_read
    with pytest.raises(HostHoldError, match="prepublish_protection_changed"):
        publish(facts, apply=True, token="host-app-token" * 3)


def test_host_app_jwt_is_fd_bound_rs256_and_never_reads_repo_key(tmp_path, monkeypatch):
    import base64
    import json
    import os

    import host_premerge_check_publisher as publisher
    from Crypto.Hash import SHA256
    from Crypto.PublicKey import RSA
    from Crypto.Signature import pkcs1_15

    key = RSA.generate(2048)
    tmp_path.chmod(0o700)
    path = tmp_path / "github-app-5818173.pem"
    path.write_bytes(key.export_key())
    path.chmod(0o400)
    monkeypatch.setattr(publisher, "_PRIVATE_DIR", tmp_path)
    monkeypatch.setattr(publisher, "_ISSUER_UID", os.geteuid())
    jwt = publisher._app_jwt(5818173, now=1_700_000_000)
    header, claims, signature = jwt.split(".")
    def decode(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    assert json.loads(decode(header)) == {"alg": "RS256", "typ": "JWT"}
    assert json.loads(decode(claims)) == {
        "iat": 1_699_999_940, "exp": 1_700_000_540, "iss": "5818173",
    }
    pkcs1_15.new(key.publickey()).verify(
        SHA256.new((header + "." + claims).encode()), decode(signature),
    )
    path.chmod(0o644)
    with pytest.raises(HostHoldError, match="host_app_key_untrusted"):
        publisher._app_jwt(5818173, now=1_700_000_000)


def test_host_app_jwt_refuses_symlinked_key(tmp_path, monkeypatch):
    import os

    import host_premerge_check_publisher as publisher

    tmp_path.chmod(0o700)
    (tmp_path / "target.pem").write_bytes(b"x" * 2000)
    (tmp_path / "github-app-5818173.pem").symlink_to("target.pem")
    monkeypatch.setattr(publisher, "_PRIVATE_DIR", tmp_path)
    monkeypatch.setattr(publisher, "_ISSUER_UID", os.geteuid())
    with pytest.raises(HostHoldError, match="host_app_key_unavailable"):
        publisher._app_jwt(5818173, now=1_700_000_000)


def test_host_app_tokens_are_repo_scoped_and_read_write_separated(monkeypatch):
    import json
    from datetime import datetime

    import host_premerge_check_publisher as publisher

    observed = []
    stamp = 1_700_000_000

    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, _max_bytes):
            return json.dumps(self.body).encode()

    class Opener:
        def open(self, request, timeout):
            assert timeout == 12
            body = json.loads(request.data)
            observed.append((request.full_url, body))
            return Response({
                "token": "ghs_fake_token_for_unit_tests_only",
                "expires_at": datetime.fromtimestamp(
                    stamp + 3000, UTC,
                ).isoformat(),
                "permissions": body["permissions"],
                "repository_selection": "selected",
            })

    monkeypatch.setattr(publisher, "_app_jwt", lambda app_id, now: "fake.jwt")
    monkeypatch.setattr(
        publisher.urllib.request, "build_opener", lambda *_: Opener(),
    )
    for write in (False, True):
        token = publisher._mint_installation_token(
            5818173, 183345910, "deyi2026/llm-first-loop",
            write_checks=write, now=stamp,
        )
        assert token.startswith("ghs_fake_token")
    assert len(observed) == 2
    for url, body in observed:
        assert url.endswith("/app/installations/183345910/access_tokens")
        assert body["repositories"] == ["llm-first-loop"]
        assert body["permissions"]["administration"] == "read"
        assert body["permissions"]["contents"] == "read"
        assert body["permissions"]["pull_requests"] == "read"
        assert body["permissions"]["actions"] == "read"
    assert observed[0][1]["permissions"]["checks"] == "read"
    assert observed[1][1]["permissions"]["checks"] == "write"


def test_host_app_token_wrong_scope_is_fail_closed(monkeypatch):
    import json

    import host_premerge_check_publisher as publisher

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, _limit):
            return json.dumps({
                "token": "ghs_fake_token_for_unit_tests_only",
                "expires_at": "2030-01-01T00:00:00Z",
                "permissions": {"checks": "write"},
                "repository_selection": "all",
            }).encode()

    class Opener:
        def open(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(publisher, "_app_jwt", lambda app_id, now: "fake.jwt")
    monkeypatch.setattr(
        publisher.urllib.request, "build_opener", lambda *_: Opener(),
    )
    with pytest.raises(HostHoldError, match="host_app_token_scope_invalid"):
        publisher._mint_installation_token(
            5818173, 183345910, "deyi2026/llm-first-loop",
            write_checks=True, now=1_700_000_000,
        )


def test_invalid_reviewer_never_mints_write_token(facts):
    payload = copy.deepcopy(facts[1]["payload"])
    payload["review"]["verdict"] = "REVISE"
    facts[1] = sign(payload)
    minted = []
    with pytest.raises(HostHoldError, match="review_missing_or_stale"):
        publish_verified(
            facts[0], repo="o/r", pr_number=PR_NUMBER, main=MAIN,
            candidate=CANDIDATE, run_id=RUN_ID, envelope=facts[1],
            public_key=TEST_PUBLIC, app_id=HOST_APP_ID, now=NOW,
            apply=True, live_state=lambda _payload: None,
            token_supplier=lambda: minted.append(True) or "ghs_fake_token",
        )
    assert minted == []


def test_read_only_preflight_never_mints_write_token(facts):
    minted = []
    result = publish_verified(
        facts[0], repo="o/r", pr_number=PR_NUMBER, main=MAIN,
        candidate=CANDIDATE, run_id=RUN_ID, envelope=facts[1],
        public_key=TEST_PUBLIC, app_id=HOST_APP_ID, now=NOW,
        apply=False, live_state=lambda _payload: None,
        token_supplier=lambda: minted.append(True) or "ghs_fake_token",
    )
    assert result["decision"] == "ELIGIBLE_TO_PUBLISH"
    assert minted == []
