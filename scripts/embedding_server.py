#!/usr/bin/env python3
"""本地 OpenAI 兼容 embedding 服务（Phase 1: 把本地 bge 挂进现有语义检索）.

- 端点: POST /v1/embeddings（OpenAI 格式，供 APIEmbedder 消费）
- 模型: BAAI/bge-small-zh-v1.5（本地缓存，中文优先，512 维）
- 零认证（本地回环）；encode 单并发但前台 query 优先于后台 prewarm
- 启动: .venv/bin/python scripts/embedding_server.py [--port 8765]
"""

from __future__ import annotations

import argparse
import os
import threading
import time

import uvicorn
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
_model = None
_warmed = False
_stats_lock = threading.Lock()
_stats = {
    "calls": 0,
    "texts": 0,
    "errors": 0,
    "foreground_calls": 0,
    "background_calls": 0,
    "queue_wait_ms_total": 0.0,
    "encode_ms_total": 0.0,
    "last_queue_wait_ms": 0.0,
    "last_encode_ms": 0.0,
    "last_batch_size": 0,
    "last_class": "",
}


class PriorityEncodeGate:
    """Single encode lane with foreground preference between encode calls.

    SentenceTransformer.encode is not preemptible once started. Background callers
    therefore use small chunks; at each chunk boundary this gate lets already-waiting
    foreground query requests acquire the lane first.
    """

    def __init__(self) -> None:
        self._cv = threading.Condition()
        self._active = False
        self._foreground_waiters = 0
        self._background_waiters = 0

    def acquire(
        self, request_class: str, *, max_wait_s: float | None = None
    ) -> tuple[bool, float]:
        foreground = request_class != "background"
        started = time.monotonic()
        with self._cv:
            if foreground:
                self._foreground_waiters += 1
            else:
                self._background_waiters += 1
            try:
                while self._active or (
                    not foreground and self._foreground_waiters > 0
                ):
                    if max_wait_s is None:
                        self._cv.wait()
                        continue
                    remaining = max_wait_s - (time.monotonic() - started)
                    if remaining <= 0:
                        return False, (time.monotonic() - started) * 1000.0
                    self._cv.wait(timeout=remaining)
                self._active = True
            finally:
                if foreground:
                    self._foreground_waiters -= 1
                else:
                    self._background_waiters -= 1
        return True, (time.monotonic() - started) * 1000.0

    def release(self) -> None:
        with self._cv:
            self._active = False
            self._cv.notify_all()

    def snapshot(self) -> dict:
        with self._cv:
            return {
                "active": self._active,
                "foreground_waiters": self._foreground_waiters,
                "background_waiters": self._background_waiters,
                "active_queue": self._foreground_waiters + self._background_waiters,
            }


_gate = PriorityEncodeGate()


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


def warm_model() -> None:
    """Load weights and execute one encode before the port becomes ready.

    The first real encode can be materially slower than model construction.  Serving
    before both phases finish lets the first foreground semantic query own model startup
    latency and hit its HTTP deadline.
    """
    global _warmed
    if _warmed:
        return
    started = time.monotonic()
    model = get_model()
    model.encode(["lfl embedding readiness warmup"], normalize_embeddings=True)
    _warmed = True
    print(
        f"[emb-server] readiness warmup complete in {time.monotonic()-started:.1f}s",
        flush=True,
    )


@app.get("/healthz")
def healthz():
    with _stats_lock:
        stats = dict(_stats)
    return {
        "ok": True,
        "model": MODEL_NAME,
        "loaded": _model is not None,
        "warmed": _warmed,
        "stats": stats,
        "queue": _gate.snapshot(),
    }


@app.post("/v1/embeddings")
def embeddings(
    req: EmbedRequest,
    request_class: str | None = Header(
        default=None, alias="X-LFL-Embedding-Class"
    ),
    deadline_ms: int | None = Header(
        default=None, alias="X-LFL-Embedding-Deadline-Ms"
    ),
):
    texts = [req.input] if isinstance(req.input, str) else list(req.input)
    texts = [t if t else " " for t in texts]  # 空串会导致 encode 报错，替换为占位
    cls = "background" if request_class == "background" else "foreground"
    wait_budget_s = (
        max(0.001, float(deadline_ms) / 1000.0)
        if deadline_ms is not None and deadline_ms > 0
        else None
    )
    acquired, queue_wait_ms = _gate.acquire(cls, max_wait_s=wait_budget_s)
    if not acquired:
        with _stats_lock:
            _stats["errors"] += 1
            _stats["last_queue_wait_ms"] = round(queue_wait_ms, 3)
            _stats["last_encode_ms"] = 0.0
            _stats["last_batch_size"] = len(texts)
            _stats["last_class"] = cls
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "message": "embedding queue deadline exceeded",
                    "type": "queue_timeout",
                },
                "x_lfl": {
                    "queue_wait_ms": round(queue_wait_ms, 3),
                    "encode_ms": 0.0,
                    "batch_size": len(texts),
                    "request_class": cls,
                },
            },
        )
    encode_started = time.monotonic()
    try:
        vecs = get_model().encode(texts, normalize_embeddings=True).tolist()
        encode_ms = (time.monotonic() - encode_started) * 1000.0
        with _stats_lock:
            _stats["calls"] += 1
            _stats["texts"] += len(texts)
            _stats[f"{cls}_calls"] += 1
            _stats["queue_wait_ms_total"] += queue_wait_ms
            _stats["encode_ms_total"] += encode_ms
            _stats["last_queue_wait_ms"] = round(queue_wait_ms, 3)
            _stats["last_encode_ms"] = round(encode_ms, 3)
            _stats["last_batch_size"] = len(texts)
            _stats["last_class"] = cls
    except Exception as exc:  # noqa: BLE001
        with _stats_lock:
            _stats["errors"] += 1
        return {"error": {"message": str(exc), "type": "encode_error"}}
    finally:
        _gate.release()
    return {
        "object": "list",
        "model": MODEL_NAME,
        "x_lfl": {
            "queue_wait_ms": round(queue_wait_ms, 3),
            "encode_ms": round(encode_ms, 3),
            "batch_size": len(texts),
            "request_class": cls,
        },
        "data": [
            {"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vecs)
        ],
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument(
        "--nice",
        type=int,
        default=int(os.environ.get("EMBEDDING_NICE", "5") or 5),
        help="Increase process niceness on POSIX (default 5; set 0 to keep current priority).",
    )
    args = ap.parse_args()
    if args.nice > 0:
        try:
            os.nice(args.nice)
            print(f"[emb-server] nice +{args.nice}", flush=True)
        except OSError:
            pass
    warm_model()
    print(f"[emb-server] starting on {args.host}:{args.port}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
