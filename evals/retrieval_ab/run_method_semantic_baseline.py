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
import dataclasses
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import llm_loop  # noqa: E402
from llm_loop.config import load_settings  # noqa: E402
from llm_loop.memory.embedder import APIEmbedder, HashEmbedder  # noqa: E402
from llm_loop.memory.retriever import SemanticRetriever  # noqa: E402
from llm_loop.methods import store as store_module  # noqa: E402
from llm_loop.methods.store import MethodStore  # noqa: E402

ALIAS_MODES = ("weak", "off")


def repo_relative(path: str | Path) -> str:
    """Repo-relative label for artifacts; absolute paths must not leak into commits."""
    try:
        return str(Path(path).resolve().relative_to(ROOT.resolve()))
    except (ValueError, OSError):
        return f"<outside-repo>/{Path(path).name}"


def code_provenance() -> dict:
    """Measure which code this harness actually imported.

    The repo keeps deployed snapshots under ``.releases/`` and shells may export
    ``PYTHONPATH`` pointing at one, so an eval can silently score the wrong tree.
    Every number below is measured here, never assumed. Paths are recorded
    repo-relative so the artifact stays portable and commit-safe.
    """
    store_file = Path(store_module.__file__).resolve()
    head = ""
    try:
        head = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        head = ""
    return {
        "llm_loop_file": repo_relative(Path(llm_loop.__file__).resolve()),
        "store_file": repo_relative(store_file),
        "store_sha256": hashlib.sha256(store_file.read_bytes()).hexdigest(),
        "alias_weight": getattr(store_module, "_ALIAS_WEIGHT", None),
        "git_head": head,
        "pythonpath": [repo_relative(entry) for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep) if entry],
    }


def without_aliases(store: MethodStore, only_ids: frozenset[str] | None = None) -> MethodStore:
    """Eval-only ablation: drop author aliases right after parsing.

    Both the lexical arm and the semantic candidate projection read records through
    ``_load_path``, so one wrapper removes the alias channel from both arms. This
    mutates the temporary-corpus store instance only; production code is untouched.
    ``only_ids`` restricts the ablation to named cards, which is how a later alias
    batch is separated from an earlier one without rewriting any card on disk.
    """
    original = store._load_path

    def load_without_aliases(path: Path):
        record = original(path)
        if record is None or not record.aliases:
            return record
        if only_ids is not None and record.method_id not in only_ids:
            return record
        return dataclasses.replace(record, aliases=())

    store._load_path = load_without_aliases  # type: ignore[method-assign]
    return store


def is_working_tree_module(module_file: str, src_root: Path) -> bool:
    """True only when the scored module lives under this repo's ``src/`` tree.

    Pure and side-effect free so a unit test can feed the exact paths the guard
    must reject (``.releases/<sha>/src/...``) without running a full eval.
    """
    try:
        return Path(module_file).resolve().is_relative_to(Path(src_root).resolve())
    except OSError:
        return False


def count_aliased_cards(corpus: Path) -> int:
    total = 0
    for card in corpus.iterdir():
        method = card / "METHOD.md"
        if not method.is_file():
            continue
        if re.search(r"^aliases:", method.read_text(encoding="utf-8", errors="replace"), re.M):
            total += 1
    return total

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
    parser.add_argument(
        "--alias-mode",
        choices=ALIAS_MODES,
        default="weak",
        help="weak: production behaviour (_ALIAS_WEIGHT channel); off: neutralize author aliases",
    )
    parser.add_argument(
        "--allow-foreign-code",
        action="store_true",
        help="permit scoring code imported from outside <repo>/src (default: fail closed)",
    )
    parser.add_argument(
        "--alias-off-ids",
        default="",
        help="path to newline-separated method_ids whose aliases are neutralized (batch ablation)",
    )
    args = parser.parse_args()

    provenance = code_provenance()
    src_root = (ROOT / "src").resolve()
    inside_tree = is_working_tree_module(str(Path(llm_loop.__file__).resolve()), src_root)
    provenance["imported_from_working_tree"] = inside_tree
    if not inside_tree and not args.allow_foreign_code:
        print(
            "[fail-closed] llm_loop resolved outside the working tree:\n"
            f"  imported: {provenance['llm_loop_file']}\n"
            f"  expected under: {src_root}\n"
            "This usually means PYTHONPATH points at a .releases/ snapshot. "
            "Re-run with PYTHONPATH= (or pass --allow-foreign-code to score it deliberately).",
            file=sys.stderr,
        )
        return 2

    load_env(ROOT / ".env")
    settings = load_settings()
    goldset_path = Path(args.goldset)
    goldset = json.loads(goldset_path.read_text(encoding="utf-8"))

    tempdir = Path(tempfile.mkdtemp(prefix="method-baseline-"))
    corpus = tempdir / "methods"
    shutil.copytree(args.methods_dir, corpus)
    store = MethodStore(str(corpus), workspace_root=str(ROOT))
    aliased_cards = count_aliased_cards(corpus)
    drop_ids: frozenset[str] | None = None
    if args.alias_off_ids:
        drop_ids = frozenset(
            line.strip()
            for line in Path(args.alias_off_ids).read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    if args.alias_mode == "off":
        store = without_aliases(store)
    elif drop_ids is not None:
        store = without_aliases(store, only_ids=drop_ids)
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
            "alias_mode": args.alias_mode,
            "aliased_cards": aliased_cards,
            "alias_off_ids": len(drop_ids) if drop_ids is not None else 0,
            "provenance": provenance,
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
