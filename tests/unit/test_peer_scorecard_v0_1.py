from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path

from scripts.qualification.peer_scorecard_v0_1 import (
    compute_report,
    main,
    render_comparison,
    validate_contract,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs" / "analysis" / "PEER-SCORECARD-v0.1.json"
CONTRACT_V02 = ROOT / "docs" / "analysis" / "PEER-SCORECARD-v0.2.json"
PROTOCOL = ROOT / "evals" / "peer_scorecard_v0" / "PROTOCOL.v0.1.md"
PROTOCOL_V02 = ROOT / "evals" / "peer_scorecard_v0" / "PROTOCOL.v0.2.md"
V01_SHA256 = "4d63a512647d8c7826ce1cd13b97a6e5a25dd8a5208decf16594b3407b8487b0"


def _contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _errors(contract: dict) -> str:
    return "\n".join(validate_contract(contract, repo_root=ROOT))


def _cell(contract: dict, product: str, dimension_id: str) -> dict:
    return next(
        cell
        for cell in contract["counterparty_cells"]
        if cell["product"] == product and cell["dimension_id"] == dimension_id
    )


def _dimension(contract: dict, dimension_id: str) -> dict:
    return next(dim for dim in contract["dimensions"] if dim["id"] == dimension_id)


def test_frozen_contract_validates_at_the_pinned_subject_commit() -> None:
    contract = _contract()
    assert validate_contract(contract, repo_root=ROOT) == []
    assert contract["schema"] == "peer-scorecard/v0.1"
    assert contract["status"] == "frozen_read_only_contract"
    assert contract["blocking"] is False
    assert contract["aggregate_verdict"] == "not_evaluated"


def test_contract_and_protocol_declare_the_same_subject_anchor() -> None:
    contract = _contract()
    commit = contract["subject_anchor"]["commit"]
    assert contract["subject_anchor"]["resolution"] == "committed_tree"
    # The protocol document must carry the same frozen identity, otherwise the
    # rubric and the measurement can drift apart.
    assert commit in PROTOCOL.read_text(encoding="utf-8")


def test_subject_anchor_is_a_real_commit_and_not_a_branch_name() -> None:
    contract = _contract()
    commit = contract["subject_anchor"]["commit"]
    assert len(commit) == 40
    assert all(char in "0123456789abcdef" for char in commit)
    probe = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "-e", f"{commit}^{{commit}}"],
        capture_output=True,
        check=False,
    )
    assert probe.returncode == 0


def test_every_declared_subject_anchor_resolves_at_the_pinned_commit() -> None:
    report = compute_report(_contract(), repo_root=ROOT)
    assert len(report["dimensions"]) == 6
    for row in report["dimensions"]:
        assert row["anchors_missing"] == [], row["id"]
        assert row["anchors_present"] == row["anchors_total"], row["id"]
        assert row["verified_rung"] is not None, row["id"]
        for counter in row["counter_anchors"]:
            assert counter["status"] in {"open", "closed"}


def test_verified_rung_is_a_lower_bound_and_names_its_unsupported_rung() -> None:
    report = compute_report(_contract(), repo_root=ROOT)
    for row in report["dimensions"]:
        if row["verified_rung"] < 4:
            # A rung that could not be reached must be named rather than implied.
            assert row["rung_unsupported_above"] is not None, row["id"]
        for counter in row["counter_anchors"]:
            if counter["status"] == "open":
                assert row["verified_rung"] < 4, row["id"]


def test_dimension_that_is_not_measurable_in_repo_says_so() -> None:
    report = compute_report(_contract(), repo_root=ROOT)
    unmeasurable = [row["id"] for row in report["dimensions"] if not row["in_repo_measurable"]]
    assert unmeasurable == ["D6_ecosystem_ux"]


def test_no_counterparty_cell_may_carry_a_number_below_the_emission_tier() -> None:
    contract = _contract()
    report = compute_report(contract, repo_root=ROOT)
    for product, dims in report["counterparty_cells"].items():
        for dimension_id, cell in dims.items():
            if cell["status"] == "unknown":
                assert cell["rung_lower_bound"] is None, (product, dimension_id)
                continue
            if cell["evidence_tier"] not in {"V", "T1"}:
                assert cell["rung_lower_bound"] is None, (product, dimension_id)
    assert report["counterparty_coverage"]["cells_eligible_for_a_number"] == 0


def test_counterparty_gaps_are_reported_as_unknown_not_as_a_failing_score() -> None:
    report = compute_report(_contract(), repo_root=ROOT)
    coverage = report["counterparty_coverage"]
    assert coverage["cells_possible"] == 36
    assert coverage["cells_declared"] + coverage["cells_unknown"] == 36


def test_cross_vendor_composite_is_withheld_with_a_reason() -> None:
    report = compute_report(_contract(), repo_root=ROOT)
    assert report["cross_vendor_composite"] == "not_evaluated"
    assert report["cross_vendor_composite_reason"].strip()
    assert report["declared_judgment_cells"] == []


def test_rejects_a_below_tier_cell_that_carries_a_number() -> None:
    # This is the exact defect the protocol exists to prevent: a counterparty
    # figure produced without verbatim, dated, vendor-published evidence.
    contract = copy.deepcopy(_contract())
    cell = _cell(contract, "cursor", "D1_long_horizon_autonomy")
    assert cell["evidence_tier"] == "T2"
    cell["rung_lower_bound"] = 4
    errors = _errors(contract)
    assert "must not carry a number" in errors
    assert "band emission requires one of" in errors


def test_rejects_source_free_cell_that_still_carries_citation_fields() -> None:
    contract = copy.deepcopy(_contract())
    cell = copy.deepcopy(_cell(contract, "cursor", "D1_long_horizon_autonomy"))
    cell["evidence_tier"] = "T4"
    contract["counterparty_cells"].append(cell)
    assert "tier T4 is source-free and must not carry url" in _errors(contract)


def test_rejects_cited_tier_missing_provenance_fields() -> None:
    contract = copy.deepcopy(_contract())
    cell = _cell(contract, "cursor", "D1_long_horizon_autonomy")
    cell.pop("url")
    cell.pop("retrieved_at")
    errors = _errors(contract)
    assert "tier T2 requires non-empty url" in errors
    assert "tier T2 requires non-empty retrieved_at" in errors


def test_rejects_widening_the_band_emission_tier_list() -> None:
    contract = copy.deepcopy(_contract())
    contract["invariants"]["band_requires_tier"] = ["V", "T1", "T2"]
    assert "band_requires_tier must be" in _errors(contract)


def test_rejects_turning_on_the_cross_vendor_composite() -> None:
    contract = copy.deepcopy(_contract())
    contract["invariants"]["cross_vendor_composite"] = "evaluated"
    assert "cross_vendor_composite must be not_evaluated" in _errors(contract)


def test_rejects_cross_tier_aggregation() -> None:
    contract = copy.deepcopy(_contract())
    contract["invariants"]["no_cross_tier_aggregation"] = False
    assert "no_cross_tier_aggregation must be true" in _errors(contract)


def test_rejects_treating_a_rung_as_a_measurement() -> None:
    contract = copy.deepcopy(_contract())
    contract["invariants"]["rung_is_lower_bound_only"] = False
    assert "rung_is_lower_bound_only must be true" in _errors(contract)


def test_rejects_resolving_the_subject_against_the_working_tree() -> None:
    contract = copy.deepcopy(_contract())
    contract["subject_anchor"]["resolution"] = "working_tree"
    assert "subject_anchor.resolution must be committed_tree" in _errors(contract)

    contract = copy.deepcopy(_contract())
    contract["invariants"]["subject_resolution"] = "working_tree"
    assert "invariants.subject_resolution must be committed_tree" in _errors(contract)


def test_rejects_blocking_scorecard_and_global_verdict() -> None:
    contract = copy.deepcopy(_contract())
    contract["blocking"] = True
    assert "blocking must remain false" in _errors(contract)

    contract = copy.deepcopy(_contract())
    contract["aggregate_verdict"] = "PASS"
    assert "aggregate_verdict must be not_evaluated" in _errors(contract)


def test_rejects_anchor_drift() -> None:
    contract = copy.deepcopy(_contract())
    _dimension(contract, "D1_long_horizon_autonomy")["anchors"][0]["anchor"] = "__NO_SUCH_SYMBOL__"
    assert "anchor drift" in _errors(contract)


def test_rejects_a_path_that_exists_only_in_the_working_tree(tmp_path: Path) -> None:
    # An untracked file proves the resolution really is the committed tree.
    repo = tmp_path / "probe-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "tracked.py").write_text("def tracked_symbol():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.py"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=probe@example.invalid",
            "-c",
            "user.name=probe",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-q",
            "-m",
            "probe",
        ],
        cwd=repo,
        check=True,
    )
    (repo / "untracked.py").write_text("def working_tree_only():\n    return 2\n", encoding="utf-8")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    contract = copy.deepcopy(_contract())
    contract["subject_anchor"]["commit"] = commit
    dimension = _dimension(contract, "D1_long_horizon_autonomy")
    dimension["anchors"][0]["path"] = "untracked.py"
    dimension["anchors"][0]["anchor"] = "def working_tree_only"
    errors = "\n".join(validate_contract(contract, repo_root=repo))
    assert "source missing in committed tree: untracked.py" in errors


def test_rejects_non_contiguous_or_non_monotonic_rungs() -> None:
    contract = copy.deepcopy(_contract())
    _dimension(contract, "D1_long_horizon_autonomy")["rungs"][1]["rung"] = 7
    assert "rungs must be contiguous from 0" in _errors(contract)

    contract = copy.deepcopy(_contract())
    rungs = _dimension(contract, "D1_long_horizon_autonomy")["rungs"]
    rungs[2]["requires"] = ["d1.goal_checkpoint"]
    assert "requires must be monotonically inclusive" in _errors(contract)


def test_rejects_rung_referencing_an_undeclared_anchor() -> None:
    contract = copy.deepcopy(_contract())
    _dimension(contract, "D1_long_horizon_autonomy")["rungs"][2]["requires"].append(
        "d1.no_such_anchor"
    )
    assert "unknown requires" in _errors(contract)


def test_rejects_counter_anchor_without_an_absence_claim() -> None:
    contract = copy.deepcopy(_contract())
    counter = _dimension(contract, "D2_concurrency_isolation")["counter_anchors"][0]
    counter.pop("proves_absent")
    assert "counter-anchor must declare proves_absent" in _errors(contract)


def test_rejects_duplicate_anchor_ids_across_dimensions() -> None:
    contract = copy.deepcopy(_contract())
    source = _dimension(contract, "D1_long_horizon_autonomy")["anchors"][0]
    clone = copy.deepcopy(source)
    clone["path"] = "src/llm_loop/core/recent_continuity.py"
    clone["anchor"] = "def latest_model_assistant_before_turn"
    _dimension(contract, "D3_context_recovery")["anchors"].append(clone)
    assert "duplicate anchor id across dimensions" in _errors(contract)


def test_rejects_judgement_cell_that_carries_a_measured_rung() -> None:
    contract = copy.deepcopy(_contract())
    contract["declared_judgment_cells"] = [
        {
            "product": "cursor",
            "judge": "someone",
            "judged_at": "2026-09-16",
            "rationale": "impression",
            "rung_lower_bound": 4,
        }
    ]
    assert "judgement cells must not carry a measured rung_lower_bound" in _errors(contract)


def test_rejects_judgement_cell_without_attribution() -> None:
    contract = copy.deepcopy(_contract())
    contract["declared_judgment_cells"] = [{"product": "cursor", "rung_lower_bound": None}]
    errors = _errors(contract)
    assert "judgement cells require non-empty judge" in errors
    assert "judgement cells require non-empty judged_at" in errors
    assert "judgement cells require non-empty rationale" in errors


def test_cli_exit_codes_separate_drift_from_recorded_unknowns(tmp_path: Path) -> None:
    assert main(["--repo-root", str(ROOT)]) == 0

    drifted = copy.deepcopy(_contract())
    _dimension(drifted, "D1_long_horizon_autonomy")["anchors"][0]["anchor"] = "__NO_SUCH_SYMBOL__"
    path = tmp_path / "drifted.json"
    path.write_text(json.dumps(drifted, ensure_ascii=False), encoding="utf-8")
    assert main(["--repo-root", str(ROOT), "--contract", str(path)]) == 1


def test_report_json_output_is_written_and_reparses(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    assert main(["--repo-root", str(ROOT), "--json-out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["cross_vendor_composite"] == "not_evaluated"
    assert report["subject_anchor"]["resolution"] == "committed_tree"


def test_contract_json_is_canonical_and_deterministic() -> None:
    raw = CONTRACT.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert raw == json.dumps(parsed, ensure_ascii=False, indent=2) + "\n"


def test_protocol_document_is_frozen_and_states_the_non_goals() -> None:
    text = PROTOCOL.read_text(encoding="utf-8")
    assert "This is a new protocol identity." in text
    assert "must not be changed after the first measurement" in text


# --- v0.2: declared-judgement channel and the side-by-side comparison view ---


def _contract_v02() -> dict:
    return json.loads(CONTRACT_V02.read_text(encoding="utf-8"))


def test_v01_contract_is_untouched_by_the_v02_extension() -> None:
    # v0.2 is a new protocol identity, not an edit of v0.1. The frozen v0.1 bytes
    # must still hash exactly as they did when v0.1 was closed.
    digest = hashlib.sha256(CONTRACT.read_bytes()).hexdigest()
    assert digest == V01_SHA256


def test_v02_contract_validates_and_carries_the_full_legacy_table() -> None:
    contract = _contract_v02()
    assert validate_contract(contract, repo_root=ROOT) == []
    assert contract["schema"] == "peer-scorecard/v0.2"
    cells = contract["declared_judgment_cells"]
    assert len(cells) == 42  # 7 subjects x 6 dimensions
    subjects = {cell["subject"] for cell in cells}
    assert subjects == {*contract["products"], "lfl"}
    assert len(contract["legacy_composites"]) == 7


def test_every_judgement_cell_is_attributed_and_scaled() -> None:
    for cell in _contract_v02()["declared_judgment_cells"]:
        assert cell["judge"]
        assert cell["judged_at"]
        assert cell["rationale"]
        assert cell["scale"] == "0-10"
        assert 0.0 <= float(cell["judged_value"]) <= 10.0
        assert "rung_lower_bound" not in cell


def test_published_legacy_composites_reproduce_from_their_own_cells() -> None:
    report = compute_report(_contract_v02(), repo_root=ROOT)
    assert len(report["legacy_composites"]) == 7
    for row in report["legacy_composites"]:
        assert row["cells"] == 6, row["subject"]
        assert row["matches"] is True, row["subject"]
    lfl = next(row for row in report["legacy_composites"] if row["subject"] == "lfl")
    assert lfl["claimed"] == 9.23
    assert lfl["computed"] == 9.2333


def test_comparison_view_keeps_the_three_channels_separate() -> None:
    report = compute_report(_contract_v02(), repo_root=ROOT)
    assert len(report["comparison"]) == 6
    for row in report["comparison"]:
        # channel A: measured lower bound, channel B: recorded opinion, channel C: peers
        assert row["subject_verified_rung"] is not None
        assert row["subject_judged_value"] is not None
        assert len(row["peers"]) == len(_contract_v02()["products"])
        for peer in row["peers"].values():
            assert "judged_value" in peer
            assert "evidence_tier" in peer
        # a merged cross-channel figure must not exist anywhere in the row
        assert "merged" not in row
        assert "composite" not in row


def test_comparison_renderer_labels_every_channel_and_never_averages() -> None:
    rendered = render_comparison(compute_report(_contract_v02(), repo_root=ROOT))
    for product in _contract_v02()["products"]:
        assert product[:10] in rendered
    assert "columns are never averaged together" in rendered
    assert "declared judgement (recorded opinion, tier T4, never merged with A)" in rendered
    assert "all published composites reproduce from their own cells" in rendered
    assert "cross-vendor composite: not_evaluated" in rendered


def test_rejects_a_published_composite_that_does_not_match_its_own_cells() -> None:
    contract = copy.deepcopy(_contract_v02())
    row = next(r for r in contract["legacy_composites"] if r["subject"] == "cursor")
    row["claimed"] = 9.99
    assert "does not match the mean of its judgement cells" in _errors(contract)


def test_rejects_judgement_value_outside_the_declared_scale() -> None:
    contract = copy.deepcopy(_contract_v02())
    contract["declared_judgment_cells"][0]["judged_value"] = 12.5
    assert "is outside the declared scale" in _errors(contract)


def test_rejects_non_numeric_judgement_value() -> None:
    contract = copy.deepcopy(_contract_v02())
    contract["declared_judgment_cells"][0]["judged_value"] = "high"
    assert "judged_value must be a number" in _errors(contract)


def test_rejects_judgement_cell_for_an_unknown_subject_or_dimension() -> None:
    contract = copy.deepcopy(_contract_v02())
    contract["declared_judgment_cells"][0]["subject"] = "some_other_tool"
    contract["declared_judgment_cells"][1]["dimension_id"] = "D99_invented"
    errors = _errors(contract)
    assert "unknown subject 'some_other_tool'" in errors
    assert "unknown dimension_id 'D99_invented'" in errors


def test_rejects_legacy_composite_without_recorded_cells() -> None:
    contract = copy.deepcopy(_contract_v02())
    contract["declared_judgment_cells"] = [
        cell for cell in contract["declared_judgment_cells"] if cell["subject"] != "codex"
    ]
    assert "no judgement cells recorded for 'codex'" in _errors(contract)


def test_unknown_schema_is_rejected() -> None:
    contract = copy.deepcopy(_contract_v02())
    contract["schema"] = "peer-scorecard/v9.9"
    assert "schema must be one of" in _errors(contract)


def test_protocol_v02_is_a_separate_frozen_identity() -> None:
    text = PROTOCOL_V02.read_text(encoding="utf-8")
    assert "This is a new protocol identity." in text
    assert "must not be changed after the first measurement" in text
    assert "does not amend" in text


def test_v02_contract_json_is_canonical_and_deterministic() -> None:
    raw = CONTRACT_V02.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert raw == json.dumps(parsed, ensure_ascii=False, indent=2) + "\n"
