"""Host-owned functional oracle contract; real Docker is tested separately."""

from __future__ import annotations

import hashlib
from pathlib import Path

from llm_loop.assurance.p112_functional_evidence import (
    SUITE,
    _canonical,
    _oracle,
    _validate_candidate,
    frozen_merge_acceptance,
    frozen_merge_acceptance_sha256,
    run_host_functional_review,
    suite_cases,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "assurance_p112_functional"
GOOD = (FIXTURES / "glm53_candidate.txt").read_bytes()
MUTANT = (FIXTURES / "touching_boundary_mutant.txt").read_bytes()
GOOD_SHA = "082802ddc8d73e80fbf0fa2c301740797bf0b97ad589d030ae80f168c6d7db66"
MUTANT_SHA = "53ffa7800bcd8d39f6702dd8b90f75b18e3bb35e677d52e5348ee590348cdb8b"


def test_exact_user_canary_byte_hashes_are_frozen():
    assert hashlib.sha256(GOOD).hexdigest() == GOOD_SHA
    assert hashlib.sha256(MUTANT).hexdigest() == MUTANT_SHA
    assert GOOD.replace(b"if s <= cur_end:", b"if s < cur_end:") == MUTANT


def test_host_oracle_is_deterministic_and_covers_touching_boundary():
    cases = suite_cases()
    assert len(cases) == 311
    assert cases[1] == [[1, 3], [3, 5], [8, 9]]
    assert _oracle(cases[1]) == [[1, 5], [8, 9]]
    assert _oracle([]) == []
    assert _oracle([[2, 2], [2, 2]]) == [[2, 2]]
    assert hashlib.sha256(_canonical(cases)).hexdigest() == (
        "13312ab84bb8ffa2e599e8c83ccfc3252e00eceaf282c8e2221ec048f825c432"
    )


def test_functional_suite_acceptance_is_exact_host_policy():
    assert frozen_merge_acceptance_sha256() == hashlib.sha256(
        _canonical(frozen_merge_acceptance())
    ).hexdigest()
    assert frozen_merge_acceptance_sha256() == (
        "add41adb284d03a41f073b3837306acfb843f929be173e852fb77a98711f648f"
    )


def test_closed_ast_permits_only_synthetic_candidates():
    assert _validate_candidate(GOOD.decode())
    assert _validate_candidate(MUTANT.decode())
    assert not _validate_candidate(
        'import os\ndef merge_closed_intervals(intervals): return []',
    )
    assert not _validate_candidate(
        'def merge_closed_intervals(intervals): return open("/etc/passwd")',
    )
    assert not _validate_candidate(
        "def merge_closed_intervals(intervals): return intervals.__class__",
    )


def test_docker_absence_never_generates_pass_receipt():
    evidence = run_host_functional_review(
        GOOD, expected_sha256=GOOD_SHA, suite=SUITE,
        docker_binary="/nonexistent/does-not-exist",
    )
    assert evidence.verdict == "UNKNOWN"
    assert evidence.guest_receipt_sha256 is None
    assert evidence.may_publish is False


def test_missing_immutable_image_returns_unknown_not_model_pass():
    evidence = run_host_functional_review(
        GOOD, expected_sha256=GOOD_SHA, suite=SUITE,
        image_ref="python@sha256:" + "0" * 64,
    )
    assert evidence.verdict == "UNKNOWN"
    assert evidence.guest_receipt_sha256 is None


def test_mismatch_or_unsupported_suite_returns_unknown():
    for source, sha, suite in (
        (GOOD, MUTANT_SHA, SUITE),
        (GOOD, GOOD_SHA, "not-frozen-v1"),
        (GOOD, GOOD_SHA, SUITE),
    ):
        result = run_host_functional_review(
            source, expected_sha256=sha, suite=suite,
            image_ref="python:latest",
        )
        assert result.verdict == "UNKNOWN"
        assert result.may_dispatch_production_effect is False
