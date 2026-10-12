#!/usr/bin/env python3
"""One fresh LFL run for the Browser compact Method Card A/B."""

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

from protocol import ARMS, METHOD_REF, METHOD_SHA256, MODEL_REF  # noqa: E402

CARD_MARKER = "[Semantic Operation Method]"
BASELINE_COMPACT_PERCEIVE = (
    "Browser SMC Phase 1 只读感知（opt-in loopback CDP host）：snapshot/hydrate/diff/wait；"
    "DOM+AX→WorldSnapshot/SemanticObject，wait=结构化 Predicate 轮询；冲突/coverage/scope/grounding 如实返回；"
    "不导航、不执行 mutation，不暴露 selector/坐标/CDP node id/AX index。"
    "通用操作方法按需 search_records(kind=method, query=method:method-semantic-operation)。"
)
BASELINE_COMPACT_ACTION = (
    "Browser SMC Phase 1 写操作：click/fill/select/navigate/scroll；使用 snapshot 的 exact Semantic ID/scope + expected_version，"
    "object mutation=object，navigate=resource，snapshot 不作为 mutation version_scope；dispatch 前机械复核；"
    "单次 dispatch，不自动 retry/rebind；ActionReceipt 只表示机械事实，不等于任务完成。"
    "通用方法按需 search_records(kind=method, query=method:method-semantic-operation)。"
)
BASELINE_FULL_ACTION = (
    "SMC Browser Phase 1 写操作（显式 opt-in）。仅支持 click/fill/select/navigate/scroll。"
    "必须提交完整 SemanticAction v0.1 与 expected_version/version_scope；runtime 会在 dispatch 前"
    "重新只读观察、核对 exact Semantic ID/version，只在机械 match 时单次 dispatch。"
    "click/fill/select/scroll 的 version_scope 固定为 object；navigate 固定为 resource；"
    "snapshot 是只读 observation/version 语义，不是 mutation precondition scope。"
    "stale/indeterminate/identity ambiguity 会 rejected；同一 action_id 不会再次执行。"
    "所有 mutation idempotency=unknown、atomicity=single_dispatch，绝不自动 retry/replay/rebind。"
    "ActionReceipt 只表示机械执行/观察事实，不代表任务完成或语义成功。"
    "通用语义操作方法可按需 search_records(kind=method, query=method:method-semantic-operation) 精确水合；"
    "是否加载和如何应用由模型决定。"
)
BASELINE_FULL_PERCEIVE = (
    "SMC Browser Phase 1 只读感知。snapshot=读取 host 已绑定的当前页面 DOM+AX，返回"
    "WorldSnapshot + SemanticObject；不会打开 URL、导航、点击、输入、滚动、执行脚本或自动重试。"
    "hydrate=按精确 GroundingRef 水合该次历史 observation；diff=仅比较两张已落盘 exact snapshot，"
    "不会重抓当前页面，也不会按名称/角色猜测对象对应关系。wait=对 structured Predicate 做只读轮询；"
    "超时未满足是 observation，不是工具故障；感官/coverage 不足返回 indeterminate。"
    "ref 过期/跨 session/不可用会如实返回。"
    "模型面只出现 Semantic ID/scope/GroundingRef，不暴露 CSS/XPath/坐标/CDP node id/AX index。"
    "通用语义操作方法可按需 search_records(kind=method, query=method:method-semantic-operation) 精确水合；"
    "是否加载和如何应用由模型决定。"
)


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
    counts = {
        "smc_perceive": 0,
        "smc_action": 0,
        "method_search": 0,
        "method_exact_query": 0,
        "method_exact_success": 0,
    }
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
        elif name == "search_records" and str(args.get("kind") or "") == "method":
            counts["method_search"] += 1
            query = str(args.get("query") or "").strip()
            exact = query == METHOD_REF
            row["method_query_exact"] = exact
            if exact:
                counts["method_exact_query"] += 1
                if call.get("status") == "success":
                    counts["method_exact_success"] += 1
        rows.append(row)
    return rows, counts


def _receipt_facts(data_dir: Path) -> dict[str, Any]:
    root = data_dir / "browser_action"
    terminal: list[dict[str, Any]] = []
    retry_true = 0
    scope_blockers = 0
    reason_counts: dict[str, int] = {}
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
                for reason in reasons:
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1
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
        "object_ok_count": sum(
            row["status"] == "ok" and row["verb"] in {"click", "fill", "select", "scroll"}
            for row in terminal
        ),
        "navigate_ok_count": sum(row["status"] == "ok" and row["verb"] == "navigate" for row in terminal),
        "failed_count": sum(row["status"] == "failed" for row in terminal),
        "rejected_count": sum(row["status"] == "rejected" for row in terminal),
        "scope_blocker_count": scope_blockers,
        "reason_counts": dict(sorted(reason_counts.items())),
    }


def _apply_card_treatment(engine: Any, arm: str) -> None:
    if arm != "card_off":
        return
    import llm_loop.tools.registry as registry_module

    registry_module._COMPACT_TOOL_DESCRIPTIONS["browser_perceive"] = BASELINE_COMPACT_PERCEIVE
    registry_module._COMPACT_TOOL_DESCRIPTIONS["browser_action"] = BASELINE_COMPACT_ACTION
    engine.registry.get("browser_perceive").description = BASELINE_FULL_PERCEIVE
    engine.registry.get("browser_action").description = BASELINE_FULL_ACTION


def _surface(engine: Any, arm: str) -> dict[str, Any]:
    _apply_card_treatment(engine, arm)
    allowed = set(ARMS[arm]["allowed_tools"])
    for name in list(engine.registry.names()):
        if name not in allowed:
            engine.registry.unregister(name)
    names = engine.registry.names()
    schemas = engine.registry.schemas(lazy=True)
    normalized = json.loads(json.dumps(schemas))
    for row in normalized:
        if row.get("name") in {"browser_perceive", "browser_action"}:
            row["description"] = "<browser-card-treatment>"
    browser_descriptions = {
        row["name"]: str(row.get("description") or "")
        for row in schemas
        if row.get("name") in {"browser_perceive", "browser_action"}
    }
    return {
        "names": names,
        "exact": set(names) == allowed,
        "sha256": _sha(schemas),
        "structure_sha256": _sha(normalized),
        "json_chars": len(json.dumps(schemas, ensure_ascii=False, sort_keys=True)),
        "method_card_visible": all(CARD_MARKER in value for value in browser_descriptions.values()),
        "browser_description_sha256": {name: hashlib.sha256(value.encode()).hexdigest() for name, value in browser_descriptions.items()},
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
    from llm_loop.methods.store import MethodStore

    settings = load_settings()
    method_record = MethodStore(settings.methods_dir, seed_dir=settings.method_seed_dir).get(METHOD_REF)
    method_available = method_record is not None
    method_content_hash = method_record.content_hash if method_record is not None else None
    engine = build_engine(settings)
    started = time.monotonic()
    payload: dict[str, Any] = {
        "arm": args.arm,
        "configured_model": MODEL_REF,
        "method_ref": METHOD_REF,
        "method_expected_available": True,
        "method_card_expected_visible": bool(ARMS[args.arm]["method_card_visible"]),
        "method_available": method_available,
        "method_content_hash": method_content_hash,
        "method_content_hash_expected": METHOD_SHA256 if method_available else None,
    }
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
                    "method_search_count": counts["method_search"],
                    "method_exact_query_count": counts["method_exact_query"],
                    "method_exact_success_count": counts["method_exact_success"],
                    "method_hydrated": bool(
                        method_available
                        and method_content_hash == METHOD_SHA256
                        and counts["method_exact_success"] > 0
                    ),
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
