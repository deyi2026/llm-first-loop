#!/usr/bin/env python3
"""M6 eval replay baseline (DESIGN-20261007-browser-semantic-guard, FR-5c/Q6).

Mechanically replays persisted browser action receipts + diff groundings +
semantic operation cards to produce the three pre-registered baseline metrics:

  1. captures_per_step  - receipt-chain full captures per terminal action
  2. verdict distribution - action status / guard / wait verdicts (era-honest)
  3. diff comparability  - comparable ratio of terminal observed-effect diffs

Report-only (Q6 closed form): no pass/fail gates, no automatic judgment. The
anomalies section lists items for model review; the model decides whether a
lesson is filed. See PROTOCOL.v0.1.md for the frozen metric definitions.

Run:  python3 evals/browser_smc_replay_baseline_v01/replay_baseline.py \
          [--receipts-root DIR] [--diffs-root DIR] [--ops-root DIR] \
          [--out-dir DIR] [--tag TAG]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_SCHEMA = "smc.browser_replay_baseline.v0.1.report"
RECEIPT_SCHEMA = "smc.action_receipt.v0.1"
ANOMALY_CAP = 20

# ---------------------------------------------------------------------------
# corpus loading
# ---------------------------------------------------------------------------


def load_corpus(
    receipts_root: Path, diffs_root: Path, ops_root: Path
) -> dict[str, Any]:
    """Read the persisted replay corpus. Malformed rows are counted, never raise."""
    actions: list[dict[str, Any]] = []
    malformed_receipt_rows = 0
    sessions: set[str] = set()
    if receipts_root.is_dir():
        for receipts_file in sorted(receipts_root.glob("*/*/receipts.jsonl")):
            session = receipts_file.parent.parent.name
            action_hash = receipts_file.parent.name
            rows: list[dict[str, Any]] = []
            for line in receipts_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    malformed_receipt_rows += 1
                    continue
                if isinstance(row, dict) and row.get("schema") == RECEIPT_SCHEMA:
                    rows.append(row)
                else:
                    malformed_receipt_rows += 1
            if rows:
                sessions.add(session)
                actions.append(
                    {"session": session, "action_hash": action_hash, "rows": rows}
                )

    diffs: dict[tuple[str, str], dict[str, Any]] = {}
    malformed_diff_docs = 0
    if diffs_root.is_dir():
        for diff_file in sorted(diffs_root.glob("*.json")):
            try:
                doc = json.loads(diff_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                malformed_diff_docs += 1
                continue
            cd = doc.get("canonical_diff")
            if not isinstance(cd, dict):
                malformed_diff_docs += 1
                continue
            key = (str(cd.get("from_version")), str(cd.get("to_version")))
            diffs[key] = doc

    cards: list[dict[str, Any]] = []
    malformed_cards = 0
    if ops_root.is_dir():
        for card_file in sorted(ops_root.glob("*/*.json")):
            try:
                card = json.loads(card_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                malformed_cards += 1
                continue
            if not isinstance(card, dict):
                malformed_cards += 1
                continue
            cards.append(card)

    return {
        "actions": actions,
        "diffs": diffs,
        "cards": cards,
        "sessions": sorted(sessions),
        "malformed_receipt_rows": malformed_receipt_rows,
        "malformed_diff_docs": malformed_diff_docs,
        "malformed_cards": malformed_cards,
        "sources": {
            "receipts_root": str(receipts_root),
            "diffs_root": str(diffs_root),
            "ops_root": str(ops_root),
        },
    }


# ---------------------------------------------------------------------------
# classification helpers (pure)
# ---------------------------------------------------------------------------


def terminal_row(action: dict[str, Any]) -> dict[str, Any]:
    """Terminal receipt of an action = highest receipt_seq row (append-only store)."""
    return max(action["rows"], key=lambda r: int(r.get("receipt_seq") or 0))


def classify_guard(row: dict[str, Any]) -> str | None:
    """None = guard key absent (pre-FR-1 era or not applicable): counted as
    not_recorded, never folded into a verdict bucket."""
    guard = row.get("guard")
    if not isinstance(guard, dict):
        return None
    verdict = str(guard.get("verdict") or "unknown")
    if verdict == "pass" and guard.get("exempted") is True:
        return "pass_exempted"
    if verdict == "reject" and str(guard.get("reason") or "").startswith("guard_timeout"):
        return "reject_timeout"
    return verdict


def classify_wait(row: dict[str, Any]) -> str | None:
    wait = row.get("wait")
    if not isinstance(wait, dict):
        return None
    return str(wait.get("verdict") or "unknown")


def resolve_diff_ref(diff_ref: Any) -> tuple[str, str] | None:
    """grounding://browser/v0.1/{to}/diff/{from} -> (from, to)."""
    if not isinstance(diff_ref, str) or "/diff/" not in diff_ref:
        return None
    tail = diff_ref.split("/diff/", 1)[1]
    to = diff_ref.split("/v0.1/", 1)[1].split("/diff/", 1)[0] if "/v0.1/" in diff_ref else ""
    if not tail or not to:
        return None
    return tail, to


def diff_outcome(
    row: dict[str, Any], diffs: dict[tuple[str, str], dict[str, Any]]
) -> tuple[str, dict[str, Any] | None]:
    """('not_available'|'doc_missing'|'comparable'|'not_comparable', doc)."""
    pair = resolve_diff_ref((row.get("observed_effects") or {}).get("diff_ref"))
    if pair is None:
        return "not_available", None
    doc = diffs.get(pair)
    if doc is None:
        return "doc_missing", None
    comparable = doc.get("canonical_diff", {}).get("comparable")
    return ("comparable" if comparable is True else "not_comparable"), doc


def receipt_diff_summary_class(row: dict[str, Any]) -> str | None:
    """FR-5b inline summary: comparable True/False/None(unknown section)."""
    summary = (row.get("observed_effects") or {}).get("diff_summary")
    if not isinstance(summary, dict):
        return None
    comparable = summary.get("comparable")
    if comparable is True:
        return "comparable_true"
    if comparable is False:
        return "comparable_false"
    return "comparable_unknown"


def op_card_execution_status(card: dict[str, Any]) -> str:
    content = card.get("content")
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            return "malformed_content"
    if isinstance(content, dict):
        return str(content.get("execution_status") or "unknown")
    return "malformed_content"


# ---------------------------------------------------------------------------
# aggregation (pure)
# ---------------------------------------------------------------------------


def aggregate(corpus: dict[str, Any]) -> dict[str, Any]:
    actions = corpus["actions"]
    diffs = corpus["diffs"]

    status_counts: Counter[str] = Counter()
    rejection_classes: Counter[str] = Counter()
    failure_reasons: Counter[str] = Counter()
    captures_by_status: dict[str, list[int]] = {}
    guard_counts: Counter[str] = Counter()
    guard_not_recorded = 0
    wait_counts: Counter[str] = Counter()
    wait_not_recorded = 0
    diff_outcomes: Counter[str] = Counter()
    not_comparable_reasons: Counter[str] = Counter()
    summary_classes: Counter[str] = Counter()
    summary_not_recorded = 0
    per_session: Counter[str] = Counter()
    failed_actions: list[dict[str, Any]] = []
    not_comparable_list: list[dict[str, Any]] = []

    for action in actions:
        row = terminal_row(action)
        session = action["session"]
        status = str(row.get("status") or "unknown")
        status_counts[status] += 1
        per_session[f"{session}:{status}"] += 1

        captures = (1 if row.get("before_version") else 0) + (
            1 if row.get("after_version") else 0
        )
        captures_by_status.setdefault(status, []).append(captures)

        if status == "rejected":
            reasons = (row.get("completeness") or {}).get("reasons") or []
            rejection_classes[str(reasons[0]) if reasons else "unspecified"] += 1
        if status == "failed":
            reason = ((row.get("retry") or {}).get("reason")) or "unspecified"
            failure_reasons[str(reason.split(":", 1)[0])] += 1
            failed_actions.append(
                {
                    "session": session,
                    "action_id": row.get("action_id"),
                    "verb": row.get("verb"),
                    "completeness_reasons": (row.get("completeness") or {}).get("reasons"),
                    "retry_reason": (row.get("retry") or {}).get("reason"),
                }
            )

        guard_class = classify_guard(row)
        if guard_class is None:
            guard_not_recorded += 1
        else:
            guard_counts[guard_class] += 1

        wait_class = classify_wait(row)
        if wait_class is None:
            wait_not_recorded += 1
        else:
            wait_counts[wait_class] += 1

        outcome, doc = diff_outcome(row, diffs)
        diff_outcomes[outcome] += 1
        if outcome == "not_comparable" and doc is not None:
            cd = doc.get("canonical_diff", {})
            reason = str(cd.get("reason") or "unspecified")
            for part in reason.split(";"):
                if part:
                    not_comparable_reasons[part] += 1
            if len(not_comparable_list) < ANOMALY_CAP:
                not_comparable_list.append(
                    {
                        "session": session,
                        "action_id": row.get("action_id"),
                        "from_version": cd.get("from_version"),
                        "to_version": cd.get("to_version"),
                        "reason": reason,
                    }
                )

        summary_class = receipt_diff_summary_class(row)
        if summary_class is None:
            summary_not_recorded += 1
        else:
            summary_classes[summary_class] += 1

    all_captures = [c for values in captures_by_status.values() for c in values]
    comparable_n = diff_outcomes["comparable"]
    comparable_den = comparable_n + diff_outcomes["not_comparable"]

    return {
        "schema": REPORT_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            **corpus["sources"],
            "sessions": len(corpus["sessions"]),
            "actions": len(actions),
            "receipt_rows": sum(len(a["rows"]) for a in actions),
            "diff_docs": len(diffs),
            "op_cards": len(corpus["cards"]),
            "malformed": {
                "receipt_rows": corpus["malformed_receipt_rows"],
                "diff_docs": corpus["malformed_diff_docs"],
                "op_cards": corpus["malformed_cards"],
            },
        },
        "captures_per_step": {
            "definition": (
                "receipt-chain full captures per terminal action = "
                "(1 if before_version else 0) + (1 if after_version else 0); "
                "model-initiated perceive snapshots are not persisted and are "
                "outside this metric"
            ),
            "n": len(all_captures),
            "mean": round(statistics.fmean(all_captures), 4) if all_captures else None,
            "median": statistics.median(all_captures) if all_captures else None,
            "max": max(all_captures) if all_captures else None,
            "histogram": dict(sorted(Counter(all_captures).items())),
            "by_status": {
                status: {
                    "n": len(values),
                    "mean": round(statistics.fmean(values), 4),
                    "histogram": dict(sorted(Counter(values).items())),
                }
                for status, values in sorted(captures_by_status.items())
            },
        },
        "verdicts": {
            "action_status": dict(sorted(status_counts.items())),
            "per_session_status": dict(sorted(per_session.items())),
            "rejection_classes": dict(sorted(rejection_classes.items())),
            "failure_reasons": dict(sorted(failure_reasons.items())),
            "guard": {
                "recorded": dict(sorted(guard_counts.items())),
                "not_recorded": guard_not_recorded,
                "era_note": (
                    "not_recorded = pre-FR-1 receipts or verbs where the guard is "
                    "not applicable; never read as a zero-reject verdict"
                ),
            },
            "wait": {
                "recorded": dict(sorted(wait_counts.items())),
                "not_recorded": wait_not_recorded,
                "era_note": (
                    "not_recorded = pre-FR-2 receipts; never read as settled"
                ),
            },
        },
        "diff_comparability": {
            "terminal_actions": len(actions),
            "comparable": comparable_n,
            "not_comparable": diff_outcomes["not_comparable"],
            "doc_missing": diff_outcomes["doc_missing"],
            "not_available_no_diff_ref": diff_outcomes["not_available"],
            "ratio": round(comparable_n / comparable_den, 4) if comparable_den else None,
            "not_comparable_reasons": dict(sorted(not_comparable_reasons.items())),
        },
        "receipt_diff_summary": {
            "recorded": dict(sorted(summary_classes.items())),
            "not_recorded": summary_not_recorded,
            "era_note": "not_recorded = pre-FR-5b receipts or feature disabled",
        },
        "semantic_op_cards": {
            "total": len(corpus["cards"]),
            "by_execution_status": dict(
                sorted(Counter(op_card_execution_status(c) for c in corpus["cards"]).items())
            ),
        },
        "anomalies": {
            "policy": (
                "Q6 report-only: items below await model review; no automatic "
                "judgment, no automatic lesson filing"
            ),
            "failed_actions": failed_actions,
            "not_comparable_diffs_capped": not_comparable_list,
        },
    }


# ---------------------------------------------------------------------------
# rendering + main
# ---------------------------------------------------------------------------


def render_markdown(report: dict[str, Any]) -> str:
    src = report["sources"]
    cps = report["captures_per_step"]
    verdicts = report["verdicts"]
    dc = report["diff_comparability"]
    lines: list[str] = []
    add = lines.append
    add("# Browser SMC replay baseline (M6)")
    add("")
    add(f"- schema: `{report['schema']}`  generated: {report['generated_at']}")
    add(
        f"- corpus: {src['actions']} actions / {src['receipt_rows']} receipt rows / "
        f"{src['diff_docs']} diff docs / {src['op_cards']} op cards / "
        f"{src['sessions']} sessions (malformed: {src['malformed']})"
    )
    add("")
    add("## captures per step (receipt-chain only)")
    add("")
    add(
        f"n={cps['n']} mean={cps['mean']} median={cps['median']} max={cps['max']} "
        f"histogram={cps['histogram']}"
    )
    for status, item in cps["by_status"].items():
        add(f"- {status}: n={item['n']} mean={item['mean']} histogram={item['histogram']}")
    add("")
    add("## verdict distribution")
    add("")
    add(f"- action_status: {verdicts['action_status']}")
    add(f"- rejection_classes: {verdicts['rejection_classes']}")
    add(f"- failure_reasons: {verdicts['failure_reasons']}")
    add(
        f"- guard recorded: {verdicts['guard']['recorded']} "
        f"not_recorded={verdicts['guard']['not_recorded']}"
    )
    add(
        f"- wait recorded: {verdicts['wait']['recorded']} "
        f"not_recorded={verdicts['wait']['not_recorded']}"
    )
    add("")
    add("## diff comparability (terminal receipts)")
    add("")
    add(
        f"- comparable={dc['comparable']} not_comparable={dc['not_comparable']} "
        f"doc_missing={dc['doc_missing']} not_available={dc['not_available_no_diff_ref']} "
        f"**ratio={dc['ratio']}**"
    )
    add(f"- not_comparable_reasons: {dc['not_comparable_reasons']}")
    ds = report["receipt_diff_summary"]
    add(
        f"- receipt diff_summary recorded: {ds['recorded']} "
        f"not_recorded={ds['not_recorded']}"
    )
    add("")
    add("## semantic op cards")
    add("")
    add(f"- {report['semantic_op_cards']['by_execution_status']}")
    add("")
    add("## anomalies (Q6 report-only, model review required)")
    add("")
    for item in report["anomalies"]["failed_actions"]:
        add(
            f"- FAILED {item['action_id']} verb={item['verb']} "
            f"reasons={item['completeness_reasons']} retry={item['retry_reason']}"
        )
    for item in report["anomalies"]["not_comparable_diffs_capped"]:
        add(
            f"- NON-COMPARABLE {item['action_id']} "
            f"{item['from_version']} -> {item['to_version']} reason={item['reason']}"
        )
    add("")
    add(f"_policy: {report['anomalies']['policy']}_")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipts-root", type=Path, default=REPO_ROOT / "data" / "browser_action")
    parser.add_argument("--diffs-root", type=Path, default=REPO_ROOT / "data" / "browser_perception" / "diffs")
    parser.add_argument("--ops-root", type=Path, default=REPO_ROOT / "data" / "browser_semantic_operation")
    parser.add_argument("--out-dir", type=Path, default=Path(__file__).resolve().parent / "results")
    parser.add_argument("--tag", default=None, help="artifact name tag (default: UTC timestamp)")
    args = parser.parse_args(argv)

    corpus = load_corpus(args.receipts_root, args.diffs_root, args.ops_root)
    report = aggregate(corpus)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    tag = args.tag or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = args.out_dir / f"baseline_{tag}.json"
    md_path = args.out_dir / f"baseline_{tag}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    (args.out_dir / "latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    print(render_markdown(report))
    print(f"[replay baseline] wrote {json_path}")
    print(f"[replay baseline] wrote {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
