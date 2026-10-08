"""MethodStore T2 card-write contract: atomicity, conflict, uncertainty and locks.

All injected crashes/disk failures use tmp_path. The production Method pool is
never accessed; append-only JSONL is a separate T1 contract.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.introspection.registry_experience import (
    _run_annotate_freshness,
    _run_record_method_qualification,
    _run_refine_method,
)
from llm_loop.methods import store as module
from llm_loop.methods.store import (
    MethodCommitUncertainError,
    MethodPersistError,
    MethodStore,
)

BODY = "\n".join(
    f"## {title}\n{title} has a concrete non-placeholder instruction.\n"
    for title in (
        "Trigger",
        "Discriminator",
        "Short path",
        "Stop conditions",
        "Verification",
        "Counterexamples",
    )
)


def _store(root: Path, *, seed: Path | None = None) -> MethodStore:
    return MethodStore(root, seed_dir=seed)


def _save(store: MethodStore, name: str = "atomic method"):
    return store.save_candidate(name=name, description="durability preflight", body=BODY)


def _card_path(root: Path, method_id: str) -> Path:
    return root / method_id / "METHOD.md"


def _no_orphan_stage(root: Path) -> bool:
    stage = root / module._STAGING_DIR
    return not stage.exists() or not list(stage.iterdir())


def test_candidate_is_atomic_and_idempotent_hooks_once(tmp_path: Path) -> None:
    store = _store(tmp_path)
    events: list[str] = []
    store.add_post_save_hook(lambda r: events.append(r.method_ref))
    first = _save(store)
    second = _save(store)
    assert first.method_ref == second.method_ref
    assert (
        first.content_hash
        == hashlib.sha256(_card_path(tmp_path, first.method_id).read_bytes()).hexdigest()
    )
    assert events == [first.method_ref]
    assert _no_orphan_stage(tmp_path)
    assert len(list(tmp_path.glob("*/METHOD.md"))) == 1


def test_candidate_pre_commit_failure_leaves_no_card_or_hook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    events: list[str] = []
    store.add_post_save_hook(lambda r: events.append(r.method_ref))

    def fail_write(_path: Path, _payload: bytes) -> None:
        raise OSError("simulated disk full before rename")

    with monkeypatch.context() as m:
        m.setattr(module, "_write_file_exclusive", fail_write)
        with pytest.raises(MethodPersistError):
            _save(store)
    assert not list(tmp_path.glob("*/METHOD.md"))
    assert _no_orphan_stage(tmp_path)
    assert events == []
    assert _save(store).status == "candidate"


def test_candidate_rename_failure_never_exposes_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_rename(_src: Path, _dst: Path) -> None:
        raise OSError("simulated rename refusal")

    with monkeypatch.context() as m:
        m.setattr(module.os, "rename", fail_rename)
        with pytest.raises(MethodPersistError):
            _save(_store(tmp_path))
    assert not list(tmp_path.glob("*/METHOD.md"))
    assert _no_orphan_stage(tmp_path)


def test_candidate_after_rename_fsync_uncertain_readback_no_blind_create(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = module._fsync_directory
    calls = 0

    def fail_root(path: Path) -> None:
        nonlocal calls
        if path == tmp_path:
            calls += 1
            raise OSError("simulated parent fsync failure")
        original(path)

    store = _store(tmp_path)
    events: list[str] = []
    store.add_post_save_hook(lambda r: events.append(r.method_ref))
    with monkeypatch.context() as m:
        m.setattr(module, "_fsync_directory", fail_root)
        with pytest.raises(MethodCommitUncertainError) as exc:
            _save(store)
    err = exc.value
    assert err.operation == "save_candidate"
    assert err.visible_state == "matches"
    assert calls == module._DIR_FSYNC_ATTEMPTS
    actual = store.get(err.method_ref)
    assert actual is not None
    assert actual.content_hash == err.expected_sha256
    assert events == []  # a derived hook is not a commit receipt
    assert _save(store).method_ref == err.method_ref
    assert events == []


def test_candidate_concurrent_create_single_card_two_store_instances(tmp_path: Path) -> None:
    stores = [_store(tmp_path), _store(tmp_path)]
    barrier = threading.Barrier(8)
    result: list[str] = []

    def worker(i: int) -> None:
        barrier.wait()
        result.append(_save(stores[i % 2], "concurrent same card").method_ref)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(result)) == 1
    assert len(list(tmp_path.glob("*/METHOD.md"))) == 1
    assert _no_orphan_stage(tmp_path)


def test_update_status_atomic_preserves_full_old_on_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    record = _save(store)
    path = _card_path(tmp_path, record.method_id)
    before = path.read_bytes()

    def fail_replace(_src: Path, _dst: Path) -> None:
        raise OSError("simulated replace failure")

    with monkeypatch.context() as m:
        m.setattr(module.os, "replace", fail_replace)
        with pytest.raises(MethodPersistError):
            store.update_status(record.method_ref, "hold")
    assert path.read_bytes() == before
    assert store.get(record.method_ref).status == "candidate"
    assert not list(path.parent.glob("*.tmp"))


def test_update_status_after_replace_fsync_uncertain_is_whole_new_card(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    record = _save(store)
    path = _card_path(tmp_path, record.method_id)

    def fail_card_dir(directory: Path) -> None:
        if directory == path.parent:
            raise OSError("simulated card-directory fsync failure")
        module.os.stat(directory)

    with monkeypatch.context() as m:
        m.setattr(module, "_fsync_directory", fail_card_dir)
        with pytest.raises(MethodCommitUncertainError) as exc:
            store.update_status(record.method_ref, "hold")
    err = exc.value
    assert err.operation == "update_status"
    assert err.visible_state == "matches"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == err.expected_sha256
    actual = store.get(record.method_ref)
    assert actual.status == "hold" and actual.body == record.body
    assert not list(path.parent.glob("*.tmp"))


def test_update_status_and_annotation_concurrent_no_lost_field(tmp_path: Path) -> None:
    stores = [_store(tmp_path), _store(tmp_path)]
    record = _save(stores[0])
    barrier = threading.Barrier(8)
    errors: list[str] = []

    def worker(i: int) -> None:
        barrier.wait()
        try:
            if i % 2:
                stores[i % 2].update_status(record.method_ref, "hold")
            else:
                stores[i % 2].annotate_freshness(record.method_ref, ["src/exact.py"])
        except Exception as exc:
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    actual = stores[0].get(record.method_ref)
    assert actual.status == "hold"
    assert actual.freshness_refs == ("src/exact.py",)
    assert actual.body == record.body


def test_annotation_pre_commit_failure_keeps_card_and_no_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    record = _save(store)
    path = _card_path(tmp_path, record.method_id)
    before = path.read_bytes()

    def fail_replace(_src: Path, _dst: Path) -> None:
        raise OSError("simulated replace failure")

    with monkeypatch.context() as m:
        m.setattr(module.os, "replace", fail_replace)
        with pytest.raises(MethodPersistError):
            store.annotate_freshness(record.method_ref, ["src/new.py"])
    assert path.read_bytes() == before
    assert not (tmp_path / "annotations.jsonl").exists()


def test_annotation_success_keeps_body_and_appends_receipt(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = _save(store)
    updated = store.annotate_freshness(record.method_ref, ["src/exact.py"])
    assert updated.body == record.body
    assert updated.freshness_refs == ("src/exact.py",)
    entries = (tmp_path / "annotations.jsonl").read_text().splitlines()
    assert len(entries) == 1
    assert json.loads(entries[0])["new"] == ["src/exact.py"]


def _seed(root: Path) -> tuple[Path, Path]:
    seed = root / "seed"
    method_dir = seed / "seed-example"
    method_dir.mkdir(parents=True)
    path = method_dir / "METHOD.md"
    path.write_text("---\nmethod_id: seed-example\nstatus: candidate\n---\n" + BODY + "\n")
    (method_dir / "qualification.json").write_text('{"seed":true}')
    return seed, path


def test_seed_overlay_atomic_and_preserves_qualification_summary(tmp_path: Path) -> None:
    seed, original = _seed(tmp_path)
    original_bytes = original.read_bytes()
    store = _store(tmp_path / "methods", seed=seed)
    updated = store.update_status("method:seed-example", "hold")
    runtime = tmp_path / "methods" / "seed-example"
    assert updated.status == "hold"
    assert original.read_bytes() == original_bytes
    assert json.loads((runtime / "qualification.json").read_text()) == {"seed": True}
    assert _no_orphan_stage(tmp_path / "methods")


def test_seed_overlay_rename_failure_does_not_expose_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed, original = _seed(tmp_path)
    root = tmp_path / "methods"
    store = _store(root, seed=seed)
    before = original.read_bytes()

    def fail_rename(_src: Path, _dst: Path) -> None:
        raise OSError("simulated seed overlay rename refusal")

    with monkeypatch.context() as m:
        m.setattr(module.os, "rename", fail_rename)
        with pytest.raises(MethodPersistError):
            store.update_status("method:seed-example", "hold")
    assert store.get("method:seed-example").status == "candidate"
    assert original.read_bytes() == before
    assert not (root / "seed-example").exists()
    assert _no_orphan_stage(root)


def test_qualification_and_promotion_remain_consistent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = _save(store)
    entry = store.record_qualification(
        record.method_ref,
        task_ref="episode:independent",
        verdict="pass",
        promotion="pass",
    )
    assert entry["qualification_episode_ref"] == "episode:independent"
    assert store.update_status(record.method_ref, "qualified").status == "qualified"
    assert store.update_status(record.method_ref, "active").status == "active"
    assert len(store.qualification_entries(record.method_ref)) == 1


def test_lock_acquire_failure_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if module.fcntl is None:
        pytest.skip("POSIX flock required")

    def fail_lock(_fd: int, _flags: int) -> None:
        raise OSError("simulated flock denial")

    with monkeypatch.context() as m:
        m.setattr(module.fcntl, "flock", fail_lock)
        with pytest.raises(MethodPersistError, match="lock unavailable"):
            _save(_store(tmp_path))
    assert not list(tmp_path.glob("*/METHOD.md"))


def test_staging_orphans_are_not_discoverable(tmp_path: Path) -> None:
    stage = tmp_path / module._STAGING_DIR / "stranded.stage"
    stage.mkdir(parents=True)
    (stage / "METHOD.md").write_text("---\nmethod_id: ghost\nstatus: active\n---\nGHOST")
    store = _store(tmp_path)
    assert store.get("method:ghost") is None
    assert all(card["id"] != "ghost" for card in store.list("ghost"))
    report = store.recover()
    assert report["orphan_stages"] == ["stranded.stage"]
    assert report["records"] == 0


def test_recover_reports_incomplete_and_invalid_without_mutation(tmp_path: Path) -> None:
    (tmp_path / "incomplete").mkdir()
    (tmp_path / "incomplete" / "qualification.json").write_text("{}")
    (tmp_path / "foreign-dir").mkdir()
    invalid = tmp_path / "invalid-card"
    invalid.mkdir()
    (invalid / "METHOD.md").write_text("---\nstatus: unsupported\n---\ncontent")
    store = _store(tmp_path)
    report = store.recover()
    assert report["incomplete_dirs"] == ["incomplete"]
    assert report["invalid_records"] == ["invalid-card"]
    assert "foreign-dir" in report["unclassified_dirs"]
    assert (invalid / "METHOD.md").exists()


def test_tool_refine_uncertain_receipt_does_not_claim_blocked_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    record = _save(store)
    error = MethodCommitUncertainError(
        "directory fsync failure",
        method_ref=record.method_ref,
        operation="update_status",
        expected_sha256="a" * 64,
        visible_state="matches",
    )

    def uncertain(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(store, "update_status", uncertain)
    host = SimpleNamespace(method_store=store, episode_ref="episode:current")
    result = _run_refine_method({"method_ref": record.method_ref, "action": "hold"}, host)
    assert result.status == ToolResultStatus.FAILURE
    assert "提交结果不确定" in result.content
    assert "禁止盲重放" in result.content
    assert "journal" not in result.content


def test_tool_annotate_precommit_receipt_is_not_uncertain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    record = _save(store)

    def fail(*_args, **_kwargs):
        raise MethodPersistError("definitely not committed")

    monkeypatch.setattr(store, "annotate_freshness", fail)
    host = SimpleNamespace(method_store=store)
    result = _run_annotate_freshness(
        {"method_ref": record.method_ref, "freshness_refs": ["src/a.py"]},
        host,
        tool_name="method_manage",
    )
    assert result.status == ToolResultStatus.FAILURE
    assert "确定未提交" in result.content
    assert "提交结果不确定" not in result.content


def test_tool_qualification_uncertain_receipt_requires_exact_readback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    record = _save(store)

    def uncertain(*_args, **_kwargs):
        raise MethodCommitUncertainError(
            "seed overlay post-rename failure",
            method_ref=record.method_ref,
            operation="seed_overlay",
            expected_sha256="b" * 64,
            visible_state="matches",
        )

    monkeypatch.setattr(store, "record_qualification", uncertain)
    host = SimpleNamespace(method_store=store, current_episode_ref=lambda: "episode:new")
    result = _run_record_method_qualification(
        {"method_ref": record.method_ref, "verdict": "pass"},
        host,
        tool_name="method_manage",
    )
    assert result.status == ToolResultStatus.FAILURE
    assert "qualification_entries" in result.content
    assert "禁止盲重放" in result.content
