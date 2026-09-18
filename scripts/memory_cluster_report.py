#!/usr/bin/env python3
"""记忆语料近重复聚类报告（只读; P0 语料编译第一步）.

用途: 为 LLM-Wiki 式写入期编译提供审定底稿。本脚本只做确定性计算
(聚类/相似度/指纹), 不做语义合并判断——合并取舍归 AI 审定、用户批准。

行为:
- 读 data/memory/index.json（只读, 不写任何源文件）
- 候选向量化: 复用本输出目录缓存（内容指纹对齐, 增量补嵌）
- cos>0.90 union-find 聚类 + content_fingerprint 精确重复标记
- 产出: data/memory_compile/cluster_report.{json,md}

运行: .venv/bin/python scripts/memory_cluster_report.py [--threshold 0.90]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "memory_compile"      # 向量缓存（gitignored, 可再生）
REPORT_DIR = ROOT / "data" / "memory_compile"   # 报告（含记忆内容预览, gitignored; 审定文件单独入库）
EMB_URL = "http://127.0.0.1:8765/v1/embeddings"


def entry_text(e: dict) -> str:
    return f"{e.get('content', '')} {' '.join(e.get('keywords') or [])}"


def content_fp(e: dict) -> str:
    return e.get("content_fingerprint") or hashlib.sha1(
        e.get("content", "").encode("utf-8")
    ).hexdigest()


def embed_batch(texts: list[str]) -> list[list[float]]:
    out = []
    for i in range(0, len(texts), 64):
        chunk = texts[i : i + 64]
        req = urllib.request.Request(
            EMB_URL,
            data=json.dumps({"model": "bge", "input": chunk}).encode(),
            headers={"Content-Type": "application/json"},
        )
        r = json.loads(urllib.request.urlopen(req, timeout=300).read())
        out.extend([d["embedding"] for d in sorted(r["data"], key=lambda x: x["index"])])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.90)
    args = ap.parse_args()

    with open(ROOT / "data" / "memory" / "index.json", encoding="utf-8") as f:
        idx = json.load(f)
    n = len(idx)
    fps = [content_fp(e) for e in idx]

    # ── 向量缓存（本目录自有, 不碰 data/memory/embeddings.json）──
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    cache_meta_path = OUT / "vectors_meta.json"
    cache_meta = {}
    if cache_meta_path.exists():
        try:
            cache_meta = json.loads(cache_meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            cache_meta = {}
    vecs_path = OUT / "vectors.npy"
    m_mat = np.load(vecs_path) if vecs_path.exists() else None
    if m_mat is not None and m_mat.shape[0] == n and cache_meta.get("fps") == fps:
        print(f"vectors cache hit: {n}x{m_mat.shape[1]}")
    else:
        print(f"embedding {n} entries via {EMB_URL} ...")
        m_mat = np.array(embed_batch([entry_text(e) for e in idx]), dtype=np.float32)
        np.save(vecs_path, m_mat)
        cache_meta_path.write_text(
            json.dumps({"fps": fps, "dim": int(m_mat.shape[1])}, ensure_ascii=False),
            encoding="utf-8",
        )
    m_mat /= np.linalg.norm(m_mat, axis=1, keepdims=True) + 1e-9

    s_mat = m_mat @ m_mat.T
    np.fill_diagonal(s_mat, 0.0)

    # ── union-find 聚类 ──
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    a_mat = s_mat > args.threshold
    for i in range(n):
        for j in np.where(a_mat[i])[0]:
            ri, rj = find(i), find(int(j))
            if ri != rj:
                parent[ri] = rj

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)

    fp_groups: dict[str, list[int]] = {}
    for i, f in enumerate(fps):
        fp_groups.setdefault(f, []).append(i)
    exact_dups = {f: g for f, g in fp_groups.items() if len(g) > 1}

    def member_view(i: int) -> dict:
        e = idx[i]
        return {
            "id": e.get("id"),
            "type": e.get("type"),
            "created_at": e.get("created_at"),
            "updated_at": e.get("updated_at") or e.get("created_at"),
            "version": e.get("version"),
            "keywords": (e.get("keywords") or [])[:6],
            "fp": fps[i][:12],
            "content_preview": e.get("content", "")[:160],
        }

    report_clusters = []
    for members in clusters.values():
        if len(members) < 2:
            continue
        sub = s_mat[np.ix_(members, members)]
        mask = sub > args.threshold
        # 主题提示: 成员 keywords 高频交集
        kw = Counter()
        for i in members:
            kw.update(w.lower() for w in (idx[i].get("keywords") or []) if w)
        exact_fp = any(
            any(m in g for m in members) for g in exact_dups.values()
        )
        report_clusters.append(
            {
                "size": len(members),
                "pair_max": round(float(sub[mask].max()), 4),
                "pair_mean": round(float(sub[mask].mean()), 4),
                "exact_fingerprint_dup": exact_fp,
                "theme_hint": [w for w, _ in kw.most_common(4)],
                "members": [member_view(i) for i in members],
            }
        )
    report_clusters.sort(key=lambda c: (-c["size"], -c["pair_max"]))

    mx = s_mat.max(axis=1)
    stats = {
        "generated_at": datetime.now(UTC).isoformat(),
        "corpus": n,
        "threshold": args.threshold,
        "in_clusters": sum(c["size"] for c in report_clusters),
        "clusters": len(report_clusters),
        "mergeable_upper_bound": sum(c["size"] - 1 for c in report_clusters),
        "exact_fingerprint_dup_entries": sum(len(g) for g in exact_dups.values()),
        "max_neighbor_dist": {
            "gt_085": int((mx > 0.85).sum()),
            "gt_090": int((mx > 0.90).sum()),
            "gt_095": int((mx > 0.95).sum()),
        },
    }

    (REPORT_DIR / "cluster_report.json").write_text(
        json.dumps({"stats": stats, "clusters": report_clusters}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    # ── Markdown 摘要（人工/AI 审定底稿）──
    lines = [
        "# 记忆近重复聚类报告",
        "",
        f"- 生成: {stats['generated_at']}",
        f"- 语料: {stats['corpus']} 条 | cos>{args.threshold} 簇: {stats['clusters']}"
        f" 覆盖 {stats['in_clusters']} 条 | 合并上界(每簇保1): {stats['mergeable_upper_bound']}",
        f"- 精确指纹重复: {stats['exact_fingerprint_dup_entries']} 条",
        "",
        "> 本报告只做确定性聚类; 合并取舍归 AI 审定(adjudication.json)→用户批准后执行。",
        "",
    ]
    for rank, c in enumerate(report_clusters[:60], 1):
        lines.append(
            f"## 簇#{rank} size={c['size']} cos[max={c['pair_max']} mean={c['pair_mean']}]"
            f"{' 精确重复' if c['exact_fingerprint_dup'] else ''} 主题≈{','.join(c['theme_hint'])}"
        )
        for m in c["members"]:
            lines.append(
                f"- `{m['id']}` {m['created_at'][:10]} v{m['version']} :: {m['content_preview'][:110]}"
            )
        lines.append("")
    (REPORT_DIR / "cluster_report.md").write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps(stats, ensure_ascii=False, indent=1))
    print(f"\n报告: {REPORT_DIR/'cluster_report.md'} (top60) / cluster_report.json (全量)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
