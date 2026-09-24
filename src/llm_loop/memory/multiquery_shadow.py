"""多查询融合影子探针（REPORT-20260924 下一步：影子模式实测延迟/命中率）.

背景：evals/retrieval_ab 多查询融合原型（dev 25 条：h@1 5→9、MRR +50%、miss 8→4；
held-out 8 条：精细调权无增益 → 等权 RRF 即候选形态）。生产接入前用 shadow 模式
实测成本体感：原查询 + LLM 盲改写 2 变体各走一遍语义链路，等权 list-RRF(k=60) 融合，
只记录不生效——返回值与 off 模式逐字节一致，主路径零行为变化。

安全契约：
- probe.run 全异常捕获（含 rewriter 网络失败）：错误也只记一行 JSONL，绝不向上抛；
- JSONL 追加写（单行小对象），读侧容错；损坏不影响主路径；
- 变体检索经 _skip_shadow 闭包防递归。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

Rewriter = Callable[[str], list[str]]
SearchFn = Callable[[str], list[str]]


def rrf_fuse(lists: list[list[str]], k: int = 60) -> list[str]:
    """等权 list-RRF（与 evals 原型同实现；held-out 消融已否证精细加权增益）."""
    scores: dict[str, float] = {}
    for ids in lists:
        for rank, rid in enumerate(ids, start=1):
            if rid:
                scores[rid] = scores.get(rid, 0.0) + 1.0 / (k + rank)
    return [rid for rid, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))]


class MultiqueryShadowProbe:
    """影子探针：旁路测量多查询融合的成本与排序差异，绝不改变主路径返回值."""

    def __init__(
        self,
        *,
        rewriter: Rewriter | None = None,
        out_path: str | Path | None = None,
        rrf_k: int = 60,
        top_n: int = 10,
        max_variants: int = 2,
    ) -> None:
        self._rewriter = rewriter
        self._out_path = Path(out_path) if out_path else None
        self._rrf_k = rrf_k
        self._top_n = top_n
        self._max_variants = max_variants

    @property
    def enabled(self) -> bool:
        return self._rewriter is not None

    def run(
        self,
        query: str,
        limit: int,
        session_id: str,
        search_fn: SearchFn,
        primary_ids: list[str],
    ) -> dict[str, Any] | None:
        """旁路执行一次多查询融合并记录。异常时记录 error 行，返回 None 不抛出."""
        if not self.enabled or not query.strip():
            return None
        record: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "kind": "multiquery_shadow",
            "session_id": session_id,
            "query": query,
            "limit": limit,
        }
        t0 = time.perf_counter()
        try:
            t_r = time.perf_counter()
            variants = [v.strip() for v in (self._rewriter(query) or [])]
            variants = [v for v in variants if v and v != query][: self._max_variants]
            rewrite_s = round(time.perf_counter() - t_r, 3)

            t_s = time.perf_counter()
            lists = [primary_ids] + [search_fn(v) for v in variants]
            search_s = round(time.perf_counter() - t_s, 3)
            fused = rrf_fuse(lists, self._rrf_k)

            top = self._top_n
            record.update({
                "n_variants": len(variants),
                "variants": variants,
                "latency": {
                    "rewrite_s": rewrite_s,
                    "search_s": search_s,
                    "total_s": round(time.perf_counter() - t0, 3),
                },
                "primary_top": [i for i in primary_ids[:top] if i],
                "fused_top": [i for i in fused[:top] if i],
                "overlap_at_5": len(set(primary_ids[:5]) & set(fused[:5])),
                # 保位护栏设计项数据：primary top1 是否被融合挤出 top1/top3
                "primary_top1_in_fused_top1": bool(primary_ids) and fused[:1] == primary_ids[:1],
                "primary_top1_in_fused_top3": bool(primary_ids) and primary_ids[0] in fused[:3],
            })
        except Exception as exc:  # noqa: BLE001 - 影子路径安全契约：绝不向上抛
            record.update({"error": f"{type(exc).__name__}: {exc}",
                           "latency": {"total_s": round(time.perf_counter() - t0, 3)}})
        try:
            self._append(record)
        except Exception:  # noqa: BLE001 - 落盘失败静默（主路径零影响）
            pass
        return record

    def _append(self, record: dict[str, Any]) -> None:
        if self._out_path is None:
            return
        self._out_path.parent.mkdir(parents=True, exist_ok=True)
        with self._out_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


_REWRITE_SYSTEM = (
    "你是检索查询改写器。把用户查询改写成 2 个不同的关键词风格检索变体："
    "中文关键词空格分隔、可混少量英文术语、贴近知识库记录措辞。"
    '只输出 JSON 数组，如 ["变体一", "变体二"]，不要解释。'
)


def make_llm_rewriter(llm: Any) -> Rewriter:
    """用主 LLMClient 构造改写器（chat 非流式、10s 超时；失败返回 [] 由探针记录）."""
    def rewrite(query: str) -> list[str]:
        resp = llm.chat(
            [{"role": "system", "content": _REWRITE_SYSTEM},
             {"role": "user", "content": query}],
            tools=[],
            timeout_s=10.0,
        )
        content = (getattr(resp, "content", None) or "").strip()
        return _parse_variants(content)
    return rewrite


def _parse_variants(content: str) -> list[str]:
    """容错解析：优先 JSON 数组；退化为逗号/引号切分."""
    try:
        data = json.loads(content)
        if isinstance(data, list):
            return [str(v) for v in data if str(v).strip()]
    except (json.JSONDecodeError, ValueError):
        pass
    out: list[str] = []
    for chunk in content.replace("，", ",").split(","):
        chunk = chunk.strip().strip('[]"\' \n\t')
        if chunk:
            out.append(chunk)
    return out
