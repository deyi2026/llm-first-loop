#!/usr/bin/env python3
"""Serial frozen MF-5 paired A/B runner. --max-new-rows=0 is zero-model preflight."""

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
    MODEL_REF,
    SCHEMA,
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
PROVIDERS = REPO / "data/providers.json"
MODEL_PORT = 8901
MAX_ITERATIONS = 12
WORKER_TIMEOUT_S = 240
BACKEND_BASELINE = "9734d57c7997bb1f7585c8311029eba25175c51a"
FC2_FIXTURE_SHA256 = "87696076cea84d4e93f172d07a1499755dbc647f396ff115a9d64571740b72a3"
FC2_PROMPT_SHA256 = {
    "click_commit": "823e7cb25a1f2f234412564a93ed221956bdbcb4214aff1d67a78fd9296c6f2d",
    "fill_submit": "d80607ace4193874d8b7deddc2988f8b6562443b99b54455e48163cc4a6ff9e2",
    "delayed_wait": "eb99aac9458104ca12770d07ce1886f9d3bd76f8955ce9b5135de33b476ae694",
}


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    tmp.replace(path)


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()


def _tracked_dirty() -> list[str]:
    out = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=REPO, text=True
    )
    return [x for x in out.splitlines() if x.strip()]


def _model_server_fact() -> dict[str, Any]:
    lines = subprocess.check_output(["ps", "-axo", "pid=,command="], text=True).splitlines()
    candidates = [x.strip() for x in lines if "mlx_lm.server" in x and f"--port {MODEL_PORT}" in x]
    if len(candidates) != 1:
        raise RuntimeError(
            f"expected exactly one mlx_lm.server on 8901; observed={len(candidates)}"
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
    doc = json.loads(PROVIDERS.read_text())
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
        ["lsof", "-nP", "-iTCP:8901"], capture_output=True, text=True, check=False
    )
    return [line for line in proc.stdout.splitlines()[1:] if "LISTEN" not in line]


def _wait_idle_or_fail() -> None:
    deadline = time.monotonic() + 8
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
            "LLM_MAX_ITERATIONS": "12",
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


def _surface_manifest(tmp_root: Path, arm: str) -> dict[str, Any]:
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
        raise RuntimeError(f"surface worker {arm} failed: {proc.stderr[-500:]}")
    doc = json.loads(result_path.read_text())
    return dict(doc["surface"])


def execution_manifest(plan: list[dict[str, Any]], tmp_root: Path) -> dict[str, Any]:
    dirty = _tracked_dirty()
    if dirty:
        raise RuntimeError(f"tracked worktree dirty before freeze: {dirty}")
    head = _git("rev-parse", "HEAD")
    if (
        subprocess.run(
            ["git", "diff", "--quiet", BACKEND_BASELINE, head, "--", "src"], cwd=REPO
        ).returncode
        != 0
    ):
        raise RuntimeError("production src changed after frozen MF-4 backend")
    server = _model_server_fact()
    if not server["prompt_concurrency_1"] or not server["decode_concurrency_1"]:
        raise RuntimeError("8901 concurrency drift")
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
    provider = _provider_contract()
    if provider != expected_provider:
        raise RuntimeError(f"provider contract drift: {provider}")
    static_plan = json.loads((HERE / "PLAN.v0.1.json").read_text())
    if static_plan != plan:
        raise RuntimeError("PLAN drift")
    if _sha_file(HERE / "fixture_server.py") != FC2_FIXTURE_SHA256:
        raise RuntimeError("fixture drift")
    prompt_sha = {
        k: hashlib.sha256(v.prompt_template.encode()).hexdigest() for k, v in TASKS.items()
    }
    if prompt_sha != FC2_PROMPT_SHA256:
        raise RuntimeError("prompt drift")
    surfaces = {arm: _surface_manifest(tmp_root, arm) for arm in ("A", "B")}
    for arm, surface in surfaces.items():
        if not surface.get("exact") or set(surface.get("names") or []) != set(ALLOWED_TOOLS):
            raise RuntimeError(f"surface mismatch {arm}")
        if surface.get("hidden_atomic_tools_present"):
            raise RuntimeError(f"atomic tool leak {arm}")
    if surfaces["A"]["operation_parameter_names"] != ["clauses"] or surfaces["A"][
        "operation_required"
    ] != ["clauses"]:
        raise RuntimeError("A is not frozen legacy clauses surface")
    if surfaces["B"]["operation_parameter_names"] != ["steps"] or surfaces["B"][
        "operation_required"
    ] != ["steps"]:
        raise RuntimeError("B is not model-friendly steps surface")
    runtime_paths = _git("ls-files", "src", "methods").splitlines()
    return {
        "schema": SCHEMA + ".execution_manifest",
        "experiment_git_head": head,
        "backend_baseline": BACKEND_BASELINE,
        "production_src_diff_after_backend": False,
        "plan_sha256": plan_sha256(plan),
        "plan_rows": len(plan),
        "model_ref": MODEL_REF,
        "model_server": server,
        "provider_contract": provider,
        "surfaces": surfaces,
        "runtime_source_sha256": {x: _sha_file(REPO / x) for x in runtime_paths},
        "source_sha256": {
            str(x.relative_to(REPO)): _sha_file(x)
            for x in [
                HERE / "protocol.py",
                HERE / "PROTOCOL.v0.1.md",
                HERE / "PLAN.v0.1.json",
                HERE / "fixture_server.py",
                HERE / "worker.py",
                HERE / "run_mf5.py",
            ]
        },
        "task_prompt_sha256": prompt_sha,
        "fixture_sha256": _sha_file(HERE / "fixture_server.py"),
        "runtime": {
            "thinking_mode": "on",
            "reasoning_effort": "medium",
            "max_iterations": 12,
            "max_tokens": 16000,
            "serial_model_runs": True,
            "tool_schema_lazy": True,
            "fallbacks": 0,
        },
    }


def _start_chrome(run_dir: Path) -> tuple[subprocess.Popen[bytes], str, str, set[int]]:
    port = _free_loopback_port()
    debug = f"http://127.0.0.1:{port}"
    profile = run_dir / "chrome-profile"
    before = _security_agent_pids()
    process = subprocess.Popen(
        chrome_args(CHROME, profile, port),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    target = _wait_page(debug)
    target_id = str(target.get("id") or "")
    if not target_id:
        raise RuntimeError("Chrome target missing")
    return process, debug, target_id, before


def _stop(process: subprocess.Popen[Any] | None) -> None:
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


def _classify(
    oracle_pass: bool, rc: int | None, worker: dict[str, Any], manifest: dict[str, Any], arm: str
) -> str:
    if rc is None:
        return "TIMEOUT"
    if worker.get("status") != "RUN_OK":
        return "INFRA_FAIL"
    surface = worker.get("surface") or {}
    if surface.get("sha256") != manifest["surfaces"][arm]["sha256"]:
        return "INVALID"
    if worker.get("fallback_used"):
        return "INVALID"
    if worker.get("model_used") not in {None, "", MODEL_REF}:
        return "INVALID"
    return "PASS" if oracle_pass else "TASK_FAIL"


def run_row(row: dict[str, Any], root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    if _git("rev-parse", "HEAD") != manifest["experiment_git_head"] or _tracked_dirty():
        raise RuntimeError("git drift before row")
    if _model_server_fact() != manifest["model_server"]:
        raise RuntimeError("8901 drift before row")
    _wait_idle_or_fail()
    task_id = str(row["task_id"])
    arm = str(row["arm"])
    run_dir = root / f"{int(row['index']):02d}-{row['pair_id']}-{arm}"
    if run_dir.exists():
        raise RuntimeError(f"run dir exists: {run_dir.name}")
    run_dir.mkdir(parents=True)
    chrome = None
    before = set()
    rc = None
    worker = {}
    oracle = {"pass": False}
    started = time.monotonic()
    try:
        with FixtureServer(task_id) as fixture:
            env = _base_env(run_dir)
            chrome, debug, target, before = _start_chrome(run_dir)
            env["LFL_BROWSER_PERCEPTION_CDP_URL"] = debug
            env["LFL_BROWSER_PERCEPTION_TARGET_ID"] = target
            result_path = run_dir / "worker-result.json"
            try:
                proc = subprocess.run(
                    [
                        str(REPO / ".venv/bin/python"),
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
                rc = proc.returncode
            except subprocess.TimeoutExpired:
                rc = None
            if result_path.is_file():
                worker = json.loads(result_path.read_text())
            else:
                startup = run_dir / "worker-startup.json"
                worker = {
                    "status": "TIMEOUT",
                    "surface": json.loads(startup.read_text()).get("surface")
                    if startup.is_file()
                    else {},
                }
            oracle = judge(task_id, fixture.state.snapshot())
    finally:
        _stop(chrome)
    security = bool(_security_agent_pids() - before)
    status = _classify(bool(oracle.get("pass")), rc, worker, manifest, arm)
    surface = worker.get("surface") or {}
    wo = {k: v for k, v in worker.items() if k != "surface"}
    wo.update(
        {
            "surface_sha256": surface.get("sha256"),
            "surface_exact": surface.get("exact"),
            "surface_json_chars": surface.get("json_chars"),
        }
    )
    return {
        **row,
        "schema": SCHEMA + ".run",
        "run_id": run_dir.name,
        "status": status,
        "oracle": oracle,
        "worker_rc": rc,
        "worker": wo,
        "security_agent_spawned": security,
        "wall_s": round(time.monotonic() - started, 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--max-new-rows", type=int, default=1)
    args = ap.parse_args()
    if args.max_new_rows < 0:
        ap.error("--max-new-rows >=0")
    root = Path(args.workdir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    plan = build_plan()
    plan_path = root / "plan.json"
    manifest_path = root / "execution-manifest.json"
    results_path = root / "results.jsonl"
    if plan_path.exists() and json.loads(plan_path.read_text()) != plan:
        raise RuntimeError("plan drift")
    if not plan_path.exists():
        _atomic_json(plan_path, plan)
    manifest = execution_manifest(plan, root)
    if manifest_path.exists() and json.loads(manifest_path.read_text()) != manifest:
        raise RuntimeError("manifest drift")
    if not manifest_path.exists():
        _atomic_json(manifest_path, manifest)
    existing = (
        [json.loads(x) for x in results_path.read_text().splitlines() if x]
        if results_path.exists()
        else []
    )
    if args.max_new_rows == 0:
        print(
            json.dumps(
                {
                    "preflight": True,
                    "model_requests": 0,
                    "git_head": manifest["experiment_git_head"],
                    "plan_sha256": manifest["plan_sha256"],
                    "surfaces": {
                        a: {
                            "sha256": s["sha256"],
                            "root": s["operation_parameter_names"],
                            "chars": s["json_chars"],
                        }
                        for a, s in manifest["surfaces"].items()
                    },
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    done = {int(x["index"]) for x in existing}
    pending = [x for x in plan if int(x["index"]) not in done][: args.max_new_rows]
    for row in pending:
        rec = run_row(row, root, manifest)
        with results_path.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
        existing.append(rec)
        print(
            json.dumps(
                {
                    "index": row["index"],
                    "pair": row["pair_id"],
                    "arm": row["arm"],
                    "status": rec["status"],
                    "oracle": bool(rec["oracle"].get("pass")),
                    "rounds": (rec.get("worker") or {}).get("rounds"),
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
                    "gate_pass": gate["pass"],
                    "hard_pass": gate["hard_pass"],
                    "efficiency_pass": gate["efficiency_pass"],
                },
                sort_keys=True,
            )
        )
        return 0 if gate["pass"] else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
