#!/usr/bin/env python3
"""Audit approved design REQs against the authoritative TaskStore (read-only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from llm_loop.introspection.goal_coverage import audit_coverage  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--design", type=Path, required=True)
    parser.add_argument("--audit-dir", type=Path, default=ROOT / "data" / "audit")
    parser.add_argument("--candidate", default="")
    args = parser.parse_args()
    report = audit_coverage(
        design_path=args.design,
        audit_dir=args.audit_dir,
        goal_id=args.goal,
        candidate_sha=args.candidate,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
