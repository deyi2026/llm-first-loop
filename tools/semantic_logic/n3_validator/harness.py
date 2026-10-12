"""Pinned, restricted, qualification-only N3 validator harness for SMC P1-C.

This module is deliberately outside ``src/llm_loop``.  It is not a production
dependency and it never grants semantic or execution authority.  P1-C accepts only the
strict P1-B canonical N3 surface as data.  Queries/rulepacks remain disabled until a
separately qualified later phase extends the surface.

The external backend is EYE distributed through the pinned ``eyereasoner`` npm package.
Every backend invocation uses EYE ``--restricted`` and runs under macOS Seatbelt with
network and host file writes denied.  Data reaches the backend only through stdin and an
in-memory Emscripten filesystem owned by the fixed bridge.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

from llm_loop.semantic_logic import load_canonical_n3

SCHEMA: Final = "smc.n3_validator_report.v0.1"
BACKEND_ID: Final = "eye-js-wasm"
PINNED_EYEREASONER_VERSION: Final = "21.1.18"
PINNED_EYEREASONER_INTEGRITY: Final = (
    "sha512-aLKl0hMCa5xvZ/qVfupyZ7vAchXwXIlVWNtbd5Zb9IUNB9FGq44yvM6N3T+Q1x9A9VL9CKB652nqT5PgpgcZDw=="
)
PINNED_SWIPL_WASM_VERSION: Final = "7.0.10"
PINNED_EYE_VERSION: Final = "EYE v11.24.5 (2026-08-23)"
PINNED_LOCK_SHA256: Final = "83d2ee38f112bea8929751a5a2c31dede5aec07312eb696ce660537d288c71be"

VALIDATOR_ROOT: Final = Path(__file__).resolve().parent
PACKAGE_LOCK: Final = VALIDATOR_ROOT / "package-lock.json"
NODE_MODULES: Final = VALIDATOR_ROOT / "node_modules"
BRIDGE: Final = VALIDATOR_ROOT / "bridge.mjs"
SANDBOX_PROBE: Final = VALIDATOR_ROOT / "sandbox_probe.mjs"

SEATBELT_PROFILE: Final = (
    "(version 1)(allow default)(deny network*)(deny file-write*)(deny process-fork)"
)
FIXED_EYE_FLAGS: Final = (
    "--nope",
    "--quiet",
    "--restricted",
    "--tactic",
    "limited-answer",
    "<ANSWER_CAP>",
    "--pass",
    "./data.n3",
)

_FORBIDDEN_RAW_MARKERS: Final = (
    "log:semantics",
    "log:content",
    "log:outputString",
    "log:outputStringTo",
    "log:notIncludes",
    "http://www.w3.org/2000/10/swap/log#semantics",
    "http://www.w3.org/2000/10/swap/log#content",
    "http://www.w3.org/2000/10/swap/log#outputString",
    "http://www.w3.org/2000/10/swap/log#outputStringTo",
    "http://www.w3.org/2000/10/swap/log#notIncludes",
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


@dataclass(frozen=True, slots=True)
class ValidatorBounds:
    wall_timeout_ms: int = 20_000
    max_input_bytes: int = 1_048_576
    max_output_bytes: int = 1_500_000
    answer_cap: int = 4_096
    max_bridge_stdout_bytes: int = 262_144
    max_bridge_stderr_bytes: int = 131_072

    def validate(self) -> None:
        checks = {
            "wall_timeout_ms": (self.wall_timeout_ms, 1, 60_000),
            "max_input_bytes": (self.max_input_bytes, 1, 2_000_000),
            "max_output_bytes": (self.max_output_bytes, 1_024, 4_000_000),
            "answer_cap": (self.answer_cap, 1, 10_000),
            "max_bridge_stdout_bytes": (self.max_bridge_stdout_bytes, 1_024, 1_000_000),
            "max_bridge_stderr_bytes": (self.max_bridge_stderr_bytes, 1_024, 1_000_000),
        }
        for label, (value, lower, upper) in checks.items():
            if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
                raise ValueError(f"{label}_out_of_range")


def _base_report(*, fixture_ref: str, bounds: ValidatorBounds, input_bytes: bytes) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "fail_closed",
        "reason": None,
        "stage": None,
        "authority": "shadow_only",
        "production_consumed": False,
        "backend_invoked": False,
        "backend": {
            "id": BACKEND_ID,
            "package": "eyereasoner",
            "package_version": PINNED_EYEREASONER_VERSION,
            "package_integrity": PINNED_EYEREASONER_INTEGRITY,
            "swipl_wasm_version": PINNED_SWIPL_WASM_VERSION,
            "eye_version": PINNED_EYE_VERSION,
            "package_lock_sha256": PINNED_LOCK_SHA256,
        },
        "profile": {
            "input": "p1b_canonical_n3_only",
            "query_surface": "disabled_p1c",
            "rulepack_surface": "disabled_p1c",
            "negation_as_failure": "forbidden",
            "custom_builtins": "forbidden",
            "remote_imports": "forbidden",
            "host_input_mode": "stdin_only",
            "eye_restricted": True,
            "seatbelt_profile": "deny_network_host_file_write_and_child_process",
            "arbitrary_input_paths": False,
            "runtime_permission_authority": False,
        },
        "fixed_eye_flags": list(FIXED_EYE_FLAGS),
        "bounds": asdict(bounds),
        "input": {
            "fixture_ref": fixture_ref,
            "bytes": len(input_bytes),
            "sha256": _sha256_bytes(input_bytes),
            "rulepack_sha256": None,
            "query_set_sha256": None,
        },
        "output": None,
        "duration_ms": None,
    }


def _fail(
    report: dict[str, Any], *, reason: str, stage: str, duration_ms: float | None = None
) -> dict[str, Any]:
    report["status"] = "fail_closed"
    report["reason"] = reason
    report["stage"] = stage
    report["duration_ms"] = duration_ms
    return report


def _load_lock() -> dict[str, Any]:
    if not PACKAGE_LOCK.is_file():
        raise ValueError("package_lock_missing")
    if _file_sha256(PACKAGE_LOCK) != PINNED_LOCK_SHA256:
        raise ValueError("package_lock_hash_mismatch")
    try:
        lock = json.loads(PACKAGE_LOCK.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("package_lock_invalid") from exc
    if lock.get("lockfileVersion") != 3:
        raise ValueError("package_lock_version_mismatch")
    packages = lock.get("packages")
    if not isinstance(packages, dict):
        raise ValueError("package_lock_packages_missing")
    eye = packages.get("node_modules/eyereasoner")
    swipl = packages.get("node_modules/swipl-wasm")
    if not isinstance(eye, dict) or not isinstance(swipl, dict):
        raise ValueError("pinned_backend_packages_missing")
    if eye.get("version") != PINNED_EYEREASONER_VERSION:
        raise ValueError("eyereasoner_version_mismatch")
    if eye.get("integrity") != PINNED_EYEREASONER_INTEGRITY:
        raise ValueError("eyereasoner_integrity_mismatch")
    if swipl.get("version") != PINNED_SWIPL_WASM_VERSION:
        raise ValueError("swipl_wasm_version_mismatch")
    return lock


def backend_installation_available() -> bool:
    return (
        PACKAGE_LOCK.is_file()
        and (NODE_MODULES / "eyereasoner" / "package.json").is_file()
        and (NODE_MODULES / "swipl-wasm" / "package.json").is_file()
        and BRIDGE.is_file()
        and shutil.which("node") is not None
        and shutil.which("sandbox-exec") is not None
    )


def _read_installed_package(name: str) -> dict[str, Any]:
    path = NODE_MODULES / name / "package.json"
    if not path.is_file():
        raise ValueError(f"installed_package_missing:{name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"installed_package_invalid:{name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"installed_package_invalid:{name}")
    return value


def _node_version(node: str) -> str:
    proc = subprocess.run(
        [node, "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
        env={"PATH": "/usr/bin:/bin:/opt/homebrew/bin", "LC_ALL": "C"},
    )
    if proc.returncode != 0:
        raise ValueError("node_version_probe_failed")
    version = proc.stdout.strip()
    if re.fullmatch(r"v([0-9]+)\.[0-9]+\.[0-9]+", version) is None:
        raise ValueError("node_version_unparseable")
    major = int(version.removeprefix("v").split(".", 1)[0])
    if major < 20:
        raise ValueError("node_version_too_old")
    return version


def _sanitized_env(temp_home: Path) -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin",
        "HOME": str(temp_home),
        "TMPDIR": str(temp_home),
        "LC_ALL": "C",
        "LANG": "C",
        "NODE_NO_WARNINGS": "1",
    }


def _sandbox_command(node: str, script: Path) -> list[str]:
    sandbox = shutil.which("sandbox-exec")
    if platform.system() != "Darwin" or not sandbox:
        raise ValueError("seatbelt_unavailable")
    return [sandbox, "-p", SEATBELT_PROFILE, node, str(script)]


def verify_backend_identity() -> dict[str, Any]:
    """Verify tracked lock + installed package + backend-reported EYE identity."""

    _load_lock()
    if not backend_installation_available():
        raise ValueError("pinned_backend_not_installed")
    eye_pkg = _read_installed_package("eyereasoner")
    swipl_pkg = _read_installed_package("swipl-wasm")
    if eye_pkg.get("version") != PINNED_EYEREASONER_VERSION:
        raise ValueError("installed_eyereasoner_version_mismatch")
    if swipl_pkg.get("version") != PINNED_SWIPL_WASM_VERSION:
        raise ValueError("installed_swipl_wasm_version_mismatch")

    node = shutil.which("node")
    if not node:
        raise ValueError("node_unavailable")
    node_version = _node_version(node)
    cli = NODE_MODULES / "eyereasoner" / "dist" / "bin" / "index.js"
    if not cli.is_file():
        raise ValueError("eyereasoner_cli_missing")
    with tempfile.TemporaryDirectory(prefix="smc-p1c-version-") as raw_home:
        home = Path(raw_home)
        proc = subprocess.run(
            [*_sandbox_command(node, cli), "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            cwd=VALIDATOR_ROOT,
            env=_sanitized_env(home),
        )
    observed = "\n".join(part.strip() for part in (proc.stdout, proc.stderr) if part.strip())
    if proc.returncode != 0 or observed != PINNED_EYE_VERSION:
        raise ValueError(f"eye_version_mismatch:{observed[:200]}")
    return {
        "backend_id": BACKEND_ID,
        "eyereasoner_version": PINNED_EYEREASONER_VERSION,
        "eyereasoner_integrity": PINNED_EYEREASONER_INTEGRITY,
        "swipl_wasm_version": PINNED_SWIPL_WASM_VERSION,
        "eye_version": observed,
        "node_version": node_version,
        "package_lock_sha256": PINNED_LOCK_SHA256,
    }


def _preflight_canonical_n3(payload: bytes) -> None:
    if any(marker.encode("utf-8") in payload for marker in _FORBIDDEN_RAW_MARKERS):
        raise ValueError("forbidden_builtin_marker")
    # Stronger than a lexical scan: P1-C accepts only exact bytes that reconstruct under
    # the strict P1-B canonical loader.  This excludes arbitrary predicates, rules,
    # prefixes, blank nodes, remote imports and noncanonical syntax before EYE runs.
    load_canonical_n3(payload)


def validate_canonical_n3(
    payload: bytes,
    *,
    fixture_ref: str,
    bounds: ValidatorBounds | None = None,
    query_set: tuple[bytes, ...] = (),
    rulepack: bytes | None = None,
) -> dict[str, Any]:
    """Validate one canonical P1-B document with the pinned restricted EYE backend."""

    active_bounds = bounds or ValidatorBounds()
    report = _base_report(fixture_ref=fixture_ref, bounds=active_bounds, input_bytes=payload)
    start = time.monotonic()
    try:
        active_bounds.validate()
    except ValueError as exc:
        return _fail(report, reason=str(exc), stage="bounds")
    if query_set or rulepack is not None:
        return _fail(report, reason="query_or_rulepack_surface_not_qualified_p1c", stage="surface")
    if len(payload) > active_bounds.max_input_bytes:
        return _fail(report, reason="input_cap_exceeded", stage="input_cap")
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError:
        return _fail(report, reason="input_not_utf8", stage="canonical_preflight")
    try:
        _preflight_canonical_n3(payload)
    except (TypeError, ValueError) as exc:
        return _fail(report, reason=f"canonical_preflight_rejected:{exc}", stage="canonical_preflight")
    try:
        identity = verify_backend_identity()
    except ValueError as exc:
        return _fail(report, reason=str(exc), stage="backend_identity")

    node = shutil.which("node")
    if not node:
        return _fail(report, reason="node_unavailable", stage="backend_identity")
    request = {
        "n3": payload.decode("utf-8"),
        "answer_cap": active_bounds.answer_cap,
        "max_output_bytes": active_bounds.max_output_bytes,
    }
    request_bytes = (json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )

    with tempfile.TemporaryDirectory(prefix="smc-p1c-eye-") as raw_home:
        home = Path(raw_home)
        proc = subprocess.Popen(
            _sandbox_command(node, BRIDGE),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=VALIDATOR_ROOT,
            env=_sanitized_env(home),
            start_new_session=True,
        )
        report["backend_invoked"] = True
        try:
            stdout, stderr = proc.communicate(
                input=request_bytes,
                timeout=active_bounds.wall_timeout_ms / 1000.0,
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            duration_ms = round((time.monotonic() - start) * 1000, 3)
            return _fail(report, reason="wall_timeout", stage="backend", duration_ms=duration_ms)

    duration_ms = round((time.monotonic() - start) * 1000, 3)
    if len(stdout) > active_bounds.max_bridge_stdout_bytes:
        return _fail(
            report,
            reason="bridge_stdout_cap_exceeded",
            stage="backend_receipt",
            duration_ms=duration_ms,
        )
    if len(stderr) > active_bounds.max_bridge_stderr_bytes:
        return _fail(
            report,
            reason="bridge_stderr_cap_exceeded",
            stage="backend_receipt",
            duration_ms=duration_ms,
        )
    if stderr:
        return _fail(
            report,
            reason="unexpected_bridge_stderr",
            stage="backend_receipt",
            duration_ms=duration_ms,
        )
    try:
        receipt = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _fail(
            report,
            reason="invalid_bridge_receipt",
            stage="backend_receipt",
            duration_ms=duration_ms,
        )
    if not isinstance(receipt, dict) or receipt.get("schema") != "smc.eyejs_bridge_receipt.v0.1":
        return _fail(
            report,
            reason="bridge_receipt_schema_mismatch",
            stage="backend_receipt",
            duration_ms=duration_ms,
        )
    expected_flags = [
        "--nope",
        "--quiet",
        "--restricted",
        "--tactic",
        "limited-answer",
        str(active_bounds.answer_cap),
        "--pass",
        "./data.n3",
    ]
    if receipt.get("eye_args") != expected_flags:
        return _fail(
            report,
            reason="bridge_flag_mismatch",
            stage="backend_receipt",
            duration_ms=duration_ms,
        )
    if proc.returncode != 0 or receipt.get("ok") is not True:
        reason = str(receipt.get("reason") or f"backend_exit_{proc.returncode}")
        report["output"] = {
            "bridge_exit_code": proc.returncode,
            "reasoner_output_bytes": receipt.get("output_bytes"),
            "reasoner_output_sha256": receipt.get("output_sha256"),
            "diagnostic_bytes": receipt.get("diagnostic_bytes"),
            "diagnostic_sha256": receipt.get("diagnostic_sha256"),
        }
        return _fail(report, reason=reason, stage="backend", duration_ms=duration_ms)

    report["status"] = "pass"
    report["reason"] = None
    report["stage"] = "complete"
    report["duration_ms"] = duration_ms
    report["backend"].update(identity)
    report["fixed_eye_flags"] = expected_flags
    report["output"] = {
        "bridge_exit_code": proc.returncode,
        "reasoner_output_bytes": receipt.get("output_bytes"),
        "reasoner_output_sha256": receipt.get("output_sha256"),
        "diagnostic_bytes": receipt.get("diagnostic_bytes"),
        "diagnostic_sha256": receipt.get("diagnostic_sha256"),
    }
    return report


def run_sandbox_probe() -> dict[str, Any]:
    """Prove the outer qualification sandbox denies network, writes and child processes."""

    if not backend_installation_available() or not SANDBOX_PROBE.is_file():
        raise ValueError("sandbox_probe_backend_unavailable")
    node = shutil.which("node")
    if not node:
        raise ValueError("node_unavailable")
    with tempfile.TemporaryDirectory(prefix="smc-p1c-probe-") as raw_home:
        home = Path(raw_home)
        write_target = home / "forbidden-write.txt"
        env = _sanitized_env(home)
        env["SMC_PROBE_WRITE_TARGET"] = str(write_target)
        proc = subprocess.run(
            _sandbox_command(node, SANDBOX_PROBE),
            check=False,
            capture_output=True,
            timeout=5,
            cwd=VALIDATOR_ROOT,
            env=env,
        )
        target_exists = write_target.exists()
    if proc.stderr:
        raise ValueError("sandbox_probe_unexpected_stderr")
    try:
        receipt = json.loads(proc.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("sandbox_probe_invalid_receipt") from exc
    if (
        proc.returncode != 0
        or receipt.get("network_denied") is not True
        or receipt.get("file_write_denied") is not True
        or receipt.get("child_process_denied") is not True
        or target_exists
    ):
        raise ValueError("sandbox_probe_failed")
    return {
        "schema": "smc.n3_validator_sandbox_probe_result.v0.1",
        "status": "pass",
        "seatbelt_profile": SEATBELT_PROFILE,
        "network_denied": True,
        "host_file_write_denied": True,
        "child_process_denied": True,
        "forbidden_write_materialized": False,
    }


def main() -> int:
    import argparse

    defaults = ValidatorBounds()
    parser = argparse.ArgumentParser(description="Validate P1-B canonical N3 with pinned EYE-js")
    parser.add_argument("--fixture-ref", required=True)
    parser.add_argument("--timeout-ms", type=int, default=defaults.wall_timeout_ms)
    parser.add_argument("--max-input-bytes", type=int, default=defaults.max_input_bytes)
    parser.add_argument("--max-output-bytes", type=int, default=defaults.max_output_bytes)
    parser.add_argument("--answer-cap", type=int, default=defaults.answer_cap)
    parser.add_argument("--sandbox-probe", action="store_true")
    args = parser.parse_args()
    if args.sandbox_probe:
        print(json.dumps(run_sandbox_probe(), sort_keys=True, separators=(",", ":")))
        return 0
    payload = os.read(0, 2_000_001)
    bounds = ValidatorBounds(
        wall_timeout_ms=args.timeout_ms,
        max_input_bytes=args.max_input_bytes,
        max_output_bytes=args.max_output_bytes,
        answer_cap=args.answer_cap,
    )
    report = validate_canonical_n3(payload, fixture_ref=args.fixture_ref, bounds=bounds)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
