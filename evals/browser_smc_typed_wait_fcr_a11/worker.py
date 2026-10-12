#!/usr/bin/env python3
"""One fresh read-only Browser mechanically-typed wait A1.1 model run."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

from protocol import ALLOWED_TOOLS, MODEL_REF, MUTATION_TOOLS  # noqa: E402

_WAIT_TOOLS = {
    "browser_wait_scope_url",
    "browser_wait_scope_ready",
    "browser_wait_scope_count",
    "browser_wait_object_state",
    "browser_wait_object_text",
}
_OLD_GENERIC_WAIT_TOOLS = {"browser_wait_scope", "browser_wait_object"}
_REQUIRED = {
    "browser_wait_scope_url": {
        "scope_ref",
        "operator",
        "value",
        "timeout_ms",
        "interval_ms",
    },
    "browser_wait_scope_ready": {
        "scope_ref",
        "state",
        "timeout_ms",
        "interval_ms",
    },
    "browser_wait_scope_count": {
        "scope_ref",
        "operator",
        "count",
        "timeout_ms",
        "interval_ms",
    },
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


def _sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _parse_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
            return dict(value) if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _safe_trace(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, call in enumerate(trace, start=1):
        name = str(call.get("name") or "")
        args = _parse_args(call.get("arguments"))
        row: dict[str, Any] = {
            "index": index,
            "name": name,
            "status": str(call.get("status") or ""),
            "arg_keys": sorted(args),
            "args_sha256": _sha(args),
        }
        if name == "browser_perceive":
            row["action"] = str(args.get("action") or "")
            row["has_predicate"] = "predicate" in args
        elif name in _WAIT_TOOLS:
            row["structurally_complete"] = set(args) == _REQUIRED[name]
            ref_key = "scope_ref" if name.startswith("browser_wait_scope_") else "object_ref"
            ref = str(args.get(ref_key) or "")
            row["ref_kind"] = (
                "scope"
                if ref.startswith("browser-") and ref.endswith(tuple()) is False
                else "object"
                if "/object/" in ref
                else "other"
            )
            if name == "browser_wait_scope_url":
                row["property"] = "url"
                row["operator"] = str(args.get("operator") or "")
                value = args.get("value")
            elif name == "browser_wait_scope_ready":
                row["property"] = "document_ready_state"
                row["operator"] = "eq"
                value = args.get("state")
            elif name == "browser_wait_scope_count":
                row["property"] = "object_count"
                row["operator"] = str(args.get("operator") or "")
                value = args.get("count")
            elif name == "browser_wait_object_state":
                row["property"] = str(args.get("property") or "")
                row["operator"] = "eq"
                value = args.get("value")
            else:
                row["property"] = str(args.get("property") or "")
                row["operator"] = str(args.get("operator") or "")
                value = args.get("value")
            row["value_type"] = type(value).__name__
        rows.append(row)
    return rows


def _tool_wait_results(
    data_dir: Path, session_id: str
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    path = data_dir / "event_logs" / f"{session_id}.jsonl"
    rows: list[dict[str, Any]] = []
    diagnostics = {
        "missing_predicate_failure_count": 0,
        "scope_target_mismatch_failure_count": 0,
    }
    if not path.is_file():
        return rows, diagnostics
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "message.appended":
            continue
        payload = event.get("payload") or {}
        tool_name = str(payload.get("tool_name") or "")
        if payload.get("role") != "tool":
            continue
        content = str(payload.get("content") or "")
        lowered = content.lower()
        diagnostics["missing_predicate_failure_count"] += int(
            "predicate must be a structured object" in lowered
            or "predicate 必须" in content
        )
        diagnostics["scope_target_mismatch_failure_count"] += int(
            "scope predicate target must equal its exact scope_ref" in lowered
        )
        if tool_name not in _WAIT_TOOLS:
            continue
        parsed: dict[str, Any] = {}
        pos = content.find("{")
        if pos >= 0:
            try:
                value = json.loads(content[pos:])
                if isinstance(value, dict):
                    parsed = value
            except json.JSONDecodeError:
                pass
        predicate_result = parsed.get("predicate_result") or {}
        observation = parsed.get("observation") or {}
        predicate = parsed.get("predicate") or {}
        rows.append(
            {
                "tool": tool_name,
                "status": str(payload.get("status") or ""),
                "result": str(predicate_result.get("result") or ""),
                "sample_count": int(predicate_result.get("sample_count") or 0),
                "observer_error_count": int(predicate_result.get("observer_error_count") or 0),
                "observation_reason": observation.get("reason"),
                "predicate_value_type": type(predicate.get("value")).__name__,
            }
        )
    return rows, diagnostics


def _surface(engine: Any) -> dict[str, Any]:
    allowed = set(ALLOWED_TOOLS)
    for name in list(engine.registry.names()):
        if name not in allowed:
            engine.registry.unregister(name)
    schemas = engine.registry.schemas(lazy=True)
    names = engine.registry.names()
    by_name = {str(row.get("name") or ""): row for row in schemas}
    perceive = by_name["browser_perceive"]
    perceive_props = (perceive.get("parameters") or {}).get("properties") or {}
    wait_params = {
        name: by_name[name].get("parameters") or {}
        for name in sorted(_WAIT_TOOLS)
    }
    return {
        "names": names,
        "exact": set(names) == allowed and not (set(names) & MUTATION_TOOLS),
        "sha256": _sha(schemas),
        "json_chars": len(json.dumps(schemas, ensure_ascii=False, sort_keys=True)),
        "tool_sha256": {str(row["name"]): _sha(row) for row in schemas},
        "perceive_actions": list((perceive_props.get("action") or {}).get("enum") or []),
        "perceive_has_predicate": "predicate" in perceive_props,
        "wait_required": {
            name: sorted(params.get("required") or []) for name, params in wait_params.items()
        },
        "wait_interval": {
            name: (params.get("properties") or {}).get("interval_ms")
            for name, params in wait_params.items()
        },
        "ready_state_schema": (
            wait_params["browser_wait_scope_ready"].get("properties") or {}
        ).get("state"),
        "object_state_value_schema": (
            wait_params["browser_wait_object_state"].get("properties") or {}
        ).get("value"),
        "object_state_properties": list(
            (
                (wait_params["browser_wait_object_state"].get("properties") or {}).get(
                    "property"
                )
                or {}
            ).get("enum")
            or []
        ),
        "scope_count_schema": (
            wait_params["browser_wait_scope_count"].get("properties") or {}
        ).get("count"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default="")
    parser.add_argument("--result-json", required=True)
    parser.add_argument("--surface-only", action="store_true")
    args = parser.parse_args()

    from llm_loop.config import load_settings
    from llm_loop.core.trace_leak.ingress_token import issue_ingress
    from llm_loop.factory import build_engine

    settings = load_settings()
    engine = build_engine(settings)
    payload: dict[str, Any] = {"configured_model": MODEL_REF}
    started = time.monotonic()
    try:
        surface = _surface(engine)
        payload["surface"] = surface
        if args.surface_only:
            payload["status"] = "SURFACE_ONLY"
        else:
            sid = engine.session.create()
            result = engine.run(sid, args.prompt, ingress=issue_ingress("cli"))
            trace = _safe_trace(list(result.tool_calls or []))
            wait_rows = [row for row in trace if row["name"] in _WAIT_TOOLS]
            first_wait = wait_rows[0] if wait_rows else {}
            first_wait_index = int(first_wait.get("index") or 0)
            snapshot_before = any(
                row["name"] == "browser_perceive"
                and row.get("action") == "snapshot"
                and row["status"] == "success"
                and int(row["index"]) < first_wait_index
                for row in trace
            )
            legacy_misuse = sum(
                row["name"] == "browser_perceive" and row.get("action") == "wait" for row in trace
            )
            snapshot_predicate = sum(
                row["name"] == "browser_perceive"
                and row.get("action") == "snapshot"
                and bool(row.get("has_predicate"))
                for row in trace
            )
            wait_results, wait_diagnostics = _tool_wait_results(Path(settings.data_dir), sid)
            first_result = wait_results[0] if wait_results else {}
            payload.update(
                {
                    "status": "RUN_OK",
                    "session_sha256": hashlib.sha256(sid.encode()).hexdigest(),
                    "rounds": result.rounds,
                    "tool_calls": trace,
                    "tool_call_count": len(trace),
                    "tokens_in": result.tokens_in,
                    "tokens_out": result.tokens_out,
                    "cache_hit_tokens": result.tokens_cache_hit,
                    "model_used": result.model_used,
                    "fallback_used": bool(result.fallback_receipt),
                    "first_wait_tool": first_wait.get("name"),
                    "first_wait_structurally_complete": bool(
                        first_wait.get("structurally_complete")
                    ),
                    "snapshot_before_first_wait": snapshot_before,
                    "first_wait_result": first_result.get("result"),
                    "first_wait_observation_reason": first_result.get("observation_reason"),
                    "first_wait_value_type": first_wait.get("value_type"),
                    "first_wait_predicate_value_type": first_result.get(
                        "predicate_value_type"
                    ),
                    "first_wait_sample_count": first_result.get("sample_count"),
                    "first_wait_observer_error_count": first_result.get("observer_error_count"),
                    "typed_wait_failure_count": sum(
                        row["status"] != "success" for row in wait_rows
                    ),
                    "legacy_wait_misuse_count": legacy_misuse,
                    "snapshot_predicate_count": snapshot_predicate,
                    **wait_diagnostics,
                    "old_generic_wait_call_count": sum(
                        row["name"] in _OLD_GENERIC_WAIT_TOOLS for row in trace
                    ),
                    "mutation_call_count": sum(row["name"] in MUTATION_TOOLS for row in trace),
                    "get_tool_schema_count": sum(row["name"] == "get_tool_schema" for row in trace),
                }
            )
    except Exception as exc:  # noqa: BLE001
        payload.update(
            {"status": "WORKER_ERROR", "error_type": type(exc).__name__, "error": str(exc)[:500]}
        )
    finally:
        payload["wall_s"] = round(time.monotonic() - started, 3)
        engine.close()

    out = Path(args.result_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return 0 if payload.get("status") in {"RUN_OK", "SURFACE_ONLY"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
