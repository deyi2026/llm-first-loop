#!/usr/bin/env python3
"""Verify the frozen Peer Scorecard v0.1 contract against a pinned commit.

This runner is deliberately read-only and non-blocking. It does:

- resolve every subject anchor against the **committed tree** of the pinned commit
  (never the working tree, so a dirty checkout cannot silently change the result);
- compute a verified evidence rung per dimension as the highest declared rung whose
  required anchors are all present and whose forbidden counter-anchors are all absent;
- inventory counterparty claims with their evidence tier, and refuse to emit a number
  for any cell below the declared band-emission tier;
- refuse the cross-tier composite by construction.

A non-zero exit means the frozen contract no longer matches the checkout being
inspected. It does **not** decide whether any product is better, or what to build next.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_SCHEMA = "peer-scorecard/v0.1"
_TIERS = ("V", "T1", "T2", "T3", "T4")
_BAND_TIERS = ("V", "T1")
_REQUIRED_CELL_FIELDS = ("url", "retrieved_at", "claim")
_SCHEMAS = ("peer-scorecard/v0.1", "peer-scorecard/v0.2")
_LEGACY_COMPOSITE_TOLERANCE = 0.005


def _run_git(repo_root: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout


def _tree_has_path(repo_root: Path, commit: str, path: str) -> bool:
    """True when ``commit:path`` exists in the committed tree (blob or tree)."""
    code, _ = _run_git(repo_root, "cat-file", "-e", f"{commit}:{path}")
    return code == 0


def _tree_read_path(repo_root: Path, commit: str, path: str) -> str | None:
    code, out = _run_git(repo_root, "show", f"{commit}:{path}")
    if code != 0:
        return None
    return out


def _is_relative(path: Any) -> bool:
    return isinstance(path, str) and bool(path) and not Path(path).is_absolute()


def _validate_anchor(
    anchor: Any,
    *,
    repo_root: Path,
    commit: str,
    label: str,
    errors: list[str],
) -> str | None:
    if not isinstance(anchor, dict):
        errors.append(f"{label}: anchor must be an object")
        return None
    anchor_id = anchor.get("id")
    if not isinstance(anchor_id, str) or not anchor_id:
        errors.append(f"{label}: anchor id must be a non-empty string")
        return None
    path = anchor.get("path")
    if not _is_relative(path):
        errors.append(f"{label} [{anchor_id}]: invalid relative path")
        return anchor_id
    text = _tree_read_path(repo_root, commit, path)
    if text is None:
        errors.append(f"{label} [{anchor_id}]: source missing in committed tree: {path}")
        return anchor_id
    needle = anchor.get("anchor")
    if not isinstance(needle, str) or not needle:
        errors.append(f"{label} [{anchor_id}]: missing anchor string")
        return anchor_id
    if needle not in text:
        errors.append(f"{label} [{anchor_id}]: anchor drift: {path}: {needle}")
    return anchor_id


def _validate_counter_anchor(
    anchor: Any,
    *,
    repo_root: Path,
    commit: str,
    label: str,
    errors: list[str],
) -> str | None:
    if not isinstance(anchor, dict):
        errors.append(f"{label}: counter-anchor must be an object")
        return None
    anchor_id = anchor.get("id")
    if not isinstance(anchor_id, str) or not anchor_id:
        errors.append(f"{label}: counter-anchor id must be a non-empty string")
        return None
    path = anchor.get("path")
    if not _is_relative(path):
        errors.append(f"{label} [{anchor_id}]: invalid relative path")
    if not anchor.get("proves_absent"):
        errors.append(f"{label} [{anchor_id}]: counter-anchor must declare proves_absent")
    return anchor_id


def _validate_cell(
    cell: Any,
    *,
    products: set[str],
    dimension_rungs: dict[str, set[int]],
    label: str,
    errors: list[str],
) -> None:
    if not isinstance(cell, dict):
        errors.append(f"{label}: cell must be an object")
        return
    product = cell.get("product")
    if product not in products:
        errors.append(f"{label}: unknown product {product!r}")
    dimension_id = cell.get("dimension_id")
    if dimension_id not in dimension_rungs:
        errors.append(f"{label}: unknown dimension_id {dimension_id!r}")
    tier = cell.get("evidence_tier")
    if tier not in _TIERS:
        errors.append(f"{label}: evidence_tier must be one of {_TIERS}, got {tier!r}")
        return

    rung = cell.get("rung_lower_bound")
    has_number = rung is not None
    if has_number and not isinstance(rung, int):
        errors.append(f"{label}: rung_lower_bound must be an integer or null")
        return

    if tier == "T4":
        # T4 is source-free by definition: it must carry neither a citation nor a number.
        if has_number:
            errors.append(
                f"{label}: tier T4 must not carry a number "
                f"(band emission requires one of {_BAND_TIERS})"
            )
        for field in _REQUIRED_CELL_FIELDS:
            value = cell.get(field)
            if isinstance(value, str) and value:
                errors.append(f"{label}: tier T4 is source-free and must not carry {field}")
        return

    # Every cited tier must carry complete provenance, not just the band-eligible ones.
    for field in _REQUIRED_CELL_FIELDS:
        value = cell.get(field)
        if not isinstance(value, str) or not value:
            errors.append(f"{label}: tier {tier} requires non-empty {field}")

    if has_number:
        if tier not in _BAND_TIERS:
            errors.append(
                f"{label}: tier {tier} must not carry a number "
                f"(band emission requires one of {_BAND_TIERS})"
            )
        elif dimension_id in dimension_rungs and rung not in dimension_rungs[dimension_id]:
            errors.append(f"{label}: rung_lower_bound {rung} is not a declared rung")


def validate_contract(contract: Any, *, repo_root: Path) -> list[str]:
    """Return deterministic contract errors. Never mutates source or runtime state."""
    errors: list[str] = []
    if not isinstance(contract, dict):
        return ["contract must be a JSON object"]

    if contract.get("schema") not in _SCHEMAS:
        errors.append(f"schema must be one of {_SCHEMAS}")
    if contract.get("status") != "frozen_read_only_contract":
        errors.append("status must be frozen_read_only_contract")
    if contract.get("blocking") is not False:
        errors.append("blocking must remain false")
    if contract.get("aggregate_verdict") != "not_evaluated":
        errors.append("aggregate_verdict must be not_evaluated")

    subject = contract.get("subject_anchor")
    if not isinstance(subject, dict):
        errors.append("subject_anchor must be an object")
        subject = {}
    commit = subject.get("commit")
    if not isinstance(commit, str) or len(commit) != 40:
        errors.append("subject_anchor.commit must be a full 40-hex commit id")
        commit = ""
    if subject.get("resolution") != "committed_tree":
        errors.append("subject_anchor.resolution must be committed_tree")
    if commit:
        code, _ = _run_git(repo_root, "cat-file", "-e", f"{commit}^{{commit}}")
        if code != 0:
            errors.append(f"subject_anchor.commit is not a commit in this repository: {commit}")

    tiers = contract.get("evidence_tiers")
    if not isinstance(tiers, dict) or set(tiers) != set(_TIERS):
        errors.append(f"evidence_tiers must declare exactly {_TIERS}")

    invariants = contract.get("invariants")
    if not isinstance(invariants, dict):
        errors.append("invariants must be an object")
        invariants = {}
    if invariants.get("subject_resolution") != "committed_tree":
        errors.append("invariants.subject_resolution must be committed_tree")
    if list(invariants.get("band_requires_tier", [])) != list(_BAND_TIERS):
        errors.append(f"invariants.band_requires_tier must be {list(_BAND_TIERS)}")
    if invariants.get("cross_vendor_composite") != "not_evaluated":
        errors.append("invariants.cross_vendor_composite must be not_evaluated")
    if invariants.get("no_cross_tier_aggregation") is not True:
        errors.append("invariants.no_cross_tier_aggregation must be true")
    if invariants.get("rung_is_lower_bound_only") is not True:
        errors.append("invariants.rung_is_lower_bound_only must be true")
    if invariants.get("counterparty_cells_without_source_are_unknown") is not True:
        errors.append("invariants.counterparty_cells_without_source_are_unknown must be true")

    products = contract.get("products")
    if not isinstance(products, list) or not products:
        errors.append("products must be a non-empty list")
        products = []
    product_set = {p for p in products if isinstance(p, str)}

    dimensions = contract.get("dimensions")
    if not isinstance(dimensions, list) or not dimensions:
        errors.append("dimensions must be a non-empty list")
        dimensions = []

    anchor_ids: list[str] = []
    dimension_ids: list[str] = []
    dimension_rungs: dict[str, set[int]] = {}
    for dim in dimensions:
        if not isinstance(dim, dict):
            errors.append("dimension must be an object")
            continue
        dim_id = dim.get("id")
        if not isinstance(dim_id, str) or not dim_id:
            errors.append("dimension id must be a non-empty string")
            continue
        if dim_id in dimension_ids:
            errors.append(f"duplicate dimension id: {dim_id}")
        dimension_ids.append(dim_id)
        label = f"dimension {dim_id}"

        anchors = dim.get("anchors")
        if not isinstance(anchors, list) or not anchors:
            errors.append(f"{label}: anchors must be a non-empty list")
            anchors = []
        local_anchor_ids: list[str] = []
        for anchor in anchors:
            anchor_id = _validate_anchor(
                anchor,
                repo_root=repo_root,
                commit=commit,
                label=label,
                errors=errors,
            )
            if anchor_id is None:
                continue
            if anchor_id in anchor_ids:
                errors.append(f"{label}: duplicate anchor id across dimensions: {anchor_id}")
            anchor_ids.append(anchor_id)
            local_anchor_ids.append(anchor_id)

        counters = dim.get("counter_anchors") or []
        if not isinstance(counters, list):
            errors.append(f"{label}: counter_anchors must be a list")
            counters = []
        local_counter_ids: list[str] = []
        for anchor in counters:
            anchor_id = _validate_counter_anchor(
                anchor,
                repo_root=repo_root,
                commit=commit,
                label=label,
                errors=errors,
            )
            if anchor_id is None:
                continue
            if anchor_id in anchor_ids:
                errors.append(f"{label}: duplicate anchor id across dimensions: {anchor_id}")
            anchor_ids.append(anchor_id)
            local_counter_ids.append(anchor_id)

        rungs = dim.get("rungs")
        if not isinstance(rungs, list) or not rungs:
            errors.append(f"{label}: rungs must be a non-empty list")
            continue
        numbers = [r.get("rung") if isinstance(r, dict) else None for r in rungs]
        if numbers != list(range(len(rungs))):
            errors.append(f"{label}: rungs must be contiguous from 0, got {numbers}")
        dimension_rungs[dim_id] = {n for n in numbers if isinstance(n, int)}
        previous: set[str] = set()
        for rung in rungs:
            if not isinstance(rung, dict):
                errors.append(f"{label}: rung must be an object")
                continue
            number = rung.get("rung")
            requires = rung.get("requires")
            forbids = rung.get("forbids")
            if not isinstance(requires, list) or not isinstance(forbids, list):
                errors.append(f"{label} rung {number}: requires/forbids must be lists")
                continue
            unknown_requires = [r for r in requires if r not in local_anchor_ids]
            if unknown_requires:
                errors.append(f"{label} rung {number}: unknown requires {unknown_requires}")
            unknown_forbids = [f for f in forbids if f not in local_counter_ids]
            if unknown_forbids:
                errors.append(f"{label} rung {number}: unknown forbids {unknown_forbids}")
            if not previous.issubset(set(requires)):
                errors.append(f"{label} rung {number}: requires must be monotonically inclusive")
            previous = set(requires)

    for index, cell in enumerate(contract.get("counterparty_cells") or []):
        _validate_cell(
            cell,
            products=product_set,
            dimension_rungs=dimension_rungs,
            label=f"counterparty_cells[{index}]",
            errors=errors,
        )

    allowed_judgement_subjects = product_set | {subject.get("subject")}
    judgement_values: dict[str, list[float]] = {}
    for index, cell in enumerate(contract.get("declared_judgment_cells") or []):
        label = f"declared_judgment_cells[{index}]"
        if not isinstance(cell, dict):
            errors.append(f"{label}: cell must be an object")
            continue
        for field in ("subject", "dimension_id", "scale", "judge", "judged_at", "rationale"):
            value = cell.get(field)
            if not isinstance(value, str) or not value:
                errors.append(f"{label}: judgement cells require non-empty {field}")
        if cell.get("subject") not in allowed_judgement_subjects:
            errors.append(f"{label}: unknown subject {cell.get('subject')!r}")
        if cell.get("dimension_id") not in dimension_rungs:
            errors.append(f"{label}: unknown dimension_id {cell.get('dimension_id')!r}")
        judged = cell.get("judged_value")
        if isinstance(judged, bool) or not isinstance(judged, (int, float)):
            errors.append(f"{label}: judged_value must be a number")
        else:
            if cell.get("scale") == "0-10" and not 0.0 <= float(judged) <= 10.0:
                errors.append(f"{label}: judged_value {judged} is outside the declared scale")
            judgement_values.setdefault(str(cell.get("subject")), []).append(float(judged))
        if "rung_lower_bound" in cell:
            errors.append(f"{label}: judgement cells must not carry a measured rung_lower_bound")

    for index, row in enumerate(contract.get("legacy_composites") or []):
        label = f"legacy_composites[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{label}: row must be an object")
            continue
        row_subject = row.get("subject")
        claimed = row.get("claimed")
        if isinstance(claimed, bool) or not isinstance(claimed, (int, float)):
            errors.append(f"{label}: claimed must be a number")
            continue
        values = judgement_values.get(str(row_subject), [])
        if not values:
            errors.append(f"{label}: no judgement cells recorded for {row_subject!r}")
            continue
        mean = sum(values) / len(values)
        if abs(mean - float(claimed)) > _LEGACY_COMPOSITE_TOLERANCE:
            errors.append(
                f"{label}: claimed composite {claimed} does not match the mean of its "
                f"judgement cells ({mean:.4f})"
            )

    return errors


def compute_report(contract: dict[str, Any], *, repo_root: Path) -> dict[str, Any]:
    """Compute the read-only report. Assumes the contract already validated."""
    subject = contract["subject_anchor"]
    commit = subject["commit"]

    dimension_rows: list[dict[str, Any]] = []
    for dim in contract["dimensions"]:
        anchors = dim["anchors"]
        present: list[str] = []
        missing: list[str] = []
        for anchor in anchors:
            text = _tree_read_path(repo_root, commit, anchor["path"])
            if text is not None and anchor["anchor"] in text:
                present.append(anchor["id"])
            else:
                missing.append(anchor["id"])

        counters: list[dict[str, Any]] = []
        for counter in dim.get("counter_anchors") or []:
            exists = _tree_has_path(repo_root, commit, counter["path"])
            counters.append(
                {
                    "id": counter["id"],
                    "path": counter["path"],
                    "status": "closed" if exists else "open",
                }
            )

        open_counter_ids = {c["id"] for c in counters if c["status"] == "open"}
        present_set = set(present)

        verified_rung: int | None = None
        unsupported_above: int | None = None
        for rung in dim["rungs"]:
            requires_ok = set(rung["requires"]).issubset(present_set)
            forbids_ok = not (set(rung["forbids"]) & open_counter_ids)
            if requires_ok and forbids_ok:
                verified_rung = rung["rung"]
            elif unsupported_above is None:
                unsupported_above = rung["rung"]
                break

        dimension_rows.append(
            {
                "id": dim["id"],
                "name": dim["name"],
                "in_repo_measurable": dim.get("in_repo_measurable", True),
                "evidence_tier": "V",
                "anchors_total": len(anchors),
                "anchors_present": len(present),
                "anchors_missing": missing,
                "verified_rung": verified_rung,
                "rung_unsupported_above": unsupported_above,
                "counter_anchors": counters,
            }
        )

    cells = contract.get("counterparty_cells") or []
    by_cell: dict[str, dict[str, Any]] = {}
    tier_histogram: dict[str, int] = dict.fromkeys(_TIERS, 0)
    for cell in cells:
        key = f"{cell['product']}::{cell['dimension_id']}"
        by_cell[key] = {
            "status": "declared",
            "evidence_tier": cell["evidence_tier"],
            "url": cell.get("url"),
            "retrieved_at": cell.get("retrieved_at"),
            "rung_lower_bound": cell.get("rung_lower_bound"),
        }
        tier_histogram[cell["evidence_tier"]] += 1

    product_rows: dict[str, dict[str, Any]] = {}
    for product in contract["products"]:
        product_rows[product] = {}
        for dim in contract["dimensions"]:
            key = f"{product}::{dim['id']}"
            product_rows[product][dim["id"]] = by_cell.get(
                key,
                {
                    "status": "unknown",
                    "evidence_tier": None,
                    "url": None,
                    "retrieved_at": None,
                    "rung_lower_bound": None,
                },
            )

    possible_cells = len(contract["products"]) * len(contract["dimensions"])
    unknown_cells = possible_cells - len(by_cell)

    judgement: dict[str, dict[str, float]] = {}
    for cell in contract.get("declared_judgment_cells") or []:
        judgement.setdefault(str(cell["subject"]), {})[str(cell["dimension_id"])] = float(
            cell["judged_value"]
        )

    legacy_rows: list[dict[str, Any]] = []
    for row in contract.get("legacy_composites") or []:
        row_subject = str(row["subject"])
        values = list(judgement.get(row_subject, {}).values())
        mean = sum(values) / len(values) if values else None
        legacy_rows.append(
            {
                "subject": row_subject,
                "claimed": float(row["claimed"]),
                "computed": None if mean is None else round(mean, 4),
                "matches": None if mean is None else abs(mean - float(row["claimed"])) <= 0.005,
                "cells": len(values),
            }
        )

    comparison_rows: list[dict[str, Any]] = []
    for row in dimension_rows:
        dim_id = row["id"]
        peers: dict[str, dict[str, Any]] = {}
        for product in contract["products"]:
            cell = product_rows[product][dim_id]
            peers[product] = {
                "judged_value": judgement.get(product, {}).get(dim_id),
                "evidence_tier": cell["evidence_tier"],
                "status": cell["status"],
            }
        comparison_rows.append(
            {
                "dimension_id": dim_id,
                "subject_judged_value": judgement.get(subject["subject"], {}).get(dim_id),
                "subject_verified_rung": row["verified_rung"],
                "in_repo_measurable": row["in_repo_measurable"],
                "peers": peers,
            }
        )

    return {
        "schema": contract["schema"],
        "subject_anchor": {
            "subject": subject["subject"],
            "commit": commit,
            "commit_date": subject.get("commit_date"),
            "branch": subject.get("branch"),
            "resolution": subject["resolution"],
            "worktree_dirty_count_at_freeze": subject.get("worktree_dirty_count_at_freeze"),
        },
        "dimensions": dimension_rows,
        "counterparty_cells": product_rows,
        "counterparty_coverage": {
            "cells_possible": possible_cells,
            "cells_declared": len(by_cell),
            "cells_unknown": unknown_cells,
            "tier_histogram": tier_histogram,
            "cells_eligible_for_a_number": tier_histogram["V"] + tier_histogram["T1"],
        },
        "declared_judgment_cells": contract.get("declared_judgment_cells") or [],
        "legacy_composites": legacy_rows,
        "comparison": comparison_rows,
        "comparison_policy": contract.get(
            "comparison_view",
            {
                "merge_policy": "columns are rendered side by side and never averaged together",
            },
        ),
        "cross_vendor_composite": "not_evaluated",
        "cross_vendor_composite_reason": (
            "The subject column is verified against a pinned commit (tier V) while every "
            "counterparty column is below the band-emission tier (T1). No vendor-symmetric "
            "verbatim evidence was collected, and one dimension is not measurable from this "
            "repository at all. Averaging across these tiers is refused by contract."
        ),
    }


def render_comparison(report: dict[str, Any]) -> str:
    """Side-by-side view. Columns are never merged into one number."""
    products = sorted({p for row in report["comparison"] for p in row["peers"]})
    lines: list[str] = []
    lines.append("comparison (columns are never averaged together)")
    lines.append("")

    header = f"{'dimension':30} {'jdg':>5} {'rung':>5}  "
    header += " ".join(f"{p[:10]:>11}" for p in products)
    lines.append(header)
    lines.append(f"{'':30} {'B':>5} {'A':>5}  " + " ".join(f"{'C':>11}" for _ in products))

    for row in report["comparison"]:
        judged = "-" if row["subject_judged_value"] is None else f"{row['subject_judged_value']:g}"
        rung = "-" if row["subject_verified_rung"] is None else str(row["subject_verified_rung"])
        cells: list[str] = []
        for product in products:
            peer = row["peers"][product]
            value = "-" if peer["judged_value"] is None else f"{peer['judged_value']:g}"
            tier = peer["evidence_tier"] or "--"
            cells.append(f"{value}/{tier}".rjust(11))
        label = row["dimension_id"]
        if not row["in_repo_measurable"]:
            label += "*"
        lines.append(f"{label:30} {judged:>5} {rung:>5}  " + " ".join(cells))

    lines.append("")
    lines.append("A = subject measured rung (tier V, committed-tree verified, lower bound)")
    lines.append("B = declared judgement (recorded opinion, tier T4, never merged with A)")
    lines.append(
        "C = 'legacy_judgement/evidence_tier'; '--' means no retrieved evidence for that cell"
    )
    lines.append("* = dimension is not measurable from this repository")
    lines.append("")

    mismatched = [row for row in report["legacy_composites"] if row["matches"] is False]
    lines.append("legacy composite arithmetic:")
    for row in report["legacy_composites"]:
        mark = "ok" if row["matches"] else "MISMATCH"
        lines.append(
            f"  {row['subject']:14} claimed {row['claimed']:>5.2f}  "
            f"computed {row['computed']:>7.4f}  cells {row['cells']:>2}  {mark}"
        )
    if not mismatched:
        lines.append("  (all published composites reproduce from their own cells)")
    cells_possible = report["counterparty_coverage"]["cells_possible"]
    evidenced = report["counterparty_coverage"]["cells_declared"]
    lines.append("")
    lines.append(
        f"evidence backing the legacy table: {evidenced}/{cells_possible} cells carry any "
        "retrieved source; 0 cells reach the verbatim tier required to emit a number."
    )
    lines.append(f"cross-vendor composite: {report['cross_vendor_composite']}")
    return "\n".join(lines)


def render_summary(report: dict[str, Any]) -> str:
    lines: list[str] = []
    anchor = report["subject_anchor"]
    lines.append(
        f"subject   : {anchor['subject']} @ {anchor['commit'][:12]} ({anchor['commit_date']})"
    )
    lines.append(f"resolution: {anchor['resolution']} (working tree is not read)")
    lines.append("")
    lines.append(f"{'dimension':34} {'rung':>4} {'unsup':>5} {'anchors':>8}  counters")
    for row in report["dimensions"]:
        rung = "-" if row["verified_rung"] is None else str(row["verified_rung"])
        unsup = "-" if row["rung_unsupported_above"] is None else str(row["rung_unsupported_above"])
        counters = ",".join(
            f"{c['id'].split('.')[-1]}={c['status']}" for c in row["counter_anchors"]
        )
        lines.append(
            f"{row['id']:34} {rung:>4} {unsup:>5} "
            f"{row['anchors_present']:>3}/{row['anchors_total']:<4}  {counters or '-'}"
        )
        if row["in_repo_measurable"] is False:
            lines.append(f"{'':34} (not measurable from this repository)")
    coverage = report["counterparty_coverage"]
    lines.append("")
    lines.append(
        "counterparty cells: "
        f"{coverage['cells_declared']}/{coverage['cells_possible']} declared, "
        f"{coverage['cells_unknown']} unknown, "
        f"eligible for a number: {coverage['cells_eligible_for_a_number']}"
    )
    lines.append(f"tier histogram    : {coverage['tier_histogram']}")
    lines.append(f"cross-vendor composite: {report['cross_vendor_composite']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        default="docs/analysis/PEER-SCORECARD-v0.1.json",
        help="path to the frozen contract, relative to the repository root",
    )
    parser.add_argument("--repo-root", default=".", help="repository root")
    parser.add_argument("--json-out", default=None, help="write the full report JSON here")
    parser.add_argument(
        "--no-comparison",
        action="store_true",
        help="suppress the side-by-side comparison view",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    contract_path = Path(args.contract)
    if not contract_path.is_absolute():
        contract_path = repo_root / contract_path
    if not contract_path.is_file():
        print(f"contract missing: {contract_path}", file=sys.stderr)
        return 2

    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    errors = validate_contract(contract, repo_root=repo_root)
    if errors:
        print("contract/provenance violations:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    report = compute_report(contract, repo_root=repo_root)
    print(render_summary(report))
    if not args.no_comparison:
        print()
        print(render_comparison(report))
    if args.json_out:
        out = Path(args.json_out)
        if not out.is_absolute():
            out = repo_root / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nreport written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
