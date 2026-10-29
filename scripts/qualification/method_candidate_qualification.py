"""Method candidate qualification harness: independent review -> durable receipt.

The gap this closes: 1500+ candidate cards carry no independent verdict and no
usage ledger, so nothing distinguishes a card that would help on the next real
task from one that only duplicates an active card. This harness makes the
qualification path reproducible and reviewable instead of a one-off in-session
judgement.

Three stages, deliberately separated:

    pack    read candidate cards -> a self-contained review packet per card
            (card body + freshness/usage facts + the independent verdict rubric)
    verdict parse an independent reviewer's structured verdicts, validate them
            against the schema and the store's own mechanical rules, and emit the
            exact ``method_manage`` calls that would record them
    apply   NOT performed by this script. Writing a qualification receipt needs a
            real episode ref (the store rejects model-invented refs), so the
            parent session — which owns the human turn and therefore the episode —
            performs the writes. This script never writes the store.

Why the split: the store records the *receipt*, not the reasoning. An
independent reviewer produces the reasoning; a session with real provenance
records where and when it happened. Collapsing the two would let a model grade
its own work under a borrowed episode ref.

Usage:
    python3 scripts/qualification/method_candidate_qualification.py pack \
        --methods-dir data/methods --out /tmp/method_qual/packets.json \
        --select-from docs/ASSESS-20260929-p5a-highfreq-triage.md

    python3 scripts/qualification/method_candidate_qualification.py verdict \
        --packets /tmp/method_qual/packets.json \
        --verdicts /tmp/method_qual/verdicts.json \
        --out /tmp/method_qual/calls.json

    # then, from the parent session (which holds the human episode):
    #   method_manage(action="record_qualification", ...)   # per card
    #   method_manage(action="refine", transition=...)       # lifecycle

The held-out write-side guard is consulted before any packet or verdict text is
emitted, because ``note``/``evidence_refs``/``task_type`` are model-reachable
fields that the store checks again on write.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

VERDICT_VALUES = ("pass", "fail", "mixed", "insufficient", "not_evaluated")
TRANSITIONS = ("qualify", "activate", "hold", "invalidate", "retire", "reopen")

# The rubric an independent reviewer must answer. It is stated as questions
# about the card's own claims, never as "is this card good" — a rubric that
# invites a verdict produces a verdict, not evidence.
REVIEW_RUBRIC = {
    "mechanism": (
        "Does the card's stated procedure still match how the workspace actually "
        "behaves today? Name the concrete artifact, tool, or file the claim rests "
        "on, and say whether you could confirm it or only infer it."
    ),
    "task_benefit": (
        "For a concrete task that would trigger this card, would following it "
        "change the outcome or only the narrative? Name the task and the "
        "observable difference. If you cannot name one, say insufficient."
    ),
    "promotion": (
        "pass only if the card adds an increment over an existing active/qualified "
        "card and its procedure is verifiable in the current workspace. fail if the "
        "card is stale or duplicates an active card. mixed or insufficient otherwise."
    ),
    "independence": (
        "Would this verdict survive if the card's author disagreed with it? List the "
        "counter-case you considered and why you rejected it."
    ),
}

# Fields the store's held-out write-side guard checks. Kept explicit so the
# harness never proposes a field the store would reject on write.
GUARDED_FIELDS = ("note", "evidence_refs", "task_type")


def _load_guard():
    try:
        from src.llm_loop.knowledge.heldout_guard import check_text
    except Exception:  # noqa: BLE001 — guard unavailable must not block read-only work
        return None
    return check_text


def _guard_fields(texts: dict[str, Any]) -> dict[str, str]:
    """Check every model-reachable field against the held-out write-side guard."""
    check = _load_guard()
    if check is None:
        return {"status": "unavailable", "reason": "guard_import_failed"}
    worst = {"status": "clean", "reason": "no probe hit", "task_id": ""}
    for key, value in texts.items():
        if key not in GUARDED_FIELDS:
            continue
        payload = " ".join(value) if isinstance(value, list) else str(value)
        result = check(payload)
        if result.get("status") == "blocked":
            return {"status": "blocked", "reason": key, "task_id": result.get("task_id", "")}
        if result.get("status") == "unavailable":
            worst = {"status": "unavailable", "reason": result.get("reason", "")}
    return worst


def _frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        return {}
    out: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line.startswith(" "):
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    return out


def _body(text: str) -> str:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    return match.group(2).strip() if match else text.strip()


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _card_dir(methods_dir: Path, name: str) -> Path | None:
    """Resolve a card by its method name (the author-written slug).

    Triage documents truncate long slugs with an ellipsis, so an exact match is
    not enough: ``resume-active-goal-...skip-reveri…`` must still resolve to
    ``resume-active-goal-from-checkpoint-git-delta-skip-reverification-<id>``.
    Prefix matching is only accepted for a truncated slug — an ambiguous prefix
    must not silently pick one card.
    """
    if not methods_dir.is_dir():
        return None
    exact = methods_dir / name
    if (exact / "METHOD.md").exists():
        return exact
    for child in sorted(methods_dir.iterdir()):
        if not child.is_dir():
            continue
        card = child / "METHOD.md"
        if not card.exists():
            continue
        meta = _frontmatter(card.read_text(encoding="utf-8", errors="replace"))
        if meta.get("name") == name or meta.get("method_id") == name:
            return child
        if child.name == name or child.name.startswith(name + "-"):
            return child
    if name.endswith("…"):
        stem = name.rstrip("…").rstrip("-")
        if len(stem) < 12:
            return None
        hits = [
            child
            for child in sorted(methods_dir.iterdir())
            if child.is_dir() and child.name.startswith(stem)
        ]
        if len(hits) == 1:
            return hits[0]
    return None


def _selected_names(select_from: Path) -> list[str]:
    """Pull card names out of an existing triage document (markdown table cells).

    Only rows whose second cell looks like a method slug are kept. Triage tables
    carry Chinese prose in later columns, and the header row carries a label —
    both would otherwise be mistaken for card names.
    """
    text = select_from.read_text(encoding="utf-8", errors="replace")
    names: list[str] = []
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        candidate = cells[1].strip("` ")
        # table rows carry "name (count/qual)" — keep the slug only
        candidate = re.sub(r"\s*\(.*\)$", "", candidate).strip()
        if not candidate or set(candidate) <= {"-", ":"}:
            continue
        # a slug is ascii kebab-case (optionally truncated with an ellipsis);
        # anything else is a header label or prose
        head = candidate[:-1] if candidate.endswith("…") else candidate
        if not head or not re.fullmatch(r"[A-Za-z0-9_.\-]+", head):
            continue
        if candidate not in names:
            names.append(candidate)
    return names


def cmd_pack(args: argparse.Namespace) -> int:
    methods_dir = Path(args.methods_dir)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    include_status = {s.strip() for s in str(args.include_status).split(",") if s.strip()}

    if args.select_from:
        names = _selected_names(Path(args.select_from))
    else:
        names = []
        for child in sorted(methods_dir.iterdir()):
            card = child / "METHOD.md"
            if not card.exists():
                continue
            meta = _frontmatter(card.read_text(encoding="utf-8", errors="replace"))
            if meta.get("status") == "candidate":
                names.append(meta.get("name") or child.name)

    packets: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for name in names:
        card_dir = _card_dir(methods_dir, name)
        if card_dir is None:
            skipped.append({"name": name, "reason": "card_not_found"})
            continue
        card_path = card_dir / "METHOD.md"
        text = card_path.read_text(encoding="utf-8", errors="replace")
        meta = _frontmatter(text)
        status = meta.get("status", "")
        if status not in include_status:
            skipped.append({"name": name, "reason": f"status={status}"})
            continue
        body = _body(text)
        usage_n = _count_lines(card_dir / "usage.jsonl")
        qual_n = _count_lines(card_dir / "qualification.jsonl")
        packet = {
            "method_ref": f"method:{meta.get('method_id', card_dir.name)}",
            "method_id": meta.get("method_id", card_dir.name),
            "name": meta.get("name", card_dir.name),
            "status": status,
            "description": meta.get("description", ""),
            "source_model": meta.get("source_model", ""),
            "source_episode_refs": meta.get("source_episode_refs", ""),
            "freshness_refs": meta.get("freshness_refs", ""),
            "card_body": body,
            "card_sha256": _sha(text),
            "usage_entries": usage_n,
            "qualification_entries": qual_n,
            "review_questions": REVIEW_RUBRIC,
        }
        guard = _guard_fields({"note": body, "evidence_refs": [], "task_type": ""})
        packet["heldout_guard"] = guard
        if guard.get("status") == "blocked":
            skipped.append({"name": name, "reason": f"heldout_blocked:{guard.get('reason', '')}"})
            continue
        packets.append(packet)

    payload = {
        "generated_by": "scripts/qualification/method_candidate_qualification.py pack",
        "methods_dir": str(methods_dir),
        "select_from": str(args.select_from) if args.select_from else "",
        "packet_count": len(packets),
        "skipped": skipped,
        "packets": packets,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"packet_count": len(packets), "skipped": len(skipped), "out": str(out_path)}, ensure_ascii=False))
    return 0


def _normalise_verdict(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "method_ref": str(raw.get("method_ref", "")).strip(),
        "verdict": str(raw.get("verdict", "not_evaluated")).strip(),
        "mechanism": str(raw.get("mechanism", "not_evaluated")).strip(),
        "task_benefit": str(raw.get("task_benefit", "not_evaluated")).strip(),
        "promotion": str(raw.get("promotion", "not_evaluated")).strip(),
        "task_type": str(raw.get("task_type", "unknown")).strip() or "unknown",
        "note": str(raw.get("note", "")).strip()[:4000],
        "evidence_refs": _as_ref_list(raw.get("evidence_refs")),
        "claims": raw.get("claims") if isinstance(raw.get("claims"), list) else [],
        "counter_case": str(raw.get("counter_case", "")).strip()[:4000],
    }


def _as_ref_list(value: object) -> list[str]:
    """Accept a list, or a bare string, without shredding a string into chars."""
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        items = [value]
    return [str(v).strip() for v in items if str(v).strip()]


def cmd_verdict(args: argparse.Namespace) -> int:
    packets = json.loads(Path(args.packets).read_text(encoding="utf-8"))
    # Review runs in batches (one independent reviewer per small batch keeps each
    # session inside its context window), so several verdict files are the normal
    # case, not an edge case.
    verdict_paths: list[Path] = []
    for raw_arg in str(args.verdicts).split(","):
        candidate = raw_arg.strip()
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_dir():
            verdict_paths.extend(sorted(path.glob("*.json")))
        else:
            verdict_paths.append(path)
    raw_verdicts: list[dict[str, Any]] = []
    for path in verdict_paths:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            loaded = loaded.get("verdicts", [])
        raw_verdicts.extend(loaded)
    by_ref = {p["method_ref"]: p for p in packets.get("packets", [])}

    calls: list[dict[str, Any]] = []
    problems: list[dict[str, str]] = []
    seen_refs: set[str] = set()
    for raw in raw_verdicts:
        v = _normalise_verdict(raw)
        ref = v["method_ref"]
        packet = by_ref.get(ref)
        if packet is None:
            problems.append({"method_ref": ref, "problem": "unknown_method_ref"})
            continue
        if ref in seen_refs:
            problems.append({"method_ref": ref, "problem": "duplicate_verdict_for_ref"})
            continue
        seen_refs.add(ref)
        bad_enum = False
        for key in ("verdict", "mechanism", "task_benefit", "promotion"):
            if v[key] not in VERDICT_VALUES:
                problems.append({"method_ref": ref, "problem": f"{key}={v[key]} not in {VERDICT_VALUES}"})
                bad_enum = True
        if bad_enum:
            # an out-of-vocabulary verdict is not a verdict: it must not reach a
            # durable receipt in any form
            continue
        guard = _guard_fields(
            {"note": v["note"], "evidence_refs": v["evidence_refs"], "task_type": v["task_type"]}
        )
        if guard.get("status") == "blocked":
            problems.append({"method_ref": ref, "problem": f"heldout_blocked:{guard.get('reason', '')}"})
            continue
        if not v["claims"]:
            problems.append({"method_ref": ref, "problem": "no_claims_declared"})
            continue
        # A claim only counts as verified when it is a mapping that says so and
        # actually carries text. Anything else — a bare string, a dict without a
        # status, an empty claim — is unverified, so a sloppy reviewer payload
        # cannot buy a promotion.
        unverified = [
            c
            for c in v["claims"]
            if not (
                isinstance(c, dict)
                and c.get("status") == "verified"
                and str(c.get("claim", "")).strip()
            )
        ]
        if unverified and v["promotion"] == "pass":
            problems.append({"method_ref": ref, "problem": "promotion_pass_with_unverified_claims"})
            continue
        # A promotion recommendation must be internally consistent with the
        # findings it claims to rest on: "nothing was evaluated" cannot promote,
        # and a failing verdict cannot promote either.
        if v["promotion"] == "pass":
            # A qualified verdict is the only verdict that may carry a
            # promotion: "fail", "not_evaluated", and the hedged
            # "mixed"/"insufficient" all mean the reviewer did not reach a
            # clean conclusion, so they must not produce a promotion.
            if v["verdict"] != "pass":
                problems.append({"method_ref": ref, "problem": "promotion_pass_with_contradictory_verdict"})
                continue
            if v["mechanism"] != "pass" or v["task_benefit"] != "pass":
                problems.append({"method_ref": ref, "problem": "promotion_pass_without_pass_findings"})
                continue
        transition = ""
        if v["promotion"] == "pass":
            transition = "qualify"
        elif v["promotion"] == "fail":
            transition = "invalidate"
        calls.append(
            {
                "method_ref": ref,
                "transition": transition,
                "record_qualification": {
                    "action": "record_qualification",
                    "method_ref": ref,
                    "verdict": v["verdict"],
                    "mechanism": v["mechanism"],
                    "task_benefit": v["task_benefit"],
                    "promotion": v["promotion"],
                    "task_type": v["task_type"],
                    "note": v["note"],
                    "evidence_refs": v["evidence_refs"],
                },
                "refine": {"action": "refine", "method_ref": ref, "transition": transition}
                if transition
                else {},
                "reviewer_claims": v["claims"],
                "counter_case": v["counter_case"],
            }
        )

    payload = {
        "generated_by": "scripts/qualification/method_candidate_qualification.py verdict",
        "call_count": len(calls),
        "problems": problems,
        "calls": calls,
        "notes": [
            "These calls are proposals, not writes. The parent session performs them.",
            "promotion=pass requires a real episode ref the store accepts; the "
            "subscriber that runs this script must supply it via the runtime, "
            "never by inventing one.",
            "transition=invalidate is only accepted by the store when an "
            "independent factual basis exists (a prior qualification verdict=fail "
            "or rejected use declarations from >=2 distinct episodes).",
        ],
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"call_count": len(calls), "problems": len(problems), "out": str(out_path)}, ensure_ascii=False))
    return 0 if not problems else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Method candidate qualification harness")
    sub = parser.add_subparsers(dest="stage", required=True)

    p_pack = sub.add_parser("pack", help="build review packets from candidate cards")
    p_pack.add_argument("--methods-dir", default="data/methods")
    p_pack.add_argument("--out", required=True)
    p_pack.add_argument("--select-from", default="", help="markdown triage doc whose table selects cards")
    p_pack.add_argument(
        "--include-status",
        default="candidate,hold",
        help="comma-separated statuses eligible for review (default: candidate,hold)",
    )
    p_pack.set_defaults(func=cmd_pack)

    p_verdict = sub.add_parser("verdict", help="validate independent verdicts into method_manage calls")
    p_verdict.add_argument("--packets", required=True)
    p_verdict.add_argument(
        "--verdicts",
        required=True,
        help="comma-separated verdict JSON files, or a directory of them (one per review batch)",
    )
    p_verdict.add_argument("--out", required=True)
    p_verdict.set_defaults(func=cmd_verdict)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
