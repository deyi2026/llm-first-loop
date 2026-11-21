"""B2 v1.9: real Git probes, conservative unknowns and zero authority."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from llm_loop.introspection.baseline_impact import (
    assess_rebased_carryover,
    probe_main_host,
    project_baseline_impact,
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True,
        text=True, check=True,
    ).stdout.strip()


def commit(repo: Path, path: str, data: str, message: str) -> str:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(data, encoding="utf-8")
    git(repo, "add", "--", path)
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Path, Path, dict, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    base = commit(repo, "README.md", "initial\n", "base")
    git(repo, "update-ref", "refs/remotes/origin/main", base)
    worktree = tmp_path / "lane"
    git(repo, "worktree", "add", "-b", "feature", str(worktree), base)
    head = commit(worktree, "src/worker.py", "def worker(): return 1\n", "lane")
    lane = {
        "lane_id": "lane-1", "version": 1, "head_sha": head,
        "base_main_sha": base, "worktree": str(worktree),
        "paths": ["src/worker.py"], "contract_changes": [],
    }
    return repo, worktree, lane, base


def impact(repo: Path, lane: dict, **kw: object) -> dict:
    return project_baseline_impact(repo, lane, **kw)["impact"]


def test_host_probe_keeps_checkout_and_local_main_distinct(setup: tuple) -> None:
    repo, _, lane, base = setup
    obs = probe_main_host(repo)
    assert obs["checkout_head"] == base
    assert obs["origin_main"] == base
    assert obs["selected_main_source"] == "host_local_tracking"
    assert obs["remote_verified"] is False
    assert impact(repo, lane)["status"] == "current"


def test_disjoint_main_advance_stale_not_merge_authority(setup: tuple) -> None:
    repo, _, lane, _ = setup
    main = commit(repo, "docs/notes.md", "notes\n", "advance")
    git(repo, "update-ref", "refs/remotes/origin/main", main)
    result = project_baseline_impact(repo, lane)
    assert result["impact"]["status"] == "stale_needs_refresh"
    assert result["impact"]["changed_paths"] == ["docs/notes.md"]
    assert result["impact"]["recommended_next_step"] == "refresh_base"
    assert not any(key in str(result) for key in ("merge_allowed", "can_skip_r9"))


def test_overlap_is_affected(setup: tuple) -> None:
    repo, _, lane, _ = setup
    main = commit(repo, "src/worker.py", "def worker(): return 2\n", "overlap")
    git(repo, "update-ref", "refs/remotes/origin/main", main)
    result = impact(repo, lane)
    assert result["status"] == "affected"
    assert result["overlap_paths"] == ["src/worker.py"]


def test_forged_caller_main_fails_closed(setup: tuple) -> None:
    repo, _, lane, base = setup
    assert impact(repo, lane, caller_main_head=base)["reason_codes"] == [
        "main_identity_untrusted"
    ]


def test_dirty_untracked_and_mismatched_head_unknown(setup: tuple) -> None:
    repo, worktree, lane, _ = setup
    (worktree / "untracked.txt").write_text("secret?\n")
    assert impact(repo, lane)["reason_codes"] == ["uncommitted_changes"]
    (worktree / "untracked.txt").unlink()
    lane["head_sha"] = "b" * 40
    assert impact(repo, lane)["reason_codes"] == ["lane_head_mismatch"]


def test_missing_claims_and_version_unknown(setup: tuple) -> None:
    repo, _, lane, _ = setup
    lane["paths"] = []
    assert impact(repo, lane)["reason_codes"] == ["paths_undeclared_or_ambiguous"]
    lane["paths"] = ["src/worker.py"]
    lane["version"] = "1"
    assert impact(repo, lane)["reason_codes"] == ["lane_snapshot_degraded"]


def test_main_diverged_is_unknown(setup: tuple) -> None:
    repo, _, lane, _ = setup
    git(repo, "update-ref", "refs/remotes/origin/main", lane["head_sha"])
    # Now base is still an ancestor; advance to a sibling of the base instead.
    lane["base_main_sha"] = "c" * 40
    assert impact(repo, lane)["reason_codes"] == ["main_diverged_or_missing_history"]


def test_contract_same_key_and_alias(setup: tuple) -> None:
    repo, _, lane, _ = setup
    main = commit(repo, "docs/api.md", "v2\n", "api")
    git(repo, "update-ref", "refs/remotes/origin/main", main)
    lane["contract_changes"] = ["auth_token"]
    peer = {"lane_id": "other", "contract_changes": ["auth_token"]}
    assert impact(repo, lane, peer_lanes=[peer])["reason_codes"] == [
        "contract_same_key_hint"
    ]
    peer["contract_changes"] = ["authToken"]
    assert impact(repo, lane, peer_lanes=[peer])["reason_codes"] == [
        "contract_alias_ambiguous"
    ]


def test_mode_change_symlink_and_binary_unknown(setup: tuple) -> None:
    repo, _, lane, _ = setup
    (repo / "bin").write_bytes(b"\x00\x01\xff")
    git(repo, "add", "bin")
    git(repo, "commit", "-m", "binary")
    git(repo, "update-ref", "refs/remotes/origin/main", git(repo, "rev-parse", "HEAD"))
    assert impact(repo, lane)["reason_codes"] == ["binary_or_numstat_unverifiable"]


def test_case_alias_unknown(setup: tuple) -> None:
    repo, worktree, lane, _ = setup
    git(worktree, "rm", "src/worker.py")
    lane["head_sha"] = commit(worktree, "src/Module.py", "one\n", "case-a")
    lane["paths"] = ["src/Module.py"]
    main = commit(repo, "src/module.py", "two\n", "case-b")
    git(repo, "update-ref", "refs/remotes/origin/main", main)
    assert impact(repo, lane)["reason_codes"] == ["path_alias_ambiguous"]


def test_after_rebase_only_candidate_not_signed_receipt(setup: tuple) -> None:
    repo, worktree, lane, base = setup
    old_head = lane["head_sha"]
    main = commit(repo, "docs/new.md", "new\n", "advance")
    git(repo, "update-ref", "refs/remotes/origin/main", main)
    git(worktree, "rebase", "main")
    new_head = git(worktree, "rev-parse", "HEAD")
    result = assess_rebased_carryover(
        repo, old_base=base, old_head=old_head,
        new_base=main, new_head=new_head,
    )
    assert result["status"] == "carryover_candidate"
    assert result["verify_receipt_issued"] is False
    assert result["requires_new_head_reviewer"] is True


def test_read_only_git_index_and_object_count(setup: tuple) -> None:
    repo, _, lane, _ = setup
    index = repo / ".git" / "index"
    before_index = hashlib.sha256(index.read_bytes()).digest()
    before_objects = git(repo, "count-objects", "-v")
    for _ in range(3):
        assert impact(repo, lane)["status"] == "current"
    assert hashlib.sha256(index.read_bytes()).digest() == before_index
    assert git(repo, "count-objects", "-v") == before_objects


def test_shallow_clone_never_claims_complete_baseline(setup: tuple, tmp_path: Path) -> None:
    repo, _, _, _ = setup
    shallow = tmp_path / "shallow"
    git(repo, "config", "receive.denyCurrentBranch", "ignore")
    subprocess.run(["git", "clone", "--depth", "1", "--branch", "main",
                    "file://" + str(repo), str(shallow)],
                   check=True, capture_output=True)
    assert git(shallow, "rev-parse", "--is-shallow-repository") == "true"
    git(shallow, "update-ref", "refs/remotes/origin/main", git(shallow, "rev-parse", "HEAD"))
    assert probe_main_host(shallow)["source_complete"] is False


def test_git_probe_avoids_bulk_process_environment_read(setup: tuple, monkeypatch) -> None:
    """R9 env ratchet: git --no-optional-locks, no os.environ bulk copy."""
    from llm_loop.introspection import baseline_impact

    repo, _, _, _ = setup
    original_run = subprocess.run
    observed = []

    def spy(*args, **kwargs):
        observed.append(args[0])
        assert "env" not in kwargs
        assert "--no-optional-locks" in args[0]
        return original_run(*args, **kwargs)

    monkeypatch.setattr(baseline_impact.subprocess, "run", spy)
    assert baseline_impact.probe_main_host(repo)["source_complete"] is True
    assert observed
