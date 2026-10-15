#!/usr/bin/env python3
"""经验卡晋升空窗与 record_use 账本失真审计（只读）。

不写任何经验卡 / usage 账本 / producer。唯一输出是本目录下的 JSON+MD。
权威口径：llm_loop.experiences.document.ExperienceDocument.from_md（代码解析器），
不用正则扫描 front matter——正则在本审计第一轮产生过假阴性（125 张被误判无 front matter）。
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from llm_loop.experiences.document import ExperienceDocument  # noqa: E402
from llm_loop.experiences.store import ExperienceStore  # noqa: E402
from llm_loop.methods.store import MethodStore  # noqa: E402

EXP_DIR = ROOT / "experiences"
METHOD_DIR = ROOT / "data" / "methods"
EXP_LEDGER = EXP_DIR / "usage.jsonl"
METHOD_LEDGER = METHOD_DIR / "usage.jsonl"


def load_cards() -> dict:
    """权威口径解析；同时记录 verification_state 是显式标注还是默认值回填。"""
    cards = {}
    parse_errors = []
    for p in sorted(EXP_DIR.glob("*.md")):
        raw = p.read_text(encoding="utf-8", errors="replace")
        try:
            doc = ExperienceDocument.from_md(raw)
        except Exception as exc:  # noqa: BLE001
            parse_errors.append({"file": p.name, "error": f"{type(exc).__name__}: {exc}"[:120]})
            continue
        m = re.match(r"\s*---\s*\n(.*?)\n---", raw, re.S)
        fm = m.group(1) if m else ""
        cards[p.stem] = {
            "verification_state": doc.verification_state,
            "vs_explicit": bool(re.search(r"^verification_state:", fm, re.M)),
            "record_kind": doc.record_kind,
            "status": doc.status,
            "has_evidence": bool(doc.evidence.strip()),
            "promoted_to_rule": doc.promoted_to_rule.strip(),
            "last_verified_at": doc.last_verified_at.strip(),
        }
    return {"cards": cards, "parse_errors": parse_errors}


def audit_cards(cards: dict) -> dict:
    dist = Counter((c["verification_state"], c["record_kind"]) for c in cards.values())
    vsx = Counter((c["verification_state"], "explicit" if c["vs_explicit"] else "defaulted")
                  for c in cards.values())
    legacy = {k: c for k, c in cards.items() if c["verification_state"] == "legacy_unclassified"}
    legacy_explicit = {k: c for k, c in legacy.items() if c["vs_explicit"]}
    legacy_defaulted = {k: c for k, c in legacy.items() if not c["vs_explicit"]}
    for name, sub in (("explicit_legacy", legacy_explicit), ("defaulted_legacy", legacy_defaulted)):
        pass
    return {
        "total_cards": len(cards),
        "verification_state_x_record_kind": {f"{a}|{b}": n for (a, b), n in sorted(dist.items())},
        "verification_state_explicitness": {f"{a}|{b}": n for (a, b), n in sorted(vsx.items())},
        "legacy_total": len(legacy),
        "legacy_explicit": len(legacy_explicit),
        "legacy_defaulted": len(legacy_defaulted),
        "legacy_explicit_profile": {
            "status": dict(Counter(c["status"] for c in legacy_explicit.values())),
            "promoted_to_rule_nonempty": sum(1 for c in legacy_explicit.values() if c["promoted_to_rule"]),
            "last_verified_nonempty": sum(1 for c in legacy_explicit.values() if c["last_verified_at"]),
        },
        "legacy_defaulted_profile": {
            "status": dict(Counter(c["status"] for c in legacy_defaulted.values())),
            "has_evidence": sum(1 for c in legacy_defaulted.values() if c["has_evidence"]),
            "promoted_to_rule_nonempty": sum(1 for c in legacy_defaulted.values() if c["promoted_to_rule"]),
            "last_verified_nonempty": sum(1 for c in legacy_defaulted.values() if c["last_verified_at"]),
        },
        "legacy_explicit_cards": [
            {"id": k, "status": c["status"], "promoted_to_rule": c["promoted_to_rule"],
             "last_verified_at": c["last_verified_at"]}
            for k, c in sorted(legacy_explicit.items())
        ],
    }


def audit_ledgers() -> dict:
    estore = ExperienceStore(EXP_DIR, semantic_ranker=None, write_guard=lambda: False)
    mstore = MethodStore(METHOD_DIR)

    exp_rows = [json.loads(l) for l in EXP_LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()]
    mth_rows = [json.loads(l) for l in METHOD_LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()]

    exp_drift, exp_entries = [], []
    for r in exp_rows:
        stem = str(r.get("experience_ref", "")).removeprefix("experience:")
        doc = estore.get(stem)
        cur_vs = getattr(doc, "verification_state", "<NODOC>") if doc else "<NODOC>"
        cur_st = getattr(doc, "status", "<NODOC>") if doc else "<NODOC>"
        dec_vs, dec_st = r.get("verification_state"), r.get("status")
        if cur_vs != dec_vs or cur_st != dec_st:
            exp_drift.append({"id": stem, "declared_vs": dec_vs, "current_vs": cur_vs,
                              "declared_status": dec_st, "current_status": cur_st})
    for stem in dict.fromkeys(str(r.get("experience_ref", "")).removeprefix("experience:") for r in exp_rows):
        raw_n = sum(1 for x in exp_rows if str(x.get("experience_ref", "")).removeprefix("experience:") == stem)
        un = estore.usage_net(f"experience:{stem}")
        kept = 0 if un is None else un["applied"] + un["not_applicable"] + un["rejected"] + un["unrecognized"]
        exp_entries.append({"id": stem, "ledger_entries": raw_n, "counted_by_usage_net": kept,
                            "net": None if un is None else un["net"],
                            "anchor": None if un is None else un["anchor"],
                            "truncated": kept < raw_n, "net_none": un is None})

    mth_drift, mth_entries = [], []
    for r in mth_rows:
        ref = str(r.get("method_ref", ""))
        rec = mstore.get(ref.removeprefix("method:"))
        cur = getattr(rec, "status", "<NODOC>") if rec else "<NODOC>"
        dec = r.get("method_status")
        if cur != dec:
            mth_drift.append({"id": ref, "declared_status": dec, "current_status": cur})
    for ref in dict.fromkeys(str(r.get("method_ref", "")) for r in mth_rows):
        raw_n = sum(1 for x in mth_rows if x.get("method_ref") == ref)
        un = mstore.usage_net(ref)
        kept = 0 if un is None else un["applied"] + un["not_applicable"] + un["rejected"] + un["unrecognized"]
        mth_entries.append({"id": ref, "ledger_entries": raw_n, "counted_by_usage_net": kept,
                            "net": None if un is None else un["net"],
                            "anchor": None if un is None else un["anchor"],
                            "truncated": kept < raw_n, "net_none": un is None})

    return {
        "experience_ledger": {
            "entries": len(exp_rows),
            "use_decision": dict(Counter(r.get("use_decision") for r in exp_rows)),
            "declared_vs": dict(Counter(r.get("verification_state") for r in exp_rows)),
            "task_benefit": dict(Counter(r.get("task_benefit") for r in exp_rows)),
            "drift": exp_drift, "drift_count": len(exp_drift),
            "per_card": exp_entries,
            "truncated_count": sum(1 for e in exp_entries if e["truncated"] or e["net_none"]),
        },
        "method_ledger": {
            "entries": len(mth_rows),
            "decision": dict(Counter(r.get("decision") for r in mth_rows)),
            "task_benefit": dict(Counter(r.get("task_benefit") for r in mth_rows)),
            "drift": mth_drift, "drift_count": len(mth_drift),
            "per_card": mth_entries,
            "truncated_count": sum(1 for e in mth_entries if e["truncated"] or e["net_none"]),
        },
    }


def main() -> int:
    loaded = load_cards()
    out = {
        "audit": "经验卡晋升空窗与 record_use 账本失真审计",
        "read_only": True,
        "authoritative_parser": "ExperienceDocument.from_md",
        "cards": audit_cards(loaded["cards"]),
        "parse_errors": loaded["parse_errors"],
        "ledgers": audit_ledgers(),
    }
    dest = Path(__file__).resolve().parent
    (dest / "promotion_gap_audit.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "ledgers"}, ensure_ascii=False, indent=2))
    lg = out["ledgers"]
    print("\n--- ledgers summary ---")
    print("experience:", lg["experience_ledger"]["entries"], "entries, drift",
          lg["experience_ledger"]["drift_count"], "truncated", lg["experience_ledger"]["truncated_count"])
    print("method:", lg["method_ledger"]["entries"], "entries, drift",
          lg["method_ledger"]["drift_count"], "truncated", lg["method_ledger"]["truncated_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
