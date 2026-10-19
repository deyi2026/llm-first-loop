#!/usr/bin/env python3
"""预注册取样：从 data/methods 里按失败模式分层抽 30 张卡（seed 固定）。

分层规则（按 Trigger/Discriminator/Short path 关键词优先命中）：
  F1 effectiveness  是否生效 / 定义处 / 移除提交 / 当前树
  F2 completion     完成 / 结案 / 验收 / done
  F3 dedupe         检索 / 去重 / 复用 / 已有卡 / 重复
  F4 edit_verify    补丁 / grep / 改完 / 替换 / 复核
  F5 other          其余
每层 6 张，不足则从 other 补齐；同层内按 sha256(card_id+seed) 排序取前 6（可复现且与目录名无关）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
METHODS = ROOT / "data" / "methods"
OUT = Path(__file__).resolve().parent
SEED = 20261019
PER_FAMILY = 6

RULES = [
    ("F1_effectiveness", ("是否生效", "定义处", "移除提交", "当前树", "生效路径")),
    ("F2_completion", ("完成", "结案", "验收", "done", "转移")),
    ("F3_dedupe", ("检索", "去重", "复用", "已有卡", "重复")),
    ("F4_edit_verify", ("补丁", "grep", "改完", "替换", "复核")),
]


def classify(text: str) -> str:
    for fam, kws in RULES:
        if any(k in text for k in kws):
            return fam
    return "F5_other"


def main() -> int:
    cards = []
    for p in sorted(METHODS.glob("*/METHOD.md")):
        raw = p.read_text(encoding="utf-8")
        cid = p.parent.name
        cards.append({
            "card_id": cid,
            "path": str(p.relative_to(ROOT)),
            "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "family": classify(raw),
            "chars": len(raw),
            "sort_key": hashlib.sha256(f"{cid}|{SEED}".encode()).hexdigest(),
        })

    buckets: dict[str, list[dict]] = {}
    for c in cards:
        buckets.setdefault(c["family"], []).append(c)
    for v in buckets.values():
        v.sort(key=lambda c: c["sort_key"])

    picked: list[dict] = []
    for fam, _ in RULES + [("F5_other", ())]:
        picked += buckets.get(fam, [])[:PER_FAMILY]
    if len(picked) < 30:
        rest = [c for c in sorted(cards, key=lambda c: c["sort_key"]) if c not in picked]
        picked += rest[: 30 - len(picked)]
    picked = picked[:30]

    rows = [
        {"pair_id": f"P{i:02d}", **{k: c[k] for k in ("card_id", "path", "sha256", "family", "chars")}}
        for i, c in enumerate(picked, 1)
    ]
    blob = "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for r in rows) + "\n"
    (OUT / "prereg_v1_cards.jsonl").write_bytes(blob.encode("utf-8"))
    freeze = {
        "seed": SEED,
        "per_family": PER_FAMILY,
        "pair_count": len(rows),
        "pool_size": len(cards),
        "families": {f: sum(1 for r in rows if r["family"] == f) for f in sorted({r["family"] for r in rows})},
        "sha256": hashlib.sha256(blob.encode("utf-8")).hexdigest(),
    }
    (OUT / "PREREG-FREEZE.json").write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(freeze, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
