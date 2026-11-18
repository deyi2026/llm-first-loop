"""RULE-AI-28 regression: a grant for another target cannot replay a frozen anchor.

Transferred to the PR #63 sole-writer Lane after CAS ownership handoff.
Tests the exact worktree+command binding without weakening reviewer attestations.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from llm_loop.tools.review_host_admission import (
    HostReviewAdmission,
    _digest,
    _Frozen,
)


def _target(workdir: Path, command: str) -> str:
    return (
        f"full_test:{workdir.resolve(strict=True)}:command:"
        f"{_digest(command.encode('utf-8'))}"
    )


def _valid_policy(host: HostReviewAdmission) -> dict[str, str]:
    """Preserve PR #63's Provider-observed model and policy-digest fail-closed gate."""
    # Synthetic PASS record: the production mint path separately validates
    # the configured reviewer chain. Consume still requires an attested model.
    model = host._reviewer_models[0] if host._reviewer_models else "unit-test-reviewer"
    return {
        "reviewer_model": model,
        "reviewer_observed_model": model,
        "policy_digest": host._policy_digest,
    }


@pytest.mark.parametrize("mismatch", ["worktree", "command"])
def test_unrelated_grant_cannot_replay_other_targets_frozen_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mismatch: str
) -> None:
    """Wrong-target PASS must deny with useful next action, without _target replay."""
    current = tmp_path / "trial"
    other = tmp_path / "old"
    current.mkdir()
    other.mkdir()
    command = "pytest -q"
    old_target = (
        _target(other, command)
        if mismatch == "worktree"
        else _target(current, "pytest tests/unit/test_old.py -q")
    )
    host = HostReviewAdmission()
    host._records["old-review"] = _Frozen(
        "full_test", "author-1", old_target, "old-frozen-sha",
        child_id="old-review", granted=True, state="settled",
        created_at=time.time(), full_test_base="f" * 40, **_valid_policy(host),
    )
    monkeypatch.setattr(host, "_derived_full_test_decision", lambda *_: None)

    def unexpected_replay(*_args: object, **_kwargs: object) -> object:
        pytest.fail("unrelated frozen review base was replayed on another target")

    monkeypatch.setattr(host, "_target", unexpected_replay)
    decision = host.check_shell("author-1", command, str(current))
    assert decision.blocked
    assert "target_mismatch" in decision.reason
    assert "review_admission" in decision.reason
    assert not host._records["old-review"].consumed


def test_exact_target_grant_still_consumes_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Filtering must not break a real same-parent, same-workdir, same-command grant."""
    current = tmp_path / "trial"
    current.mkdir()
    command = "pytest -q"
    target = _target(current, command)
    host = HostReviewAdmission()
    host._records["current-review"] = _Frozen(
        "full_test", "author-1", target, "same-frozen-sha",
        child_id="current-review", granted=True, state="settled",
        created_at=time.time(), full_test_base="a" * 40, **_valid_policy(host),
    )
    seen: list[dict[str, object]] = []

    def matching_target(
        kind: str, workdir: str, cmd: str, *_args: object, **kwargs: object
    ) -> tuple[str, str, str, str, dict[str, str], tuple[()]]:
        assert (kind, workdir, cmd) == ("full_test", str(current), command)
        seen.append(kwargs)
        return ("same-frozen-sha", target, "", "", {}, ())

    monkeypatch.setattr(host, "_target", matching_target)
    first = host.check_shell("author-1", command, str(current))
    assert first.allowed
    assert len(seen) == 1
    assert seen[0]["full_test_base"] == "a" * 40
    assert host._records["current-review"].consumed
    second = host.check_shell("author-1", command, str(current))
    assert second.blocked


def test_other_parent_grant_never_consumed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = tmp_path / "trial"
    current.mkdir()
    command = "pytest -q"
    host = HostReviewAdmission()
    host._records["other-parent"] = _Frozen(
        "full_test", "author-2", _target(current, command), "same-frozen-sha",
        child_id="other-parent", granted=True, state="settled",
        created_at=time.time(), full_test_base="a" * 40, **_valid_policy(host),
    )
    monkeypatch.setattr(host, "_derived_full_test_decision", lambda *_: None)
    decision = host.check_shell("author-1", command, str(current))
    assert decision.blocked
    assert "parent_mismatch" in decision.reason
    assert not host._records["other-parent"].consumed


def test_same_target_changed_material_denied_without_consuming_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A target match is necessary but not sufficient: frozen SHA still governs."""
    current = tmp_path / "trial"
    current.mkdir()
    command = "pytest -q"
    target = _target(current, command)
    host = HostReviewAdmission()
    host._records["current-review"] = _Frozen(
        "full_test", "author-1", target, "original-frozen-sha",
        child_id="current-review", granted=True, state="settled",
        created_at=time.time(), full_test_base="a" * 40, **_valid_policy(host),
    )
    monkeypatch.setattr(
        host, "_target",
        lambda *_args, **_kwargs: (
            "changed-material-sha", target, "", "", {}, ()
        ),
    )
    decision = host.check_shell("author-1", command, str(current))
    assert decision.blocked
    assert not host._records["current-review"].consumed


def test_missing_full_test_workdir_is_reported_without_replaying_grants(
    tmp_path: Path
) -> None:
    host = HostReviewAdmission()
    missing = tmp_path / "not-a-worktree"
    decision = host.check_shell("author-1", "pytest -q", str(missing))
    assert decision.blocked
    assert "full_test_workdir_invalid" in decision.reason
