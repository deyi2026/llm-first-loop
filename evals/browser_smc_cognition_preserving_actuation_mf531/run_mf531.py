#!/usr/bin/env python3
"""Serial frozen MF-5.3.1 root-direct Perceive+Operate qualification runner. --max-new-rows=0 is zero-model preflight."""

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
    ALLOWED_TOOLS,
    BROWSER_CAPABILITIES,
    IMPLEMENTATION_COMMIT,
    MODEL_REF,
    ROWS,
    SCHEMA,
    SEED,
    TASKS,
    build_plan,
    judge,
    plan_sha256,
    prompt_for,
    qualification_gate,
)

from scripts.qualification.smc_browser_live_navigation import (  # noqa: E402
    _free_loopback_port,
    _security_agent_pids,
    _wait_page,
    chrome_args,
)

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
WORKER = HERE / "worker.py"
GIT_COMMON_DIR = Path(
    subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=REPO,
        text=True,
    ).strip()
).resolve()
PRIMARY_REPO = GIT_COMMON_DIR.parent
PYTHON = PRIMARY_REPO / ".venv/bin/python"
PROVIDERS = PRIMARY_REPO / "data/providers.json"
MODEL_PORT = 8901
MAX_ITERATIONS = 12
WORKER_TIMEOUT_S = 240
FIXTURE_SHA256 = "87696076cea84d4e93f172d07a1499755dbc647f396ff115a9d64571740b72a3"
PROMPT_SHA256 = {
    "click_commit": "823e7cb25a1f2f234412564a93ed221956bdbcb4214aff1d67a78fd9296c6f2d",
    "fill_submit": "d80607ace4193874d8b7deddc2988f8b6562443b99b54455e48163cc4a6ff9e2",
    "delayed_wait": "eb99aac9458104ca12770d07ce1886f9d3bd76f8955ce9b5135de33b476ae694",
}


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


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()


def _tracked_dirty() -> list[str]:
    out = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=REPO,
        text=True,
    )
    return [line for line in out.splitlines() if line.strip()]


def _model_server_fact() -> dict[str, Any]:
    lines = subprocess.check_output(["ps", "-axo", "pid=,command="], text=True).splitlines()
    candidates = [
        line.strip() for line in lines if "mlx_lm.server" in line and f"--port {MODEL_PORT}" in line
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            f"expected exactly one mlx_lm.server on {MODEL_PORT}; observed={len(candidates)}"
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
        ["lsof", "-nP", f"-iTCP:{MODEL_PORT}"],
        check=False,
        capture_output=True,
        text=True,
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
    env["PYTHONPATH"] = os.pathsep.join([str(REPO / "src"), str(REPO), old_pp]).rstrip(os.pathsep)
    env.update(
        {
            "LLM_API_KEY": "local-eval",
            "SMC_EXPECTED_RUNTIME_ROOT": str(REPO),
            "LLM_BASE_URL": "http://127.0.0.1:8901/v1",
            "LLM_MODEL": MODEL_REF,
            "LLM_THINKING_MODE": "on",
            "LLM_REASONING_EFFORT": "medium",
            "LLM_MAX_ITERATIONS": str(MAX_ITERATIONS),
            "LLM_TIMEOUT_S": "1800",
            "LLM_MAX_TOKENS": "16000",
            "MODEL_FALLBACKS": "",
            "RUN_MODE": "standard",
            "TOOL_SCHEMA_LAZY": "1",
            "DATA_DIR": str(data_dir),
            "EVIDENCE_MODE": "enforce",
            "EXTRACT_ENABLED": "0",
            "SUMMARY_MODE": "off",
            "METHOD_REFLECTION_MODE": "off",
            "METHODS_DIR": str(data_dir / "methods"),
            "METHOD_SEED_DIR": str(REPO / "methods"),
            "RUNNER_BACKGROUND": "0",
            "LFL_SMX_PERCEIVE": "",
            "MCP_SERVERS": "",
            "LFL_BROWSER_PERCEPTION_CDP_URL": "",
            "LFL_BROWSER_PERCEPTION_TARGET_ID": "",
            "LFL_BROWSER_ACTION_ENABLED": "1",
        }
    )
    return env


def _surface_manifest(tmp_root: Path) -> dict[str, Any]:
    run_dir = tmp_root / "surface-perceive-operate"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    env = _base_env(run_dir)
    env["LFL_BROWSER_PERCEPTION_CDP_URL"] = "http://127.0.0.1:9"
    env["LFL_BROWSER_PERCEPTION_TARGET_ID"] = "manifest-only"
    result_path = run_dir / "surface.json"
    proc = subprocess.run(
        [
            str(PYTHON),
            str(WORKER),
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
        raise RuntimeError(f"surface worker failed: {proc.stderr[-500:]}")
    doc = json.loads(result_path.read_text(encoding="utf-8"))
    if doc.get("resolved_max_iterations") != MAX_ITERATIONS:
        raise RuntimeError("surface worker max_iterations drift")
    return dict(doc["surface"])


def execution_manifest(plan: list[dict[str, Any]], tmp_root: Path) -> dict[str, Any]:
    dirty = _tracked_dirty()
    if dirty:
        raise RuntimeError(f"tracked worktree dirty before freeze: {dirty}")
    head = _git("rev-parse", "HEAD")
    if (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", IMPLEMENTATION_COMMIT, head],
            cwd=REPO,
            check=False,
        ).returncode
        != 0
    ):
        raise RuntimeError("MF-5.3.1 implementation commit is not an ancestor of experiment head")
    if (
        subprocess.run(
            ["git", "diff", "--quiet", IMPLEMENTATION_COMMIT, head, "--", "src", "methods"],
            cwd=REPO,
            check=False,
        ).returncode
        != 0
    ):
        raise RuntimeError("production src/methods changed after MF-5.3.1 implementation commit")

    server = _model_server_fact()
    if not server["prompt_concurrency_1"] or not server["decode_concurrency_1"]:
        raise RuntimeError("8901 is not prompt/decode concurrency=1")
    if not server["max_tokens_16000"]:
        raise RuntimeError("8901 max token contract drift")
    if server["model_basename"].lower() != "ornith-1.5-35b-a3b-mlx".lower():
        raise RuntimeError(f"8901 model identity drift: {server['model_basename']}")

    provider = _provider_contract()
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
        raise RuntimeError("committed PLAN.v0.1.json differs from protocol.build_plan()")
    if [(row["task_id"], row["repeat"]) for row in plan] != list(ROWS):
        raise RuntimeError("six-row task/repeat order drift")
    if _sha_file(HERE / "fixture_server.py") != FIXTURE_SHA256:
        raise RuntimeError("fixture bytes drifted from prior matrix")
    prompt_sha = {
        task_id: hashlib.sha256(task.prompt_template.encode("utf-8")).hexdigest()
        for task_id, task in TASKS.items()
    }
    if prompt_sha != PROMPT_SHA256:
        raise RuntimeError(f"prompt template drift: {prompt_sha}")

    surface = _surface_manifest(tmp_root)
    if not surface.get("exact") or set(surface.get("names") or []) != set(ALLOWED_TOOLS):
        raise RuntimeError(f"provider surface mismatch: {surface}")
    if surface.get("browser_capabilities_exact") is not True:
        raise RuntimeError(f"Browser capability surface drift: {surface.get('browser_capability_names')}")
    if set(surface.get("browser_capability_names") or []) != set(BROWSER_CAPABILITIES):
        raise RuntimeError("MF-5.3.1 must expose exactly Perceive+Operate as Browser capabilities")
    if surface.get("perceive_actions") != ["snapshot", "hydrate", "diff", "wait"]:
        raise RuntimeError(f"Perceive action surface drift: {surface.get('perceive_actions')}")
    if set(surface.get("perceive_wait_kinds") or []) != {
        "page_ready", "page_url", "object_state", "object_text"
    }:
        raise RuntimeError(f"Perceive wait kind drift: {surface.get('perceive_wait_kinds')}")
    expected_perceive = [
        {"action": "snapshot", "kind": "", "fields": ["action", "projection_limit"], "required": ["action"], "closed": True},
        {"action": "hydrate", "kind": "", "fields": ["action", "grounding_ref"], "required": ["action", "grounding_ref"], "closed": True},
        {"action": "diff", "kind": "", "fields": ["action", "from_version", "to_version"], "required": ["action", "from_version", "to_version"], "closed": True},
        {"action": "wait", "kind": "page_ready", "fields": ["action", "kind", "state", "within_ms"], "required": ["action", "kind", "state"], "closed": True},
        {"action": "wait", "kind": "page_url", "fields": ["action", "kind", "match", "url", "within_ms"], "required": ["action", "kind", "match", "url"], "closed": True},
        {"action": "wait", "kind": "object_state", "fields": ["action", "kind", "object_ref", "state", "value", "within_ms"], "required": ["action", "kind", "object_ref", "state", "value"], "closed": True},
        {"action": "wait", "kind": "object_text", "fields": ["action", "field", "kind", "match", "object_ref", "text", "within_ms"], "required": ["action", "field", "kind", "match", "object_ref", "text"], "closed": True},
    ]
    if surface.get("perceive_root_direct") is not True:
        raise RuntimeError("Perceive root-direct oneOf missing")
    if surface.get("perceive_branch_count") != 7:
        raise RuntimeError(f"Perceive branch count drift: {surface.get('perceive_branch_count')}")
    if surface.get("perceive_branch_signatures") != expected_perceive:
        raise RuntimeError(f"Perceive root branch drift: {surface.get('perceive_branch_signatures')}")
    if surface.get("perceive_lazy_full_branch_equal") is not True:
        raise RuntimeError("Perceive lazy/full root branches diverged")
    if surface.get("perceive_has_nested_condition"):
        raise RuntimeError("Perceive leaked nested condition into provider contract")
    if surface.get("perceive_exposes_poll_interval"):
        raise RuntimeError("Perceive leaked runtime polling cadence into provider contract")
    if surface.get("full_perceive_recursive_closed") is not True:
        raise RuntimeError("full Perceive schema is not recursively closed")
    if surface.get("operation_direct_root") is not True or surface.get("operation_has_steps"):
        raise RuntimeError("Operate must be direct-root single mutation without steps")
    if set(surface.get("operation_verbs") or []) != {
        "navigate", "click", "set_text", "append_text", "select", "scroll"
    }:
        raise RuntimeError(f"Operate verb surface drift: {surface.get('operation_verbs')}")
    if surface.get("full_operation_recursive_closed") is not True:
        raise RuntimeError("full Operate schema is not recursively closed")
    if surface.get("hidden_atomic_tools_present"):
        raise RuntimeError("hidden atomic Browser tools leaked into treatment surface")
    if surface.get("cognition_contract_visible") is not True:
        raise RuntimeError("cognition-preserving Perceive+Operate description drift")

    runtime_paths = _git("ls-files", "src", "methods").splitlines()
    source_paths = [
        HERE / "protocol.py",
        HERE / "PROTOCOL.v0.1.md",
        HERE / "PLAN.v0.1.json",
        HERE / "fixture_server.py",
        HERE / "worker.py",
        HERE / "run_mf531.py",
        REPO / "src/llm_loop/tools/builtin/browser_perceive.py",
        REPO / "src/llm_loop/tools/builtin/browser_semantic_operation.py",
        REPO / "src/llm_loop/tools/builtin/browser_semantic_execute.py",
        REPO / "src/llm_loop/tools/builtin/browser_wait.py",
        REPO / "src/llm_loop/browser/perception.py",
        REPO / "src/llm_loop/browser/action.py",
        REPO / "src/llm_loop/tools/registry.py",
        REPO / "src/llm_loop/factory.py",
    ]
    return {
        "schema": SCHEMA + ".execution_manifest",
        "experiment_git_head": head,
        "implementation_commit": IMPLEMENTATION_COMMIT,
        "production_diff_after_implementation": False,
        "tracked_dirty": False,
        "runtime_source_sha256": {path: _sha_file(REPO / path) for path in runtime_paths},
        "seed": SEED,
        "plan_sha256": plan_sha256(plan),
        "plan_rows": len(plan),
        "model_ref": MODEL_REF,
        "model_server": server,
        "provider_contract": provider,
        "surface": surface,
        "source_sha256": {str(path.relative_to(REPO)): _sha_file(path) for path in source_paths},
        "task_prompt_sha256": prompt_sha,
        "fixture_sha256": _sha_file(HERE / "fixture_server.py"),
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
        },
    }


def _start_chrome(run_dir: Path) -> tuple[subprocess.Popen[bytes], str, str, set[int]]:
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


def _classify(
    *,
    oracle_pass: bool,
    worker_rc: int | None,
    worker: dict[str, Any],
    manifest: dict[str, Any],
) -> str:
    if worker_rc is None:
        return "TIMEOUT"
    if worker.get("status") != "RUN_OK":
        return "INFRA_FAIL"
    surface = worker.get("surface") or {}
    if set(surface.get("names") or []) != set(ALLOWED_TOOLS):
        return "INVALID"
    if surface.get("sha256") != (manifest.get("surface") or {}).get("sha256"):
        return "INVALID"
    if worker.get("fallback_used"):
        return "INVALID"
    if worker.get("model_used") not in {None, "", MODEL_REF}:
        return "INVALID"
    return "PASS" if oracle_pass else "TASK_FAIL"


def run_row(row: dict[str, Any], root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    if _git("rev-parse", "HEAD") != manifest["experiment_git_head"] or _tracked_dirty():
        raise RuntimeError("git identity drift before measured row")
    if _model_server_fact() != manifest["model_server"]:
        raise RuntimeError("8901 model server identity/config drift before measured row")
    for path, expected in manifest["runtime_source_sha256"].items():
        if _sha_file(REPO / path) != expected:
            raise RuntimeError(f"runtime source drift before measured row: {path}")
    _wait_idle_or_fail()

    task_id = str(row["task_id"])
    run_dir = root / f"{int(row['index']):02d}-{task_id}-r{int(row['repeat'])}-root-direct-perceive-operate"
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
        with FixtureServer(task_id) as fixture:
            env = _base_env(run_dir)
            chrome_proc, debug_base, target_id, before_security = _start_chrome(run_dir)
            env["LFL_BROWSER_PERCEPTION_CDP_URL"] = debug_base
            env["LFL_BROWSER_PERCEPTION_TARGET_ID"] = target_id
            result_path = run_dir / "worker-result.json"
            try:
                proc = subprocess.run(
                    [
                        str(PYTHON),
                        str(WORKER),
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
                startup_doc = (
                    json.loads(startup.read_text(encoding="utf-8")) if startup.is_file() else {}
                )
                worker = {"status": "TIMEOUT", "surface": startup_doc.get("surface")}
            oracle = judge(task_id, fixture.state.snapshot())
    finally:
        _stop_process(chrome_proc)

    security_agent_spawned = bool(_security_agent_pids() - before_security)
    status = _classify(
        oracle_pass=bool(oracle.get("pass")),
        worker_rc=worker_rc,
        worker=worker,
        manifest=manifest,
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
    return {
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
        existing = [
            json.loads(line)
            for line in results_path.read_text(encoding="utf-8").splitlines()
            if line
        ]
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
                    "implementation_commit": manifest["implementation_commit"],
                    "plan_sha256": manifest["plan_sha256"],
                    "surface_sha256": manifest["surface"]["sha256"],
                    "surface_names": manifest["surface"]["names"],
                    "surface_chars": manifest["surface"]["json_chars"],
                    "browser_capabilities": manifest["surface"]["browser_capability_names"],
                    "perceive_actions": manifest["surface"]["perceive_actions"],
                    "perceive_wait_kinds": manifest["surface"]["perceive_wait_kinds"],
                    "perceive_root_direct": manifest["surface"]["perceive_root_direct"],
                    "perceive_branch_count": manifest["surface"]["perceive_branch_count"],
                    "perceive_has_nested_condition": manifest["surface"]["perceive_has_nested_condition"],
                    "perceive_lazy_full_branch_equal": manifest["surface"]["perceive_lazy_full_branch_equal"],
                    "operate_verbs": manifest["surface"]["operation_verbs"],
                    "operate_direct_root": manifest["surface"]["operation_direct_root"],
                    "cognition_contract_visible": manifest["surface"]["cognition_contract_visible"],
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
        print(
            json.dumps(
                {
                    "index": row["index"],
                    "task": row["task_id"],
                    "repeat": row["repeat"],
                    "status": record["status"],
                    "oracle": bool(record["oracle"].get("pass")),
                    "rounds": (record.get("worker") or {}).get("rounds"),
                    "perceive_calls": (record.get("worker") or {}).get("perceive_call_count"),
                    "operation_calls": (record.get("worker") or {}).get("operation_call_count"),
                    "ground_probe": (record.get("worker") or {}).get("ground_probe_amplification_count"),
                    "duplicates": (record.get("worker") or {}).get("duplicate_successful_mutation_count"),
                    "protocol_repair": (record.get("worker") or {}).get(
                        "protocol_repair_episode_count"
                    ),
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
                {"qualification_complete": True, "gate_pass": gate["pass"]},
                sort_keys=True,
            )
        )
        return 0 if gate["pass"] else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
