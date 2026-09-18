#!/usr/bin/env python3
"""本地 OpenAI 兼容 embedding 服务（Phase 1: 把本地 bge 挂进现有语义检索）.

- 端点: POST /v1/embeddings（OpenAI 格式，供 APIEmbedder 消费）
- 模型: BAAI/bge-small-zh-v1.5（本地缓存，中文优先，512 维）
- 零认证（本地回环）；encode 串行加锁（单用户影子测试足够）
- 启动: .venv/bin/python scripts/embedding_server.py [--port 8765]
"""

from __future__ import annotations

import argparse
import threading
import time

from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
_lock = threading.Lock()
_model = None
_stats = {"calls": 0, "texts": 0, "errors": 0}


class EmbedRequest(BaseModel):
    model: str = ""
    input: str | list[str] = ""


app = FastAPI(title="local-embedding-server")


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        t0 = time.time()
        _model = SentenceTransformer(MODEL_NAME)
        print(f"[emb-server] loaded {MODEL_NAME} in {time.time()-t0:.1f}s", flush=True)
    return _model


@app.get("/healthz")
def healthz():
    return {"ok": True, "model": MODEL_NAME, "loaded": _model is not None, "stats": _stats}


@app.post("/v1/embeddings")
def embeddings(req: EmbedRequest):
    texts = [req.input] if isinstance(req.input, str) else list(req.input)
    texts = [t if t else " " for t in texts]  # 空串会导致 encode 报错，替换为占位
    try:
        with _lock:
            vecs = get_model().encode(texts, normalize_embeddings=True).tolist()
        _stats["calls"] += 1
        _stats["texts"] += len(texts)
    except Exception as exc:  # noqa: BLE001
        _stats["errors"] += 1
        return {"error": {"message": str(exc), "type": "encode_error"}}
    return {
        "object": "list",
        "model": MODEL_NAME,
        "data": [
            {"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vecs)
        ],
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    print(f"[emb-server] starting on {args.host}:{args.port}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
