#!/usr/bin/env python3
"""Static gate: env-sensitive exact-number tests must declare their env pins.

Root cause: COMPACT_RATIO is read directly from os.environ
(src/llm_loop/core/prompt_build/stages/history_budget_prep.py). Ambient
injection or real-.env residue leaking via load_env_file() shifts compaction
thresholds (max_chars x ratio) and flips exact-number assertions red with
zero code change (R817 / 2026-09-09 lesson; see the autouse fixture docstring
in tests/unit/test_compact_observability_r817.py).

Rule: a test file that (a) references exact compaction budget stat keys AND
(b) invokes the history budget builders MUST declare its COMPACT_RATIO
dependency -- explicit setenv/delenv, or the shared autouse pin fixture.
Undeclared files fail the gate. Baseline at introduction: 0 violations.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BUDGET_ASSERT_KEYS = (
    "trigger_limit_chars",
    "effective_budget_chars",
    "archive_target_chars",
)
BUILDER_ENTRIES = (
    "build_history_messages",
    "_build_llm_messages",
    "run_history_budget_prep",
    "run_history_postprocess",
)
ENV_DECLARATIONS = (
    "COMPACT_RATIO",
    "_pin_compact_ratio_env",
)


def main() -> int:
    violations: list[str] = []
    files = sorted(ROOT.glob("tests/**/*.py"))
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        if (
            any(k in text for k in BUDGET_ASSERT_KEYS)
            and any(b in text for b in BUILDER_ENTRIES)
            and not any(d in text for d in ENV_DECLARATIONS)
        ):
            violations.append(str(path.relative_to(ROOT)))
    if violations:
        print("FAIL test env-pin gate: exact-budget asserts without COMPACT_RATIO declaration:")
        for v in violations:
            print(f"   - {v}")
        print("   fix: explicit monkeypatch.setenv('COMPACT_RATIO', ...) or reference")
        print("   _pin_compact_ratio_env (sample: tests/unit/test_compact_observability_r817.py)")
        return 1
    print(
        f"PASS test env-pin gate: scanned {len(files)} test files, 0 undeclared COMPACT_RATIO dependents"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
