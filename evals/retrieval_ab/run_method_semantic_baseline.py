#!/usr/bin/env python3
"""Frozen 30-query method-card retrieval baseline.

Channels: current keyword (MethodStore.list), CJK-bigram keyword diagnostic,
semantic-only, and the production fusion path (keyword list + semantic RRF,
same parameters as RecordSearcher._search_method for method scope).

The method corpus is copied to a temporary directory before warming so the
production data directory and its embedding cache are never written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from llm_loop.config import load_settings  # noqa: E402
from llm_loop.memory.embedder import APIEmbedder, HashEmbedder  # noqa: E402
from llm_loop.memory.retriever import SemanticRetriever  # noqa: E402
from llm_loop.methods.store import MethodStore  # noqa: E402

TOKEN = re.compile(r"[a-z0-9]{2,}|[\u4e00-\u9fff]+")
HAN = re.compile(r"[\u4e00-\u9fff]")


def load_env(path: Path) -> None:
    """Load .env without python-dotenv; quoted values and trailing comments handled."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if value[:1] in {"'", '"'}:
            value = value[1:-1]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        os.environ.setdefault(key.strip(), value)


def bigram_query(query: str) -> str:
    """Approximate CJK tokenization with overlapping bigrams (diagnostic only)."""
    terms: list[str] = []
    for run in TOKEN.findall(query.lower()):
        if HAN.match(run):
            terms.extend(run[i : i + 2] for i in range(max(1, len(run) - 1)))
        else:
            terms.append(run)
    return " ".join(terms)


def ids_of(entries: list[dict]) -> list[str]:
    return [str(entry.get("id") or "") for entry in entries]


def rank_of(ids: list[str], target: str) -> int | None:
    for position, item in enumerate(ids, 1):
        if item == target:
            return position
    return None


def percentile(values: list[float], ratio: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * ratio))
    return round(ordered[index], 2)


def summarize(rows: list[dict], channel: str) -> dict:
    ranks = [row[channel + "_rank"] for row in rows]
    total = len(ranks)
    latencies = [row[channel + "_ms"] for row in rows]
    result = {
        "hit@1": round(sum(1 for rank in ranks if rank == 1) / total, 4),
        "hit@3": round(sum(1 for rank in ranks if rank and rank <= 3) / total, 4),
        "hit@5": round(sum(1 for rank in ranks if rank and rank <= 5) / total, 4),
        "hit@10": round(sum(1 for rank in ranks if rank and rank <= 10) / total, 4),
        "mrr@10": round(sum(1.0 / rank for rank in ranks if rank) / total, 4),
        "latency_ms": {
            "mean": round(statistics.mean(latencies), 2),
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
        },
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--goldset",
        default=str(ROOT / "evals/retrieval_ab/method-goldset-20261020.json"),
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "evals/retrieval_ab/method-semantic-baseline-20261020.json"),
    )
    parser.add_argument("--methods-dir", default=str(ROOT / "data/methods"))
    parser.add_argument("--limit", type=int, default=5, help="production method limit")
    parser.add_argument("--semantic-top-k", type=int, default=10, help="rank depth measured")
    parser.add_argument("--no-warm", action="store_true")
    args = parser.parse_args()

    load_env(ROOT / ".env")
    settings = load_settings()
    goldset_path = Path(args.goldset)
    goldset = json.loads(goldset_path.read_text(encoding="utf-8"))

    tempdir = Path(tempfile.mkdtemp(prefix="method-baseline-"))
    corpus = tempdir / "methods"
    shutil.copytree(args.methods_dir, corpus)
    store = MethodStore(str(corpus), workspace_root=str(ROOT))
    embedder = APIEmbedder(
        api_key=settings.embedding_api_key,
        base_url=settings.embedding_base_url,
        model=settings.embedding_model,
    )
    retriever = SemanticRetriever(
        embedder,
        timeout_s=settings.retrieve_timeout_s,
        semantic_top_k=settings.retrieve_semantic_top_k,
        memory_dir=settings.memory_dir,
        archive_dir=settings.archive_dir,
        fallback_embedder=HashEmbedder(dim=settings.embedding_dim),
    )
    retriever.configure_method_dir(str(corpus))
    probe = embedder.embed("dimension probe")
    warm = None
    if not args.no_warm:
        warm = retriever.warm_method_store(store, max_candidates=5000, max_passes=3)

    rows: list[dict] = []
    for item in goldset["queries"]:
        query, target = item["query"], item["id"]
        row: dict = {"id": target, "status": item["status"], "query": query}

        started = time.perf_counter()
        keyword = store.list(query, args.limit)
        row["keyword_ms"] = (time.perf_counter() - started) * 1000
        row["keyword_ids"] = ids_of(keyword)

        started = time.perf_counter()
        bigram = store.list(bigram_query(query), args.limit)
        row["bigram_ms"] = (time.perf_counter() - started) * 1000
        row["bigram_ids"] = ids_of(bigram)

        keyword_hits = store.list(query, max(args.limit * 4, 20))
        started = time.perf_counter()
        semantic = retriever.search(
            query, top_k=args.semantic_top_k, scope="method", method=store, keyword_results=[]
        )
        row["semantic_ms"] = (time.perf_counter() - started) * 1000
        row["semantic_mode"] = semantic.mode
        row["semantic_ids"] = ids_of(semantic.entries)

        started = time.perf_counter()
        fused = retriever.search(
            query,
            top_k=args.semantic_top_k,
            scope="method",
            method=store,
            keyword_results=keyword_hits,
        )
        row["prod_ms"] = (time.perf_counter() - started) * 1000
        row["prod_mode"] = fused.mode
        row["prod_ids"] = ids_of(fused.entries)

        for channel in ("keyword", "bigram", "semantic", "prod"):
            row[channel + "_rank"] = rank_of(row[channel + "_ids"], target)
        rows.append(row)

    statuses = sorted({row["status"] for row in rows})
    result = {
        "schema": "method-retrieval-baseline/v1",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "goldset": {
            "path": str(goldset_path.relative_to(ROOT)),
            "sha256": hashlib.sha256(goldset_path.read_bytes()).hexdigest(),
            "queries": len(rows),
        },
        "config": {
            "provider": settings.embedding_provider,
            "model": settings.embedding_model,
            "dim_setting": settings.embedding_dim,
            "dim_actual": len(probe) if probe else None,
            "semantic_available": retriever.semantic_available(),
            "semantic_top_k": settings.retrieve_semantic_top_k,
            "method_limit": args.limit,
            "warm": warm,
        },
        "channels": {},
        "by_status": {},
        "rows": rows,
    }
    for channel in ("keyword", "bigram", "semantic", "prod"):
        result["channels"][channel] = summarize(rows, channel)
    for status in statuses:
        subset = [row for row in rows if row["status"] == status]
        result["by_status"][status] = {
            channel: summarize(subset, channel) for channel in ("keyword", "bigram", "semantic", "prod")
        }

    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result["channels"], ensure_ascii=False, indent=1))
    shutil.rmtree(tempdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
