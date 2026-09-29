#!/usr/bin/env python3
"""Run the frozen EEv2.2 real-model A/B matrix sequentially."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from evals.execution_efficiency_v2.scorer_v0_2 import score_row_v0_2
from evals.execution_efficiency_v2.surfaces_v0_2 import (
    ARMS_V0_2,
    install_surface_overlay,
    surface_facts,
)
from evals.execution_efficiency_v2.tasks_v0_2 import (
    TASK_BY_ID_V0_2,
    row_id,
    schedule_v0_2,
    validate_v0_2,
)
from evals.pilot import telemetry as pilot_telemetry
from llm_loop.config import load_settings
from llm_loop.core.trace_leak.ingress_token import issue_ingress
from llm_loop.factory import build_engine

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DEFAULT_MANIFEST = HERE / "EEV22-MANIFEST.v0.2.json"
DEFAULT_OUTPUT = HERE / "EEV22-RAW.v0.2.jsonl"
DEFAULT_TRACE = HERE / "EEV22-WIRE.v0.2.jsonl"
DEFAULT_CACHE_WIRE = HERE / "EEV22-CACHE-WIRE.v0.2.jsonl"
DEFAULT_WORKDIR = Path("/tmp/lfl-eev22-v02")


def _stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _copy_provider_registry(settings: Any, target: Path) -> list[str]:
    source = Path(settings.data_dir)
    target.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for name in ("providers.local.json", "providers.json"):
        src = source / name
        if src.is_file():
            shutil.copy2(src, target / name)
            copied.append(name)
    return copied


def _manifest_guard(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "lfl-execution-efficiency-v2.2-manifest/v0.2":
        raise RuntimeError("wrong EEv2.2 manifest schema")
    if manifest.get("model_request_started") is not False:
        raise RuntimeError("EEv2.2 manifest freeze flag drift")
    if manifest.get("arms") != list(ARMS_V0_2) or int(manifest.get("row_count") or 0) != 36:
        raise RuntimeError("EEv2.2 matrix shape drift")
    if manifest.get("tasks_sha256") != _sha_text(
        _stable(list(TASK_BY_ID_V0_2.values()))
    ):
        raise RuntimeError("EEv2.2 task content drift")
    if manifest.get("scorer_sha256") != _sha_file(HERE / "scorer_v0_2.py"):
        raise RuntimeError("EEv2.2 scorer drift")
    if manifest.get("base_scorer_sha256") != _sha_file(HERE / "scorer.py"):
        raise RuntimeError("EEv2.2 base scorer drift")
    if manifest.get("task_source_sha256") != _sha_file(HERE / "tasks_v0_2.py"):
        raise RuntimeError("EEv2.2 task source drift")
    if manifest.get("surface_source_sha256") != _sha_file(HERE / "surfaces_v0_2.py"):
        raise RuntimeError("EEv2.2 surface source drift")
    if manifest.get("runner_source_sha256") != _sha_file(HERE / "run_v0_2.py"):
        raise RuntimeError("EEv2.2 runner source drift")
    if manifest.get("cache_treatment") != "forced_cache_prompt_false":
        raise RuntimeError("EEv2.2 cache treatment drift")
    return manifest


def _lfrt_json(settings: Any, *args: str) -> dict[str, Any]:
    raw = str(settings.lfrt_cli or "").strip()
    if not raw:
        raise RuntimeError("EEv2.2 requires configured lfrt")
    path = str(Path(raw).expanduser())
    proc = subprocess.run(
        [path, *args, "--json"],
        text=True,
        capture_output=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"lfrt {' '.join(args)} failed: {proc.stderr[-500:]}")
    return json.loads(proc.stdout)


def _runtime_guard(settings: Any, manifest: dict[str, Any]) -> None:
    observation = _lfrt_json(settings, "runtime-observation")
    status = _lfrt_json(settings, "status")
    runtime = observation.get("runtime") or {}
    data = status.get("data") or {}
    config = data.get("config") or {}
    activity = data.get("activity") or {}
    expected = manifest.get("local_runtime") or {}
    facts = {
        "contract": observation.get("contract"),
        "backend": runtime.get("backend"),
        "type": runtime.get("type"),
        "model": runtime.get("model"),
        "port": runtime.get("port"),
        "n_parallel": runtime.get("n_parallel"),
        "alias": config.get("alias"),
        "ctx": config.get("ctx"),
        "shards": config.get("shards"),
    }
    if observation.get("ok") is not True or observation.get("state") != "observed":
        raise RuntimeError("EEv2.2 local runtime is not observed")
    if facts != expected:
        raise RuntimeError(f"EEv2.2 local runtime identity drift: {facts!r}")
    if int(activity.get("est_conns") or 0) != 0:
        raise RuntimeError("EEv2.2 refuses a measured row with an established 8901 client")


def _setup(task: dict[str, Any], ws: Path) -> None:
    setup = str(task.get("setup") or "")
    if not setup:
        return
    proc = subprocess.run(
        ["/bin/sh", "-c", setup], cwd=ws, text=True, capture_output=True, timeout=30
    )
    if proc.returncode != 0:
        raise RuntimeError(f"setup failed: {proc.stderr[-500:]}")


def _verify(task: dict[str, Any], ws: Path) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            [sys.executable, "-c", str(task["verify"])],
            cwd=ws,
            text=True,
            capture_output=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return False, "VERIFIER-TIMEOUT"
    return proc.returncode == 0, (proc.stderr[-800:] if proc.returncode else "")


def _bound_prompt(task: dict[str, Any]) -> str:
    return (
        "工作目录（绝对路径）已由运行时绑定；所有相对路径和命令都在该目录解析。"
        f"任务：{task['prompt']}"
    )


def _read_trace(path: Path, session_id: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [row for row in rows if str(row.get("session_id") or "") == session_id]


@contextlib.contextmanager
def _wire_capture(client: Any, *, row_id: str, capture: Path):
    http_client = getattr(client, "_client", None)
    original = getattr(http_client, "build_request", None)
    if http_client is None or not callable(original):
        raise RuntimeError("EEv2.2 requires httpx-style OpenAI client")
    records: list[dict[str, Any]] = []

    def _build_request(method: Any, url: Any, *args: Any, **kwargs: Any):
        body = kwargs.get("json")
        is_chat = str(method).upper() == "POST" and str(url).rstrip("/").endswith(
            "/chat/completions"
        )
        if is_chat and not isinstance(body, dict):
            raise RuntimeError("EEv2.2 chat request missing JSON body")
        if is_chat:
            body = dict(body)
            body["cache_prompt"] = False
            kwargs["json"] = body
        request = original(method, url, *args, **kwargs)
        if is_chat:
            encoded = json.loads(bytes(request.content).decode("utf-8"))
            record = {
                "schema": "lfl-eev22-cache-wire/v0.2",
                "row_id": row_id,
                "cache_prompt": encoded.get("cache_prompt"),
                "model": encoded.get("model"),
                "tools_n": len(encoded.get("tools") or []),
                "tools_hash16": hashlib.sha256(
                    json.dumps(
                        encoded.get("tools") or [], ensure_ascii=False, sort_keys=True
                    ).encode("utf-8")
                ).hexdigest()[:16],
            }
            records.append(record)
            _append_jsonl(capture, record)
        return request

    http_client.build_request = _build_request
    try:
        yield records
    finally:
        http_client.build_request = original


def _opaque_workspace(row: str) -> str:
    return "ws-" + hashlib.sha256(row.encode()).hexdigest()[:20]


def _run_one(
    task: dict[str, Any],
    arm: str,
    repeat: int,
    *,
    workdir: Path,
    trace_path: Path,
    cache_wire_path: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    rid = row_id(task["id"], arm, repeat)
    ws = workdir / _opaque_workspace(rid)
    if ws.exists():
        raise RuntimeError(f"workspace already exists for missing row: {ws}")
    ws.mkdir(parents=True)
    _setup(task, ws)

    settings = load_settings()
    _runtime_guard(settings, manifest)
    row_data = ws / ".lfldata"
    copied = _copy_provider_registry(settings, row_data)
    engine = build_engine(
        replace(
            settings,
            data_dir=str(row_data),
            learning_plane_enabled=False,
            method_reflection_mode="off",
        )
    )
    try:
        baseline_surface = surface_facts(engine.registry, arm)
        if baseline_surface != manifest["surface_facts"][arm]:
            raise RuntimeError(f"EEv2.2 {arm} surface drift")
        original_schemas = install_surface_overlay(engine.registry, arm)
        try:
            if engine.llm_pool is None:
                raise RuntimeError("EEv2.2 requires production model pool")
            eval_model_ref = str(manifest["model_ref"])
            client, provider_id, model_id = engine.llm_pool.get_resolved_client(
                eval_model_ref
            )
            if (
                provider_id != manifest["resolved_provider"]
                or model_id != manifest["resolved_model"]
                or client.wire_protocol != manifest["wire_protocol"]
                or settings.reasoning_effort != manifest["reasoning_effort"]
            ):
                raise RuntimeError("EEv2.2 provider/model/reasoning drift")
            engine.set_workspace(str(ws))
            sid = engine.session.create(model_override=eval_model_ref)
            prompt = _bound_prompt(task)
            old_env = {
                key: os.environ.get(key)
                for key in ("LLM_PAYLOAD_TRACE", "LLM_PAYLOAD_TRACE_PATH")
            }
            os.environ["LLM_PAYLOAD_TRACE"] = "1"
            os.environ["LLM_PAYLOAD_TRACE_PATH"] = str(trace_path)
            result = None
            run_error = ""
            started = time.perf_counter()
            try:
                with _wire_capture(
                    client, row_id=rid, capture=cache_wire_path
                ) as cache_records:
                    try:
                        result = engine.run(
                            sid,
                            prompt,
                            model=eval_model_ref,
                            reasoning_effort=settings.reasoning_effort,
                            ingress=issue_ingress("cli"),
                        )
                    except Exception as exc:  # noqa: BLE001 - formal measured fact
                        run_error = f"{type(exc).__name__}: {exc}"
            finally:
                elapsed_s = round(time.perf_counter() - started, 3)
                for key, value in old_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

            passed, verify_error = _verify(task, ws)
            session_path = Path(engine.session._path(sid))
            events = pilot_telemetry.events_lfl(session_path) if session_path.exists() else None
            raw_fcr = pilot_telemetry.extract_raw(events) if events else None
            legacy_fcr = (
                pilot_telemetry.score_fcr(raw_fcr, events, task)
                if raw_fcr is not None and events is not None
                else None
            )
            traces = _read_trace(trace_path, sid)
            expected = manifest["surface_facts"][arm]
            wire_match = bool(traces) and all(
                int(row.get("tools_n") or 0) == int(expected["effective_tool_count"])
                and str(row.get("tools_hash") or "") == expected["openai_tools_hash16"]
                and str(row.get("model") or "") == model_id
                for row in traces
            )
            cache_wire_match = len(cache_records) == len(traces) and len(traces) > 0 and all(
                int(rec.get("tools_n") or 0) == int(expected["effective_tool_count"])
                and str(rec.get("tools_hash16") or "") == expected["openai_tools_hash16"]
                for rec in cache_records
            )
            tokens_in = int(getattr(result, "tokens_in", 0) or 0) if result else 0
            cache_hit = int(getattr(result, "tokens_cache_hit", 0) or 0) if result else 0
            row = {
                "schema": "lfl-execution-efficiency-v2.2-row/v0.2",
                "row_id": rid,
                "task_id": task["id"],
                "family": task["family"],
                "arm": arm,
                "repeat": repeat,
                "workspace": ws.name,
                "decision_acceptable_tools_v22": task[
                    "decision_acceptable_tools_v22"
                ],
                "decision_required_arguments_v22": task.get(
                    "decision_required_arguments_v22"
                ),
                "neutral_prefix_tools_v22": task.get("neutral_prefix_tools_v22") or [],
                "neutral_prefix_max_v22": int(task.get("neutral_prefix_max_v22") or 0),
                "provider_registry_files": copied,
                "model_ref": eval_model_ref,
                "resolved_provider": provider_id,
                "resolved_model": model_id,
                "wire_protocol": client.wire_protocol,
                "reasoning_effort": settings.reasoning_effort,
                "surface": baseline_surface,
                "wire_records": traces,
                "wire_all_match": wire_match,
                "cache_treatment": "forced_cache_prompt_false",
                "cache_wire_records": cache_records,
                "cache_wire_match": cache_wire_match,
                "run_error": run_error,
                "elapsed_s": elapsed_s,
                "external_pass": passed,
                "verify_error": verify_error,
                "rounds": int(getattr(result, "rounds", 0) or 0) if result else 0,
                "tool_calls": len(getattr(result, "tool_calls", []) or []) if result else 0,
                "tokens_in": tokens_in or None,
                "cache_hit_tokens": cache_hit if tokens_in else None,
                "new_prefill_tokens": max(tokens_in - cache_hit, 0) if tokens_in else None,
                "tokens_out": int(getattr(result, "tokens_out", 0) or 0) if result else None,
                "reasoning_tokens": getattr(result, "reasoning_tokens", None) if result else None,
                "history_compacted": bool(getattr(result, "history_compacted", False))
                if result
                else False,
                "run_incomplete": bool(getattr(result, "run_incomplete", True))
                if result
                else True,
                "fcr_raw": raw_fcr,
                "fcr_scored": legacy_fcr,
                "fcr_events": events,
            }
            row["eev2_scored"] = score_row_v0_2(row, task=task)
            if not cache_records or any(
                rec.get("cache_prompt") is not False for rec in cache_records
            ):
                raise RuntimeError("EEv2.2 cache_prompt=false wire contract missing")
            return row
        finally:
            engine.registry.schemas = original_schemas
    finally:
        engine.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--trace", type=Path, default=DEFAULT_TRACE)
    ap.add_argument("--cache-wire", type=Path, default=DEFAULT_CACHE_WIRE)
    ap.add_argument("--workdir", type=Path, default=DEFAULT_WORKDIR)
    ap.add_argument("--only-row", default="")
    ap.add_argument("--max-rows", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    errors = validate_v0_2()
    if errors:
        raise RuntimeError("EEv2.2 task validation failed: " + "; ".join(errors))
    manifest = _manifest_guard(args.manifest)
    settings = load_settings()
    if args.dry_run:
        print(
            json.dumps(
                {
                    "rows": len(schedule_v0_2()),
                    "arms": list(ARMS_V0_2),
                    "model": manifest["model_ref"],
                    "reasoning_effort": settings.reasoning_effort,
                    "surface_facts": manifest["surface_facts"],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    existing = {}
    if args.output.exists():
        for line in args.output.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                existing[str(row.get("row_id") or "")] = row
    pending = []
    for task, arm, repeat in schedule_v0_2():
        rid = row_id(task["id"], arm, repeat)
        if rid in existing:
            continue
        if args.only_row and rid != args.only_row:
            continue
        pending.append((task, arm, repeat))
    if args.max_rows > 0:
        pending = pending[: args.max_rows]
    args.workdir.mkdir(parents=True, exist_ok=True)
    for task, arm, repeat in pending:
        row = _run_one(
            task,
            arm,
            repeat,
            workdir=args.workdir,
            trace_path=args.trace,
            cache_wire_path=args.cache_wire,
            manifest=manifest,
        )
        _append_jsonl(args.output, row)
        scored = row["eev2_scored"]
        print(
            json.dumps(
                {
                    "row_id": row["row_id"],
                    "pass": row["external_pass"],
                    "fcr": scored["first_call_ready"],
                    "wrong_tool": scored["wrong_tool_first_call_count"],
                    "arg_miss": scored["first_action_oracle_arg_mismatch_count"],
                    "rejects": scored["rejected_call_count"],
                    "barriers": scored["serial_tool_barrier_count"],
                    "wall_s": row["elapsed_s"],
                },
                sort_keys=True,
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
