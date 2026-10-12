#!/usr/bin/env python3
"""Resource, freshness, write-time and fail-open gates for Experience semantic."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def _canonical_root() -> Path:
    common_dir = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        text=True,
    ).strip()
    return Path(common_dir).resolve().parent


CANONICAL = _canonical_root()

from llm_loop.experiences.document import ExperienceDocument  # noqa: E402
from llm_loop.experiences.store import ExperienceStore  # noqa: E402
from llm_loop.memory.embedder import APIEmbedder  # noqa: E402
from llm_loop.memory.retriever import SemanticRetriever  # noqa: E402


def health() -> dict:
    with urllib.request.urlopen("http://127.0.0.1:8765/healthz", timeout=2) as response:
        return json.loads(response.read())


def wait_background(retriever: SemanticRetriever, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not bool(getattr(retriever, "_prewarm_inflight", False)):
            return
        time.sleep(0.02)
    raise TimeoutError("background Experience prewarm did not settle")


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="lfl-experience-resource-"))
    exp_dir = CANONICAL / "experiences"
    result: dict = {}
    try:
        # Gate 1: a totally cold API cache must not make foreground embed requests.
        cold_cache = work / "cold-cache"
        cold_emb = APIEmbedder(api_key="", base_url="http://127.0.0.1:8765/v1", model="bge", timeout_s=1.0)
        cold = SemanticRetriever(cold_emb, timeout_s=1.0)
        cold.configure_experience_cache_dir(cold_cache)
        cold_store = ExperienceStore(exp_dir, semantic_ranker=cold.rank_cached_candidates)
        lexical_store = ExperienceStore(exp_dir)
        query = "readonly 工具都卡住但 execute_command 正常，怎么判断是线程池阻塞还是服务挂了"
        lexical_ids = [row["id"] for row in lexical_store.search_outcome(query, 5, record_kind="experience").records]
        h0 = health()
        started = time.monotonic()
        cold_rows = cold_store.search_outcome(query, 5, record_kind="experience").records
        cold_ms = (time.monotonic() - started) * 1000
        h1 = health()
        cold_diag = dict(cold_store.last_semantic_diagnostics)
        wait_background(cold)
        h2 = health()
        result["cold_fail_open"] = {
            "latency_ms": round(cold_ms, 1),
            "same_lexical_order": [row["id"] for row in cold_rows] == lexical_ids,
            "fallback_reason": cold_diag.get("semantic_fallback_reason"),
            "missing_count": cold_diag.get("candidate_missing_count"),
            "prewarm_scheduled": cold_diag.get("prewarm_scheduled"),
            "foreground_calls_delta": h1["stats"]["foreground_calls"] - h0["stats"]["foreground_calls"],
            "background_calls_after_settle": h2["stats"]["background_calls"] - h0["stats"]["background_calls"],
            "background_diag": dict(getattr(cold, "_last_background_diag", {}) or {}),
        }

        # Gate 2: startup warm completes the whole canonical set, then hot query costs one foreground embed.
        warm = cold.warm_experience_store(cold_store)
        h3 = health()
        started = time.monotonic()
        hot_rows = cold_store.search_outcome(query, 5, record_kind="experience").records
        hot_ms = (time.monotonic() - started) * 1000
        h4 = health()
        result["startup_warm_hot"] = {
            "warm": warm,
            "latency_ms": round(hot_ms, 1),
            "top1": hot_rows[0]["id"] if hot_rows else None,
            "semantic_diagnostics": cold_store.last_semantic_diagnostics,
            "foreground_calls_delta": h4["stats"]["foreground_calls"] - h3["stats"]["foreground_calls"],
        }

        # Gate 3: a long-lived reader sees vectors persisted by another retriever process-equivalent instance.
        shared_cache = work / "shared-cache"
        reader_emb = APIEmbedder(api_key="", base_url="http://127.0.0.1:8765/v1", model="bge", timeout_s=1.0)
        reader = SemanticRetriever(reader_emb, timeout_s=1.0)
        reader.configure_experience_cache_dir(shared_cache)
        reader_store = ExperienceStore(exp_dir, semantic_ranker=reader.rank_cached_candidates)
        writer_emb = APIEmbedder(api_key="", base_url="http://127.0.0.1:8765/v1", model="bge", timeout_s=1.0)
        writer = SemanticRetriever(writer_emb, timeout_s=1.0)
        writer.configure_experience_cache_dir(shared_cache)
        writer_store = ExperienceStore(exp_dir, semantic_ranker=writer.rank_cached_candidates)
        writer_warm = writer.warm_experience_store(writer_store)
        refresh_rows = reader_store.search_outcome(query, 5, record_kind="experience").records
        result["cross_process_refresh"] = {
            "writer_remaining_missing": writer_warm.get("remaining_missing"),
            "reader_top1": refresh_rows[0]["id"] if refresh_rows else None,
            "reader_diagnostics": reader_store.last_semantic_diagnostics,
        }

        # Gate 4: a new durable Experience schedules its vector before the first search.
        new_exp_dir = work / "new-experiences"
        new_cache = work / "new-cache"
        write_emb = APIEmbedder(api_key="", base_url="http://127.0.0.1:8765/v1", model="bge", timeout_s=1.0)
        write_sem = SemanticRetriever(write_emb, timeout_s=1.0)
        write_sem.configure_experience_cache_dir(new_cache)
        write_store = ExperienceStore(new_exp_dir, semantic_ranker=write_sem.rank_cached_candidates)
        write_store.add_post_save_hook(write_sem.schedule_experience_candidate)
        doc = ExperienceDocument(
            title="服务重启统一经过 managed service control",
            scenario="需要安全重启受托管的 LFL 服务",
            root_cause="绕过受管控制面会丢失代次与回执身份",
            solution="通过 managed service control 登记并验证动作终态",
            evidence="qualification fixture",
            tags=["service-control", "restart"],
            source={"kind": "qualification"},
            record_kind="experience",
            verification_state="verified",
        )
        h5 = health()
        filename = write_store.save(doc)
        wait_background(write_sem)
        h6 = health()
        candidates = write_store.semantic_candidates(record_kind="experience")
        missing_after_write = write_sem._missing_candidate_count(candidates, write_sem._primary_engine())  # noqa: SLF001
        first_rows = write_store.search_outcome("托管服务重启要走哪个控制面", 5, record_kind="experience").records
        h7 = health()
        result["write_time_vectorization"] = {
            "filename": filename,
            "background_calls_delta": h6["stats"]["background_calls"] - h5["stats"]["background_calls"],
            "missing_after_write": missing_after_write,
            "first_query_top1": first_rows[0]["id"] if first_rows else None,
            "first_query_foreground_calls": h7["stats"]["foreground_calls"] - h6["stats"]["foreground_calls"],
            "first_query_diagnostics": write_store.last_semantic_diagnostics,
        }

        # Gate 5: with candidate vectors hot but query endpoint unavailable, preserve lexical order.
        dead_emb = APIEmbedder(api_key="", base_url="http://127.0.0.1:9/v1", model="bge", timeout_s=0.05)
        dead = SemanticRetriever(dead_emb, timeout_s=0.08)
        dead.configure_experience_cache_dir(work / "dead-cache")
        # Fault injection seeds only derived candidate vectors; query transport remains the real dead endpoint.
        dead._experience_emb_cache.update(cold._experience_emb_cache)  # noqa: SLF001
        dead_store = ExperienceStore(exp_dir, semantic_ranker=dead.rank_cached_candidates)
        started = time.monotonic()
        dead_rows = dead_store.search_outcome(query, 5, record_kind="experience").records
        dead_ms = (time.monotonic() - started) * 1000
        result["query_transport_fail_open"] = {
            "latency_ms": round(dead_ms, 1),
            "same_lexical_order": [row["id"] for row in dead_rows] == lexical_ids,
            "diagnostics": dead_store.last_semantic_diagnostics,
            "degradation_marked": bool(dead_rows and "[语义检索降级]" in str(dead_rows[0].get("degraded") or "")),
        }

        for embedder in (cold_emb, reader_emb, writer_emb, write_emb, dead_emb):
            embedder.close()
        final = health()
        result["server_final"] = {"errors": final["stats"]["errors"], "queue": final["queue"]}
        output = ROOT / "evals/retrieval_ab/experience-resource-faults-20260926.json"
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
