"""Two-axis Agent completion gate: LFL run terminal + independent pytest evidence.

A model-authored completion claim is never an acceptance input. The LFL run must
end normally and a separate pytest process must pass against declared artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_SCHEMA = "lfl.agent-completion/v1"
_VERIFIER = "lfl-agent-completion/1"
_HEX_256 = re.compile(r"^[0-9a-f]{64}$")
_PYTEST_SUMMARY = re.compile(
    r"(?:(?P<passed>\d+)\s+passed)?"
    r"(?:,\s*)?(?:(?P<failed>\d+)\s+failed)?"
    r"(?:,\s*)?(?:(?P<errors>\d+)\s+errors?)?"
    r"(?:,\s*)?(?:(?P<skipped>\d+)\s+skipped)?"
)


def parse_pytest_summary(output: str) -> dict[str, int]:
    """Parse the final pytest summary; absence of a real pass count is not PASS."""
    for line in reversed(output.splitlines()):
        if "no tests ran" in line.lower():
            return {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
        if not any(word in line for word in ("passed", "failed", "error", "skipped")):
            continue
        match = _PYTEST_SUMMARY.search(line.strip())
        if match is None:
            continue
        values = {
            key: int(match.group(key) or 0) for key in ("passed", "failed", "errors", "skipped")
        }
        if any(values.values()):
            return values
    return {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}


def _is_pytest_command(command: list[str]) -> bool:
    if not command:
        return False
    executable = Path(command[0]).name.lower()
    if executable in {"pytest", "pytest.exe"}:
        return True
    return (
        executable in {"python", "python3", "python.exe", "python3.exe"}
        and len(command) >= 3
        and command[1:3] == ["-m", "pytest"]
    )


def _preflight_artifact_paths(workspace: Path, artifact_paths: list[str]) -> None:
    """Validate the output boundary BEFORE running verifier code."""
    if not artifact_paths:
        raise ValueError("at least one --artifact path is required")
    for raw in artifact_paths:
        candidate = Path(raw)
        if candidate.is_absolute():
            raise ValueError(f"artifact path must be workspace-relative: {raw}")
        path = (workspace / candidate).resolve(strict=False)
        try:
            path.relative_to(workspace)
        except ValueError as exc:
            raise ValueError(f"artifact path escapes workspace: {raw}") from exc


def _artifact_records(workspace: Path, artifact_paths: list[str]) -> list[dict[str, Any]]:
    if not artifact_paths:
        raise ValueError("at least one --artifact path is required")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in artifact_paths:
        candidate = Path(raw)
        if candidate.is_absolute():
            raise ValueError(f"artifact path must be workspace-relative: {raw}")
        path = (workspace / candidate).resolve(strict=True)
        try:
            relative = path.relative_to(workspace)
        except ValueError as exc:
            raise ValueError(f"artifact path escapes workspace: {raw}") from exc
        if not path.is_file():
            raise ValueError(f"artifact is not a regular file: {raw}")
        key = relative.as_posix()
        if key in seen:
            continue
        seen.add(key)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        records.append({"path": key, "sha256": digest, "size_bytes": path.stat().st_size})
    return records


def _source_sha(workspace: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40,64}", value) else None


def run_pytest_verification(
    *,
    workspace: Path | str,
    command: list[str],
    session_id: str,
    artifact_paths: list[str],
    timeout_s: int = 600,
) -> dict[str, Any]:
    """Run an independent pytest process and create a hash-bound verification receipt."""
    root = Path(workspace).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("workspace must be a directory")
    argv = [str(part) for part in command]
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not _is_pytest_command(argv):
        raise ValueError("verification command must invoke pytest directly or via python -m pytest")
    if not session_id.strip():
        raise ValueError("run receipt must contain a non-empty session_id")
    if timeout_s < 1 or timeout_s > 3600:
        raise ValueError("timeout_s must be between 1 and 3600")
    _preflight_artifact_paths(root, artifact_paths)

    started = time.monotonic()
    timed_out = False
    error_type = ""
    try:
        completed = subprocess.run(
            argv,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            shell=False,
        )
        test_exit_code = int(completed.returncode)
        summary = parse_pytest_summary((completed.stdout or "") + "\n" + (completed.stderr or ""))
    except subprocess.TimeoutExpired:
        timed_out = True
        error_type = "TimeoutExpired"
        test_exit_code = 124
        summary = {"passed": 0, "failed": 0, "errors": 1, "skipped": 0}
    except OSError as exc:
        timed_out = False
        test_exit_code = 127
        summary = {"passed": 0, "failed": 0, "errors": 1, "skipped": 0}
        error_type = type(exc).__name__
    else:
        error_type = ""

    artifacts = _artifact_records(root, artifact_paths)
    return {
        "schema": "lfl.verification/v1",
        "verifier": _VERIFIER,
        "session_id": session_id,
        "workspace": str(root),
        "source_sha": _source_sha(root),
        "test_command": argv,
        "test_exit_code": test_exit_code,
        "timed_out": timed_out,
        "error_type": error_type,
        **summary,
        "artifacts": artifacts,
        "duration_s": round(time.monotonic() - started, 3),
    }


def evaluate_agent_completion(
    run_record: dict[str, Any],
    verification: dict[str, Any] | None,
) -> dict[str, Any]:
    """Accept only when both the LFL run and independent code verification pass."""
    run_reasons: list[str] = []
    if run_record.get("schema") != "lfl.cli/v1" or run_record.get("type") != "result":
        run_reasons.append("run_receipt_invalid")
    if run_record.get("status") != "completed":
        run_reasons.append("run_not_completed")
    if run_record.get("exit_code") != 0:
        run_reasons.append("run_exit_nonzero")
    if run_record.get("run_incomplete") is not False:
        run_reasons.append("run_incomplete")
    if run_record.get("provider_output_truncated") is not False:
        run_reasons.append("provider_output_truncated")
    if run_record.get("projection_cannot_fit") is not False:
        run_reasons.append("projection_cannot_fit")
    if run_record.get("cancel_reason"):
        run_reasons.append("run_cancelled")
    if not isinstance(run_record.get("session_id"), str) or not run_record["session_id"].strip():
        run_reasons.append("run_session_id_missing")

    verification_reasons: list[str] = []
    if verification is None:
        verification_reasons.append("verification_missing")
    else:
        if (
            verification.get("schema") != "lfl.verification/v1"
            or verification.get("verifier") != _VERIFIER
        ):
            verification_reasons.append("verification_receipt_invalid")
        if verification.get("session_id") != run_record.get("session_id"):
            verification_reasons.append("session_id_mismatch")
        if verification.get("test_exit_code") != 0 or verification.get("timed_out") is True:
            verification_reasons.append("verification_failed")
        if not isinstance(verification.get("passed"), int) or verification.get("passed", 0) < 1:
            verification_reasons.append("verification_has_no_passes")
        if verification.get("failed", 0) != 0 or verification.get("errors", 0) != 0:
            verification_reasons.append("verification_failed")
        artifacts = verification.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            verification_reasons.append("artifacts_missing")
        else:
            for artifact in artifacts:
                if (
                    not isinstance(artifact, dict)
                    or not isinstance(artifact.get("path"), str)
                    or not artifact["path"].strip()
                    or not isinstance(artifact.get("sha256"), str)
                    or _HEX_256.fullmatch(artifact["sha256"]) is None
                ):
                    verification_reasons.append("artifact_digest_invalid")
                    break

    run_ok = not run_reasons
    verification_ok = not verification_reasons
    reasons = list(dict.fromkeys(run_reasons + verification_reasons))
    return {
        "schema": _SCHEMA,
        "accepted": run_ok and verification_ok,
        "status": "accepted" if run_ok and verification_ok else "not_accepted",
        "run_ok": run_ok,
        "verification_ok": verification_ok,
        "session_id": run_record.get("session_id"),
        "run_reasons": run_reasons,
        "verification_reasons": verification_reasons,
        "reasons": reasons,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="LFL Agent completion gate: completed Run AND independent pytest/artifact verification"
    )
    parser.add_argument(
        "--run-json", type=Path, required=True, help="lfl chat --output json result file"
    )
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument(
        "--artifact", action="append", default=[], help="workspace-relative output file; repeatable"
    )
    parser.add_argument("--timeout-s", type=int, default=600)
    parser.add_argument(
        "--output", type=Path, default=None, help="write decision JSON; default stdout"
    )
    parser.add_argument(
        "--test-command",
        nargs=argparse.REMAINDER,
        required=True,
        help="pytest argv, e.g. --test-command python -m pytest -q tests/unit/test_x.py",
    )
    args = parser.parse_args(argv)
    try:
        run_record = json.loads(args.run_json.read_text(encoding="utf-8"))
        if not isinstance(run_record, dict):
            raise ValueError("run receipt must be a JSON object")
        verification = run_pytest_verification(
            workspace=args.workspace,
            command=args.test_command,
            session_id=str(run_record.get("session_id") or ""),
            artifact_paths=args.artifact,
            timeout_s=args.timeout_s,
        )
        decision = evaluate_agent_completion(run_record, verification)
        output = {**decision, "verification": verification}
        rendered = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
        if args.output is None:
            sys.stdout.write(rendered)
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        return 0 if decision["accepted"] else 1
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        ValueError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"agent completion verification error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
