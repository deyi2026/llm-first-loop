#!/usr/bin/env python3
"""Serial orchestrator for v0.6-A2.1 recovery-instrumented smoke."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

from fixture_server import FixtureServer  # noqa: E402
from protocol import (  # noqa: E402
    ARMS,
    MODEL_REF,
    SCHEMA,
    SEED,
    TASKS,
    build_plan,
    judge,
    plan_sha256,
    prompt_for,
    smoke_gate,
)

from evals.browser_smc_semantic_execute_recovery_smoke.observations import (  # noqa: E402
    atomic_json,
    declared_round,
    finalize_worker,
    run_profile,
)
from scripts.qualification.smc_browser_live_navigation import (  # noqa: E402
    _free_loopback_port,
    _security_agent_pids,
    _wait_page,
    chrome_args,
)

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
WORKER = HERE / "worker.py"
PROVIDERS = REPO / "data" / "providers.json"
MODEL_PORT = 8901
RUNTIME_REPO = REPO
PROFILE = run_profile("repeat12")
V05_PLAN_SHA256 = "490c1e2cd1b9377468eb07dc06d05b8950faf10db4b61748ff89af1005b8f878"
V05_FIXTURE_SHA256 = "87696076cea84d4e93f172d07a1499755dbc647f396ff115a9d64571740b72a3"
V05_PROMPT_SHA256 = {
    "click_commit": "823e7cb25a1f2f234412564a93ed221956bdbcb4214aff1d67a78fd9296c6f2d",
    "fill_submit": "d80607ace4193874d8b7deddc2988f8b6562443b99b54455e48163cc4a6ff9e2",
    "delayed_wait": "eb99aac9458104ca12770d07ce1886f9d3bd76f8955ce9b5135de33b476ae694",
}


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()


def _tracked_dirty() -> list[str]:
    out = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=REPO, text=True
    )
    return [line for line in out.splitlines() if line.strip()]


def _model_server_fact() -> dict[str, Any]:
    lines = subprocess.check_output(["ps", "-axo", "pid=,command="], text=True).splitlines()
    candidates = [
        line.strip() for line in lines if "mlx_lm.server" in line and f"--port {MODEL_PORT}" in line
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            f"expected one mlx_lm.server on {MODEL_PORT}, observed={len(candidates)}"
        )
    pid_raw, command = candidates[0].split(None, 1)
    parts = command.split()
    model_arg = parts[parts.index("--model") + 1] if "--model" in parts else ""
    return {
        "pid": int(pid_raw),
        "command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(),
        "model_basename": Path(model_arg).name if model_arg else "",
        "prompt_concurrency_1": "--prompt-concurrency 1" in command,
        "decode_concurrency_1": "--decode-concurrency 1" in command,
        "max_tokens_16000": "--max-tokens 16000" in command,
    }


def _provider_contract() -> dict[str, Any]:
    doc = json.loads(PROVIDERS.read_text(encoding="utf-8"))
    providers = doc.get("providers", doc) if isinstance(doc, dict) else {}
    provider = providers.get("cognilocal", {}) if isinstance(providers, dict) else {}
    models = provider.get("models") or {}
    model = models.get("ornith-1.5-35b-a3b-mlx", {}) if isinstance(models, dict) else {}
    return {
        "timeout_s": provider.get("timeout_s"),
        "max_input_tokens": provider.get("max_input_tokens"),
        "max_tokens": provider.get("max_tokens"),
        "temperature": model.get("temperature"),
        "top_p": model.get("top_p"),
        "top_k": model.get("top_k"),
        "min_p": model.get("min_p"),
        "wire_protocol": model.get("wire_protocol"),
    }


def _established_8901() -> list[str]:
    proc = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{MODEL_PORT}"], check=False, capture_output=True, text=True
    )
    return [line for line in proc.stdout.splitlines()[1:] if "LISTEN" not in line]


def _wait_idle_or_fail() -> None:
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if not _established_8901():
            return
        time.sleep(0.25)
    raise RuntimeError("8901 has an external established client; measured run refused")


def _base_env(run_dir: Path) -> dict[str, str]:
    data_dir = run_dir / ".lfldata"
    data_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PROVIDERS, data_dir / "providers.json")
    env = dict(os.environ)
    old_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join([str(RUNTIME_REPO / "src"), str(REPO), old_pp]).rstrip(
        os.pathsep
    )
    env.update(
        {
            "LLM_API_KEY": "local-eval",
            "SMC_EXPECTED_RUNTIME_ROOT": str(RUNTIME_REPO),
            "LLM_BASE_URL": "http://127.0.0.1:8901/v1",
            "LLM_MODEL": MODEL_REF,
            "LLM_THINKING_MODE": "on",
            "LLM_REASONING_EFFORT": "medium",
            "LLM_MAX_ITERATIONS": str(PROFILE["max_iterations"]),
            "LLM_TIMEOUT_S": "1800",
            "LLM_MAX_TOKENS": "16000",
            "MODEL_FALLBACKS": "",
            "RUN_MODE": "standard",
            "TOOL_SCHEMA_LAZY": "1",
            "DATA_DIR": str(data_dir),
            # FC2-A qualification requires the same production truncation path that
            # emits evidence:// recovery_ref facts; freeze it here rather than
            # inheriting a caller shell/.env state.
            "EVIDENCE_MODE": "enforce",
            "EXTRACT_ENABLED": "0",
            "SUMMARY_MODE": "off",
            "METHOD_REFLECTION_MODE": "off",
            "METHODS_DIR": str(data_dir / "methods"),
            "METHOD_SEED_DIR": str(RUNTIME_REPO / "methods"),
            "RUNNER_BACKGROUND": "0",
            "LFL_SMX_PERCEIVE": "",
            "MCP_SERVERS": "",
            "LFL_BROWSER_PERCEPTION_CDP_URL": "",
            "LFL_BROWSER_PERCEPTION_TARGET_ID": "",
            "LFL_BROWSER_ACTION_ENABLED": "1",
        }
    )
    return env


def _surface_manifest(arm: str, tmp_root: Path) -> dict[str, Any]:
    run_dir = tmp_root / f"surface-{arm}"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    env = _base_env(run_dir)
    env["LFL_BROWSER_PERCEPTION_CDP_URL"] = "http://127.0.0.1:9"
    env["LFL_BROWSER_PERCEPTION_TARGET_ID"] = "manifest-only"
    result_path = run_dir / "surface.json"
    proc = subprocess.run(
        [
            str(REPO / ".venv/bin/python"),
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
        raise RuntimeError(f"surface worker failed arm={arm}: {proc.stderr[-500:]}")
    doc = json.loads(result_path.read_text(encoding="utf-8"))
    if doc.get("resolved_max_iterations") != PROFILE["max_iterations"]:
        raise RuntimeError("worker resolved round ceiling differs from manifest")
    return dict(doc["surface"])


def execution_manifest(plan: list[dict[str, Any]], tmp_root: Path) -> dict[str, Any]:
    dirty = _tracked_dirty()
    if dirty:
        raise RuntimeError(f"tracked working tree is dirty before model execution: {dirty}")
    runtime_head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=RUNTIME_REPO, text=True
    ).strip()
    runtime_dirty = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=RUNTIME_REPO, text=True
    ).strip()
    if runtime_dirty:
        raise RuntimeError("runtime source tree is dirty")
    runtime_paths = subprocess.check_output(
        ["git", "ls-files", "src", "methods"], cwd=RUNTIME_REPO, text=True
    ).splitlines()
    runtime_hashes = {p: _sha_file(RUNTIME_REPO / p) for p in runtime_paths}
    server = _model_server_fact()
    if not server["prompt_concurrency_1"] or not server["decode_concurrency_1"]:
        raise RuntimeError("8901 concurrency identity is not the frozen single-run configuration")
    provider_contract = _provider_contract()
    expected_provider_contract = {
        "timeout_s": 1800,
        "max_input_tokens": 184000,
        "max_tokens": 16000,
        "temperature": 0.0,
        "top_p": 1.0,
        "top_k": 0,
        "min_p": 0.0,
        "wire_protocol": "openai",
    }
    if provider_contract != expected_provider_contract:
        raise RuntimeError(f"cognilocal provider contract drift: {provider_contract}")

    current_plan_sha = plan_sha256(plan)
    if current_plan_sha != V05_PLAN_SHA256:
        raise RuntimeError(f"A2 plan drifted from frozen v0.5 matrix: {current_plan_sha}")
    if _sha_file(HERE / "fixture_server.py") != V05_FIXTURE_SHA256:
        raise RuntimeError("A2 fixture is not byte-identical to frozen v0.5 fixture")
    current_prompt_sha = {
        task_id: hashlib.sha256(task.prompt_template.encode("utf-8")).hexdigest()
        for task_id, task in TASKS.items()
    }
    if current_prompt_sha != V05_PROMPT_SHA256:
        raise RuntimeError(f"A2 prompt templates drifted from v0.5: {current_prompt_sha}")

    surfaces = {arm: _surface_manifest(arm, tmp_root) for arm in ARMS}
    for arm, surface in surfaces.items():
        if not surface.get("exact") or set(surface.get("names") or []) != set(
            ARMS[arm]["allowed_tools"]
        ):
            raise RuntimeError(f"surface mismatch arm={arm}: {surface}")
    semantic = surfaces["semantic_execute"]
    if semantic.get("perceive_actions") != ["snapshot", "hydrate", "diff"] or semantic.get(
        "perceive_has_predicate"
    ):
        raise RuntimeError("browser_perceive split surface drift")
    if set(semantic.get("mutation_parameter_names") or []) != {"verb", "target_ref", "args"}:
        raise RuntimeError("semantic_execute did not expose the frozen three-field contract")
    if not semantic.get("semantic_usage_visible"):
        raise RuntimeError("semantic_execute compact description lost its use path")
    expected_required = {
        "browser_wait_scope_url": {"scope_ref", "operator", "value", "timeout_ms", "interval_ms"},
        "browser_wait_scope_ready": {"scope_ref", "state", "timeout_ms", "interval_ms"},
        "browser_wait_scope_count": {"scope_ref", "operator", "count", "timeout_ms", "interval_ms"},
        "browser_wait_object_state": {
            "object_ref",
            "property",
            "value",
            "timeout_ms",
            "interval_ms",
        },
        "browser_wait_object_text": {
            "object_ref",
            "property",
            "operator",
            "value",
            "timeout_ms",
            "interval_ms",
        },
    }
    actual_required = semantic.get("wait_required") or {}
    if set(actual_required) != set(expected_required) or any(
        set(actual_required.get(name) or []) != required
        for name, required in expected_required.items()
    ):
        raise RuntimeError("mechanically typed wait required-field drift")
    for name, spec in (semantic.get("wait_interval") or {}).items():
        if name not in expected_required or spec != {
            "type": "integer",
            "minimum": 1,
            "maximum": 5000,
        }:
            raise RuntimeError(f"typed wait interval drift: {name}")
    if semantic.get("ready_state_schema") != {
        "type": "string",
        "enum": ["loading", "interactive", "complete"],
    }:
        raise RuntimeError("ready-state provider schema drift")
    if semantic.get("object_state_value_schema") != {"type": "boolean"}:
        raise RuntimeError("object-state boolean schema drift")
    if semantic.get("scope_count_schema") != {"type": "integer", "minimum": 0}:
        raise RuntimeError("scope-count integer schema drift")
    if "visible" in set(semantic.get("object_state_properties") or []):
        raise RuntimeError("unsupported live visible capability leaked into provider surface")
    if semantic.get("old_generic_wait_present"):
        raise RuntimeError("old generic wait tools leaked into A2 provider surface")

    source_paths = [
        HERE / "protocol.py",
        HERE / "PROTOCOL.v0.6-A2.md",
        HERE / "PROTOCOL.v0.8-REPEAT-DIAGNOSTIC.md",
        HERE / "PLAN.v0.6-A2.json",
        HERE / "fixture_server.py",
        HERE / "worker.py",
        HERE / "run_a2.py",
        HERE / "observations.py",
        HERE / "audit_observations.py",
        REPO / "src/llm_loop/tools/builtin/browser_semantic_execute.py",
        REPO / "src/llm_loop/tools/builtin/browser_perceive.py",
        REPO / "src/llm_loop/tools/builtin/browser_wait.py",
        REPO / "src/llm_loop/browser/cdp_host.py",
        REPO / "src/llm_loop/browser/perception.py",
        REPO / "src/llm_loop/browser/action.py",
        REPO / "src/llm_loop/browser/cdp_action_host.py",
        REPO / "src/llm_loop/browser/method_card.py",
        REPO / "src/llm_loop/tools/registry.py",
        REPO / "scripts/qualification/smc_browser_live_semantic_execute.py",
    ]
    return {
        "schema": SCHEMA + ".execution_manifest",
        "git_head": _git("rev-parse", "HEAD"),
        "runtime_git_head": runtime_head,
        "runtime_source_sha256": runtime_hashes,
        "experiment_profile": dict(PROFILE),
        "tracked_dirty": False,
        "seed": SEED,
        "plan_sha256": current_plan_sha,
        "plan_rows": len(plan),
        "model_ref": MODEL_REF,
        "model_server": server,
        "provider_contract": provider_contract,
        "surfaces": surfaces,
        "treatment": {
            "mode": "semantic_execute_plus_mechanically_typed_wait_a2",
            "mutation_tool": "browser_semantic_execute",
            "legacy_full_action_in_gate": False,
            "method_discovery_tool_exposed": False,
            "v05_plan_identity_preserved": True,
            "v05_fixture_identity_preserved": True,
            "v05_prompt_identity_preserved": True,
        },
        "source_sha256": {str(path.relative_to(REPO)): _sha_file(path) for path in source_paths},
        "task_prompt_sha256": current_prompt_sha,
        "runtime": {
            "thinking_mode": "on",
            "reasoning_effort": "medium",
            "max_iterations": PROFILE["max_iterations"],
            "llm_timeout_s": 1800,
            "worker_timeout_s": 240,
            "max_tokens": 16000,
            "tool_schema_lazy": True,
            "fallbacks": 0,
            "extract_enabled": False,
            "summary_mode": "off",
            "method_reflection_mode": "off",
            "serial_model_runs": True,
        },
    }


def _start_smc_chrome(
    run_dir: Path,
) -> tuple[subprocess.Popen[bytes], str, str, set[int]]:
    port = _free_loopback_port()
    debug_base = f"http://127.0.0.1:{port}"
    profile = run_dir / "chrome-profile"
    before_security = _security_agent_pids()
    process = subprocess.Popen(
        chrome_args(CHROME, profile, port),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    target = _wait_page(debug_base)
    target_id = str(target.get("id") or "")
    if not target_id:
        raise RuntimeError("SMC Chrome target missing exact id")
    return process, debug_base, target_id, before_security


def _stop_process(process: subprocess.Popen[Any] | None) -> None:
    if process is None:
        return
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=3.0)


def _classify_run_status(
    *,
    oracle_pass: bool,
    worker_rc: int | None,
    worker_payload: dict[str, Any],
    surface: dict[str, Any],
    allowed_tools: set[str],
    manifest_surface: dict[str, Any],
) -> str:
    if worker_rc is None:
        return "TIMEOUT"
    if worker_payload.get("status") != "RUN_OK":
        return "INFRA_FAIL"
    if set(surface.get("names") or []) != allowed_tools:
        return "INVALID"
    if surface.get("sha256") != manifest_surface.get("sha256"):
        return "INVALID"
    if worker_payload.get("fallback_used"):
        return "INVALID"
    if worker_payload.get("model_used") not in {None, "", MODEL_REF}:
        return "INVALID"
    return "PASS" if oracle_pass else "TASK_FAIL"


def run_row(row: dict[str, Any], root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    if _git("rev-parse", "HEAD") != manifest["git_head"] or _tracked_dirty():
        raise RuntimeError("git identity drift before measured run")
    if _model_server_fact() != manifest["model_server"]:
        raise RuntimeError("8901 model server identity/config drift before measured run")
    for path, expected in manifest["runtime_source_sha256"].items():
        if _sha_file(RUNTIME_REPO / path) != expected:
            raise RuntimeError(f"runtime source drift: {path}")
    _wait_idle_or_fail()
    task_id = str(row["task_id"])
    arm = str(row["arm"])
    run_dir = root / f"{int(row['index']):02d}-{task_id}-r{row['repeat']}-{arm}"
    if run_dir.exists():
        raise RuntimeError(f"run directory already exists: {run_dir.name}")
    run_dir.mkdir(parents=True)
    chrome_proc: subprocess.Popen[Any] | None = None
    before_security: set[int] = set()
    started = time.monotonic()
    worker_payload: dict[str, Any] = {}
    worker_rc: int | None = None
    oracle: dict[str, Any] = {"pass": False, "missing": True}
    try:
        with FixtureServer(task_id) as fixture:
            original_record = fixture.state.record

            def record_with_observation(event: dict[str, Any]) -> None:
                original_record(event)
                observation = {
                    "round": declared_round(run_dir),
                    "oracle": judge(task_id, fixture.state.snapshot()),
                }
                with (run_dir / "oracle-observations.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(observation, sort_keys=True) + "\n")
                    handle.flush()

            fixture.state.record = record_with_observation
            env = _base_env(run_dir)
            chrome_proc, debug_base, target_id, before_security = _start_smc_chrome(run_dir)
            env["LFL_BROWSER_PERCEPTION_CDP_URL"] = debug_base
            env["LFL_BROWSER_PERCEPTION_TARGET_ID"] = target_id
            prompt = prompt_for(task_id, fixture.url)
            result_path = run_dir / "worker-result.json"
            try:
                proc = subprocess.run(
                    [
                        str(REPO / ".venv/bin/python"),
                        str(WORKER),
                        "--arm",
                        arm,
                        "--prompt",
                        prompt,
                        "--result-json",
                        str(result_path),
                    ],
                    cwd=run_dir,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=PROFILE["worker_timeout_s"],
                )
                worker_rc = proc.returncode
            except subprocess.TimeoutExpired:
                worker_rc = None
            worker_payload = finalize_worker(run_dir, timed_out=worker_rc is None)
            oracle = judge(task_id, fixture.state.snapshot())
    finally:
        _stop_process(chrome_proc)

    security_agent_spawned = bool(_security_agent_pids() - before_security)
    surface = worker_payload.get("surface") or {}
    status = _classify_run_status(
        oracle_pass=bool(oracle.get("pass")),
        worker_rc=worker_rc,
        worker_payload=worker_payload,
        surface=surface,
        allowed_tools=set(ARMS[arm]["allowed_tools"]),
        manifest_surface=manifest["surfaces"][arm],
    )
    return {
        **row,
        "schema": SCHEMA + ".run",
        "run_id": run_dir.name,
        "manifest_git_head": manifest["git_head"],
        "manifest_plan_sha256": manifest["plan_sha256"],
        "status": status,
        "oracle": oracle,
        "worker_rc": worker_rc,
        "worker": {key: value for key, value in worker_payload.items() if key != "surface"}
        | {
            "surface_sha256": surface.get("sha256"),
            "surface_exact": surface.get("exact") if surface else None,
            "surface_json_chars": surface.get("json_chars"),
        },
        "security_agent_spawned": security_agent_spawned,
        "wall_s": round(time.monotonic() - started, 3),
    }


def main() -> int:
    global RUNTIME_REPO, PROFILE
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--max-new-rows", type=int, default=1)
    parser.add_argument("--runtime-root", type=Path, default=REPO)
    parser.add_argument("--profile", choices=["repeat12", "diagnostic16"], default="repeat12")
    args = parser.parse_args()
    RUNTIME_REPO = args.runtime_root.resolve()
    PROFILE = run_profile(args.profile)
    if args.max_new_rows < 0:
        parser.error("--max-new-rows must be >= 0")
    root = Path(args.workdir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    plan = build_plan()
    plan_path = root / "plan.json"
    plan_path.write_text(
        json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest = execution_manifest(plan, root)
    manifest_path = root / "execution-manifest.json"
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing != manifest:
            raise RuntimeError("execution manifest drift; refusing to mix evidence")
    else:
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    results_path = root / "results.jsonl"
    existing_rows: list[dict[str, Any]] = []
    if results_path.exists():
        existing_rows = [
            json.loads(line)
            for line in results_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    done = {int(row["index"]) for row in existing_rows}
    pending = [row for row in plan if int(row["index"]) not in done][: args.max_new_rows]
    for row in pending:
        record = run_row(row, root, manifest)
        with results_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        existing_rows.append(record)
        print(
            json.dumps(
                {
                    "index": row["index"],
                    "task": row["task_id"],
                    "arm": row["arm"],
                    "status": record["status"],
                    "oracle": record["oracle"].get("pass"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    if len(existing_rows) == len(plan):
        gate = smoke_gate(existing_rows)
        if not PROFILE["qualification_eligible"]:
            atomic_json(
                root / "diagnostic-summary.json",
                {
                    "qualification_eligible": False,
                    "profile": dict(PROFILE),
                    "task_pass": sum(bool(row["oracle"].get("pass")) for row in existing_rows),
                    "timeout_rows": sum(row["status"] == "TIMEOUT" for row in existing_rows),
                    "rows": [
                        {"index": row["index"], "status": row["status"]} for row in existing_rows
                    ],
                },
            )
            print(
                json.dumps({"diagnostic_complete": True, "qualification_eligible": False}),
                flush=True,
            )
            return 0
        (root / "smoke-gate.json").write_text(
            json.dumps(gate, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps({"smoke_gate": gate}, ensure_ascii=False), flush=True)
        return 0 if gate["pass"] else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
