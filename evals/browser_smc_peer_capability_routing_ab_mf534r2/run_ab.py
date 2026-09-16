#!/usr/bin/env python3
"""Serial frozen compact-description-only paired A/B routing qualification."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from evals.browser_smc_cognition_preserving_actuation_mf534 import run_mf534 as base  # noqa: E402
from evals.browser_smc_cognition_preserving_actuation_mf534.protocol import (  # noqa: E402
    ALLOWED_TOOLS,
    BROWSER_CAPABILITIES,
    MODEL_REF,
    TASKS,
    judge,
    prompt_for,
)
from evals.browser_smc_peer_capability_routing_ab_mf534r2.protocol import (  # noqa: E402
    PRODUCTION_ANCHOR,
    ROUTING_RED_COMMIT,
    SCHEMA,
    build_plan,
    plan_sha256,
    qualification_gate,
    routing_score,
)
from evals.browser_smc_peer_capability_routing_red_mf534r1.scorer import (  # noqa: E402
    compact_description_treatment,
    score_compact_boundary,
)

WORKER = HERE / "worker.py"
BASE_FIXTURE = REPO / "evals/browser_smc_cognition_preserving_actuation_mf534/fixture_server.py"
BASE_WORKER = REPO / "evals/browser_smc_cognition_preserving_actuation_mf534/worker.py"
RED_SCORER = REPO / "evals/browser_smc_peer_capability_routing_red_mf534r1/scorer.py"
MAX_ITERATIONS = base.MAX_ITERATIONS
WORKER_TIMEOUT_S = base.WORKER_TIMEOUT_S


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _surface_manifest(tmp_root: Path, arm: str) -> dict[str, Any]:
    run_dir = tmp_root / f"surface-{arm}"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    env = base._base_env(run_dir)
    env["LFL_BROWSER_PERCEPTION_CDP_URL"] = "http://127.0.0.1:9"
    env["LFL_BROWSER_PERCEPTION_TARGET_ID"] = "manifest-only"
    result_path = run_dir / "surface.json"
    proc = subprocess.run(
        [
            str(base.PYTHON),
            str(WORKER),
            "--arm",
            arm,
            "--surface-only",
            "--result-json",
            str(result_path),
        ],
        cwd=run_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"surface worker {arm} failed: {proc.stderr[-500:]}")
    doc = json.loads(result_path.read_text(encoding="utf-8"))
    if doc.get("resolved_max_iterations") != MAX_ITERATIONS:
        raise RuntimeError(f"surface worker {arm} max_iterations drift")
    surface = dict(doc["surface"])
    surface["routing_ab_arm"] = doc.get("routing_ab_arm")
    surface["compact_treatment_applied"] = doc.get("compact_treatment_applied")
    surface["compact_description_fingerprints"] = doc.get("compact_description_fingerprints")
    return surface


def _description_hypothesis() -> dict[str, Any]:
    from llm_loop.tools.registry import _COMPACT_TOOL_DESCRIPTIONS

    p_a = str(_COMPACT_TOOL_DESCRIPTIONS["browser_perceive"])
    o_a = str(_COMPACT_TOOL_DESCRIPTIONS["browser_operate"])
    p_b, o_b = compact_description_treatment(p_a, o_a)
    return {
        "A": {
            "perceive_sha256": _sha_text(p_a),
            "operate_sha256": _sha_text(o_a),
            "boundary_score": score_compact_boundary(p_a, o_a),
        },
        "B": {
            "perceive_sha256": _sha_text(p_b),
            "operate_sha256": _sha_text(o_b),
            "boundary_score": score_compact_boundary(p_b, o_b),
        },
    }


def execution_manifest(plan: list[dict[str, Any]], tmp_root: Path) -> dict[str, Any]:
    dirty = base._tracked_dirty()
    if dirty:
        raise RuntimeError(f"tracked worktree dirty before freeze: {dirty}")
    head = base._git("rev-parse", "HEAD")
    for required in (ROUTING_RED_COMMIT, PRODUCTION_ANCHOR):
        if (
            subprocess.run(
                ["git", "merge-base", "--is-ancestor", required, head],
                cwd=REPO,
                check=False,
            ).returncode
            != 0
        ):
            raise RuntimeError(f"required anchor is not ancestor: {required}")
    if (
        subprocess.run(
            ["git", "diff", "--quiet", PRODUCTION_ANCHOR, head, "--", "src", "methods"],
            cwd=REPO,
            check=False,
        ).returncode
        != 0
    ):
        raise RuntimeError("production src/methods changed after compact-description anchor")

    server = base._model_server_fact()
    if not server["prompt_concurrency_1"] or not server["decode_concurrency_1"]:
        raise RuntimeError("8901 is not prompt/decode concurrency=1")
    if not server["max_tokens_16000"]:
        raise RuntimeError("8901 max token contract drift")
    if server["model_basename"].lower() != "ornith-1.5-35b-a3b-mlx":
        raise RuntimeError(f"8901 model identity drift: {server['model_basename']}")

    provider = base._provider_contract()
    expected_provider = {
        "timeout_s": 1800,
        "max_input_tokens": 184000,
        "max_tokens": 16000,
        "temperature": 0.0,
        "top_p": 1.0,
        "top_k": 0,
        "min_p": 0.0,
        "wire_protocol": "openai",
    }
    if provider != expected_provider:
        raise RuntimeError(f"provider contract drift: {provider}")

    static_plan = json.loads((HERE / "PLAN.v0.1.json").read_text(encoding="utf-8"))
    if static_plan != plan:
        raise RuntimeError("PLAN.v0.1.json differs from protocol.build_plan()")
    if len(plan) != 12:
        raise RuntimeError("paired plan must contain 12 rows")

    prompt_sha = {
        task_id: hashlib.sha256(task.prompt_template.encode("utf-8")).hexdigest()
        for task_id, task in TASKS.items()
    }
    if prompt_sha != base.PROMPT_SHA256:
        raise RuntimeError(f"prompt template drift: {prompt_sha}")
    if _sha_file(BASE_FIXTURE) != base.FIXTURE_SHA256:
        raise RuntimeError("fixture bytes drifted from MF534")

    surfaces = {arm: _surface_manifest(tmp_root, arm) for arm in ("A", "B")}
    for arm, surface in surfaces.items():
        if not surface.get("exact") or set(surface.get("names") or []) != set(ALLOWED_TOOLS):
            raise RuntimeError(f"provider surface mismatch {arm}: {surface}")
        if set(surface.get("browser_capability_names") or []) != set(BROWSER_CAPABILITIES):
            raise RuntimeError(f"Browser capability surface drift {arm}")
        if surface.get("routing_ab_arm") != arm:
            raise RuntimeError(f"worker arm identity drift {arm}")
        if bool(surface.get("compact_treatment_applied")) != (arm == "B"):
            raise RuntimeError(f"treatment application drift {arm}")
        if surface.get("perceive_actions") != ["snapshot", "hydrate", "diff", "wait"]:
            raise RuntimeError(f"Perceive action surface drift {arm}")
        if set(surface.get("operation_verbs") or []) != {
            "navigate", "click", "set_text", "append_text", "select", "scroll"
        }:
            raise RuntimeError(f"Operate verbs drift {arm}")
        if surface.get("hidden_atomic_tools_present"):
            raise RuntimeError(f"hidden Browser tools leaked {arm}")
        if surface.get("cognition_contract_visible") is not True:
            raise RuntimeError(f"cognition contract drift {arm}")

    if surfaces["A"]["perceive_parameters_sha256"] != surfaces["B"]["perceive_parameters_sha256"]:
        raise RuntimeError("Perceive parameter schema differs between arms")
    if surfaces["A"]["operation_parameters_sha256"] != surfaces["B"]["operation_parameters_sha256"]:
        raise RuntimeError("Operate parameter schema differs between arms")
    if surfaces["A"]["full_surface_sha256"] != surfaces["B"]["full_surface_sha256"]:
        raise RuntimeError("full provider surface differs between arms")
    if surfaces["A"]["sha256"] == surfaces["B"]["sha256"]:
        raise RuntimeError("compact treatment did not change lazy provider surface")

    hypothesis = _description_hypothesis()
    if hypothesis["A"]["boundary_score"]["pass"] is not False:
        raise RuntimeError("A deterministic boundary RED unexpectedly green")
    if hypothesis["B"]["boundary_score"]["pass"] is not True:
        raise RuntimeError("B deterministic boundary hypothesis is not green")
    for arm in ("A", "B"):
        fp = surfaces[arm].get("compact_description_fingerprints") or {}
        if fp.get("browser_perceive_sha256") != hypothesis[arm]["perceive_sha256"]:
            raise RuntimeError(f"Perceive compact description hash drift {arm}")
        if fp.get("browser_operate_sha256") != hypothesis[arm]["operate_sha256"]:
            raise RuntimeError(f"Operate compact description hash drift {arm}")

    runtime_paths = base._git("ls-files", "src", "methods").splitlines()
    source_paths = [
        HERE / "protocol.py",
        HERE / "PROTOCOL.v0.1.md",
        HERE / "PLAN.v0.1.json",
        HERE / "worker.py",
        HERE / "run_ab.py",
        BASE_FIXTURE,
        BASE_WORKER,
        RED_SCORER,
        REPO / "src/llm_loop/tools/registry.py",
        REPO / "src/llm_loop/factory.py",
    ]
    return {
        "schema": SCHEMA + ".execution_manifest",
        "experiment_git_head": head,
        "routing_red_commit": ROUTING_RED_COMMIT,
        "production_anchor": PRODUCTION_ANCHOR,
        "production_diff_after_anchor": False,
        "tracked_dirty": False,
        "runtime_source_sha256": {path: _sha_file(REPO / path) for path in runtime_paths},
        "source_sha256": {str(path.relative_to(REPO)): _sha_file(path) for path in source_paths},
        "seed": 2026091701,
        "plan_sha256": plan_sha256(plan),
        "plan_rows": len(plan),
        "model_ref": MODEL_REF,
        "model_server": server,
        "provider_contract": provider,
        "surfaces": surfaces,
        "description_hypothesis": hypothesis,
        "task_prompt_sha256": prompt_sha,
        "fixture_sha256": _sha_file(BASE_FIXTURE),
        "description_only_identity": True,
        "runtime": {
            "thinking_mode": "on",
            "reasoning_effort": "medium",
            "max_iterations": MAX_ITERATIONS,
            "llm_timeout_s": 1800,
            "worker_timeout_s": WORKER_TIMEOUT_S,
            "max_tokens": 16000,
            "tool_schema_lazy": True,
            "evidence_mode": "enforce",
            "fallbacks": 0,
            "serial_model_runs": True,
            "second_local_model": False,
        },
    }


def _classify(
    *, oracle_pass: bool, worker_rc: int | None, worker: dict[str, Any], manifest: dict[str, Any], arm: str
) -> str:
    if worker_rc is None:
        return "TIMEOUT"
    if worker.get("status") != "RUN_OK":
        return "INFRA_FAIL"
    surface = worker.get("surface") or {}
    if set(surface.get("names") or []) != set(ALLOWED_TOOLS):
        return "INVALID"
    if surface.get("sha256") != manifest["surfaces"][arm]["sha256"]:
        return "INVALID"
    if worker.get("routing_ab_arm") != arm:
        return "INVALID"
    if worker.get("fallback_used"):
        return "INVALID"
    if worker.get("model_used") not in {None, "", MODEL_REF}:
        return "INVALID"
    return "PASS" if oracle_pass else "TASK_FAIL"


def run_row(row: dict[str, Any], root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    if base._git("rev-parse", "HEAD") != manifest["experiment_git_head"] or base._tracked_dirty():
        raise RuntimeError("git identity drift before measured row")
    if base._model_server_fact() != manifest["model_server"]:
        raise RuntimeError("8901 model server identity/config drift before measured row")
    for path, expected in manifest["runtime_source_sha256"].items():
        if _sha_file(REPO / path) != expected:
            raise RuntimeError(f"runtime source drift before measured row: {path}")
    base._wait_idle_or_fail()

    task_id = str(row["task_id"])
    arm = str(row["arm"])
    run_dir = root / f"{int(row['index']):02d}-{task_id}-r{int(row['repeat'])}-{arm}"
    if run_dir.exists():
        raise RuntimeError(f"run directory already exists: {run_dir.name}")
    run_dir.mkdir(parents=True)
    chrome_proc: subprocess.Popen[Any] | None = None
    before_security: set[int] = set()
    worker_rc: int | None = None
    worker: dict[str, Any] = {}
    oracle: dict[str, Any] = {"pass": False, "missing": True}
    started = time.monotonic()
    try:
        with base.FixtureServer(task_id) as fixture:
            env = base._base_env(run_dir)
            chrome_proc, debug_base, target_id, before_security = base._start_chrome(run_dir)
            env["LFL_BROWSER_PERCEPTION_CDP_URL"] = debug_base
            env["LFL_BROWSER_PERCEPTION_TARGET_ID"] = target_id
            result_path = run_dir / "worker-result.json"
            try:
                proc = subprocess.run(
                    [
                        str(base.PYTHON),
                        str(WORKER),
                        "--arm",
                        arm,
                        "--prompt",
                        prompt_for(task_id, fixture.url),
                        "--result-json",
                        str(result_path),
                    ],
                    cwd=run_dir,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=WORKER_TIMEOUT_S,
                )
                worker_rc = proc.returncode
            except subprocess.TimeoutExpired:
                worker_rc = None
            if result_path.is_file():
                worker = json.loads(result_path.read_text(encoding="utf-8"))
            else:
                startup = run_dir / "worker-startup.json"
                startup_doc = json.loads(startup.read_text(encoding="utf-8")) if startup.is_file() else {}
                worker = {"status": "TIMEOUT", "surface": startup_doc.get("surface")}
            oracle = judge(task_id, fixture.state.snapshot())
    finally:
        base._stop_process(chrome_proc)

    security_agent_spawned = bool(base._security_agent_pids() - before_security)
    status = _classify(
        oracle_pass=bool(oracle.get("pass")),
        worker_rc=worker_rc,
        worker=worker,
        manifest=manifest,
        arm=arm,
    )
    surface = worker.get("surface") or {}
    worker_without_surface = {key: value for key, value in worker.items() if key != "surface"}
    worker_without_surface.update(
        {
            "surface_sha256": surface.get("sha256"),
            "surface_exact": surface.get("exact") if surface else None,
            "surface_json_chars": surface.get("json_chars"),
        }
    )
    record = {
        **row,
        "schema": SCHEMA + ".run",
        "run_id": run_dir.name,
        "manifest_git_head": manifest["experiment_git_head"],
        "manifest_plan_sha256": manifest["plan_sha256"],
        "status": status,
        "oracle": oracle,
        "worker_rc": worker_rc,
        "worker": worker_without_surface,
        "security_agent_spawned": security_agent_spawned,
        "wall_s": round(time.monotonic() - started, 3),
    }
    record["routing"] = routing_score(record)
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--max-new-rows", type=int, default=1)
    args = parser.parse_args()
    if args.max_new_rows < 0:
        parser.error("--max-new-rows must be >=0")

    root = Path(args.workdir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    plan = build_plan()
    plan_path = root / "plan.json"
    if plan_path.exists():
        if json.loads(plan_path.read_text(encoding="utf-8")) != plan:
            raise RuntimeError("plan drift; refusing to mix evidence")
    else:
        _atomic_json(plan_path, plan)

    manifest = execution_manifest(plan, root)
    manifest_path = root / "execution-manifest.json"
    if manifest_path.exists():
        if json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
            raise RuntimeError("execution manifest drift; refusing to mix evidence")
    else:
        _atomic_json(manifest_path, manifest)

    results_path = root / "results.jsonl"
    existing: list[dict[str, Any]] = []
    if results_path.exists():
        existing = [json.loads(line) for line in results_path.read_text(encoding="utf-8").splitlines() if line]
    seen = [int(row.get("index") or 0) for row in existing]
    if len(seen) != len(set(seen)) or any(index not in range(1, len(plan) + 1) for index in seen):
        raise RuntimeError("existing results have duplicate/out-of-range row index")

    if args.max_new_rows == 0:
        print(
            json.dumps(
                {
                    "preflight": True,
                    "model_requests": 0,
                    "experiment_git_head": manifest["experiment_git_head"],
                    "plan_sha256": manifest["plan_sha256"],
                    "description_only_identity": manifest["description_only_identity"],
                    "surface_A_sha256": manifest["surfaces"]["A"]["sha256"],
                    "surface_B_sha256": manifest["surfaces"]["B"]["sha256"],
                    "perceive_parameters_equal": manifest["surfaces"]["A"]["perceive_parameters_sha256"]
                    == manifest["surfaces"]["B"]["perceive_parameters_sha256"],
                    "operate_parameters_equal": manifest["surfaces"]["A"]["operation_parameters_sha256"]
                    == manifest["surfaces"]["B"]["operation_parameters_sha256"],
                    "full_surface_equal": manifest["surfaces"]["A"]["full_surface_sha256"]
                    == manifest["surfaces"]["B"]["full_surface_sha256"],
                    "A_boundary_green": manifest["description_hypothesis"]["A"]["boundary_score"]["pass"],
                    "B_boundary_green": manifest["description_hypothesis"]["B"]["boundary_score"]["pass"],
                    "model_server": manifest["model_server"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    done = set(seen)
    pending = [row for row in plan if int(row["index"]) not in done][: args.max_new_rows]
    for row in pending:
        record = run_row(row, root, manifest)
        with results_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        existing.append(record)
        routing = record.get("routing") or {}
        print(
            json.dumps(
                {
                    "index": row["index"],
                    "pair": row["pair_id"],
                    "arm": row["arm"],
                    "status": record["status"],
                    "oracle": bool(record["oracle"].get("pass")),
                    "first_call_routing": routing.get("routing_verdict"),
                    "failure_kind": routing.get("failure_kind"),
                    "recovered_later": routing.get("recovered_later"),
                    "rounds": (record.get("worker") or {}).get("rounds"),
                    "protocol_repair": (record.get("worker") or {}).get("protocol_repair_episode_count"),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )

    if len(existing) == len(plan):
        gate = qualification_gate(existing)
        _atomic_json(root / "qualification-gate.json", gate)
        print(
            json.dumps(
                {
                    "qualification_complete": True,
                    "measurement_valid": gate["measurement_valid"],
                    "treatment_signal": gate["treatment_signal"],
                    "A_first_call_routing": gate["arms"]["A"]["first_call_routing_pass"],
                    "B_first_call_routing": gate["arms"]["B"]["first_call_routing_pass"],
                },
                sort_keys=True,
            )
        )
        return 0 if gate["measurement_valid"] else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
