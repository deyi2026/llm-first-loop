#!/usr/bin/env python3
"""Disposable development receipt CLI; never a release/Host/CI credential."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from llm_loop.introspection.dev_gate import run_dev_gate  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--req", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--design", type=Path, required=True)
    parser.add_argument("--audit-dir", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    # Dev receipts are intentionally temporary. Permanent release evidence
    # belongs to the existing R9/Host/CI durable surfaces, not this CLI.
    temp_roots = (
        Path(tempfile.gettempdir()).resolve(),
        Path("/tmp").resolve(),
        Path("/var/tmp").resolve(),
    )
    receipt = args.receipt.resolve()
    if not args.receipt.is_absolute() or not any(
        receipt.is_relative_to(temp_root) for temp_root in temp_roots
    ):
        parser.error("--receipt must be an absolute temporary path")
    report = run_dev_gate(
        root=Path.cwd().resolve(),
        design=args.design,
        audit_dir=args.audit_dir,
        goal_id=args.goal,
        req_id=args.req,
        base=args.base,
        dry_run=args.dry_run,
    )
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=receipt.parent, prefix=".dev_gate_", delete=False
    ) as handle:
        temporary = Path(handle.name)
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temporary, receipt)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 2 if report["status"] == "DRY_RUN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
