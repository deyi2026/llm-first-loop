#!/usr/bin/env python3
"""Serial orchestrator for the isolated Browser SMC real-model A/B."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
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
    out = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=REPO, text=True)
    return [line for line in out.splitlines() if line.strip()]


def _model_server_fact() -> dict[str, Any]:
    cmd = ["ps", "-axo", "pid=,command="]
    lines = subprocess.check_output(cmd, text=True).splitlines()
    candidates = [line.strip() for line in lines if "mlx_lm.server" in line and f"--port {MODEL_PORT}" in line]
    if len(candidates) != 1:
        raise RuntimeError(f"expected one mlx_lm.server on {MODEL_PORT}, observed={len(candidates)}")
    pid_raw, command = candidates[0].split(None, 1)
    model_arg = ""
    parts = command.split()
    if "--model" in parts:
        model_arg = parts[parts.index("--model") + 1]
    return {
        "pid": int(pid_raw),
        "command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(),
        "model_basename": Path(model_arg).name if model_arg else "",
        "prompt_concurrency_1": "--prompt-concurrency 1" in command,
        "decode_concurrency_1": "--decode-concurrency 1" in command,
        "max_tokens_16000": "--max-tokens 16000" in command,
    }


def _playwright_fact() -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    version = importlib.metadata.version("playwright")
    with sync_playwright() as playwright:
        executable = Path(playwright.chromium.executable_path)
    revision: int | None = None
    cache_root = executable.parent
    for parent in executable.parents:
        match = re.fullmatch(r"chromium-(\d+)", parent.name)
        if match:
            revision = int(match.group(1))
            cache_root = parent.parent
            break
    return {
        "package_version": version,
        "chromium_revision": revision,
        "chromium_basename": executable.name,
        "headless_shell_present": bool(
            revision is not None
            and (cache_root / f"chromium_headless_shell-{revision}").is_dir()
        ),
    }


def _established_8901() -> list[str]:
    proc = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{MODEL_PORT}"], check=False, capture_output=True, text=True
    )
    return [line for line in proc.stdout.splitlines()[1:] if "LISTEN" not in line]


def _wait_idle_or_fail() -> None:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not _established_8901():
            return
        time.sleep(0.25)
    raise RuntimeError("8901 has an external established client; measured run refused")


def _base_env(run_dir: Path, arm: str) -> dict[str, str]:
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
            "LLM_MAX_ITERATIONS": "12",
            "LLM_TIMEOUT_S": "90",
            "LLM_MAX_TOKENS": "4096",
            "MODEL_FALLBACKS": "",
            "RUN_MODE": "standard",
            "TOOL_SCHEMA_LAZY": "1",
            "DATA_DIR": str(data_dir),
            "EXTRACT_ENABLED": "0",
            "SUMMARY_MODE": "off",
            "METHOD_REFLECTION_MODE": "off",
            "RUNNER_BACKGROUND": "0",
            "LFL_SMX_PERCEIVE": "",
            "MCP_SERVERS": "",
            "LFL_BROWSER_PERCEPTION_CDP_URL": "",
            "LFL_BROWSER_PERCEPTION_TARGET_ID": "",
            "LFL_BROWSER_ACTION_ENABLED": "0",
        }
    )
    if arm == "smc":
        env["LFL_BROWSER_ACTION_ENABLED"] = "1"
    return env


def _surface_manifest(arm: str, tmp_root: Path) -> dict[str, Any]:
    run_dir = tmp_root / f"surface-{arm}"
    run_dir.mkdir(parents=True, exist_ok=True)
    env = _base_env(run_dir, arm)
    if arm == "smc":
        env["LFL_BROWSER_PERCEPTION_CDP_URL"] = "http://127.0.0.1:9"
        env["LFL_BROWSER_PERCEPTION_TARGET_ID"] = "manifest-only"
    result_path = run_dir / "surface.json"
    proc = subprocess.run(
        [str(REPO / ".venv/bin/python"), str(WORKER), "--arm", arm, "--surface-only", "--result-json", str(result_path)],
        cwd=run_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"surface worker failed arm={arm}: {proc.stderr[-500:]}")
    return json.loads(result_path.read_text(encoding="utf-8"))["surface"]


def execution_manifest(plan: list[dict[str, Any]], tmp_root: Path) -> dict[str, Any]:
    dirty = _tracked_dirty()
    if dirty:
        raise RuntimeError(f"tracked working tree is dirty before model execution: {dirty}")
    server = _model_server_fact()
    if not server["prompt_concurrency_1"] or not server["decode_concurrency_1"]:
        raise RuntimeError("8901 concurrency identity is not the frozen single-run configuration")
    surfaces = {arm: _surface_manifest(arm, tmp_root) for arm in ARMS}
    for arm, surface in surfaces.items():
        if not surface.get("exact") or set(surface.get("names") or []) != set(ARMS[arm]["allowed_tools"]):
            raise RuntimeError(f"surface mismatch arm={arm}: {surface}")
    source_paths = [
        HERE / "protocol.py",
        HERE / "fixture_server.py",
        HERE / "worker.py",
        HERE / "run_ab.py",
        HERE / "analyze.py",
        REPO / "src/llm_loop/tools/registry.py",
        REPO / "src/llm_loop/tools/builtin/browser_perceive.py",
        REPO / "src/llm_loop/tools/builtin/browser_action.py",
        REPO / "src/llm_loop/browser/action.py",
        REPO / "src/llm_loop/browser/cdp_action_host.py",
        REPO / "scripts/qualification/smc_browser_live_navigation.py",
    ]
    return {
        "schema": SCHEMA + ".execution_manifest",
        "git_head": _git("rev-parse", "HEAD"),
        "tracked_dirty": False,
        "seed": SEED,
        "plan_sha256": plan_sha256(plan),
        "plan_rows": len(plan),
        "model_ref": MODEL_REF,
        "model_server": server,
        "legacy_playwright": _playwright_fact(),
        "surfaces": surfaces,
        "source_sha256": {str(path.relative_to(REPO)): _sha_file(path) for path in source_paths},
        "task_prompt_sha256": {
            task_id: hashlib.sha256(task.prompt_template.encode("utf-8")).hexdigest()
            for task_id, task in TASKS.items()
        },
        "runtime": {
            "thinking_mode": "on",
            "reasoning_effort": "medium",
            "max_iterations": 12,
            "llm_timeout_s": 90,
            "max_tokens": 4096,
            "tool_schema_lazy": True,
            "fallbacks": 0,
            "extract_enabled": False,
            "summary_mode": "off",
            "method_reflection_mode": "off",
        },
    }


def _start_smc_chrome(run_dir: Path) -> tuple[subprocess.Popen[bytes], str, str, set[int]]:
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


def run_row(row: dict[str, Any], root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    if _git("rev-parse", "HEAD") != manifest["git_head"] or _tracked_dirty():
        raise RuntimeError("git identity drift before measured run")
    if _model_server_fact() != manifest["model_server"]:
        raise RuntimeError("8901 model server identity/config drift before measured run")
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
    try:
        with FixtureServer(task_id) as fixture:
            env = _base_env(run_dir, arm)
            if arm == "smc":
                chrome_proc, debug_base, target_id, before_security = _start_smc_chrome(run_dir)
                env["LFL_BROWSER_PERCEPTION_CDP_URL"] = debug_base
                env["LFL_BROWSER_PERCEPTION_TARGET_ID"] = target_id
            prompt = prompt_for(task_id, fixture.url)
            result_path = run_dir / "worker-result.json"
            try:
                proc = subprocess.run(
                    [str(REPO / ".venv/bin/python"), str(WORKER), "--arm", arm, "--prompt", prompt, "--result-json", str(result_path)],
                    cwd=run_dir,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=240,
                )
                worker_rc = proc.returncode
            except subprocess.TimeoutExpired:
                proc = None
                worker_rc = None
            if result_path.is_file():
                worker_payload = json.loads(result_path.read_text(encoding="utf-8"))
            oracle = judge(task_id, fixture.state.snapshot())
    finally:
        _stop_process(chrome_proc)

    security_agent_spawned = bool(_security_agent_pids() - before_security) if arm == "smc" else False
    status = "PASS" if oracle.get("pass") and worker_payload.get("status") == "RUN_OK" else "TASK_FAIL"
    if worker_rc is None:
        status = "TIMEOUT"
    elif worker_payload.get("status") != "RUN_OK":
        status = "INFRA_FAIL"
    surface = worker_payload.get("surface") or {}
    if set(surface.get("names") or []) != set(ARMS[arm]["allowed_tools"]):
        status = "INVALID"
    if surface.get("sha256") != manifest["surfaces"][arm]["sha256"]:
        status = "INVALID"
    if worker_payload.get("fallback_used"):
        status = "INVALID"
    if worker_payload.get("model_used") not in {None, "", MODEL_REF}:
        status = "INVALID"
    return {
        **row,
        "schema": SCHEMA + ".run",
        "run_id": run_dir.name,
        "manifest_git_head": manifest["git_head"],
        "manifest_plan_sha256": manifest["plan_sha256"],
        "status": status,
        "oracle": oracle,
        "worker_rc": worker_rc,
        "worker": {
            key: value
            for key, value in worker_payload.items()
            if key not in {"surface"}
        }
        | {
            "surface_sha256": surface.get("sha256"),
            "surface_exact": bool(surface.get("exact")),
            "surface_json_chars": surface.get("json_chars"),
        },
        "security_agent_spawned": security_agent_spawned,
        "wall_s": round(time.monotonic() - started, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--phase", choices=("smoke", "remainder", "all"), default="smoke")
    args = parser.parse_args()
    root = Path(args.workdir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    plan = build_plan()
    plan_path = root / "plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    manifest = execution_manifest(plan, root)
    manifest_path = root / "execution-manifest.json"
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing != manifest:
            raise RuntimeError("execution manifest drift; refusing to mix evidence")
    else:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    results_path = root / "results.jsonl"
    existing_rows: list[dict[str, Any]] = []
    if results_path.exists():
        existing_rows = [json.loads(line) for line in results_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    done = {int(row["index"]) for row in existing_rows}
    if args.phase == "smoke":
        selected = [row for row in plan if row["smoke"]]
    elif args.phase == "remainder":
        gate = smoke_gate(existing_rows)
        if not gate["pass"]:
            raise RuntimeError(f"smoke gate not satisfied: {gate}")
        selected = [row for row in plan if not row["smoke"]]
    else:
        selected = list(plan)

    for row in selected:
        if int(row["index"]) in done:
            continue
        record = run_row(row, root, manifest)
        with results_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        existing_rows.append(record)
        done.add(int(row["index"]))
        print(json.dumps({"index": row["index"], "task": row["task_id"], "arm": row["arm"], "status": record["status"], "oracle": record["oracle"].get("pass")}, ensure_ascii=False), flush=True)
        if row.get("smoke") and len([r for r in existing_rows if r.get("smoke")]) == 6:
            gate = smoke_gate(existing_rows)
            (root / "smoke-gate.json").write_text(json.dumps(gate, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"smoke_gate": gate}, ensure_ascii=False), flush=True)
            if args.phase == "all" and not gate["pass"]:
                return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
