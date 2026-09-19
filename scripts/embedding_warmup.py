#!/usr/bin/env python3
"""批量预热 embedding 缓存（阶段 1 配套: API 模式冷启动超时降级的解法）.

- 语料: MemoryStore 全量条目（与 SemanticRetriever._candidates 同格式: content + keywords）
- 批量走本地服务 /v1/embeddings（list input），写 data/memory/embeddings.json
- 版本键 = APIEmbedder.vector_version（同实例取值，保证与运行时一致）
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

import httpx

from llm_loop.memory.embedder import APIEmbedder
from llm_loop.memory.store import MemoryStore

BATCH = 256


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--service", default="http://127.0.0.1:8765/v1")
    ap.add_argument("--model", default="bge")
    ap.add_argument("--memory-dir", default="data/memory")
    args = ap.parse_args()

    emb = APIEmbedder(api_key="", base_url=args.service, model=args.model, timeout_s=30)
    version = emb.vector_version
    cache_path = Path(args.memory_dir) / "embeddings.json"

    existing: dict[str, list] = {}
    if cache_path.exists():
        import json

        raw = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and raw.get("v") == version:
            existing = raw.get("data", {})
        else:
            bak = cache_path.with_suffix(f".json.bak-{time.strftime('%Y%m%dT%H%M%S')}")
            shutil.copy2(cache_path, bak)
            print(f"[warmup] 版本变更({raw.get('v', '?')}→{version})，旧缓存备份 -> {bak.name}")

    ms = MemoryStore(args.memory_dir)
    entries = ms.all()
    todo = [
        (f"memory:{e.id}", f"{e.content} {' '.join(e.keywords)}")
        for e in entries
        if f"memory:{e.id}" not in existing
    ]
    print(f"[warmup] corpus={len(entries)} cached={len(existing)} todo={len(todo)} version={version}")
    if not todo:
        print("[warmup] 已是最新，无需预热")
        return 0

    t0 = time.time()
    vecs: list[list[float]] = []
    with httpx.Client(timeout=120) as client:
        for i in range(0, len(todo), BATCH):
            chunk = todo[i : i + BATCH]
            r = client.post(
                f"{args.service}/embeddings",
                json={"model": args.model, "input": [c[1] for c in chunk]},
            )
            r.raise_for_status()
            vecs.extend(d["embedding"] for d in r.json()["data"])
    dt = time.time() - t0
    assert len(vecs) == len(todo)

    for (key, _), v in zip(todo, vecs, strict=True):
        existing[key] = v
    payload = {"v": version, "data": existing}
    cache_path.write_text(
        __import__("json").dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[warmup] 完成: +{len(todo)} 条, 耗时 {dt:.1f}s, 缓存 -> {cache_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
