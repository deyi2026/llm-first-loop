"""Qualification harness: the gates must actually block, not merely pass through.

The harness proposes `method_manage` calls; it never writes the store. These
tests pin the parts that keep an unverified card from reaching a durable
receipt: unknown refs, out-of-vocabulary verdicts, promotion=pass without
verified claims, and verdict stage output that carries no reviewer reasoning.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "qualification" / "method_candidate_qualification.py"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

sys.path.insert(0, str(REPO_ROOT / "scripts" / "qualification"))

import method_candidate_qualification as harness  # noqa: E402


def _packet(method_ref: str = "method:demo-card") -> dict:
    return {
        "method_ref": method_ref,
        "method_id": "demo-card",
        "name": "demo-card",
        "status": "candidate",
        "card_body": "body",
        "usage_entries": 0,
        "qualification_entries": 0,
    }


def _verdict(**overrides) -> dict:
    base = {
        "method_ref": "method:demo-card",
        "verdict": "pass",
        "mechanism": "pass",
        "task_benefit": "pass",
        "promotion": "pass",
        "task_type": "demo",
        "note": "checked against the repo",
        "evidence_refs": ["docs/x.md"],
        "claims": [{"claim": "artifact exists", "status": "verified"}],
        "counter_case": "considered stale alternative",
    }
    base.update(overrides)
    return base


def _run_verdict(tmp_path: Path, verdicts: list[dict]) -> tuple[dict, int]:
    packets = tmp_path / "packets.json"
    raw = tmp_path / "verdicts.json"
    out = tmp_path / "calls.json"
    packets.write_text(json.dumps({"packets": [_packet()]}), encoding="utf-8")
    raw.write_text(json.dumps({"verdicts": verdicts}), encoding="utf-8")
    args = harness.main(["verdict", "--packets", str(packets), "--verdicts", str(raw), "--out", str(out)])
    return json.loads(out.read_text(encoding="utf-8")), args


def test_valid_verdict_produces_qualify_call(tmp_path: Path) -> None:
    payload, code = _run_verdict(tmp_path, [_verdict()])
    assert code == 0
    assert payload["problems"] == []
    assert payload["call_count"] == 1
    call = payload["calls"][0]
    assert call["transition"] == "qualify"
    assert call["record_qualification"]["action"] == "record_qualification"
    assert call["refine"]["transition"] == "qualify"


def test_unknown_method_ref_is_rejected(tmp_path: Path) -> None:
    payload, code = _run_verdict(tmp_path, [_verdict(method_ref="method:not-in-packets")])
    assert code == 2
    assert payload["call_count"] == 0
    assert payload["problems"][0]["problem"] == "unknown_method_ref"


def test_out_of_vocabulary_verdict_is_rejected(tmp_path: Path) -> None:
    payload, code = _run_verdict(tmp_path, [_verdict(verdict="excellent")])
    assert code == 2
    assert payload["call_count"] == 0
    assert any("not in" in p["problem"] for p in payload["problems"])


def test_promotion_pass_requires_verified_claims(tmp_path: Path) -> None:
    payload, code = _run_verdict(
        tmp_path, [_verdict(claims=[{"claim": "probably fine", "status": "unverified"}])]
    )
    assert code == 2
    assert payload["call_count"] == 0
    assert payload["problems"][0]["problem"] == "promotion_pass_with_unverified_claims"


def test_verdict_without_claims_is_rejected(tmp_path: Path) -> None:
    payload, code = _run_verdict(tmp_path, [_verdict(claims=[])])
    assert code == 2
    assert payload["call_count"] == 0
    assert payload["problems"][0]["problem"] == "no_claims_declared"


def test_fail_verdict_maps_to_invalidate(tmp_path: Path) -> None:
    payload, code = _run_verdict(
        tmp_path, [_verdict(verdict="fail", mechanism="fail", task_benefit="fail", promotion="fail")]
    )
    assert code == 0
    assert payload["calls"][0]["transition"] == "invalidate"


def test_insufficient_promotion_produces_no_transition(tmp_path: Path) -> None:
    payload, code = _run_verdict(tmp_path, [_verdict(promotion="insufficient")])
    assert code == 0
    call = payload["calls"][0]
    assert call["transition"] == ""
    assert call["refine"] == {}


def test_harness_never_writes_the_store(tmp_path: Path) -> None:
    """The verdict stage is proposal-only: it must not create or modify cards."""
    card_dir = tmp_path / "methods" / "demo-card"
    card_dir.mkdir(parents=True)
    (card_dir / "METHOD.md").write_text(
        "---\nname: demo-card\nstatus: candidate\n---\n\nbody\n", encoding="utf-8"
    )
    packets = tmp_path / "packets.json"
    raw = tmp_path / "verdicts.json"
    out = tmp_path / "calls.json"
    packets.write_text(
        json.dumps({"packets": [{"method_ref": "method:demo-card"}]}), encoding="utf-8"
    )
    raw.write_text(json.dumps({"verdicts": [_verdict()]}), encoding="utf-8")
    harness.main(
        ["verdict", "--packets", str(packets), "--verdicts", str(raw), "--out", str(out)]
    )
    assert not (card_dir / "qualification.jsonl").exists()
    assert "status: candidate" in (card_dir / "METHOD.md").read_text(encoding="utf-8")


def test_selected_names_ignores_header_and_prose_cells(tmp_path: Path) -> None:
    doc = tmp_path / "triage.md"
    doc.write_text(
        "| # | 卡（次数/qual） | 处置建议 |\n"
        "|---|---|---|\n"
        "| 1 | real-card-name (4/0) | 建议保留 |\n"
        "| 2 | truncated-name… (2/0) | 建议独立证据 |\n",
        encoding="utf-8",
    )
    names = harness._selected_names(doc)
    assert names == ["real-card-name", "truncated-name…"]


def test_card_dir_resolves_truncated_slug_uniquely(tmp_path: Path) -> None:
    methods = tmp_path / "methods"
    card = methods / "resume-active-goal-from-checkpoint-git-delta-skip-reverification-82a6c"
    card.mkdir(parents=True)
    (card / "METHOD.md").write_text("---\nname: x\nstatus: candidate\n---\n", encoding="utf-8")
    resolved = harness._card_dir(methods, "resume-active-goal-from-checkpoint-git-delta-skip-reveri…")
    assert resolved is not None
    assert resolved.name.startswith("resume-active-goal-from-checkpoint")


def test_card_dir_refuses_ambiguous_truncated_prefix(tmp_path: Path) -> None:
    methods = tmp_path / "methods"
    for suffix in ("aaa", "bbb"):
        card = methods / f"shared-prefix-name-{suffix}"
        card.mkdir(parents=True)
        (card / "METHOD.md").write_text("---\nname: x\nstatus: candidate\n---\n", encoding="utf-8")
    resolved = harness._card_dir(methods, "shared-prefix-name…")
    assert resolved is None


def test_multiple_verdict_files_are_merged(tmp_path: Path) -> None:
    """Review runs in batches; the harness must accept a directory of verdicts."""
    packets = tmp_path / "packets.json"
    packets.write_text(
        json.dumps(
            {
                "packets": [
                    {"method_ref": "method:a"},
                    {"method_ref": "method:b"},
                ]
            }
        ),
        encoding="utf-8",
    )
    vdir = tmp_path / "verdicts"
    vdir.mkdir()
    (vdir / "01.json").write_text(
        json.dumps({"verdicts": [_verdict(method_ref="method:a")]}), encoding="utf-8"
    )
    (vdir / "02.json").write_text(
        json.dumps({"verdicts": [_verdict(method_ref="method:b")]}), encoding="utf-8"
    )
    out = tmp_path / "calls.json"
    code = harness.main(
        ["verdict", "--packets", str(packets), "--verdicts", str(vdir), "--out", str(out)]
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert code == 0
    assert payload["call_count"] == 2
    assert {c["method_ref"] for c in payload["calls"]} == {"method:a", "method:b"}


def test_duplicate_verdict_for_same_ref_is_rejected(tmp_path: Path) -> None:
    packets = tmp_path / "packets.json"
    packets.write_text(json.dumps({"packets": [{"method_ref": "method:a"}]}), encoding="utf-8")
    vdir = tmp_path / "verdicts"
    vdir.mkdir()
    (vdir / "01.json").write_text(
        json.dumps({"verdicts": [_verdict(method_ref="method:a")]}), encoding="utf-8"
    )
    (vdir / "02.json").write_text(
        json.dumps({"verdicts": [_verdict(method_ref="method:a")]}), encoding="utf-8"
    )
    out = tmp_path / "calls.json"
    code = harness.main(
        ["verdict", "--packets", str(packets), "--verdicts", str(vdir), "--out", str(out)]
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert code == 2
    assert payload["call_count"] == 1
    assert any(p["problem"] == "duplicate_verdict_for_ref" for p in payload["problems"])


def test_string_claims_do_not_count_as_verified(tmp_path: Path) -> None:
    """A reviewer that writes bare strings must not buy a promotion."""
    payload, code = _run_verdict(tmp_path, [_verdict(claims=["probably fine"])])
    assert code == 2
    assert payload["call_count"] == 0
    assert payload["problems"][0]["problem"] == "promotion_pass_with_unverified_claims"


def test_claim_dict_without_status_is_not_verified(tmp_path: Path) -> None:
    payload, code = _run_verdict(
        tmp_path, [_verdict(claims=[{"claim": "no status field"}])]
    )
    assert code == 2
    assert payload["call_count"] == 0
    assert payload["problems"][0]["problem"] == "promotion_pass_with_unverified_claims"


def test_empty_claim_text_is_not_verified(tmp_path: Path) -> None:
    payload, code = _run_verdict(
        tmp_path, [_verdict(claims=[{"claim": "   ", "status": "verified"}])]
    )
    assert code == 2
    assert payload["call_count"] == 0
    assert payload["problems"][0]["problem"] == "promotion_pass_with_unverified_claims"


def test_promotion_pass_rejected_when_verdict_not_evaluated(tmp_path: Path) -> None:
    payload, code = _run_verdict(tmp_path, [_verdict(verdict="not_evaluated")])
    assert code == 2
    assert payload["call_count"] == 0
    assert payload["problems"][0]["problem"] == "promotion_pass_with_contradictory_verdict"


def test_promotion_pass_rejected_when_mechanism_not_pass(tmp_path: Path) -> None:
    payload, code = _run_verdict(tmp_path, [_verdict(mechanism="insufficient")])
    assert code == 2
    assert payload["call_count"] == 0
    assert payload["problems"][0]["problem"] == "promotion_pass_without_pass_findings"


def test_evidence_refs_as_bare_string_is_kept_intact(tmp_path: Path) -> None:
    payload, code = _run_verdict(tmp_path, [_verdict(evidence_refs="docs/x.md")])
    assert code == 0
    assert payload["calls"][0]["record_qualification"]["evidence_refs"] == ["docs/x.md"]


def test_promotion_pass_rejected_when_verdict_mixed(tmp_path: Path) -> None:
    """A hedged verdict must not carry a promotion."""
    payload, code = _run_verdict(tmp_path, [_verdict(verdict="mixed")])
    assert code == 2
    assert payload["call_count"] == 0
    assert payload["problems"][0]["problem"] == "promotion_pass_with_contradictory_verdict"


def test_promotion_pass_rejected_when_verdict_insufficient(tmp_path: Path) -> None:
    payload, code = _run_verdict(tmp_path, [_verdict(verdict="insufficient")])
    assert code == 2
    assert payload["call_count"] == 0
    assert payload["problems"][0]["problem"] == "promotion_pass_with_contradictory_verdict"


def test_promotion_pass_rejected_when_verdict_fail(tmp_path: Path) -> None:
    payload, code = _run_verdict(tmp_path, [_verdict(verdict="fail")])
    assert code == 2
    assert payload["call_count"] == 0
    assert payload["problems"][0]["problem"] == "promotion_pass_with_contradictory_verdict"
