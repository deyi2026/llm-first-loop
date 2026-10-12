#!/usr/bin/env python3
"""Freeze the EEv2.1 protocol before the first model request."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

from evals.execution_efficiency_v2.surfaces_v0_1 import (
    ARMS_V0_1,
    PORTABILITY_FACT,
    assert_single_delta,
    surface_facts,
)
from evals.execution_efficiency_v2.tasks_v0_1 import (
    REPEATS_V0_1,
    TASKS_V0_1,
    schedule_v0_1,
    validate_v0_1,
)
from llm_loop.config import load_settings
from llm_loop.factory import build_engine

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = Path(__file__).resolve().parent / "EEV21-MANIFEST.v0.1.json"


def _stable(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy_provider_registry(settings, target: Path) -> list[str]:
    source = Path(settings.data_dir)
    target.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for name in ("providers.local.json", "providers.json"):
        src = source / name
        if src.is_file():
            shutil.copy2(src, target / name)
            copied.append(name)
    return copied


def build_manifest(*, model_ref: str = "") -> dict:
    errors = validate_v0_1()
    if errors:
        raise RuntimeError("EEv2.1 task validation failed: " + "; ".join(errors))
    settings = load_settings()
    effective_model_ref = model_ref.strip() or settings.llm_model
    with tempfile.TemporaryDirectory(prefix="lfl-eev21-freeze-") as td:
        data_dir = Path(td) / "data"
        copied = _copy_provider_registry(settings, data_dir)
        engine = build_engine(
            replace(
                settings,
                data_dir=str(data_dir),
                learning_plane_enabled=False,
                method_reflection_mode="off",
            )
        )
        try:
            assert_single_delta(engine.registry)
            surfaces = {arm: surface_facts(engine.registry, arm) for arm in ARMS_V0_1}
            if engine.llm_pool is None:
                raise RuntimeError("EEv2.1 requires production model-pool routing")
            client, provider_id, model_id = engine.llm_pool.get_resolved_client(
                effective_model_ref
            )
            return {
                "schema": "lfl-execution-efficiency-v2.1-manifest/v0.1",
                "model_request_started": False,
                "git_head": __import__("subprocess").check_output(
                    ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                ).strip(),
                "arms": list(ARMS_V0_1),
                "repeats": list(REPEATS_V0_1),
                "row_count": len(schedule_v0_1()),
                "task_ids": [task["id"] for task in TASKS_V0_1],
                "task_families": {task["id"]: task["family"] for task in TASKS_V0_1},
                "tasks_sha256": _sha_text(_stable(TASKS_V0_1)),
                "portability_fact": PORTABILITY_FACT,
                "portability_fact_sha256": _sha_text(PORTABILITY_FACT),
                "surface_facts": surfaces,
                "tool_set_equal": (
                    surfaces[ARMS_V0_1[0]]["effective_tool_names"]
                    == surfaces[ARMS_V0_1[1]]["effective_tool_names"]
                ),
                "surface_delta_chars": (
                    surfaces[ARMS_V0_1[1]]["openai_tools_chars"]
                    - surfaces[ARMS_V0_1[0]]["openai_tools_chars"]
                ),
                "model_ref": effective_model_ref,
                "runtime_default_model_ref": settings.llm_model,
                "resolved_provider": provider_id,
                "resolved_model": model_id,
                "wire_protocol": client.wire_protocol,
                "reasoning_effort": settings.reasoning_effort,
                "tool_schema_lazy": bool(settings.tool_schema_lazy),
                "precheck_enabled": bool(settings.precheck_enabled),
                "provider_registry_files": copied,
                "scorer_sha256": _sha_file(
                    ROOT / "evals/execution_efficiency_v2/scorer.py"
                ),
                "task_source_sha256": _sha_file(
                    ROOT / "evals/execution_efficiency_v2/tasks_v0_1.py"
                ),
                "surface_source_sha256": _sha_file(
                    ROOT / "evals/execution_efficiency_v2/surfaces_v0_1.py"
                ),
                "runner_source_sha256": _sha_file(
                    ROOT / "evals/execution_efficiency_v2/run_v0_1.py"
                ),
                "cache_treatment": "provider_default_observed",
                "qualification_order": [
                    "verified_correctness_hard_gate",
                    "first_call_ready_v2",
                    "wrong_tool_and_argument_oracle_misses",
                    "mechanical_contract_and_runtime_failures",
                    "repair_paths",
                    "serial_barriers_and_wall_time",
                    "uncached_input_cache_hit_output_tokens",
                ],
                "weighted_score": None,
                "semantic_tool_hiding": False,
                "production_runtime_mutation": False,
            }
        finally:
            engine.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--model-ref", default="")
    args = ap.parse_args()
    payload = build_manifest(model_ref=args.model_ref)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
