"""嵌入服务抽象 Embedder（design.md §3.2.2.1 / DFX-CMP-03）.

- Embedder 协议: 供应商可插拔，不改核心循环结构
- NullEmbedder: 恒 None → 一律关键词检索（EMBEDDING_PROVIDER=none 默认，P0 回归安全）
- HashEmbedder: 本地轻量语义嵌入（字符 n-gram 哈希向量，零依赖确定性）
- APIEmbedder: OpenAI 兼容 embeddings 端点（httpx，密钥仅 env 读取）
- embed 异常路径如实返回 None（调用方回退关键词并如实标注 FR-P1-RET-04）
"""

from __future__ import annotations

import contextlib
import hashlib
import math
import threading
import time
from typing import Protocol

import httpx


class Embedder(Protocol):
    """嵌入服务协议（DFX-CMP-03: 接入新供应商仅实现本协议）."""

    provider: str

    def embed(self, text: str) -> list[float] | None:
        """文本 → 语义向量；None = 语义不可用（调用方回退关键词并如实标注）."""
        ...

    def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        """批量文本 → 向量列表（按位对齐；None = 该条不可用）.

        EVO-20260924-d9c5ad20（冷启动批量预热）: 实现方可选；调用方以 getattr 探测，
        旧第三方实现无此方法时回退逐条 embed，语义不变。
        """
        ...


class NullEmbedder:
    """空嵌入器: 恒返回 None → 一律关键词检索（P0 回归安全）."""

    provider = "none"

    def embed(self, text: str) -> list[float] | None:
        return None

    def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        return [None] * len(texts)


class HashEmbedder:
    """本地轻量语义嵌入（字符 n-gram 哈希向量，T6 增强: 2+3-gram 混合）.

    零依赖、确定性、无网络；维度 EMBEDDING_DIM（默认 128）。
    2-gram + 3-gram 字符哈希构造稀疏向量 → L2 归一化，支持余弦相似度。
    vector_version: 向量算法版本（缓存按版本校验，算法变更自动重建缓存防混用）。
    """

    provider = "hash"
    vector_version = "hash-v2"

    def __init__(self, dim: int = 128) -> None:
        self._dim = max(16, int(dim))

    def embed(self, text: str) -> list[float] | None:
        if not text:
            return None
        vec = [0.0] * self._dim
        norm_text = text.lower().strip()
        # T6: 2-gram + 3-gram 混合（3-gram 提升长词/语义短语区分度；2-gram 保持 v1 召回面）
        grams: list[str] = []
        for n in (2, 3):
            grams.extend(norm_text[i : i + n] for i in range(max(1, len(norm_text) - n + 1)))
        for g in grams:
            idx = int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16) % self._dim
            vec[idx] += 1.0
        # L2 归一化
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            return None
        return [v / norm for v in vec]

    def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        """本地零网络，逐条即可（成本可忽略）。"""
        return [self.embed(t) for t in texts]


class APIEmbedder:
    """OpenAI 兼容 embeddings 端点（DFX-CMP-03）.

    密钥仅从 env 读取（DFX-SEC-02），不写入日志/JSON。
    """

    provider = "api"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout_s: float = 5.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        # T6 版本化缓存对齐: 按端点+模型区分向量，换模型/端点自动重建缓存防混用
        # （retriever._emb_version() 经 getattr 读取；experiences/store.py 同样消费）
        self.vector_version = f"api-v1:{base_url.rstrip('/')}:{model}"
        self._client = httpx.Client(timeout=timeout_s)
        self._diag_lock = threading.Lock()
        self.last_diagnostics: dict[str, float | int | str] = {}

    def _set_diagnostics(self, diag: dict[str, float | int | str]) -> None:
        with self._diag_lock:
            self.last_diagnostics = dict(diag)

    def embed(self, text: str) -> list[float] | None:
        return self.embed_with_timeout(text, timeout_s=self.timeout_s)

    def embed_with_timeout(
        self, text: str, *, timeout_s: float, request_class: str = "foreground"
    ) -> list[float] | None:
        """Embed one text with a caller-owned deadline.

        Semantic retrieval has a tighter foreground budget than the generic embedding
        client timeout.  Per-call timeout prevents the generic 5s HTTP timeout from
        leaking through a 1s retrieval budget.
        """
        if not text:
            return None
        started = time.monotonic()
        try:
            headers = {
                **(
                    {"Authorization": f"Bearer {self.api_key}"}
                    if self.api_key
                    else {}
                ),
                "Content-Type": "application/json",
                "X-LFL-Embedding-Class": (
                    "background" if request_class == "background" else "foreground"
                ),
                "X-LFL-Embedding-Deadline-Ms": str(
                    max(10, int(float(timeout_s) * 1000.0 * 0.35))
                ),
            }
            resp = self._client.post(
                f"{self.base_url}/embeddings",
                # 本地 embedding 端点无需认证（api_key 为空时不发 Authorization 头）。
                headers=headers,
                json={"model": self.model, "input": text},
                timeout=max(0.01, float(timeout_s)),
            )
            if resp.status_code >= 400:
                diag: dict[str, float | int | str] = {
                    "request_class": request_class,
                    "http_ms": round((time.monotonic() - started) * 1000.0, 3),
                    "timeout_s": float(timeout_s),
                    "error": f"http_{resp.status_code}",
                }
                with contextlib.suppress(Exception):
                    payload = resp.json()
                    meta = payload.get("x_lfl") if isinstance(payload, dict) else None
                    if isinstance(meta, dict):
                        for key in ("queue_wait_ms", "encode_ms", "batch_size"):
                            value = meta.get(key)
                            if isinstance(value, (int, float)):
                                diag[key] = value
                        error_payload = payload.get("error")
                        if isinstance(error_payload, dict) and error_payload.get("type"):
                            diag["error"] = str(error_payload["type"])
                self._set_diagnostics(diag)
                return None
            data = resp.json()
            meta = data.get("x_lfl") if isinstance(data, dict) else None
            diag: dict[str, float | int | str] = {
                "request_class": request_class,
                "http_ms": round((time.monotonic() - started) * 1000.0, 3),
                "timeout_s": float(timeout_s),
                "error": "",
            }
            if isinstance(meta, dict):
                for key in ("queue_wait_ms", "encode_ms", "batch_size"):
                    value = meta.get(key)
                    if isinstance(value, (int, float)):
                        diag[key] = value
            self._set_diagnostics(diag)
            return data["data"][0]["embedding"]
        except Exception as exc:  # noqa: BLE001 — 嵌入失败如实返回 None，不抛穿
            self._set_diagnostics(
                {
                    "request_class": request_class,
                    "http_ms": round((time.monotonic() - started) * 1000.0, 3),
                    "timeout_s": float(timeout_s),
                    "error": type(exc).__name__,
                }
            )
            return None

    def embed_batch_with_timeout(
        self,
        texts: list[str],
        *,
        timeout_s: float,
        request_class: str = "foreground",
        chunk_size: int = 16,
    ) -> list[list[float] | None]:
        """Batch embed under one caller-owned wall-clock budget.

        Docs semantic ranking is a foreground operation over an already-admitted
        candidate set.  It must not inherit the generic 5s client timeout or let one
        large encode monopolize the shared local embedding lane.  Small chunks bound
        each non-preemptible server encode; every subsequent chunk consumes only the
        remaining caller budget.
        """
        out: list[list[float] | None] = [None] * len(texts)
        idx_map = [i for i, text in enumerate(texts) if text]
        if not idx_map:
            return out
        deadline = time.monotonic() + max(0.01, float(timeout_s))
        chunk_size = max(1, min(int(chunk_size), self._BATCH_CHUNK))
        started = time.monotonic()
        total_queue_ms = 0.0
        total_encode_ms = 0.0
        completed = 0
        error = ""

        for start in range(0, len(idx_map), chunk_size):
            remaining = deadline - time.monotonic()
            if remaining <= 0.01:
                error = "batch_deadline_exhausted"
                break
            chunk = idx_map[start : start + chunk_size]
            try:
                resp = self._client.post(
                    f"{self.base_url}/embeddings",
                    headers={
                        **(
                            {"Authorization": f"Bearer {self.api_key}"}
                            if self.api_key
                            else {}
                        ),
                        "Content-Type": "application/json",
                        "X-LFL-Embedding-Class": (
                            "background"
                            if request_class == "background"
                            else "foreground"
                        ),
                        "X-LFL-Embedding-Deadline-Ms": str(
                            max(10, int(remaining * 1000.0 * 0.35))
                        ),
                    },
                    json={"model": self.model, "input": [texts[i] for i in chunk]},
                    timeout=max(0.01, remaining),
                )
                payload = resp.json()
                meta = payload.get("x_lfl") if isinstance(payload, dict) else None
                if isinstance(meta, dict):
                    total_queue_ms += float(meta.get("queue_wait_ms") or 0.0)
                    total_encode_ms += float(meta.get("encode_ms") or 0.0)
                if resp.status_code >= 400:
                    payload_error = payload.get("error") if isinstance(payload, dict) else None
                    if isinstance(payload_error, dict) and payload_error.get("type"):
                        error = str(payload_error["type"])
                    else:
                        error = f"http_{resp.status_code}"
                    break
                rows = payload.get("data") if isinstance(payload, dict) else None
                if not isinstance(rows, list) or len(rows) != len(chunk):
                    error = "invalid_batch_response"
                    break
                if any(not isinstance(row, dict) or "embedding" not in row for row in rows):
                    error = "invalid_batch_response"
                    break
                for index, row in zip(chunk, rows, strict=True):
                    out[index] = row["embedding"]
                completed += len(chunk)
            except Exception as exc:  # noqa: BLE001 — caller fails open to lexical
                error = type(exc).__name__
                break

        self._set_diagnostics(
            {
                "request_class": request_class,
                "http_ms": round((time.monotonic() - started) * 1000.0, 3),
                "timeout_s": float(timeout_s),
                "queue_wait_ms": round(total_queue_ms, 3),
                "encode_ms": round(total_encode_ms, 3),
                "batch_size": completed,
                "error": error,
            }
        )
        return out

    _BATCH_CHUNK = 16  # background prewarm: short lock holds let foreground queries interleave
    _BATCH_YIELD_S = 0.02  # lower background duty cycle on hosts shared with local LLM inference
    _BACKGROUND_QUEUE_DEADLINE_MS = 250
    _BACKGROUND_HTTP_TIMEOUT_S = 1.5

    def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        """批量嵌入（EVO-20260924-d9c5ad20 冷启动预热）。

        小片 HTTP 批量替代 N 次单条往返；片间主动让出 CPU/统一内存带宽，避免
        后台预热持续压低同机本地 LLM 的前台生成吞吐；空文本位置直接 None；
        响应条数不齐/异常 → 当前 chunk 保留 None，交给后续后台轮次重试。
        不在一次后台预热中串行逐条补偿，避免单个超时放大成 N×timeout 长尾。
        """
        out: list[list[float] | None] = [None] * len(texts)
        idx_map = [i for i, t in enumerate(texts) if t]
        for s in range(0, len(idx_map), self._BATCH_CHUNK):
            chunk = idx_map[s : s + self._BATCH_CHUNK]
            try:
                resp = self._client.post(
                    f"{self.base_url}/embeddings",
                    headers={
                        **(
                            {"Authorization": f"Bearer {self.api_key}"}
                            if self.api_key
                            else {}
                        ),
                        "Content-Type": "application/json",
                        "X-LFL-Embedding-Class": "background",
                        "X-LFL-Embedding-Deadline-Ms": str(
                            self._BACKGROUND_QUEUE_DEADLINE_MS
                        ),
                    },
                    json={"model": self.model, "input": [texts[i] for i in chunk]},
                    timeout=min(self.timeout_s, self._BACKGROUND_HTTP_TIMEOUT_S),
                )
                if resp.status_code >= 400:
                    continue
                rows = (resp.json().get("data") or [])
                if len(rows) != len(chunk) or any("embedding" not in r for r in rows):
                    continue
                for i, row in zip(chunk, rows, strict=True):
                    out[i] = row["embedding"]
                if s + self._BATCH_CHUNK < len(idx_map):
                    time.sleep(self._BATCH_YIELD_S)
            except Exception:  # noqa: BLE001 — 后台失败留待后续预热轮次重试
                continue
        return out

    def close(self) -> None:
        self._client.close()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """余弦相似度（HashEmbedder 向量已归一化；API 向量可能未归一化，此处再归一）."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
