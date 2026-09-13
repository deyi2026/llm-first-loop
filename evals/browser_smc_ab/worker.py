#!/usr/bin/env python3
"""One fresh LFL run for one arm of the Browser SMC real-model A/B."""

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
sys.path.insert(0, str(REPO / "evals" / "pilot"))

from protocol import ARMS, MODEL_REF  # noqa: E402


def _sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _safe_error(exc: Exception) -> str:
    return (
        str(exc)
        .replace(str(Path.cwd()), "<run_dir>")
        .replace(str(REPO), "<repo>")[:500]
    )


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


def _safe_tool_trace(trace: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    counts = {"legacy_physical_exec": 0, "legacy_dry_run": 0, "smc_perceive": 0, "smc_action": 0}
    for index, call in enumerate(trace, start=1):
        name = str(call.get("name") or "")
        args = _parse_args(call.get("arguments"))
        row: dict[str, Any] = {
            "index": index,
            "name": name,
            "status": call.get("status"),
            "arg_keys": sorted(args),
            "args_sha256": _sha(args),
            "args_chars": len(json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)),
        }
        if name == "browser_perceive":
            counts["smc_perceive"] += 1
            row["action"] = str(args.get("action") or "")
        elif name == "browser_action":
            counts["smc_action"] += 1
            row["verb"] = str(args.get("verb") or "")
            row["version_scope"] = str(args.get("version_scope") or "")
        elif name in {"playwright_exec", "playwright_test"}:
            confirm = bool(args.get("confirm", False))
            row["confirm"] = confirm
            if confirm:
                counts["legacy_physical_exec"] += 1
            else:
                counts["legacy_dry_run"] += 1
            if name == "playwright_exec":
                code = str(args.get("code") or "")
                row["code_chars"] = len(code)
                row["helper_counts"] = {
                    helper: code.count(helper + "(")
                    for helper in ("goto", "click", "fill", "wait", "js", "axtree_text", "screenshot")
                }
        rows.append(row)
    return rows, counts


def _receipt_facts(data_dir: Path) -> dict[str, Any]:
    root = data_dir / "browser_action"
    terminal: list[dict[str, Any]] = []
    retry_true = 0
    scope_blockers = 0
    if root.is_dir():
        for path in root.rglob("receipts.jsonl"):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    doc = json.loads(line)
                except json.JSONDecodeError:
                    continue
                retry = doc.get("retry") or {}
                completeness = doc.get("completeness") or {}
                reasons = [str(reason) for reason in (completeness.get("reasons") or [])]
                scope_blockers += sum(
                    "version_scope_mismatch" in reason
                    or "different_snapshot_same_generation" in reason
                    for reason in reasons
                )
                retry_true += int(retry.get("automatic_retry_performed") is True)
                if doc.get("status") in {"ok", "failed", "rejected"}:
                    terminal.append(
                        {
                            "status": doc.get("status"),
                            "verb": doc.get("verb"),
                            "retry_reason": retry.get("reason"),
                            "boundary_events": [e.get("event") for e in (doc.get("boundary_events") or []) if isinstance(e, dict)],
                            "completeness_complete": bool(completeness.get("complete")),
                            "completeness_reasons": reasons,
                        }
                    )
    return {
        "terminal_count": len(terminal),
        "terminal": terminal,
        "automatic_retry_true_count": retry_true,
        "ok_count": sum(row["status"] == "ok" for row in terminal),
        "failed_count": sum(row["status"] == "failed" for row in terminal),
        "rejected_count": sum(row["status"] == "rejected" for row in terminal),
        "scope_blocker_count": scope_blockers,
    }


def _surface(engine: Any, arm: str) -> dict[str, Any]:
    allowed = set(ARMS[arm]["allowed_tools"])
    for name in list(engine.registry.names()):
        if name not in allowed:
            engine.registry.unregister(name)
    names = engine.registry.names()
    schemas = engine.registry.schemas(lazy=True)
    return {
        "names": names,
        "exact": set(names) == allowed,
        "sha256": _sha(schemas),
        "json_chars": len(json.dumps(schemas, ensure_ascii=False, sort_keys=True)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=sorted(ARMS), required=True)
    parser.add_argument("--prompt", default="")
    parser.add_argument("--result-json", required=True)
    parser.add_argument("--surface-only", action="store_true")
    args = parser.parse_args()

    from llm_loop.config import load_settings
    from llm_loop.core.trace_leak.ingress_token import issue_ingress
    from llm_loop.factory import build_engine

    settings = load_settings()
    engine = build_engine(settings)
    started = time.monotonic()
    payload: dict[str, Any] = {"arm": args.arm, "configured_model": MODEL_REF}
    try:
        surface = _surface(engine, args.arm)
        payload["surface"] = surface
        if args.surface_only:
            payload["status"] = "SURFACE_ONLY"
        else:
            sid = engine.session.create()
            result = engine.run(sid, args.prompt, ingress=issue_ingress("cli"))
            trace, counts = _safe_tool_trace(list(result.tool_calls or []))
            data_dir = Path(settings.data_dir)
            receipts = _receipt_facts(data_dir)
            raw_fcr: dict[str, Any] | None = None
            try:
                from telemetry import fcr_lfl

                raw_fcr, _events = fcr_lfl(Path.cwd(), sid)
            except Exception:
                raw_fcr = None
            payload.update(
                {
                    "status": "RUN_OK",
                    "session_sha256": hashlib.sha256(sid.encode("utf-8")).hexdigest(),
                    "rounds": result.rounds,
                    "tool_calls": trace,
                    "tool_call_count": len(trace),
                    "tokens_in": result.tokens_in,
                    "tokens_out": result.tokens_out,
                    "cache_hit_tokens": result.tokens_cache_hit,
                    "truncated": bool(result.truncated),
                    "model_used": result.model_used,
                    "fallback_used": bool(result.fallback_receipt),
                    "final_answer_chars": len(result.final_answer or ""),
                    "final_answer_sha256": hashlib.sha256((result.final_answer or "").encode("utf-8")).hexdigest(),
                    "smc_perceive_count": counts["smc_perceive"],
                    "smc_action_count": counts["smc_action"],
                    "smc_adopted": counts["smc_perceive"] > 0 and counts["smc_action"] > 0,
                    "legacy_physical_exec_count": counts["legacy_physical_exec"],
                    "legacy_dry_run_count": counts["legacy_dry_run"],
                    "receipt_facts": receipts,
                    "fcr_raw": raw_fcr,
                }
            )
    except Exception as exc:  # noqa: BLE001 - worker error must be serialized for classification.
        payload.update(
            {
                "status": "WORKER_ERROR",
                "error_type": type(exc).__name__,
                "error": _safe_error(exc),
            }
        )
    finally:
        payload["wall_s"] = round(time.monotonic() - started, 3)
        engine.close()

    out = Path(args.result_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return 0 if payload.get("status") in {"RUN_OK", "SURFACE_ONLY"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
