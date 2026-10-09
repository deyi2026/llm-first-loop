"""Session digests are scoped, recoverable projections, not semantic verdicts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from llm_loop.event_log.store import EventStore
from llm_loop.knowledge.session_digest import SessionDigest, SessionDigestReader
from llm_loop.knowledge.session_digest_cli import main

SID = "digest-s1"


def _events(tmp_path: Path):
    store = EventStore(tmp_path / "events")
    store.append(SID, "message.appended", {"message": {
        "role": "assistant", "content": "I claim PASS; this remains unverified 🧪\n" * 20,
    }})
    store.append(SID, "knowledge.reference_prepared", {
        "run_ref": "run:s1", "knowledge_event_key": "k1",
        "refs": ["method:probe"], "reference_chars": 30,
    })
    store.append(SID, "provider.transport.opened", {
        "call_id": "call:a", "attempt_id": "attempt:a", "model_id": "glm-5.3",
        "prepared": {"knowledge_references": [{
            "run_ref": "run:s1", "knowledge_event_key": "k1", "refs": ["method:probe"],
            "reference_chars": 30, "reference_sha256": "a" * 64,
        }]},
    })
    store.append(SID, "provider.transport.settled", {
        "call_id": "call:a", "attempt_id": "attempt:a",
        "outcome": "success", "status_code": 200,
        "usage": {"input_tokens": 21, "output_tokens": 4}, "usage_observations": 1,
    })
    store.append(SID, "knowledge.method_declaration", {
        "run_ref": "run:s1", "ref": "method:probe", "decision": "adapted",
        "task_benefit": "not_evaluated",
    })
    store.append(SID, "knowledge.run_outcome", {
        "run_ref": "run:s1", "reason": "completed", "tokens_in": 21,
        "tokens_out": 4, "duration_ms": 80, "task_benefit": "not_evaluated",
    })
    return store, SessionDigestReader(store, SID)


def test_digest_preserves_scope_coverage_and_model_claim_authority(tmp_path):
    store, reader = _events(tmp_path)
    before = {p: p.read_bytes() for p in (tmp_path / "events").rglob("*") if p.is_file()}
    digest = reader.build(preview_chars=40)
    data = digest.to_dict()
    assert data["session_id"] == SID and data["coverage"]["end_seq"] == 6
    assert data["source_complete"] and data["snapshot_complete"]
    assert data["task_success"] == data["task_benefit"] == "not_evaluated"
    assert data["events"][0]["preview_complete"] is False
    assert data["events"][0]["payload_sha256"] == hashlib.sha256(
        json.dumps(store.read(SID)[0].payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    assert data["observations"]["declarations"][0]["payload"]["decision"] == "adapted"
    assert data["observations"]["outcomes"][0]["payload"]["reason"] == "completed"
    assert data["transport"][0]["knowledge_delivery"] == "http_success_observed"
    assert data["transport"][0]["model_attention"] == "unknown"
    assert data["transport"][0]["usage"]["input_tokens"] == 21
    restored = SessionDigest.from_dict(json.loads(json.dumps(data)))
    assert restored.to_dict() == data and "not_evaluated" in restored.render_markdown()
    first = restored.page(start=0, limit=2)
    second = restored.page(start=first["next_start"], limit=2)
    assert second["events"][0]["seq"] == 3 and second["next_start"] == 4
    assert {p: p.read_bytes() for p in before} == before


def test_exact_event_hydration_is_complete_and_sha_bound(tmp_path):
    store, reader = _events(tmp_path)
    digest = reader.build(preview_chars=10)
    row = digest.to_dict()["events"][0]
    texts = []
    cursor = 0
    sha = None
    while cursor is not None:
        result = reader.hydrate(digest, row["event_ref"], start=cursor,
                                max_chars=27, expected_event_sha256=sha)
        assert result["state"] == "current"
        texts.append(result["text"])
        sha = result["event_sha256"]
        nxt = result["next_start"]
        assert nxt is None or nxt > cursor
        cursor = nxt
    exact = store.read_source_files(SID)[0][1].splitlines(keepends=True)[0].decode()
    assert "".join(texts) == exact
    full = reader.hydrate(digest, row["event_ref"], max_chars=10000)
    assert full["text"] == exact and full["projection_complete"]
    with pytest.raises(ValueError, match="expected_event_sha256"):
        reader.hydrate(digest, row["event_ref"], start=10)


def test_appended_event_marks_view_stale_without_losing_old_exact_event(tmp_path):
    store, reader = _events(tmp_path)
    digest = reader.build()
    row = digest.to_dict()["events"][0]
    store.append(SID, "message.appended", {"message": {"role": "user", "content": "new"}})
    result = reader.hydrate(digest, row["event_ref"])
    assert result["state"] == "stale_view" and result["view_current"] is False
    assert result["event_sha256"] == row["event_sha256"]
    path = tmp_path / "events" / (SID + ".jsonl")
    path.write_bytes(path.read_bytes().replace(b"I claim PASS", b"Source drift"))
    drift = reader.hydrate(digest, row["event_ref"])
    assert drift["state"] == "source_changed" and drift["text"] == ""


@pytest.mark.parametrize("case", ["corrupt", "foreign", "gap", "duplicate"])
def test_source_integrity_errors_are_never_silently_skipped(tmp_path, case):
    store, reader = _events(tmp_path)
    path = tmp_path / "events" / (SID + ".jsonl")
    raw = path.read_bytes()
    if case == "corrupt":
        raw += b'{"unfinished":\n'
    elif case == "foreign":
        raw = raw.replace(SID.encode(), b"foreign-s1", 1)
    elif case == "gap":
        raw = raw.replace(b'"seq": 2', b'"seq": 8', 1)
    else:
        raw += raw.splitlines(keepends=True)[-1]
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        reader.build()


def test_other_session_and_missing_source_are_explicit(tmp_path):
    store, reader = _events(tmp_path)
    foreign = reader.build().to_dict()
    foreign["session_id"] = "foreign-s1"
    with pytest.raises(ValueError, match="fingerprint"):
        SessionDigest.from_dict(foreign)
    store.append("foreign-s1", "message.appended", {"message": {"content": "private"}})
    foreign_digest = SessionDigestReader(store, "foreign-s1").build()
    with pytest.raises(ValueError, match="scope"):
        reader.hydrate(foreign_digest, foreign_digest.to_dict()["events"][0]["event_ref"])
    missing = SessionDigestReader(store, "absent-s1")
    with pytest.raises(ValueError, match="unavailable"):
        missing.build()


def test_multisegment_capture_and_concurrent_drift_are_explicit(tmp_path, monkeypatch):
    store, reader = _events(tmp_path)
    path = tmp_path / "events" / (SID + ".jsonl")
    rows = path.read_bytes().splitlines(keepends=True)
    path.unlink()
    directory = tmp_path / "events" / SID
    directory.mkdir()
    (directory / "1.jsonl").write_bytes(b"".join(rows[:3]))
    (directory / "2.jsonl").write_bytes(b"".join(rows[3:]))
    assert len(reader.build().to_dict()["source_files"]) == 2
    original = store.read_source_files
    calls = 0

    def changing(session):
        nonlocal calls
        calls += 1
        captured = original(session)
        if calls % 2 == 0:
            return [(name, raw + b"\n") for name, raw in captured]
        return captured

    monkeypatch.setattr(store, "read_source_files", changing)
    with pytest.raises(ValueError, match="changed"):
        reader.build()


def test_cli_exports_and_rehydrates_without_provider_or_canonical_writes(tmp_path, capsys):
    _, _ = _events(tmp_path)
    args = ["--events-dir", str(tmp_path / "events"), "--session-id", SID]
    assert main(["build", *args]) == 0
    data = json.loads(capsys.readouterr().out)
    path = tmp_path / "digest.json"
    path.write_text(json.dumps(data))
    assert main(["show", "--digest", str(path), "--session-id", SID, "--format", "markdown"]) == 0
    assert data["digest_ref"] in capsys.readouterr().out
    assert main(["hydrate", "--digest", str(path), "--event-ref",
                 data["events"][0]["event_ref"], *args, "--max-chars", "10000"]) == 0
    hydrated = json.loads(capsys.readouterr().out)
    assert hydrated["projection_complete"] and "I claim PASS" in hydrated["text"]


@pytest.mark.parametrize("change, expected", [
    ("missing_http", "unknown"), ("error", "http_error_observed"),
    ("wrong_identity", "unknown"), ("duplicate", "unknown"),
    ("wrong_run", "unknown"),
])
def test_delivery_requires_unambiguous_matching_request_and_http_facts(tmp_path, change, expected):
    _, reader = _events(tmp_path)
    path = tmp_path / "events" / (SID + ".jsonl")
    rows = [json.loads(raw) for raw in path.read_text().splitlines()]
    if change == "missing_http":
        rows[3]["payload"].pop("status_code")
        rows[3]["payload"].pop("usage_observations")
    elif change == "error":
        rows[3]["payload"].update(outcome="error", status_code=503)
    elif change == "wrong_identity":
        rows[3]["payload"]["call_id"] = "foreign-call"
    elif change == "wrong_run":
        rows[2]["payload"]["prepared"]["knowledge_references"][0]["run_ref"] = "foreign-run"
    else:
        duplicate = {**rows[3], "seq": 7, "event_id": "duplicate-settlement"}
        rows.append(duplicate)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    pairs = reader.build().to_dict()["transport"]
    assert pairs[0]["knowledge_delivery"] == expected
    if change == "missing_http":
        assert pairs[0]["usage_state"] == "unknown"


def test_unterminated_source_is_not_a_complete_digest(tmp_path):
    _, reader = _events(tmp_path)
    path = tmp_path / "events" / (SID + ".jsonl")
    path.write_bytes(path.read_bytes().rstrip(b"\n"))
    with pytest.raises(ValueError, match="unterminated"):
        reader.build()
