#!/usr/bin/env python3
"""Freeze the EEv2.2 protocol before the first model request."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path

from evals.execution_efficiency_v2.surfaces_v0_2 import (
    ARMS_V0_2,
    PORTABILITY_FACT,
    assert_single_delta,
    surface_facts,
)
from evals.execution_efficiency_v2.tasks_v0_2 import (
    REPEATS_V0_2,
    TASKS_V0_2,
    schedule_v0_2,
    validate_v0_2,
)
from llm_loop.config import load_settings
from llm_loop.factory import build_engine

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = Path(__file__).resolve().parent / "EEV22-MANIFEST.v0.2.json"


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


def _lfrt_json(settings, *args: str) -> dict:
    path = str(settings.lfrt_cli or "").strip()
    if not path:
        raise RuntimeError("EEv2.2 requires configured lfrt")
    proc = subprocess.run(
        [path, *args, "--json"],
        text=True,
        capture_output=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"lfrt {' '.join(args)} failed: {proc.stderr[-500:]}")
    return json.loads(proc.stdout)


def build_manifest(*, model_ref: str = "") -> dict:
    errors = validate_v0_2()
    if errors:
        raise RuntimeError("EEv2.2 task validation failed: " + "; ".join(errors))
    settings = load_settings()
    effective_model_ref = model_ref.strip() or settings.llm_model
    if effective_model_ref != "cognilocal/qwen3.8-flash-next":
        raise RuntimeError("EEv2.2 replication is frozen to current-default Qwen")
    observation = _lfrt_json(settings, "runtime-observation")
    status = _lfrt_json(settings, "status")
    runtime = observation.get("runtime") or {}
    status_data = status.get("data") or {}
    config = status_data.get("config") or {}
    activity = status_data.get("activity") or {}
    if (
        observation.get("ok") is not True
        or observation.get("state") != "observed"
        or runtime.get("type") != "llama-server"
        or runtime.get("backend") != "llama"
        or int(runtime.get("port") or 0) != 8901
        or int(runtime.get("n_parallel") or 0) != 1
        or str(config.get("alias") or "") != "qwen3.8-flash-next"
        or int(activity.get("est_conns") or 0) != 0
    ):
        raise RuntimeError("EEv2.2 local Qwen runtime precondition failed")
    with tempfile.TemporaryDirectory(prefix="lfl-eev22-freeze-") as td:
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
            surfaces = {arm: surface_facts(engine.registry, arm) for arm in ARMS_V0_2}
            if engine.llm_pool is None:
                raise RuntimeError("EEv2.2 requires production model-pool routing")
            client, provider_id, model_id = engine.llm_pool.get_resolved_client(
                effective_model_ref
            )
            return {
                "schema": "lfl-execution-efficiency-v2.2-manifest/v0.2",
                "model_request_started": False,
                "git_head": __import__("subprocess").check_output(
                    ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                ).strip(),
                "arms": list(ARMS_V0_2),
                "repeats": list(REPEATS_V0_2),
                "row_count": len(schedule_v0_2()),
                "task_ids": [task["id"] for task in TASKS_V0_2],
                "task_families": {task["id"]: task["family"] for task in TASKS_V0_2},
                "tasks_sha256": _sha_text(_stable(TASKS_V0_2)),
                "portability_fact": PORTABILITY_FACT,
                "portability_fact_sha256": _sha_text(PORTABILITY_FACT),
                "surface_facts": surfaces,
                "tool_set_equal": (
                    surfaces[ARMS_V0_2[0]]["effective_tool_names"]
                    == surfaces[ARMS_V0_2[1]]["effective_tool_names"]
                ),
                "surface_delta_chars": (
                    surfaces[ARMS_V0_2[1]]["openai_tools_chars"]
                    - surfaces[ARMS_V0_2[0]]["openai_tools_chars"]
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
                    ROOT / "evals/execution_efficiency_v2/scorer_v0_2.py"
                ),
                "task_source_sha256": _sha_file(
                    ROOT / "evals/execution_efficiency_v2/tasks_v0_2.py"
                ),
                "surface_source_sha256": _sha_file(
                    ROOT / "evals/execution_efficiency_v2/surfaces_v0_2.py"
                ),
                "runner_source_sha256": _sha_file(
                    ROOT / "evals/execution_efficiency_v2/run_v0_2.py"
                ),
                "base_scorer_sha256": _sha_file(
                    ROOT / "evals/execution_efficiency_v2/scorer.py"
                ),
                "cache_treatment": "forced_cache_prompt_false",
                "local_runtime": {
                    "contract": observation.get("contract"),
                    "backend": runtime.get("backend"),
                    "type": runtime.get("type"),
                    "model": runtime.get("model"),
                    "port": runtime.get("port"),
                    "n_parallel": runtime.get("n_parallel"),
                    "alias": config.get("alias"),
                    "ctx": config.get("ctx"),
                    "shards": config.get("shards"),
                },
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
                "production_app_service_restart": False,
                "local_model_runtime_switched_for_eval": True,
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
