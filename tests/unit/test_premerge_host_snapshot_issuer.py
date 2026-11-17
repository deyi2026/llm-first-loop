"""Independent operator Host issuer: key isolation, live state and signature tests."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from premerge_host import _verified_snapshot
from premerge_host_snapshot_issuer import (
    IssuerHoldError,
    check_receipts,
    crypto,
    fetch_json,
    keygen,
    local_state,
    public_bytes,
    read_rows,
    remote_state,
    secure_bytes,
    sign_payload,
    write_all,
)

MAIN = "a" * 40
CANDIDATE = "b" * 40
LANE = "lane-test"


@pytest.fixture
def crypto_for_unit_tests(monkeypatch):
    """Exercise real Ed25519 without depending on macOS-only installed site.

    Production crypto() still enforces the root-owned site; that security
    boundary is independently covered by the negative test below.
    """
    from Crypto.PublicKey import ECC
    from Crypto.Signature import eddsa

    monkeypatch.setattr("premerge_host_snapshot_issuer.crypto",
                        lambda: (ECC, eddsa))
    return ECC, eddsa


def test_crypto_rejects_missing_or_untrusted_runtime(tmp_path, monkeypatch):
    missing = tmp_path / "missing-site"
    monkeypatch.setattr("premerge_host_snapshot_issuer._TRUSTED_SITE", str(missing))
    with pytest.raises(FileNotFoundError):
        crypto()
    untrusted = tmp_path / "user-owned-site"
    untrusted.mkdir()
    monkeypatch.setattr("premerge_host_snapshot_issuer._TRUSTED_SITE", str(untrusted))
    with pytest.raises(IssuerHoldError, match="crypto_runtime_untrusted"):
        crypto()


def test_ed25519_signature_is_accepted_by_real_host_verifier(crypto_for_unit_tests):
    ecc, _ = crypto_for_unit_tests
    key = ecc.generate(curve="Ed25519")
    payload = {"checked_at": time.time(), "main_sha": MAIN,
               "candidate_sha": CANDIDATE, "repo": "deyi2026/llm-first-loop"}
    envelope = sign_payload(payload, key.export_key(format="PEM").encode())
    assert _verified_snapshot(envelope, key.public_key().export_key(format="PEM"),
                              time.time()) == payload
    envelope["payload"]["main_sha"] = CANDIDATE
    with pytest.raises(Exception, match="host_snapshot_signature_invalid"):
        _verified_snapshot(envelope, key.public_key().export_key(format="PEM"),
                           time.time())


def test_keygen_requires_separate_owner_and_refuses_reuse(tmp_path, crypto_for_unit_tests):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    with pytest.raises(IssuerHoldError, match="issuer_uid_invalid"):
        keygen(directory, expected_uid=os.geteuid() + 1)
    result = keygen(directory, expected_uid=os.geteuid())
    assert result["key_id"] and Path(result["private_path"]).stat().st_mode & 0o077 == 0
    assert b"PRIVATE KEY" in secure_bytes(Path(result["private_path"]), os.geteuid())
    with pytest.raises(FileExistsError):
        keygen(directory, expected_uid=os.geteuid())


def test_private_key_rejects_symlink_and_permissive_mode(tmp_path):
    private = tmp_path / "key.pem"
    private.write_text("secret")
    private.chmod(0o644)
    with pytest.raises(IssuerHoldError, match="evidence_mode_or_size_invalid"):
        secure_bytes(private, os.geteuid())
    private.chmod(0o600)
    assert secure_bytes(private, os.geteuid()) == b"secret"
    link = tmp_path / "link.pem"
    link.symlink_to(private)
    with pytest.raises(OSError):
        secure_bytes(link, os.geteuid())


def test_public_authority_file_refuses_world_writable(tmp_path):
    file = tmp_path / "queue.jsonl"
    file.write_text('{}\n')
    file.chmod(0o666)
    with pytest.raises(IssuerHoldError, match="authority_file_writable_or_large"):
        public_bytes(file, os.geteuid())
    file.chmod(0o644)
    assert read_rows(file, os.geteuid()) == [{}]


def test_write_all_handles_short_writes_and_rejects_zero_progress(monkeypatch):
    read_fd, write_fd = os.pipe()
    original_write = os.write
    try:
        monkeypatch.setattr("premerge_host_snapshot_issuer.os.write",
                            lambda fd, data: original_write(fd, bytes(data)[:2]))
        write_all(write_fd, b"abcdefg")
        assert os.read(read_fd, 7) == b"abcdefg"
        monkeypatch.setattr("premerge_host_snapshot_issuer.os.write",
                            lambda fd, data: 0)
        with pytest.raises(IssuerHoldError, match="issuer_write_incomplete"):
            write_all(write_fd, b"x")
    finally:
        os.close(write_fd)
        os.close(read_fd)


def receipts():
    return (
        {"candidate_sha": CANDIDATE, "terminal": True, "verdict": "PASS",
         "p0": 0, "p1": 0, "reviewer_model": "glm/glm-5.3-flash",
         "reviewer_session_id": "review-session"},
        {"candidate_sha": CANDIDATE, "full": True, "exit_code": 0,
         "log_sha256": "a" * 64},
        {"candidate_sha": CANDIDATE, "main_sha": MAIN,
         "contracts_verified": True, "merge_tree_clean": True},
    )


def test_operator_owned_receipts_required_for_review_r9_integration():
    review, r9, integration = receipts()
    a, b, c = check_receipts(review, r9, integration,
                             main=MAIN, candidate=CANDIDATE)
    assert a["terminal"] and b["exit_code"] == 0 and c["clean"]
    for which, field, value in (
        (0, "verdict", "REVISE"), (0, "p1", 1),
        (0, "reviewer_model", "deepseek/deepseek-v4-flash"),
        (1, "exit_code", 1), (1, "log_sha256", "0"),
        (2, "contracts_verified", False), (2, "main_sha", CANDIDATE),
    ):
        copies = [dict(x) for x in receipts()]
        copies[which][field] = value
        with pytest.raises(IssuerHoldError):
            check_receipts(*copies, main=MAIN, candidate=CANDIDATE)


def state_fixture(tmp_path):
    audit = tmp_path / "audit"
    audit.mkdir()
    lane = {"lane_id": LANE, "status": "merging", "head_sha": CANDIDATE,
            "base_main_sha": MAIN, "version": 4, "verify_ref": "review-1"}
    queue = {"queue_id": "q-1", "lane_id": LANE, "status": "merging",
             "head_sha": CANDIDATE, "base_main_sha": MAIN,
             "slot_acquired_at": "2026-11-17T01:00:00+08:00", "slot_owner": "operator",
             "version": 3, "last_preflight": {"main_head": MAIN, "verdict": "pass"},
             "stale": False}
    board = {"main_head": MAIN, "degraded": False, "lanes": [dict(lane)]}
    def write(name, rows):
        (audit / name).write_text("".join(json.dumps(x) + "\n" for x in rows))
    write("lanes.jsonl", [lane])
    write("merge_queue.jsonl", [queue])
    return audit, lane, queue, board, write


def test_real_queue_merging_and_exclusive_slot_is_required(tmp_path):
    audit, lane, queue, board, write = state_fixture(tmp_path)
    a, b = local_state(LANE, MAIN, CANDIDATE, audit_dir=audit,
                       owner=os.geteuid(), board=board)
    assert a["status"] == b["status"] == "merging" and b["slot_held"]
    for status, slot in (("ready_for_confirm", ""),
                         ("ready_for_confirm", "2026-11-17T01:00:00+08:00"),
                         ("merging", ""), ("preflight", "2026-11-17T01:00:00+08:00")):
        bad = dict(queue, status=status, slot_acquired_at=slot)
        write("merge_queue.jsonl", [bad])
        with pytest.raises(IssuerHoldError):
            local_state(LANE, MAIN, CANDIDATE, audit_dir=audit,
                        owner=os.geteuid(), board=board)
    write("merge_queue.jsonl", [queue, dict(queue, lane_id="other")])
    with pytest.raises(IssuerHoldError, match="merge_slot_not_exclusive"):
        local_state(LANE, MAIN, CANDIDATE, audit_dir=audit,
                    owner=os.geteuid(), board=board)


@pytest.mark.parametrize("degraded", [True, ["audit_state_incomplete"],
                                       {"reason": "missing"}, None, 0, ""])
def test_board_degraded_fails_closed(tmp_path, degraded):
    audit, _, _, board, _ = state_fixture(tmp_path)
    board["degraded"] = degraded
    with pytest.raises(IssuerHoldError, match="board_main_untrusted"):
        local_state(LANE, MAIN, CANDIDATE, audit_dir=audit,
                    owner=os.geteuid(), board=board)


def test_board_missing_degraded_fails_closed(tmp_path):
    audit, _, _, board, _ = state_fixture(tmp_path)
    del board["degraded"]
    with pytest.raises(IssuerHoldError, match="board_main_untrusted"):
        local_state(LANE, MAIN, CANDIDATE, audit_dir=audit,
                    owner=os.geteuid(), board=board)


def test_board_empty_degraded_list_is_healthy(tmp_path):
    audit, _, _, board, _ = state_fixture(tmp_path)
    board["degraded"] = []
    lane, queue = local_state(LANE, MAIN, CANDIDATE, audit_dir=audit,
                              owner=os.geteuid(), board=board)
    assert lane["status"] == queue["status"] == "merging"


def test_lane_board_version_drift_and_preflight_failure_hold(tmp_path):
    audit, lane, queue, board, write = state_fixture(tmp_path)
    board["lanes"][0]["version"] += 1
    with pytest.raises(IssuerHoldError, match="lane_snapshot_untrusted"):
        local_state(LANE, MAIN, CANDIDATE, audit_dir=audit,
                    owner=os.geteuid(), board=board)
    board["lanes"][0]["version"] -= 1
    write("merge_queue.jsonl", [dict(queue, last_preflight={"main_head": MAIN, "verdict": "fail"})])
    with pytest.raises(IssuerHoldError, match="queue_snapshot_untrusted"):
        local_state(LANE, MAIN, CANDIDATE, audit_dir=audit,
                    owner=os.geteuid(), board=board)


def test_remote_run_identity_must_be_green(monkeypatch):
    from premerge_host_snapshot_issuer import _REPO
    prefix = "https://api.github.com/repos/" + _REPO
    data = {
        prefix + "/branches/main": {"commit": {"sha": MAIN}},
        prefix + "/pulls/52": {"state": "open", "draft": False,
                                "head": {"sha": CANDIDATE},
                                "base": {"sha": MAIN, "ref": "main"},
                                "merge_commit_sha": "c" * 40},
        prefix + "/actions/runs/123": {"id": 123, "event": "pull_request",
                                      "status": "completed", "conclusion": "success",
                                      "head_sha": CANDIDATE},
    }
    monkeypatch.setattr("premerge_host_snapshot_issuer.fetch_json", lambda url: data[url])
    assert remote_state(52, 123) == (MAIN, CANDIDATE)
    data[prefix + "/actions/runs/123"]["conclusion"] = "failure"
    with pytest.raises(IssuerHoldError, match="ci_run_not_verified"):
        remote_state(52, 123)


def test_no_arbitrary_url_or_signer_web_route():
    with pytest.raises(IssuerHoldError, match="url_not_allowlisted"):
        fetch_json("https://attacker.invalid/sign")


def test_operator_issuer_atomic_publish_and_no_overwrite(tmp_path, monkeypatch, crypto_for_unit_tests):
    """Synthetic end-to-end issue path; live source checks are tested separately."""
    import hashlib
    from types import SimpleNamespace

    from premerge_host_snapshot_issuer import issue

    private_dir = tmp_path / "private"
    private_dir.mkdir(mode=0o700)
    output_dir = tmp_path / "receipts"
    output_dir.mkdir(mode=0o750)
    keygen(private_dir, expected_uid=os.geteuid())
    review, r9, integration = receipts()
    raw_log = b"pytest summary\nci_gate all tests PASS\n"
    r9["log_sha256"] = hashlib.sha256(raw_log).hexdigest()
    r9["log_path"] = str(tmp_path / "r9.log")
    (tmp_path / "r9.log").write_bytes(raw_log)
    paths = []
    for name, data in (("review", review), ("r9", r9), ("integration", integration)):
        path = private_dir / (name + ".json")
        path.write_text(json.dumps(data))
        path.chmod(0o600)
        paths.append(path)
    worktree = tmp_path / "candidate"
    worktree.mkdir()
    monkeypatch.setattr("premerge_host_snapshot_issuer.remote_state",
                        lambda pr, run_id: (MAIN, CANDIDATE))
    lane = {"lane_id": LANE, "status": "merging", "version": 3,
            "head_sha": CANDIDATE, "base_main_sha": MAIN, "verify_ref": "v"}
    queue = {"queue_id": "q", "lane_id": LANE, "status": "merging",
             "version": 2, "slot_held": True, "last_preflight_main_sha": MAIN}
    monkeypatch.setattr("premerge_host_snapshot_issuer.local_state",
                        lambda *args, **kwargs: (lane, queue))
    monkeypatch.setattr("premerge_host_snapshot_issuer.public_bytes",
                        lambda *args, **kwargs: raw_log)
    orig_stat = Path.stat

    def owner_stat(self, *args, **kwargs):
        st = orig_stat(self, *args, **kwargs)
        if self == worktree:
            return SimpleNamespace(st_uid=os.geteuid() + 1, st_mode=st.st_mode)
        return st

    monkeypatch.setattr(Path, "stat", owner_stat)

    def fake_git(cmd, **kwargs):
        if "rev-parse" in cmd:
            return SimpleNamespace(returncode=0, stdout=CANDIDATE)
        if "merge-base" in cmd:
            return SimpleNamespace(returncode=0, stdout=MAIN)
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr("premerge_host_snapshot_issuer.subprocess.run", fake_git)
    params = dict(pr=53, run_id=123, lane_id=LANE, worktree=worktree,
                  review_path=paths[0], r9_path=paths[1], integration_path=paths[2],
                  private_dir=private_dir, output_dir=output_dir,
                  audit_dir=tmp_path, expected_main=MAIN, expected_candidate=CANDIDATE,
                  expected_uid=os.geteuid(), web_uid=os.geteuid() + 1,
                  web_group_gid=os.getgid())
    result = issue(**params)
    assert result["decision"] == "SIGNED"
    output = Path(result["snapshot_path"])
    assert output.is_file() and output.stat().st_mode & 0o007 == 0
    envelope = json.loads(output.read_text())
    ecc, _ = crypto()
    public = ecc.import_key(secure_bytes(private_dir / "host-ed25519.pem", os.geteuid()))
    assert _verified_snapshot(envelope, public.public_key().export_key(format="PEM"),
                              time.time())["queue"]["status"] == "merging"
    assert "host_snapshot_publish_intent" in (private_dir / "issuer-audit.jsonl").read_text()
    with pytest.raises(FileExistsError):
        issue(**params)
    assert len(list(private_dir.glob(".snapshot-pending-*"))) == 0
