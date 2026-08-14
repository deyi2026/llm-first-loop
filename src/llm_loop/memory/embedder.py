"""嵌入服务抽象 Embedder（design.md §3.2.2.1 / DFX-CMP-03）.

- Embedder 协议: 供应商可插拔，不改核心循环结构
- NullEmbedder: 恒 None → 一律关键词检索（EMBEDDING_PROVIDER=none 默认，P0 回归安全）
- HashEmbedder: 本地轻量语义嵌入（字符 n-gram 哈希向量，零依赖确定性）
- APIEmbedder: OpenAI 兼容 embeddings 端点（httpx，密钥仅 env 读取）
- embed 异常路径如实返回 None（调用方回退关键词并如实标注 FR-P1-RET-04）
"""

from __future__ import annotations

import hashlib
import math
from typing import Protocol

import httpx


class Embedder(Protocol):
    """嵌入服务协议（DFX-CMP-03: 接入新供应商仅实现本协议）."""

    provider: str

    def embed(self, text: str) -> list[float] | None:
        """文本 → 语义向量；None = 语义不可用（调用方回退关键词并如实标注）."""
        ...


class NullEmbedder:
    """空嵌入器: 恒返回 None → 一律关键词检索（P0 回归安全）."""

    provider = "none"

    def embed(self, text: str) -> list[float] | None:
        return None


class HashEmbedder:
    """本地轻量语义嵌入（字符 n-gram 哈希向量）.

    零依赖、确定性、无网络；维度 EMBEDDING_DIM（默认 128）。
    用 2-gram 字符哈希构造稀疏向量 → L2 归一化，支持余弦相似度。
    """

    provider = "hash"

    def __init__(self, dim: int = 128) -> None:
        self._dim = max(16, int(dim))

    def embed(self, text: str) -> list[float] | None:
        if not text:
            return None
        vec = [0.0] * self._dim
        norm_text = text.lower().strip()
        # 字符 2-gram 哈希
        grams = [norm_text[i : i + 2] for i in range(max(1, len(norm_text) - 1))]
        for g in grams:
            idx = int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16) % self._dim
            vec[idx] += 1.0
        # L2 归一化
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            return None
        return [v / norm for v in vec]


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
        self._client = httpx.Client(timeout=timeout_s)

    def embed(self, text: str) -> list[float] | None:
        if not text:
            return None
        try:
            resp = self._client.post(
                f"{self.base_url}/embeddings",
                # 本地 embedding 端点无需认证（api_key 为空时不发 Authorization 头）。
                headers=(
                    {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
                    if self.api_key else {"Content-Type": "application/json"}
                ),
                json={"model": self.model, "input": text},
            )
            if resp.status_code >= 400:
                return None
            data = resp.json()
            return data["data"][0]["embedding"]
        except Exception:  # noqa: BLE001 — 嵌入失败如实返回 None，不抛穿
            return None

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
