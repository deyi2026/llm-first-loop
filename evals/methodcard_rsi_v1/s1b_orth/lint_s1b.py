#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S1b 卡污染检查：等长 / 同结构 / 内容无关 / 与 pool 的 8-gram 重合 / 不自引。"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GOLD = ROOT / "s1_gold_filler" / "cards" / "gold.md"
NEW = HERE / "cards" / "filler_orth.md"
POOL = ROOT / "s0_p28" / "pool_p28.jsonl"

SECTIONS = ("Trigger", "Discriminator", "Short path", "Stop conditions",
            "Verification", "Counterexamples")
FORBIDDEN = {
    "链接内容判定": ["链接", "正文", "网页", "抓取", "HTML", "页面"],
    "澄清提问": ["你想", "要不要", "是否要", "请告诉我", "回复 A", "回复A", "确认一下"],
    "互斥选项": ["选项", "二选一", "三选一", "任选", "选一个", "请选择"],
    "昂贵动作": ["发布", "推送", "发稿", "注册", "上线"],
    "成本词": ["成本", "可逆", "边界", "昂贵", "免费", "耗时"],
    "暂停等待": ["暂停", "等待确认", "等你确认", "先校验", "校验后"],
}


def chars(t: str) -> dict:
    return {"chars": len(t), "cjk": len(re.findall(r"[\u4e00-\u9fff]", t)),
            "utf8_bytes": len(t.encode("utf-8"))}


def ngrams(t: str, n: int = 8) -> set[str]:
    return {t[i:i + n] for i in range(max(0, len(t) - n + 1))}


def main() -> int:
    g = GOLD.read_text(encoding="utf-8")
    c = NEW.read_text(encoding="utf-8")
    gc, cc = chars(g), chars(c)
    questions = [json.loads(l)["question"] for l in POOL.read_text(encoding="utf-8").splitlines() if l.strip()]

    cg = ngrams(c)
    overlaps = []
    for q in questions:
        qg = ngrams(q)
        inter = len(cg & qg)
        jac = inter / len(cg | qg) if (cg | qg) else 0.0
        cover = inter / len(cg) if cg else 0.0
        overlaps.append((cover, jac))
    max_cover = max(x[0] for x in overlaps)
    max_jac = max(x[1] for x in overlaps)

    hits = {}
    for label, words in FORBIDDEN.items():
        hits[label] = [w for w in words if w in c]

    sections_ok = all(f"## {s}" in c for s in SECTIONS)
    # 结构对齐：gold 有的六节，新卡也必须有
    gold_sections = [s for s in SECTIONS if f"## {s}" in g]
    missing = [s for s in gold_sections if f"## {s}" not in c]

    out = {"gold": gc, "filler_orth": cc,
           "len_diff_pct": round(abs(cc["chars"] - gc["chars"]) / gc["chars"] * 100, 2),
           "cjk_diff_pct": round(abs(cc["cjk"] - gc["cjk"]) / gc["cjk"] * 100, 2),
           "sections_ok": sections_ok, "missing_sections": missing,
           "forbidden_hits": {k: v for k, v in hits.items() if v},
           "ngram8": {"max_cover_of_card": round(max_cover, 4),
                      "max_jaccard": round(max_jac, 4),
                      "threshold": 0.3,
                      "pass": max_cover <= 0.3 and max_jac <= 0.3},
           "pass": (sections_ok and not missing and not any(hits.values())
                    and max_cover <= 0.3 and max_jac <= 0.3
                    and abs(cc["chars"] - gc["chars"]) / gc["chars"] <= 0.10)}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    (HERE / "lint_s1b.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
