"""R4 freshness anchor resolution (M0-R4 minimal batch, 2026-11-16).

Pins DESIGN v1.3.1 §R4/§4.4④/C8 read-side semantics on the method store:
- three anchor kinds (path/code/evidence) surfaced with anchor_root_id and
  resolution_state (resolved/missing/unresolvable);
- evidence:// refs are never stat-ed: unresolvable even when a literal
  URI-shaped file happens to exist (F11/C8 — no trusted resolver in batch);
- release/bundle layout without a src/ mapping => unresolvable, never a fake
  missing/current (F10); genuine deletion inside a repo checkout => missing;
- traversal / absolute / symlink escapes => unresolvable (write gate also
  refuses them up front);
- the content baseline is a real SHA256: an mtime-and-size-preserving rewrite
  still flips the state to changed;
- legacy compatibility: old keys and old snapshot vocabulary keep comparing
  identically, unresolvable refs leave missing_refs, and freshness() is
  read-only — a broken anchor never invalidates the card.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from llm_loop.methods.store import MethodStore

BODY = "## Trigger\n测试触发条件足够长\n"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _make_store(tmp_path: Path) -> tuple[MethodStore, Path]:
    ws = tmp_path / "ws"
    methods = tmp_path / "methods"
    ws.mkdir()
    methods.mkdir()
    return MethodStore(methods, workspace_root=ws), ws


def _card(store: MethodStore, name: str, refs: list[str]):
    record = store.save_candidate(name=name, description=f"{name} 的描述行用于区分", body=BODY)
    return store.annotate_freshness(record.method_ref, refs)


def _append_baseline(record, hashes: dict[str, str]) -> None:
    qpath = Path(record.path).parent / "qualification.jsonl"
    with qpath.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {"ts": "2026-11-16T01:00:00+08:00", "verdict": "pass", "freshness_hashes": hashes}
            )
            + "\n"
        )


def test_path_anchor_resolved_and_mtime_preserving_rewrite_flips_state(tmp_path):
    store, ws = _make_store(tmp_path)
    (ws / "a.txt").write_bytes(b"v1")
    record = _card(store, "freshness path anchor probe", ["a.txt"])
    _append_baseline(record, {"a.txt": _sha(b"v1")})

    fresh = store.freshness(record.method_ref)
    assert fresh["state"] == "current"
    anchor = fresh["anchors"]["a.txt"]
    assert anchor["anchor_kind"] == "path"
    assert anchor["anchor_root_id"] == "workspace"
    assert anchor["resolution_state"] == "resolved"
    assert anchor["content_sha256"] == _sha(b"v1")
    assert fresh["unresolvable_refs"] == []

    stat = os.stat(ws / "a.txt")
    (ws / "a.txt").write_bytes(b"v2")  # same byte size, real content change
    os.utime(ws / "a.txt", (stat.st_atime, stat.st_mtime))  # mtime preserved
    fresh2 = store.freshness(record.method_ref)
    assert fresh2["state"] == "changed"
    assert fresh2["changed_refs"] == ["a.txt"]


def test_code_anchor_resolves_against_repo_root_with_git_identity(tmp_path):
    store, ws = _make_store(tmp_path)
    (ws / "pyproject.toml").write_text('version = "9.9"\n', encoding="utf-8")
    (ws / "src" / "llm_loop").mkdir(parents=True)
    (ws / "src" / "llm_loop" / "mod.py").write_bytes(b"print('hi')\n")
    head_sha = "1c600241848dbc986046afcddc3dc533cbb85a36"
    (ws / ".git").mkdir()
    (ws / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    ref_dir = ws / ".git" / "refs" / "heads"
    ref_dir.mkdir(parents=True)
    (ref_dir / "main").write_text(head_sha + "\n", encoding="utf-8")

    record = _card(store, "freshness code anchor repo probe", ["src/llm_loop/mod.py"])
    _append_baseline(record, {"src/llm_loop/mod.py": _sha(b"print('hi')\n")})

    fresh = store.freshness(record.method_ref)
    anchor = fresh["anchors"]["src/llm_loop/mod.py"]
    assert anchor["anchor_kind"] == "code"
    assert anchor["anchor_root_id"] == "git:" + head_sha[:12]
    assert anchor["resolution_state"] == "resolved"
    assert anchor["content_sha256"] == _sha(b"print('hi')\n")
    assert fresh["state"] == "current"


def test_code_anchor_maps_src_prefix_inside_bundle_layout(tmp_path):
    store, ws = _make_store(tmp_path)
    bundled = ws / "_bundled"
    (bundled / "llm_loop").mkdir(parents=True)
    (bundled / "manifest.json").write_text(json.dumps({"version": "0.6.54"}), encoding="utf-8")
    (bundled / "llm_loop" / "store.py").write_bytes(b"X=1\n")

    record = _card(store, "freshness code anchor bundle probe", ["src/llm_loop/store.py"])
    _append_baseline(record, {"src/llm_loop/store.py": _sha(b"X=1\n")})

    anchor = store.freshness(record.method_ref)["anchors"]["src/llm_loop/store.py"]
    assert anchor["anchor_kind"] == "code"
    assert anchor["anchor_root_id"] == "bundle:0.6.54"
    assert anchor["resolution_state"] == "resolved"
    assert anchor["content_sha256"] == _sha(b"X=1\n")


def test_wheel_layout_without_src_is_unresolvable_not_missing(tmp_path):
    store, ws = _make_store(tmp_path)
    (ws / "llm_loop").mkdir()  # site/release layout: package dir, no src/, no repo markers
    ref = "src/llm_loop/absent_here.py"
    record = _card(store, "freshness wheel layout probe", [ref])
    # an old wheel-side baseline recorded the legacy vocabulary value "missing"
    _append_baseline(record, {ref: "missing"})

    fresh = store.freshness(record.method_ref)
    anchor = fresh["anchors"][ref]
    assert anchor["anchor_kind"] == "code"
    assert anchor["resolution_state"] == "unresolvable"
    assert anchor["anchor_root_id"] == ""  # no trusted code root claims the miss
    assert fresh["current"][ref] == "missing"  # legacy snapshot vocabulary preserved
    assert fresh["missing_refs"] == []  # never fake-missing (F10)
    assert fresh["unresolvable_refs"] == [ref]
    assert fresh["state"] == "unresolvable"  # P1-A: unresolved anchor never yields card-level current


def test_evidence_ref_is_unresolvable_even_when_uri_shaped_file_exists(tmp_path):
    store, ws = _make_store(tmp_path)
    # a literal file whose name is the collapsed URI path — evidence resolution
    # must never consult it (the old bug stat-ed evidence:// as a path)
    uri_dir = ws / "evidence:" / "v1"
    uri_dir.mkdir(parents=True)
    (uri_dir / "abc").write_bytes(b"not-evidence")
    ref = "evidence://v1/abc"
    record = _card(store, "freshness evidence anchor probe", [ref])

    fresh = store.freshness(record.method_ref)
    anchor = fresh["anchors"][ref]
    assert anchor["anchor_kind"] == "evidence"
    assert anchor["anchor_root_id"] == "evidence-store"
    assert anchor["resolution_state"] == "unresolvable"
    assert anchor["content_sha256"] == ""
    assert fresh["unresolvable_refs"] == [ref]


def test_traversal_symlink_and_backslash_are_unresolvable(tmp_path):
    store, ws = _make_store(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"secret")
    os.symlink(outside, ws / "escape_link.txt")

    for raw in ("../outside.txt", "/etc/hosts", "escape_link.txt", "a\\b.txt"):
        resolved = store._resolve_freshness_anchor(raw)
        assert resolved["resolution_state"] == "unresolvable", raw
        assert resolved["content_sha256"] == "", raw

    # the write gate still refuses traversal/absolute refs up front
    record = store.save_candidate(
        name="freshness write gate probe", description="描述行足够区分", body=BODY
    )
    with pytest.raises(ValueError):
        store.annotate_freshness(record.method_ref, ["../outside.txt"])


def test_old_card_baseline_keeps_legacy_contract_and_never_invalidates(tmp_path):
    store, ws = _make_store(tmp_path)
    (ws / "a.txt").write_bytes(b"v1")
    ev = "evidence://v1/legacy"
    record = _card(store, "freshness compat probe", ["a.txt", ev])
    _append_baseline(record, {"a.txt": _sha(b"v1"), ev: "missing"})
    card_path = Path(record.path)
    before = card_path.read_bytes()

    fresh = store.freshness(record.method_ref)
    # legacy keys all present with legacy semantics
    assert fresh["state"] == "unresolvable"  # P1-A guard: evidence ref unresolved
    assert fresh["changed_refs"] == []
    assert fresh["missing_refs"] == []  # evidence ref left missing_refs...
    assert fresh["unresolvable_refs"] == [ev]  # ...and is reported unresolvable
    assert fresh["baseline"][ev] == "missing"
    assert set(fresh["anchors"]) == {"a.txt", ev}
    # read-only: card bytes untouched and the card stays retrievable
    assert card_path.read_bytes() == before
    assert store.get(record.method_ref) is not None


def test_unbaselined_and_not_tracked_branches_expose_anchor_trio(tmp_path):
    store, ws = _make_store(tmp_path)
    plain = store.save_candidate(name="freshness untracked probe", description="描述", body=BODY)
    assert store.freshness(plain.method_ref)["state"] == "not_tracked"

    (ws / "b.txt").write_bytes(b"hi")
    record = _card(store, "freshness annotate-only probe", ["b.txt"])
    fresh = store.freshness(record.method_ref)
    # P1-B: the real annotate path established a baseline, so an annotate-only
    # card now reads current (the unbaselined branch is pinned by the
    # unresolvable-refs test: no resolvable anchor => no baseline).
    assert fresh["state"] == "current"
    assert fresh["anchors"]["b.txt"]["resolution_state"] == "resolved"
    assert fresh["anchor_baseline"] == {"b.txt": _sha(b"hi")}
    assert "unresolvable_refs" in fresh


def test_annotate_freshness_establishes_real_sha_baseline(tmp_path):
    """P1-B: the real annotate path (no hand-forged qualification.jsonl) must
    persist a content-SHA baseline for resolvable refs and freshness() must
    read it back: current now, changed after a real content edit."""
    store, ws = _make_store(tmp_path)
    (ws / "c.txt").write_bytes(b"k1")
    record = store.save_candidate(name="annotate baseline probe", description="描述行足够区分", body=BODY)
    record = store.annotate_freshness(record.method_ref, ["c.txt"])

    fresh = store.freshness(record.method_ref)
    assert fresh["state"] == "current"
    assert fresh["anchor_baseline"] == {"c.txt": _sha(b"k1")}
    assert fresh["anchor_changed_refs"] == []

    journal = (tmp_path / "methods" / "annotations.jsonl").read_text(encoding="utf-8")
    payload = json.loads(journal.strip().splitlines()[-1])
    baseline = payload["anchor_baseline"]
    assert baseline["resolver_version"] == "r4-anchor-v1"
    assert baseline["sampled_at"]
    assert baseline["anchors"]["c.txt"]["anchor_root_id"] == "workspace"
    assert baseline["anchors"]["c.txt"]["content_sha256"] == _sha(b"k1")

    (ws / "c.txt").write_bytes(b"k2")  # real content change, no manual baseline edit
    fresh2 = store.freshness(record.method_ref)
    assert fresh2["state"] == "changed"
    assert fresh2["anchor_changed_refs"] == ["c.txt"]


def test_annotate_unresolvable_refs_create_no_baseline_and_never_current(tmp_path):
    """P1-B negative: unresolvable refs must not create an empty baseline, and
    the card can never claim current without any resolvable baseline."""
    store, ws = _make_store(tmp_path)
    (ws / "llm_loop").mkdir()  # release layout only: no src/ mapping for code refs
    record = store.save_candidate(name="annotate unresolvable probe", description="描述行足够区分", body=BODY)
    record = store.annotate_freshness(record.method_ref, ["src/llm_loop/ghost.py", "evidence://v1/x"])

    journal = (tmp_path / "methods" / "annotations.jsonl").read_text(encoding="utf-8")
    payload = json.loads(journal.strip().splitlines()[-1])
    assert "anchor_baseline" not in payload  # no empty baseline for unresolvable refs

    fresh = store.freshness(record.method_ref)
    assert fresh["anchor_baseline"] is None
    assert fresh["state"] == "unbaselined"  # no baseline => no current claim
    assert set(fresh["unresolvable_refs"]) == {"src/llm_loop/ghost.py", "evidence://v1/x"}


def test_annotate_mixed_refs_baseline_excludes_unresolvable(tmp_path):
    """Mixed refs: the journal baseline carries only the resolvable ref, and
    the unresolved evidence ref keeps the card out of state=current (P1-A)."""
    store, ws = _make_store(tmp_path)
    (ws / "d.txt").write_bytes(b"m1")
    record = store.save_candidate(name="annotate mixed probe", description="描述行足够区分", body=BODY)
    record = store.annotate_freshness(record.method_ref, ["d.txt", "evidence://v1/y"])

    fresh = store.freshness(record.method_ref)
    assert fresh["anchor_baseline"] == {"d.txt": _sha(b"m1")}
    assert fresh["state"] == "unresolvable"  # not current while evidence unresolved
    assert fresh["unresolvable_refs"] == ["evidence://v1/y"]
    assert fresh["anchor_changed_refs"] == []


def test_code_anchor_root_id_via_worktree_pointer_and_packed_refs(tmp_path):
    """P2: linked-worktree ``.git`` pointer file and packed-refs fallback both
    yield the true root_id; identity never falls back to a fabricated version."""
    store, ws = _make_store(tmp_path)
    (ws / "pyproject.toml").write_text("", encoding="utf-8")
    (ws / "src" / "llm_loop").mkdir(parents=True)
    (ws / "src" / "llm_loop" / "m.py").write_bytes(b"z")
    sha = "9e6b438cc814844fde49b519824cd359b5a27cdc"
    git_dir = tmp_path / "gd" / "worktrees" / "wt"
    git_dir.mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/lane\n", encoding="utf-8")
    (git_dir / "commondir").write_text("../../", encoding="utf-8")  # shared common gitdir
    # loose ref absent on purpose: identity must come from the common packed-refs
    (tmp_path / "gd" / "packed-refs").write_text(f"{sha} refs/heads/lane\n", encoding="utf-8")
    (ws / ".git").write_text(f"gitdir: {git_dir}\n", encoding="utf-8")  # pointer FILE

    record = _card(store, "worktree root id probe", ["src/llm_loop/m.py"])
    anchor = store.freshness(record.method_ref)["anchors"]["src/llm_loop/m.py"]
    assert anchor["anchor_kind"] == "code"
    assert anchor["anchor_root_id"] == "git:" + sha[:12]
    assert anchor["resolution_state"] == "resolved"
