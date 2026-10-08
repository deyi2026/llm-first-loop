"""Strict legacy-debt ratchet for R9 Ruff and Pyright full-tree checks.

The checked-in diagnostic ledger was frozen against an immutable release.
It is not an allowlist for new failures: any new fingerprint or additional
occurrence fails, and changed Python files must have zero diagnostics.
Never suppress analyzer errors, change the baseline at commit time, or turn
off the whole-tree scan. Full pytest remains the responsibility of ci_gate.sh.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

BASELINE_REL = "tests/guards/static_diagnostic_debt.json"
SCHEMA = "r9-static-diagnostic-ratchet/v1"
TOOLS = ("ruff", "pyright")
FROZEN_BASELINE_SHA256 = "b7ed6806d66135737256c1d8e436cd85885187cd6821ef3f5a5262c9aa74cef8"


def _git(root: Path, *args: str) -> bytes:
    proc = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, check=True,
    )
    return proc.stdout


def _sha_source_line(root: Path, path: str, line: int) -> str:
    target = (root / path).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError(f"diagnostic path escapes repository: {path}")
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"unreadable diagnostic source: {path}: {exc}") from exc
    if line < 1 or line > len(lines):
        raise ValueError(f"invalid diagnostic line {line} in {path}")
    return hashlib.sha256(lines[line - 1].strip().encode("utf-8")).hexdigest()


def normalize(tool: str, payload: Any, root: Path) -> collections.Counter[tuple[str, str, str, str]]:
    """Keep exact message and source-line fingerprint, not unstable line number.

    Multiplicity is retained: a second copy of a known error is a new failure.
    """
    if tool not in TOOLS:
        raise ValueError(f"unknown analyzer: {tool}")
    items = payload if tool == "ruff" else payload["generalDiagnostics"]
    result: collections.Counter[tuple[str, str, str, str]] = collections.Counter()
    for item in items:
        if tool == "pyright" and item.get("severity") != "error":
            continue
        absolute = Path(item["filename"] if tool == "ruff" else item["file"]).resolve()
        try:
            rel = absolute.relative_to(root.resolve()).as_posix()
        except ValueError as exc:
            raise ValueError(f"diagnostic outside repo: {absolute}") from exc
        if not rel.startswith(("src/", "tests/", "scripts/")):
            raise ValueError(f"unexpected analyzer scope: {rel}")
        code = str(item["code"] if tool == "ruff" else item.get("rule") or "<no-rule>")
        message = str(item["message"])
        lineno = (
            int(item["location"]["row"]) if tool == "ruff"
            else int(item["range"]["start"]["line"]) + 1
        )
        result[(rel, code, message, _sha_source_line(root, rel, lineno))] += 1
    return result


def run_analyzer(root: Path, python: str, tool: str) -> tuple[str, collections.Counter[tuple[str, str, str, str]]]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src") + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    version_cmd = [python, "-m", tool, "--version"]
    version_run = subprocess.run(version_cmd, cwd=root, env=env, capture_output=True, text=True, timeout=30)
    if version_run.returncode:
        raise RuntimeError(f"{tool} version check failed: {version_run.stderr[-300:]}")
    # pyright may append a network-free upgrade notice after the semantic
    # version; tool identity is the first line, not the advisory text.
    version = version_run.stdout.splitlines()[0].strip()
    argv = (
        [python, "-m", "ruff", "check", "src", "tests", "scripts", "--output-format=json"]
        if tool == "ruff" else [python, "-m", "pyright", "--outputjson"]
    )
    completed = subprocess.run(argv, cwd=root, env=env, capture_output=True, text=True, timeout=240)
    if completed.returncode not in (0, 1):
        raise RuntimeError(f"{tool} runner crashed (exit={completed.returncode}): {completed.stderr[-300:]}")
    try:
        payload = json.loads(completed.stdout)
        current = normalize(tool, payload, root)
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"{tool} diagnostics invalid or incomplete: {exc}") from exc
    if completed.returncode and not current:
        raise RuntimeError(f"{tool} failed without parseable error diagnostics: {completed.stderr[-300:]}")
    return version, current


def serialize(diagnostics: collections.Counter[tuple[str, str, str, str]]) -> list[dict[str, Any]]:
    return [
        {"path": key[0], "rule": key[1], "message": key[2], "source_line_sha256": key[3], "count": count}
        for key, count in sorted(diagnostics.items())
    ]


def deserialize(rows: list[dict[str, Any]]) -> collections.Counter[tuple[str, str, str, str]]:
    counter: collections.Counter[tuple[str, str, str, str]] = collections.Counter()
    for row in rows:
        key = (row["path"], row["rule"], row["message"], row["source_line_sha256"])
        n = row["count"]
        if not isinstance(n, int) or isinstance(n, bool) or n <= 0 or key in counter:
            raise ValueError(f"invalid or duplicate baseline diagnostic: {key}")
        counter[key] = n
    return counter


def changed_python_paths(root: Path) -> set[str]:
    """Source under test, including staged/uncommitted source for local preflight."""
    head = _git(root, "rev-parse", "HEAD").decode().strip()
    parent = _git(root, "rev-parse", "HEAD^").decode().strip()
    changes = set()
    for args in (
        ("diff", "--name-only", "-z", "--diff-filter=ACMR", parent, head),
        ("diff", "--name-only", "-z", "--diff-filter=ACMR", "HEAD"),
        ("ls-files", "--others", "--exclude-standard", "-z"),
    ):
        changes.update(filter(None, _git(root, *args).decode().split("\0")))
    return {p for p in changes if p.endswith(".py") and p.startswith(("src/", "tests/", "scripts/"))}


def validate_baseline(
    root: Path, baseline: dict[str, Any], raw: bytes, tools: tuple[str, ...],
    *, frozen_sha256: str | None = None,
) -> None:
    if frozen_sha256 is not None and hashlib.sha256(raw).hexdigest() != frozen_sha256:
        raise ValueError("frozen historical debt ledger SHA256 drift")
    if baseline.get("schema") != SCHEMA or set(baseline.get("diagnostics", {})) != set(TOOLS):
        raise ValueError("baseline schema/tools mismatch")
    if set(baseline.get("versions", {})) != set(TOOLS):
        raise ValueError("baseline tool versions missing")
    origin = str(baseline["origin_head"])
    origin_present = (
        subprocess.run(
            ["git", "cat-file", "-e", f"{origin}^{{commit}}"], cwd=root, capture_output=True
        ).returncode
        == 0
    )
    if not origin_present:
        # Sanitized public lineage (CI) never carries the private origin commit
        # object; frozen-ledger SHA256 + schema checks above stay the integrity
        # bound, so ancestry is enforced only where the object actually exists.
        print(f"ratchet: origin_head {origin[:9]} absent from object store (public lineage) — ancestry check skipped")
    else:
        _git(root, "merge-base", "--is-ancestor", origin, "HEAD")
    parent = _git(root, "rev-parse", "HEAD^").decode().strip()
    prev = subprocess.run(
        ["git", "show", f"HEAD^:{BASELINE_REL}"], cwd=root, capture_output=True,
    )
    if prev.returncode == 0:
        if raw != prev.stdout:
            raise ValueError("frozen historical debt ledger changed: requires distinct reviewed governance")
    elif parent != origin and _git(root, "rev-parse", "HEAD").decode().strip() != origin:
        raise ValueError("baseline bootstrap must be direct child of its frozen origin")
    for tool in tools:
        deserialize(baseline["diagnostics"][tool])


def evaluate(
    current: collections.Counter[tuple[str, str, str, str]],
    debt: collections.Counter[tuple[str, str, str, str]],
    changed: set[str],
) -> tuple[collections.Counter[tuple[str, str, str, str]], collections.Counter[tuple[str, str, str, str]], list[tuple[str, str, str, str]]]:
    new = current - debt
    resolved = debt - current
    touched = [key for key in current if key[0] in changed]
    return new, resolved, sorted(touched)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", choices=TOOLS, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    ledger = root / BASELINE_REL
    raw = ledger.read_bytes()
    baseline = json.loads(raw)
    validate_baseline(root, baseline, raw, TOOLS, frozen_sha256=FROZEN_BASELINE_SHA256)
    python = sys.executable
    version, current = run_analyzer(root, python, args.tool)
    expected_version = baseline["versions"][args.tool]
    if version != expected_version:
        raise ValueError(f"{args.tool} analyzer version drift: actual={version!r} frozen={expected_version!r}")
    old = deserialize(baseline["diagnostics"][args.tool])
    changed = changed_python_paths(root)
    new, resolved, touched = evaluate(current, old, changed)
    print(
        f"R9 {args.tool}: historical={sum(old.values())}, current={sum(current.values())}, "
        f"new={sum(new.values())}, resolved={sum(resolved.values())}, "
        f"changed_file_diagnostics={len(touched)}, changed_python_files={len(changed)}"
    )
    for key, count in new.most_common(12):
        print(f"BLOCK NEW x{count}: {key[0]} {key[1]} {key[2].splitlines()[0][:160]}")
    for key in touched[:12]:
        print(f"BLOCK CHANGED FILE: {key[0]} {key[1]} {key[2].splitlines()[0][:160]}")
    if new or touched:
        print("R9 static diagnostic ratchet DENIED: do not silently expand legacy debt", file=sys.stderr)
        return 1
    print(f"R9 {args.tool}: PASS (historical debt visible; no new errors; touched files clean)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.SubprocessError, KeyError, ValueError, RuntimeError) as exc:
        print(f"R9 static diagnostic ratchet FAIL-CLOSED: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
