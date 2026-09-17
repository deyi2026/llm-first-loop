from __future__ import annotations

import json
import runpy
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from llm_loop.semantic_logic import canonical_n3_bytes, project_document

ROOT = Path(__file__).resolve().parents[2]
HARNESS_PATH = ROOT / "tools/semantic_logic/n3_validator/harness.py"
HARNESS = runpy.run_path(str(HARNESS_PATH))
P1A = runpy.run_path(str(ROOT / "tests/unit/test_smc_semantic_logic_p1a.py"))

ValidatorBounds = HARNESS["ValidatorBounds"]
validate_canonical_n3 = HARNESS["validate_canonical_n3"]
verify_backend_identity = HARNESS["verify_backend_identity"]
run_sandbox_probe = HARNESS["run_sandbox_probe"]
backend_installation_available = HARNESS["backend_installation_available"]
CASE_BUILDERS = P1A["CASE_BUILDERS"]
MANIFEST = P1A["MANIFEST"]


def _manifest_cases() -> list[tuple[str, str]]:
    return [
        (str(gate["gate_id"]), str(case["fixture_id"]))
        for gate in MANIFEST["gates"]
        for case in gate["cases"]
    ]


def _case_wire(tmp_path: Path, gate_id: str, fixture_id: str) -> bytes:
    canonical = CASE_BUILDERS[fixture_id](tmp_path / fixture_id)
    graph = project_document(
        graph_id=fixture_id,
        document=canonical,
        domain="browser",
        source_ref=f"python_oracle:{gate_id}:{fixture_id}",
    )
    return canonical_n3_bytes(graph)


def _small_wire() -> bytes:
    graph = project_document(
        graph_id="p1c-small",
        document={"value": 1, "unknown": None},
        domain="test",
        source_ref="python_oracle:p1c-small",
    )
    return canonical_n3_bytes(graph)


BACKEND_READY = backend_installation_available()
LIVE_BACKEND = pytest.mark.skipif(
    not BACKEND_READY,
    reason="qualification-only pinned N3 backend is not installed in this checkout",
)


def test_p1c_reuses_exact_15_case_frozen_manifest() -> None:
    frozen = _manifest_cases()
    assert len(frozen) == 15
    assert len({fixture_id for _, fixture_id in frozen}) == 15
    assert set(CASE_BUILDERS) == {fixture_id for _, fixture_id in frozen}


def test_p1c_validator_is_outside_production_and_node_modules_is_untracked() -> None:
    validator_root = ROOT / "tools/semantic_logic/n3_validator"
    assert validator_root.is_dir()
    assert (validator_root / ".gitignore").read_text(encoding="utf-8") == "node_modules/\n"

    offenders: list[str] = []
    for path in (ROOT / "src/llm_loop").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "n3_validator" in text or "tools.semantic_logic" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_bounds_surface_and_input_caps_fail_closed_before_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    wire = _small_wire()
    globals_ = validate_canonical_n3.__globals__

    def forbidden_backend() -> dict[str, Any]:
        raise AssertionError("backend should not be reached")

    monkeypatch.setitem(globals_, "verify_backend_identity", forbidden_backend)

    report = validate_canonical_n3(
        wire,
        fixture_ref="bounds",
        bounds=ValidatorBounds(wall_timeout_ms=0),
    )
    assert (report["status"], report["stage"], report["reason"]) == (
        "fail_closed",
        "bounds",
        "wall_timeout_ms_out_of_range",
    )

    report = validate_canonical_n3(wire, fixture_ref="query", query_set=(b"x",))
    assert (report["status"], report["stage"], report["reason"]) == (
        "fail_closed",
        "surface",
        "query_or_rulepack_surface_not_qualified_p1c",
    )

    report = validate_canonical_n3(wire, fixture_ref="rulepack", rulepack=b"x")
    assert report["stage"] == "surface"

    report = validate_canonical_n3(
        wire,
        fixture_ref="input-cap",
        bounds=ValidatorBounds(max_input_bytes=len(wire) - 1),
    )
    assert (report["status"], report["stage"], report["reason"]) == (
        "fail_closed",
        "input_cap",
        "input_cap_exceeded",
    )


def test_noncanonical_or_builtin_surface_fails_before_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    globals_ = validate_canonical_n3.__globals__

    def forbidden_backend() -> dict[str, Any]:
        raise AssertionError("backend should not be reached")

    monkeypatch.setitem(globals_, "verify_backend_identity", forbidden_backend)

    report = validate_canonical_n3(b"not n3\n", fixture_ref="noncanonical")
    assert report["status"] == "fail_closed"
    assert report["stage"] == "canonical_preflight"
    assert str(report["reason"]).startswith("canonical_preflight_rejected:")

    report = validate_canonical_n3(
        _small_wire() + b"log:semantics\n",
        fixture_ref="builtin-marker",
    )
    assert report["status"] == "fail_closed"
    assert report["stage"] == "canonical_preflight"
    assert report["reason"] == "canonical_preflight_rejected:forbidden_builtin_marker"


def test_package_lock_tamper_is_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = Path(HARNESS["PACKAGE_LOCK"])
    tampered = tmp_path / "package-lock.json"
    payload = json.loads(original.read_text(encoding="utf-8"))
    payload["name"] = "tampered"
    tampered.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    globals_ = HARNESS["_load_lock"].__globals__
    monkeypatch.setitem(globals_, "PACKAGE_LOCK", tampered)
    with pytest.raises(ValueError, match="package_lock_hash_mismatch"):
        HARNESS["_load_lock"]()


@LIVE_BACKEND
def test_backend_identity_is_pinned_and_versioned() -> None:
    identity = verify_backend_identity()
    assert identity == {
        "backend_id": "eye-js-wasm",
        "eyereasoner_version": "21.1.18",
        "eyereasoner_integrity": HARNESS["PINNED_EYEREASONER_INTEGRITY"],
        "swipl_wasm_version": "7.0.10",
        "eye_version": "EYE v11.24.5 (2026-08-23)",
        "node_version": subprocess.check_output([shutil.which("node") or "node", "--version"], text=True).strip(),
        "package_lock_sha256": HARNESS["PINNED_LOCK_SHA256"],
    }


@LIVE_BACKEND
def test_sandbox_denies_network_host_write_and_child_process() -> None:
    result = run_sandbox_probe()
    assert result["status"] == "pass"
    assert result["network_denied"] is True
    assert result["host_file_write_denied"] is True
    assert result["child_process_denied"] is True
    assert result["forbidden_write_materialized"] is False


@LIVE_BACKEND
@pytest.mark.parametrize(("gate_id", "fixture_id"), _manifest_cases())
def test_all_15_frozen_cases_pass_restricted_pinned_backend(
    tmp_path: Path, gate_id: str, fixture_id: str
) -> None:
    wire = _case_wire(tmp_path, gate_id, fixture_id)
    report = validate_canonical_n3(wire, fixture_ref=fixture_id)

    assert report["schema"] == "smc.n3_validator_report.v0.1"
    assert report["status"] == "pass"
    assert report["stage"] == "complete"
    assert report["reason"] is None
    assert report["authority"] == "shadow_only"
    assert report["production_consumed"] is False
    assert report["backend_invoked"] is True
    assert report["profile"]["eye_restricted"] is True
    assert report["profile"]["query_surface"] == "disabled_p1c"
    assert report["profile"]["rulepack_surface"] == "disabled_p1c"
    assert report["profile"]["negation_as_failure"] == "forbidden"
    assert "--restricted" in report["fixed_eye_flags"]
    assert report["input"]["bytes"] == len(wire)
    assert report["output"]["bridge_exit_code"] == 0
    assert report["output"]["diagnostic_bytes"] == 0


@LIVE_BACKEND
def test_live_timeout_and_output_cap_fail_closed(tmp_path: Path) -> None:
    wire = _case_wire(tmp_path, "S1", "S1-object-grounding-compile")

    timed = validate_canonical_n3(
        wire,
        fixture_ref="timeout",
        bounds=ValidatorBounds(wall_timeout_ms=1),
    )
    assert (timed["status"], timed["stage"], timed["reason"]) == (
        "fail_closed",
        "backend",
        "wall_timeout",
    )

    capped = validate_canonical_n3(
        wire,
        fixture_ref="output-cap",
        bounds=ValidatorBounds(max_output_bytes=1_024),
    )
    assert capped["status"] == "fail_closed"
    assert capped["stage"] == "backend"
    assert capped["reason"] == "output_cap_exceeded"
    assert capped["output"]["reasoner_output_bytes"] > 1_024


@LIVE_BACKEND
def test_repeated_validation_has_stable_reasoner_output_hash(tmp_path: Path) -> None:
    wire = _case_wire(tmp_path, "S3", "S3-unknown-or-unstable-identity")
    first = validate_canonical_n3(wire, fixture_ref="repeat-1")
    second = validate_canonical_n3(wire, fixture_ref="repeat-2")

    assert first["status"] == second["status"] == "pass"
    assert first["output"]["reasoner_output_sha256"] == second["output"]["reasoner_output_sha256"]
    assert first["output"]["diagnostic_sha256"] == second["output"]["diagnostic_sha256"]
