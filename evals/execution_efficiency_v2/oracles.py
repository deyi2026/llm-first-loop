"""Execution Efficiency v2 first-action oracles.

These are intentionally broader than the historical pilot ``first_tools=[read]``
default.  The v2 question is whether the first action is mechanically appropriate for
the task, not whether the model chose one preferred implementation style.

Do not infer these classes from prompt text at scoring time.  New benchmark rows must
pre-register their acceptable classes here (or carry an explicit v2 oracle) before
generation if they are to contribute to wrong-tool/FCR-v2 metrics.
"""

from __future__ import annotations

FIRST_ACTION_ACCEPTABLE_CLASSES: dict[str, frozenset[str]] = {
    "t01_read_first_line": frozenset({"read"}),
    # The prompt explicitly says to run gen.py; its first process exit is deliberately
    # transient.  A command call is therefore the intended first action, not a mistake.
    "t02_retry_transient": frozenset({"command"}),
    # Running the supplied failing test first and reading the supplied sources first are
    # both legitimate diagnostic openings.
    "t04_fix_bug": frozenset({"read", "command"}),
    # Direct shell aggregation and explicit file reads are both mechanically sufficient.
    "t05_multi_file_sum": frozenset({"read", "command"}),
    # A bounded read and a shell line-selector are both direct ways to acquire line 2024.
    "t09_big_file_line": frozenset({"read", "command"}),
    # The task explicitly requires whoami/pwd from real command output.
    "t11_env_facts": frozenset({"command"}),
}
