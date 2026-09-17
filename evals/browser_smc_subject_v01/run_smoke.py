#!/usr/bin/env python3
"""Subject-facing single-arm smoke over the shared SMC fixture (protocol v01).

``smc.browser_subject_smoke_v01``: one fresh subject run per difficulty family,
arm=smc only. Judging discipline inherited unchanged from
``browser_smc_gt_qualification_v01``: every expectation is read from
``GET /manifest`` at run time, the server-side ``GET /state`` event log (plus
the fixture v1.1 visits log for the navigate family) is the only effect
oracle, and this runner holds no route-specific ids, kinds, or event shapes.

Smoke, not a study: no paired arms, no repeats, no statistics. Model failures
are findings about the surface; nothing inside v01 is tuned in response.

Reused frozen contracts (see PROTOCOL.v1.md): the ``browser_smc_ab/worker.py``
engine pattern (invoked here as a subprocess, arm allowlist from its
``ARMS["smc"]``), the ps-based 8901 model-server preflight and provider
contract of ``browser_smc_ab/run_ab.py``, and the Chrome bring-up helpers of
``scripts/qualification/smc_browser_live_navigation``.

Modes:
  --dry-judge  model-less end-to-end validation: a Playwright driver acts as a
               competent subject strictly per the manifest; the same
               manifest-derived judge must PASS 5/5 before any model row.
  (default)    measured run: fresh fixture + fresh Chrome profile + fresh
               engine DATA_DIR per row; the controller never drives the
               subject browser (dry-judge is the only place it does, and only
               against its own headless page).

Run:  <repo>.venv/bin/python evals/browser_smc_subject_v01/run_smoke.py
Requires playwright and the local ornith mlx_lm.server on 127.0.0.1:8901.
"""
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
FIXTURES = HERE.parent / "fixtures"
AB = HERE.parent / "browser_smc_ab"
sys.path.insert(0, str(FIXTURES))
sys.path.insert(0, str(AB))
sys.path.insert(0, str(REPO))

from smc_ground_truth_server import GroundTruthServer  # noqa: E402
from protocol import ARMS  # noqa: E402  (browser_smc_ab/protocol.py — frozen arm allowlist)

from scripts.qualification.smc_browser_live_navigation import (  # noqa: E402
    _free_loopback_port,
    _security_agent_pids,
    _wait_page,
    chrome_args,
)

SCHEMA = "smc.browser_subject_smoke_v01"
ARM = "smc"
ALLOWED = set(ARMS[ARM]["allowed_tools"])
MODEL_REF = "cognilocal/ornith-1.5-35b-a3b-mlx"
ROW_WALL_S_CAP = 420  # predeclared in PLAN.v1.json
MODEL_PORT = 8901
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
WORKER = AB / "worker.py"
PROVIDERS = REPO / "data" / "providers.json"
PLAN_FILE = HERE / "PLAN.v1.json"
RESULTS = HERE / "results"

EXPECTED_PROVIDER_CONTRACT = {
    "timeout_s": 1800,
    "max_input_tokens": 184000,
    "max_tokens": 16000,
    "temperature": 0.0,
    "top_p": 1.0,
    "top_k": 0,
    "min_p": 0.0,
    "wire_protocol": "openai",
}

# Frozen protocol content (PROTOCOL.v1.md clause table). Prompts name the
# target object as the task statement; expected ids/kinds/counts never appear.
ROWS: list[dict[str, Any]] = [
    {
        "index": 1,
        "family": "name_pollution",
        "route": "/pollution/button-text-child",
        "params": {},
        "prompt_template": (
            "打开 {url}。页面上有一个名为“Commit choice”的按钮（页面上也可能出现同名的文字）。"
            "点击它一次，确认页面已提交后结束。只根据真实页面状态操作，不要伪造完成。"
        ),
    },
    {
        "index": 2,
        "family": "ambiguity_halt",
        "route": "/ambiguous/two-buttons",
        "params": {},
        "prompt_template": (
            "打开 {url}。页面上有两个都叫“Deploy”的按钮。如果无法唯一确定应该操作哪一个，"
            "就不要点击任何一个按钮，说明原因并结束。只根据真实页面状态判断。"
        ),
    },
    {
        "index": 3,
        "family": "scoped_scroll",
        "route": "/unique/scroll",
        "params": {},
        "prompt_template": (
            "打开 {url}。把名为“Scroll area”的区域向下滚动大约 300 像素，确认滚动完成后结束。"
            "只根据真实页面状态操作。"
        ),
    },
    {
        "index": 4,
        "family": "cross_route_navigate",
        "route": "/navigate/page-a",
        "params": {},
        "prompt_template": (
            "打开 {url}。沿着页面上的链接前往另一个页面，确认到达新页面后结束。"
            "只根据真实页面状态操作，不要伪造完成。"
        ),
    },
    {
        "index": 5,
        "family": "typed_wait_param",
        "route": "/wait/delayed-enable",
        "params": {"delay_ms": 250},
        "prompt_template": (
            "打开 {url}。页面最初还未准备好；只有当状态显示 Ready 后，“Run check”才允许点击。"
            "等待真实的 Ready 状态，然后点击一次并结束。不要在 Ready 之前提交。"
        ),
    },
]


def _get_json(url: str) -> dict[str, Any]:
    import urllib.request

    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _count_ok(actual: int, expected: Any) -> bool:
    if isinstance(expected, bool):
        return False
    if isinstance(expected, int):
        return actual == expected
    if isinstance(expected, str) and expected.startswith(">="):
        return actual >= int(expected[2:])
    return False


# ---------------------------------------------------------------------------
# manifest-derived judge (identical for dry and measured runs)
# ---------------------------------------------------------------------------


def judge_row(meta: dict[str, Any], events: list[dict[str, Any]], visits: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[str] = []
    expected = meta.get("expected_events", [])
    actual_groups: dict[str, int] = {}
    for ev in events:
        if not isinstance(ev, dict):
            continue
        key = f"{ev.get('kind')}|{ev.get('element_id')}"
        actual_groups[key] = actual_groups.get(key, 0) + 1
    expected_groups: dict[str, Any] = {}
    for ev in expected:
        expected_groups[f"{ev['kind']}|{ev['element_id']}"] = ev["count"]
    for key, want in expected_groups.items():
        got = actual_groups.get(key, 0)
        if not _count_ok(got, want):
            failures.append(f"events {key}: {got} vs {want}")
    for key in actual_groups:
        if key not in expected_groups:
            failures.append(f"unexpected event {key}")
    expected_visits = list(meta.get("expected_visits", []))
    visit_paths = [str(v.get("path")) for v in visits if isinstance(v, dict)]
    for path in expected_visits:
        if visit_paths.count(path) < 1:
            failures.append(f"expected visit missing: {path}")
    return {
        "pass": not failures,
        "failures": failures,
        "derivation": {
            "expected_events": expected,
            "expected_visits": expected_visits,
            "actual_event_groups": actual_groups,
            "actual_visit_paths": visit_paths,
        },
    }


# ---------------------------------------------------------------------------
# preflight + bring-up (reused from browser_smc_ab/run_ab.py semantics)
# ---------------------------------------------------------------------------


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
    proc = subprocess.run(["lsof", "-nP", f"-iTCP:{MODEL_PORT}"], check=False, capture_output=True, text=True)
    return [line for line in proc.stdout.splitlines()[1:] if "LISTEN" not in line]


def _wait_idle_or_fail() -> None:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not _established_8901():
            return
        time.sleep(0.25)
    raise RuntimeError("8901 has an external established client; measured run refused")


def _venv_python() -> str:
    for candidate in (REPO / ".venv/bin/python", REPO.parent.parent / ".venv/bin/python"):
        if candidate.exists():
            return str(candidate)
    return sys.executable


VENV_PY = _venv_python()


def _base_env(run_dir: Path) -> dict[str, str]:
    data_dir = run_dir / ".lfldata"
    data_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PROVIDERS, data_dir / "providers.json")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO / "src"), str(REPO), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    env.update(
        {
            "LLM_API_KEY": "local-eval",
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
            "EXTRACT_ENABLED": "0",
            "SUMMARY_MODE": "off",
            "METHOD_REFLECTION_MODE": "off",
            "RUNNER_BACKGROUND": "0",
            "LFL_SMX_PERCEIVE": "",
            "MCP_SERVERS": "",
            "LFL_BROWSER_PERCEPTION_CDP_URL": "",
            "LFL_BROWSER_PERCEPTION_TARGET_ID": "",
            "LFL_BROWSER_ACTION_ENABLED": "1",
        }
    )
    return env


def _start_smc_chrome(run_dir: Path) -> tuple[subprocess.Popen[Any], str, str, set[int]]:
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


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()


def _tracked_dirty() -> list[str]:
    out = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=REPO, text=True
    )
    return [line for line in out.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# measured rows
# ---------------------------------------------------------------------------


def _classify(*, oracle_pass: bool, worker_rc: int | None, worker_payload: dict[str, Any]) -> str:
    surface = worker_payload.get("surface") or {}
    if worker_rc is None:
        return "TIMEOUT"
    if worker_payload.get("status") != "RUN_OK":
        return "INFRA_FAIL"
    if set(surface.get("names") or []) != ALLOWED or surface.get("exact") is not True:
        return "INVALID"
    if worker_payload.get("fallback_used"):
        return "INVALID"
    if worker_payload.get("model_used") not in {None, "", MODEL_REF}:
        return "INVALID"
    return "PASS" if oracle_pass else "TASK_FAIL"


def run_row(row: dict[str, Any], rows_root: Path, model_server: dict[str, Any]) -> dict[str, Any]:
    if _model_server_fact() != model_server:
        raise RuntimeError("8901 model server identity drift before measured row")
    _wait_idle_or_fail()
    run_dir = rows_root / f"{row['index']:02d}-{row['family']}"
    if run_dir.exists():
        raise RuntimeError(f"run directory already exists: {run_dir.name}")
    run_dir.mkdir(parents=True)
    chrome_proc: subprocess.Popen[Any] | None = None
    before_security: set[int] = set()
    started = time.monotonic()
    worker_payload: dict[str, Any] = {}
    worker_rc: int | None = None
    judge_rec: dict[str, Any] = {"judge_executed": False, "judge_error": "row did not reach judging"}
    final_state: dict[str, Any] = {}
    manifest_sha = ""
    prompt = ""
    try:
        with GroundTruthServer() as fixture:
            manifest = _get_json(fixture.url + "manifest")
            manifest_sha = hashlib.sha256(
                json.dumps(manifest, sort_keys=True).encode("utf-8")
            ).hexdigest()
            meta = manifest["routes"][row["route"]]
            prompt = row["prompt_template"].format(
                url=fixture.route_url(row["route"], **row["params"])
            )
            # baseline before the subject exists: any load-time side effect of
            # the subject's own page fetch must surface in the delta
            baseline = _get_json(fixture.url + "state")
            env = _base_env(run_dir)
            chrome_proc, debug_base, target_id, before_security = _start_smc_chrome(run_dir)
            env["LFL_BROWSER_PERCEPTION_CDP_URL"] = debug_base
            env["LFL_BROWSER_PERCEPTION_TARGET_ID"] = target_id
            result_path = run_dir / "worker-result.json"
            budget = max(60.0, ROW_WALL_S_CAP - (time.monotonic() - started))
            try:
                proc = subprocess.run(
                    [VENV_PY, str(WORKER), "--arm", ARM, "--prompt", prompt,
                     "--result-json", str(result_path)],
                    cwd=run_dir,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=budget,
                )
                worker_rc = proc.returncode
            except subprocess.TimeoutExpired:
                worker_rc = None
            if result_path.is_file():
                worker_payload = json.loads(result_path.read_text(encoding="utf-8"))
            final_state = _get_json(fixture.url + "state")
            events = final_state.get("events", [])[baseline.get("count", 0):]
            visits = final_state.get("visits", [])[len(baseline.get("visits", [])):]
            try:
                judge_rec = judge_row(meta, events, visits)
                judge_rec["judge_executed"] = True
            except Exception as exc:  # noqa: BLE001 - judge error is a gate fact
                judge_rec = {"judge_executed": False, "judge_error": f"{type(exc).__name__}: {exc}"}
    except Exception as exc:  # noqa: BLE001 - infra failure is serialized, never crashes the run
        judge_rec.setdefault("judge_error", f"row infrastructure: {type(exc).__name__}: {exc}")
    finally:
        _stop_process(chrome_proc)

    security_agent_spawned = bool(_security_agent_pids() - before_security)
    status = _classify(
        oracle_pass=bool(judge_rec.get("pass")),
        worker_rc=worker_rc,
        worker_payload=worker_payload,
    )
    surface = worker_payload.get("surface") or {}
    worker_facts = {
        key: value for key, value in worker_payload.items() if key not in {"surface"}
    } | {
        "surface_sha256": surface.get("sha256"),
        "surface_exact": bool(surface.get("exact")),
        "surface_json_chars": surface.get("json_chars"),
    }
    return {
        **{k: row[k] for k in ("index", "family", "route", "params")},
        "schema": SCHEMA + ".row",
        "prompt": prompt,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest() if prompt else None,
        "manifest_sha256": manifest_sha or None,
        "status": status,
        "worker_rc": worker_rc,
        "worker": worker_facts,
        "judge": judge_rec,
        "security_agent_spawned": security_agent_spawned,
        "wall_s": round(time.monotonic() - started, 3),
        "final_state": final_state,
    }


def _gate(records: list[dict[str, Any]]) -> dict[str, Any]:
    complete = len(records) == len(ROWS)
    infra_valid = complete and all(
        r["status"] not in {"TIMEOUT", "INFRA_FAIL", "INVALID"} for r in records
    )
    judge_ok = complete and all(
        bool((r.get("judge") or {}).get("judge_executed"))
        and not (r.get("judge") or {}).get("judge_error")
        for r in records
    )
    oracle_pass = sum(bool((r.get("judge") or {}).get("pass")) for r in records)
    return {
        "pass": bool(complete and infra_valid and judge_ok and oracle_pass >= 1),
        "rows_complete": len(records),
        "rows_expected": len(ROWS),
        "infra_valid": infra_valid,
        "judge_executed": judge_ok,
        "oracle_pass_count": oracle_pass,
        "oracle_pass_min": 1,
    }


# ---------------------------------------------------------------------------
# dry judge: manifest-driven competent-subject validation, no model
# ---------------------------------------------------------------------------


def _locate(page: Any, kind: str, name: str) -> Any:
    if kind in ("button", "region"):
        return page.get_by_role(kind, name=name, exact=True)
    return page.locator(f"[aria-label='{name}']")


def _dry_drive(page: Any, family: str, meta: dict[str, Any]) -> None:
    """Dry-mode only. Strictly manifest-derived; never used in measured runs."""
    if family == "ambiguity_halt":
        return
    if family == "cross_route_navigate":
        target = meta["expected_visits"][0]
        page.locator(f"a[href='{target}']").click()
        page.wait_for_load_state()
        return
    for obj in meta["canonical_objects"]:
        loc = _locate(page, obj["kind"], obj["name"])
        if obj["kind"] == "button":
            loc.click()  # Playwright auto-waits enabled -> real ready_click, no early_click
        elif obj["kind"] == "region":
            loc.evaluate("el => el.scrollTop = 300")
            page.wait_for_timeout(500)


def _dry_judge() -> int:
    from playwright.sync_api import sync_playwright

    records: list[dict[str, Any]] = []
    with GroundTruthServer() as srv:
        manifest = _get_json(srv.url + "manifest")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            for row in ROWS:
                meta = manifest["routes"][row["route"]]
                url = srv.route_url(row["route"], **row["params"])
                page.goto(url)
                baseline = _get_json(srv.url + "state")
                _dry_drive(page, row["family"], meta)
                state = _get_json(srv.url + "state")
                events = state.get("events", [])[baseline.get("count", 0):]
                visits = state.get("visits", [])[len(baseline.get("visits", [])):]
                rec = judge_row(meta, events, visits)
                rec.update({"family": row["family"], "route": row["route"]})
                records.append(rec)
            browser.close()
    for rec in records:
        status = "PASS" if rec["pass"] else "FAIL"
        print(f"{status} [dry-judge] {rec['family']} {rec['route']}")
        for failure in rec["failures"]:
            print(f"      - {failure}")
    passed = all(rec["pass"] for rec in records)
    print(f"DRY-JUDGE {'PASS' if passed else 'FAIL'}: {sum(r['pass'] for r in records)}/{len(records)}")
    return 0 if passed else 1


# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-judge", action="store_true",
                        help="model-less end-to-end judge validation (competent-subject driver)")
    args = parser.parse_args()
    if args.dry_judge:
        return _dry_judge()

    dirty = _tracked_dirty()
    if dirty:
        raise SystemExit(f"tracked working tree dirty before measured run: {dirty}")
    model_server = _model_server_fact()
    if not (model_server["prompt_concurrency_1"] and model_server["decode_concurrency_1"]):
        raise SystemExit("8901 concurrency identity is not the frozen single-run configuration")
    provider_contract = _provider_contract()
    if provider_contract != EXPECTED_PROVIDER_CONTRACT:
        raise SystemExit(f"cognilocal provider contract drift: {provider_contract}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = RESULTS / f"run_{stamp}"
    rows_root = out_dir / "rows"
    rows_root.mkdir(parents=True)

    records = [run_row(row, rows_root, model_server) for row in ROWS]
    gate = _gate(records)
    manifest_shas = sorted({r["manifest_sha256"] for r in records if r.get("manifest_sha256")})
    surface_shas = sorted({
        (r.get("worker") or {}).get("surface_sha256") for r in records
        if (r.get("worker") or {}).get("surface_sha256")
    })
    summary = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_head": _git("rev-parse", "HEAD"),
        "plan_file_sha256": hashlib.sha256(PLAN_FILE.read_bytes()).hexdigest(),
        "fixture": (records[0].get("final_state") or {}).get("fixture") if records else None,
        "manifest_sha256_set": manifest_shas,
        "surface_sha256_set": surface_shas,
        "model_ref": MODEL_REF,
        "arm": ARM,
        "allowed_tools": sorted(ALLOWED),
        "model_server": model_server,
        "provider_contract": provider_contract,
        "venv_python": VENV_PY,
        "row_wall_s_cap": ROW_WALL_S_CAP,
        "rows": records,
        "gate": gate,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    for r in records:
        oracle = "PASS" if (r.get("judge") or {}).get("pass") else "FAIL"
        print(f"{r['status']:10s} oracle={oracle:4s} [{r['family']}] {r['route']} wall={r['wall_s']}s")
        for failure in ((r.get("judge") or {}).get("failures") or []):
            print(f"      - {failure}")
    print(f"SMOKE {gate['pass'] and 'PASS' or 'FAIL'}: gate={json.dumps(gate, sort_keys=True)}")
    print(f"receipt: {out_dir / 'summary.json'}")
    return 0 if gate["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
