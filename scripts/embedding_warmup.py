#!/usr/bin/env python3
"""批量预热 versioned embedding 缓存.

- 语料: MemoryStore 全量条目（与 SemanticRetriever._candidates 同格式: content + keywords）
- 使用运行时同一个 APIEmbedder/版本化 cache path，避免 warm legacy embeddings.json
  但运行时继续命中旧 embeddings-<version>.json 的 split-brain；
- 批量走 APIEmbedder.embed_batch，继承 background class / chunk / yield 资源约束；
- 幂等: 只嵌入缓存缺失的条目；写前备份旧文件

用法: .venv/bin/python scripts/embedding_warmup.py [--service http://127.0.0.1:8765/v1] [--model bge]
前置: scripts/embedding_server.py 已启动
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from llm_loop.memory.embedder import APIEmbedder
from llm_loop.memory.retriever import SemanticRetriever
from llm_loop.memory.store import MemoryStore


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--service", default="http://127.0.0.1:8765/v1")
    ap.add_argument("--model", default="bge")
    ap.add_argument("--memory-dir", default="data/memory")
    args = ap.parse_args()

    emb = APIEmbedder(api_key="", base_url=args.service, model=args.model, timeout_s=30)
    retriever = SemanticRetriever(emb, timeout_s=30.0, memory_dir=args.memory_dir)
    version = emb.vector_version
    cache_path = retriever._mem_cache_path
    assert cache_path is not None
    # ck2 binds vectors to candidate content, so warmup must use the exact same
    # candidate/cache-key authority as runtime search.  Ignore any malformed/old
    # stable-id rows accidentally written into the ck2 file by an older warmup script.
    existing: dict[str, list] = {
        key: value
        for key, value in retriever._mem_emb_cache.items()
        if "#sha256:" in key
    }

    ms = MemoryStore(args.memory_dir)
    candidates = retriever._memory_cache_candidates(ms)
    todo = [
        (retriever._vector_cache_key(cand), cand["content"])
        for cand in candidates
        if retriever._vector_cache_key(cand) not in existing
    ]
    print(
        f"[warmup] corpus={len(candidates)} cached={len(existing)} "
        f"todo={len(todo)} version={version}"
    )
    if not todo:
        print("[warmup] 已是最新，无需预热")
        return 0

    if cache_path.exists():
        bak = cache_path.with_suffix(
            f"{cache_path.suffix}.bak-{time.strftime('%Y%m%dT%H%M%S')}"
        )
        shutil.copy2(cache_path, bak)
        print(f"[warmup] 备份当前版本化缓存 -> {bak.name}")
        # Rebuild the active ck2 file from authoritative content-bound keys. This is
        # safe during rolling deployment because ck1 processes use a different file.
        cache_path.unlink()

    t0 = time.time()
    vecs = emb.embed_batch([text for _key, text in todo])
    dt = time.time() - t0
    assert len(vecs) == len(todo)

    for (key, _), v in zip(todo, vecs, strict=True):
        if v is None:
            raise RuntimeError(f"embedding warmup failed for {key}")
        existing[key] = v
    retriever._mem_emb_cache = existing
    retriever._persist_emb_cache(cache_path, existing, emb)
    emb.close()
    print(f"[warmup] 完成: +{len(todo)} 条, 耗时 {dt:.1f}s, 缓存 -> {cache_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
