#!/usr/bin/env python3
"""Frozen Experience semantic OFF/ON qualification against the canonical corpus."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def _canonical_root() -> Path:
    explicit = str(os.environ.get("LFL_CANONICAL_ROOT") or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    common_dir = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        text=True,
    ).strip()
    return Path(common_dir).resolve().parent


CANONICAL = _canonical_root()

from llm_loop.config import load_settings  # noqa: E402
from llm_loop.core.trace_leak.ingress_token import issue_ingress  # noqa: E402
from llm_loop.experiences.store import ExperienceStore  # noqa: E402
from llm_loop.factory import build_engine  # noqa: E402
from llm_loop.memory.embedder import APIEmbedder  # noqa: E402
from llm_loop.memory.retriever import SemanticRetriever  # noqa: E402
from llm_loop.runtime.resolver import apply_to_environ, resolve_effective  # noqa: E402

GOLD = Path(__file__).with_name("experience-goldset-20260926.json")


def health() -> dict:
    with urllib.request.urlopen("http://127.0.0.1:8765/healthz", timeout=2) as response:
        return json.loads(response.read())


def _rank(ids: list[str], target: str | None) -> int | None:
    return ids.index(target) + 1 if target and target in ids else None


def tool_phase(output: Path, repeats: int) -> None:
    payload = json.loads(GOLD.read_text(encoding="utf-8"))
    cache_dir = Path(tempfile.mkdtemp(prefix="lfl-experience-tool-cache-"))
    emb = APIEmbedder(api_key="", base_url="http://127.0.0.1:8765/v1", model="bge", timeout_s=1.0)
    sem = SemanticRetriever(emb, timeout_s=1.0)
    sem.configure_experience_cache_dir(cache_dir)
    on = ExperienceStore(CANONICAL / "experiences", semantic_ranker=sem.rank_cached_candidates)
    off = ExperienceStore(CANONICAL / "experiences")
    pre = health()
    warm_started = time.monotonic()
    warm = sem.warm_experience_store(on)
    warm_ms = (time.monotonic() - warm_started) * 1000
    mid = health()
    rows: list[dict] = []
    latencies: list[float] = []
    try:
        for repeat in range(1, repeats + 1):
            for task in payload["tool_tasks"]:
                off_rows = off.search_outcome(task["query"], 5, record_kind=task["kind"]).records
                started = time.monotonic()
                on_rows = on.search_outcome(task["query"], 5, record_kind=task["kind"]).records
                latency = (time.monotonic() - started) * 1000
                latencies.append(latency)
                off_ids = [row["id"] for row in off_rows]
                on_ids = [row["id"] for row in on_rows]
                diag = on.last_semantic_diagnostics
                rows.append(
                    {
                        "repeat": repeat,
                        "id": task["id"],
                        "kind": task["kind"],
                        "class": task["class"],
                        "target": task["target"],
                        "off_ids": off_ids,
                        "on_ids": on_ids,
                        "off_rank": _rank(off_ids, task["target"]),
                        "on_rank": _rank(on_ids, task["target"]),
                        "noise_expansion": [item for item in on_ids if item not in off_ids] if task["class"] == "noise" else [],
                        "semantic_effective": bool(diag.get("semantic_effective")),
                        "semantic_fallback_reason": diag.get("semantic_fallback_reason") or "",
                        "candidate_missing_count": int(diag.get("candidate_missing_count", 0) or 0),
                        "semantic_hit_count": int(diag.get("semantic_hit_count", 0) or 0),
                        "latency_ms": round(latency, 1),
                    }
                )
    finally:
        emb.close()
        shutil.rmtree(cache_dir, ignore_errors=True)
    post = health()
    positive = [row for row in rows if row["target"]]
    noise = [row for row in rows if row["class"] == "noise"]
    gains = [row for row in positive if row["on_rank"] and (row["off_rank"] is None or row["on_rank"] < row["off_rank"])]
    summary = {
        "repeats": repeats,
        "rows": len(rows),
        "warm": warm,
        "warm_wall_ms": round(warm_ms, 1),
        "warm_calls": mid["stats"]["calls"] - pre["stats"]["calls"],
        "warm_texts": mid["stats"]["texts"] - pre["stats"]["texts"],
        "positive_on_rank1": sum(row["on_rank"] == 1 for row in positive),
        "positive_off_rank1": sum(row["off_rank"] == 1 for row in positive),
        "ordering_gain_rows": len(gains),
        "noninferior_positive_rows": sum(bool(row["on_rank"] and (row["off_rank"] is None or row["on_rank"] <= row["off_rank"])) for row in positive),
        "noise_rows_without_expansion": sum(not row["noise_expansion"] for row in noise),
        "noise_rows": len(noise),
        "fallback_runs": sum(bool(row["semantic_fallback_reason"]) for row in rows),
        "missing_sum": sum(row["candidate_missing_count"] for row in rows),
        "latency_p50_ms": round(statistics.median(latencies), 1),
        "latency_max_ms": round(max(latencies), 1),
        "server_error_delta": post["stats"]["errors"] - pre["stats"]["errors"],
        "server_queue_after": post["queue"],
    }
    output.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _prepare_model_settings(arm: str, data_dir: Path):
    effective = resolve_effective("web")
    apply_to_environ(effective)
    settings = load_settings()
    for name in ("providers.local.json", "providers.json"):
        source = CANONICAL / "data" / name
        if source.exists():
            shutil.copy2(source, data_dir / name)
    return replace(
        settings,
        data_dir=str(data_dir),
        experiences_dir=str(CANONICAL / "experiences"),
        methods_dir=str(data_dir / "methods"),
        method_seed_dir=str(ROOT / "methods"),
        skills_dir=str(ROOT / "skills"),
        docs_dir=str(ROOT / "docs"),
        embedding_provider="api",
        semantic_memory_enabled=False,
        semantic_archive_enabled=False,
        semantic_method_enabled=False,
        semantic_docs_enabled=False,
        semantic_experience_enabled=(arm == "on"),
        learning_plane_enabled=False,
        method_reflection_mode="off",
        event_log_enabled=False,
        max_iterations=4,
        _extra={},
    )


def _tool_args(call: dict) -> dict:
    raw = call.get("arguments")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def model_phase(output: Path, repeats: int) -> None:
    payload = json.loads(GOLD.read_text(encoding="utf-8"))
    pre = health()
    rows: list[dict] = []
    for arm in ("off", "on"):
        root = Path(tempfile.mkdtemp(prefix=f"lfl-experience-model-{arm}-"))
        data_dir = root / "data"
        data_dir.mkdir(parents=True)
        (data_dir / "methods").mkdir()
        engine = build_engine(_prepare_model_settings(arm, data_dir))
        try:
            for repeat in range(1, repeats + 1):
                for task in payload["model_tasks"]:
                    sid = engine.session.create()
                    prompt = (
                        f"只调用 search_records 一次，kind={task['kind']}，query={json.dumps(task['query'], ensure_ascii=False)}，limit=5。"
                        "根据返回的 compact discovery cards 判断最直接匹配当前问题的 stable experience_ref。"
                        "历史卡片 task_applicability=not_evaluated，不要把它当当前任务授权。"
                        "如果没有卡片直接支持问题，就输出 NONE。不要水合，不要调用其他工具。"
                        "最终只输出 experience:<id> 或 NONE。"
                    )
                    started = time.monotonic()
                    result = engine.run(sid, prompt, ingress=issue_ingress("cli"))
                    calls = [
                        {"name": call.get("name"), "status": call.get("status"), "arguments": _tool_args(call)}
                        for call in list(result.tool_calls or [])
                    ]
                    answer = (result.final_answer or "").strip().strip("` \n\t.。")
                    search_calls = [call for call in calls if call["name"] == "search_records"]
                    exact_call = (
                        len(search_calls) == 1
                        and search_calls[0]["arguments"].get("kind") == task["kind"]
                        and str(search_calls[0]["arguments"].get("query") or "").strip() == task["query"]
                    )
                    rows.append(
                        {
                            "arm": arm,
                            "repeat": repeat,
                            "id": task["id"],
                            "class": task["class"],
                            "target": task["target"],
                            "correct": answer == task["target"],
                            "answer": answer,
                            "rounds": result.rounds,
                            "model_used": result.model_used,
                            "fallback_used": bool(result.fallback_receipt),
                            "tool_calls": calls,
                            "only_one_exact_search": len(calls) == 1 and exact_call,
                            "elapsed_s": round(time.monotonic() - started, 2),
                        }
                    )
        finally:
            engine.close()
            shutil.rmtree(root, ignore_errors=True)
    post = health()
    summary = {
        "repeats": repeats,
        "rows": len(rows),
        "off_correct": sum(row["correct"] for row in rows if row["arm"] == "off"),
        "on_correct": sum(row["correct"] for row in rows if row["arm"] == "on"),
        "rows_per_arm": len(rows) // 2,
        "only_one_exact_search": sum(row["only_one_exact_search"] for row in rows),
        "fallback_rows": sum(row["fallback_used"] for row in rows),
        "server_error_delta": post["stats"]["errors"] - pre["stats"]["errors"],
        "server_queue_after": post["queue"],
    }
    output.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["tool", "model"])
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if args.phase == "tool":
        tool_phase(output, args.repeats)
    else:
        model_phase(output, args.repeats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
