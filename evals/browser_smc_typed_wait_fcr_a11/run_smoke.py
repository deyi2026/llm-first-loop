#!/usr/bin/env python3
"""Serial orchestrator for v0.6-A1.1 mechanically-typed wait FCR smoke."""

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

import httpx

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

from fixture_server import FixtureServer  # noqa: E402
from protocol import (  # noqa: E402
    ALLOWED_TOOLS,
    MODEL_REF,
    SCHEMA,
    TASKS,
    build_plan,
    plan_sha256,
    smoke_gate,
    worker_gate_check,
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
        "command_sha256": hashlib.sha256(command.encode()).hexdigest(),
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
    env["PYTHONPATH"] = os.pathsep.join([str(REPO / "src"), str(REPO), old_pp]).rstrip(os.pathsep)
    env.update(
        {
            "LLM_API_KEY": "local-eval",
            "LLM_BASE_URL": "http://127.0.0.1:8901/v1",
            "LLM_MODEL": MODEL_REF,
            "LLM_THINKING_MODE": "on",
            "LLM_REASONING_EFFORT": "medium",
            "LLM_MAX_ITERATIONS": "8",
            "LLM_TIMEOUT_S": "1800",
            "LLM_MAX_TOKENS": "16000",
            "MODEL_FALLBACKS": "",
            "RUN_MODE": "standard",
            "TOOL_SCHEMA_LAZY": "1",
            "DATA_DIR": str(data_dir),
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
            "LFL_BROWSER_ACTION_ENABLED": "",
        }
    )
    return env


def _surface_manifest(tmp_root: Path) -> dict[str, Any]:
    run_dir = tmp_root / "surface"
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
    return dict(json.loads(result_path.read_text(encoding="utf-8"))["surface"])


def execution_manifest(plan: list[dict[str, Any]], tmp_root: Path) -> dict[str, Any]:
    dirty = _tracked_dirty()
    if dirty:
        raise RuntimeError(f"tracked working tree is dirty before model execution: {dirty}")
    server = _model_server_fact()
    if not server["prompt_concurrency_1"] or not server["decode_concurrency_1"]:
        raise RuntimeError("8901 concurrency identity is not frozen single-run configuration")
    provider = _provider_contract()
    expected = {
        "timeout_s": 1800,
        "max_input_tokens": 184000,
        "max_tokens": 16000,
        "temperature": 0.0,
        "top_p": 1.0,
        "top_k": 0,
        "min_p": 0.0,
        "wire_protocol": "openai",
    }
    if provider != expected:
        raise RuntimeError(f"provider contract drift: {provider}")
    surface = _surface_manifest(tmp_root)
    if not surface.get("exact") or set(surface.get("names") or []) != set(ALLOWED_TOOLS):
        raise RuntimeError(f"read-only surface mismatch: {surface}")
    if surface.get("perceive_actions") != ["snapshot", "hydrate", "diff"] or surface.get(
        "perceive_has_predicate"
    ):
        raise RuntimeError("browser_perceive split surface drift")
    expected_required = {
        "browser_wait_scope_url": {"scope_ref", "operator", "value", "timeout_ms", "interval_ms"},
        "browser_wait_scope_ready": {"scope_ref", "state", "timeout_ms", "interval_ms"},
        "browser_wait_scope_count": {"scope_ref", "operator", "count", "timeout_ms", "interval_ms"},
        "browser_wait_object_state": {"object_ref", "property", "value", "timeout_ms", "interval_ms"},
        "browser_wait_object_text": {
            "object_ref",
            "property",
            "operator",
            "value",
            "timeout_ms",
            "interval_ms",
        },
    }
    actual_required = surface.get("wait_required") or {}
    if set(actual_required) != set(expected_required) or any(
        set(actual_required.get(name) or []) != required
        for name, required in expected_required.items()
    ):
        raise RuntimeError("mechanically typed wait required-field drift")
    for name, spec in (surface.get("wait_interval") or {}).items():
        if name not in expected_required or spec != {
            "type": "integer",
            "minimum": 1,
            "maximum": 5000,
        }:
            raise RuntimeError(f"typed wait interval drift: {name}")
    if surface.get("ready_state_schema") != {
        "type": "string",
        "enum": ["loading", "interactive", "complete"],
    }:
        raise RuntimeError("ready-state provider schema drift")
    if surface.get("object_state_value_schema") != {"type": "boolean"}:
        raise RuntimeError("object-state boolean schema drift")
    if surface.get("scope_count_schema") != {"type": "integer", "minimum": 0}:
        raise RuntimeError("scope-count integer schema drift")
    if "visible" in set(surface.get("object_state_properties") or []):
        raise RuntimeError("unsupported live visible capability leaked into provider surface")
    source_paths = [
        HERE / "protocol.py",
        HERE / "PROTOCOL.v0.6-A1.1.md",
        HERE / "PLAN.v0.6-A1.1.json",
        HERE / "fixture_server.py",
        HERE / "worker.py",
        HERE / "run_smoke.py",
        REPO / "src/llm_loop/browser/cdp_host.py",
        REPO / "src/llm_loop/browser/perception.py",
        REPO / "src/llm_loop/tools/builtin/browser_wait.py",
        REPO / "src/llm_loop/tools/builtin/browser_perceive.py",
        REPO / "src/llm_loop/tools/registry.py",
    ]
    return {
        "schema": SCHEMA + ".execution_manifest",
        "git_head": _git("rev-parse", "HEAD"),
        "tracked_dirty": False,
        "plan_sha256": plan_sha256(plan),
        "model_ref": MODEL_REF,
        "model_server": server,
        "provider_contract": provider,
        "surface": surface,
        "source_sha256": {str(path.relative_to(REPO)): _sha_file(path) for path in source_paths},
        "task_prompt_sha256": {
            task_id: hashlib.sha256(task.prompt.encode()).hexdigest()
            for task_id, task in TASKS.items()
        },
        "runtime": {
            "thinking_mode": "on",
            "reasoning_effort": "medium",
            "max_iterations": 8,
            "llm_timeout_s": 1800,
            "worker_timeout_s": 180,
            "max_tokens": 16000,
            "tool_schema_lazy": True,
            "fallbacks": 0,
            "serial_model_runs": True,
            "fixture_page_preopened": True,
        },
    }


def _wait_target_url(
    debug_base: str, expected_url: str, *, timeout_s: float = 8.0
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    with httpx.Client(timeout=1.0, trust_env=False, follow_redirects=False) as client:
        while time.monotonic() < deadline:
            try:
                rows = [
                    x
                    for x in client.get(f"{debug_base}/json/list").json()
                    if isinstance(x, dict) and x.get("type") == "page"
                ]
                if len(rows) == 1 and str(rows[0].get("url") or "") == expected_url:
                    return rows[0]
            except (httpx.HTTPError, ValueError, TypeError):
                pass
            time.sleep(0.1)
    raise TimeoutError("fixture page did not become current Chrome target")


def _start_chrome(run_dir: Path, url: str) -> tuple[subprocess.Popen[bytes], str, str, set[int]]:
    port = _free_loopback_port()
    debug_base = f"http://127.0.0.1:{port}"
    profile = run_dir / "chrome-profile"
    before_security = _security_agent_pids()
    args = chrome_args(CHROME, profile, port)
    args[-1] = url
    process = subprocess.Popen(
        args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
    )
    _wait_page(debug_base)
    target = _wait_target_url(debug_base, url)
    target_id = str(target.get("id") or "")
    if not target_id:
        raise RuntimeError("Chrome target missing exact id")
    return process, debug_base, target_id, before_security


def _stop_process(process: subprocess.Popen[Any] | None) -> None:
    if process is None:
        return
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=3)


def run_row(row: dict[str, Any], root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    if _git("rev-parse", "HEAD") != manifest["git_head"] or _tracked_dirty():
        raise RuntimeError("git identity drift before measured run")
    if _model_server_fact() != manifest["model_server"]:
        raise RuntimeError("8901 model server identity/config drift")
    _wait_idle_or_fail()
    task_id = str(row["task_id"])
    run_dir = root / f"{int(row['index']):02d}-{task_id}"
    if run_dir.exists():
        raise RuntimeError(f"run dir already exists: {run_dir.name}")
    run_dir.mkdir(parents=True)
    chrome = None
    before_security: set[int] = set()
    worker: dict[str, Any] = {}
    worker_rc: int | None = None
    started = time.monotonic()
    try:
        with FixtureServer(task_id) as fixture:
            env = _base_env(run_dir)
            chrome, debug_base, target_id, before_security = _start_chrome(run_dir, fixture.url)
            env["LFL_BROWSER_PERCEPTION_CDP_URL"] = debug_base
            env["LFL_BROWSER_PERCEPTION_TARGET_ID"] = target_id
            result_path = run_dir / "worker-result.json"
            try:
                proc = subprocess.run(
                    [
                        str(REPO / ".venv/bin/python"),
                        str(WORKER),
                        "--prompt",
                        TASKS[task_id].prompt,
                        "--result-json",
                        str(result_path),
                    ],
                    cwd=run_dir,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                worker_rc = proc.returncode
            except subprocess.TimeoutExpired:
                worker_rc = None
            if result_path.is_file():
                worker = json.loads(result_path.read_text(encoding="utf-8"))
    finally:
        _stop_process(chrome)
    surface = worker.get("surface") or {}
    if worker_rc is None:
        status = "TIMEOUT"
    elif worker.get("status") != "RUN_OK":
        status = "INFRA_FAIL"
    elif (
        surface.get("sha256") != manifest["surface"]["sha256"]
        or not surface.get("exact")
        or worker.get("fallback_used")
        or worker.get("model_used") not in {None, "", MODEL_REF}
    ):
        status = "INVALID"
    else:
        status = "PASS" if worker_gate_check(row, worker)["pass"] else "TASK_FAIL"
    return {
        **row,
        "schema": SCHEMA + ".run",
        "run_id": run_dir.name,
        "status": status,
        "worker_rc": worker_rc,
        "worker": {k: v for k, v in worker.items() if k != "surface"}
        | {"surface_sha256": surface.get("sha256"), "surface_exact": bool(surface.get("exact"))},
        "security_agent_spawned": bool(_security_agent_pids() - before_security),
        "wall_s": round(time.monotonic() - started, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--max-new-rows", type=int, default=1)
    args = parser.parse_args()
    root = Path(args.workdir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    plan = build_plan()
    (root / "plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    manifest = execution_manifest(plan, root)
    mp = root / "execution-manifest.json"
    if mp.exists():
        if json.loads(mp.read_text()) != manifest:
            raise RuntimeError("execution manifest drift")
    else:
        mp.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    rp = root / "results.jsonl"
    rows = [json.loads(x) for x in rp.read_text().splitlines() if x.strip()] if rp.exists() else []
    done = {int(x["index"]) for x in rows}
    for row in [x for x in plan if int(x["index"]) not in done][: args.max_new_rows]:
        rec = run_row(row, root, manifest)
        with rp.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
        rows.append(rec)
        print(
            json.dumps(
                {"index": row["index"], "task": row["task_id"], "status": rec["status"]},
                ensure_ascii=False,
            ),
            flush=True,
        )
    if len(rows) == len(plan):
        gate = smoke_gate(rows)
        (root / "smoke-gate.json").write_text(
            json.dumps(gate, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps({"smoke_gate": gate}, ensure_ascii=False), flush=True)
        return 0 if gate["pass"] else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
