#!/usr/bin/env python3
"""ANCHOR 包机械构造：从 IQ v1 已开封工件抽样并生成人类锚评分表。

确定性：SAMPLE_SEED / ORDER_SEED 固定，重跑字节一致。
不修改任何冻结件；只读 iq_sealed.json / iq_sheet.md / IQ-RESULT.json。
"""
import json, random, re, hashlib, datetime, pathlib

BASE = pathlib.Path(__file__).resolve().parent.parent
ANCHOR = BASE / "anchor"
SAMPLE_SEED = 20261006   # 抽样
ORDER_SEED = 20261007    # 呈序

sealed = json.loads((BASE / "iq_sealed.json").read_text())
result = json.loads((BASE / "IQ-RESULT.json").read_text())
sheet = (BASE / "iq_sheet.md").read_text()

by_case = {c["case_id"]: dict(c, opaque_id=op) for op, c in sealed["cases"].items()}
cert_B = set(result["certified_B_case_ids"])
all_ids = sorted(by_case)

def cell(cid): return by_case[cid]["cell"]
strata = {
    "A": [c for c in all_ids if cell(c) == "A"],                      # 全取 6
    "B_cert": [c for c in all_ids if cell(c) == "B" and c in cert_B],  # 取 1
    "B_uncert": [c for c in all_ids if cell(c) == "B" and c not in cert_B],  # 取 1
    "C": [c for c in all_ids if cell(c) == "C"],                      # 取 2
    "D": [c for c in all_ids if cell(c) == "D"],                      # 取 2
}
take = {"A": 6, "B_cert": 1, "B_uncert": 1, "C": 2, "D": 2}

rng = random.Random(SAMPLE_SEED)
sample = []
for k in ["A", "B_cert", "B_uncert", "C", "D"]:
    pool = sorted(strata[k])
    sample += rng.sample(pool, take[k])
assert len(sample) == 12, sample

# 从盲表抽取题面（按 opaque_id 分节）
sections = re.split(r"(?m)(?=^## \d+\. `)", sheet)
case_sec = {}
for sec in sections[1:]:
    m = re.match(r"^## \d+\. `([0-9a-f]+)`", sec)
    if m:
        case_sec[m.group(1)] = sec.rstrip() + "\n"
missing = [by_case[c]["opaque_id"] for c in sample if by_case[c]["opaque_id"] not in case_sec]
assert not missing, f"sheet 缺节: {missing}"

rng2 = random.Random(ORDER_SEED)
order = sample[:]
rng2.shuffle(order)

now = "2026-10-05T23:31:00+08:00"
lines = [
    "# IQ v1 人类锚补验评分表（12 例；呈序 seed=%d；题面逐字取自 iq_sheet.md，无标签无格号）" % ORDER_SEED,
    "",
    "> 假设你正在执行下面的【任务】，手头只有这张【方法卡】。该卡对本任务是否适用？",
    "> APPLY = 采纳其指引会实质改变/正确化本任务的执行；SKIP = 不适用。",
    "> 请附一行理由（12 例每例一行，APPLY/SKIP + 一句理由）。",
    "",
    "**答卷**：直接在本会话按呈序粘贴 12 行，或填 `ANCHOR-ANSWER.jsonl`：",
    "`{\"opaque_id\":\"…\",\"verdict\":\"APPLY|SKIP\",\"reason\":\"一行理由\",\"ts\":\"ISO时间\"}`",
    "",
]
for i, cid in enumerate(order, 1):
    op = by_case[cid]["opaque_id"]
    body = case_sec[op]
    body = re.sub(r"^## \d+\. ", f"## {i}. ", body, count=1, flags=re.M)
    lines.append(body)
sheet_out = ANCHOR / "ANCHOR-SHEET.md"
sheet_out.write_text("\n".join(lines))

(ANCHOR / "ANCHOR-ANSWER.jsonl").write_text(
    "".join(json.dumps({"opaque_id": by_case[c]["opaque_id"], "verdict": "", "reason": "", "ts": ""}, ensure_ascii=False) + "\n" for c in order)
)

meta = {
    "built_at": now,
    "sample_seed": SAMPLE_SEED, "order_seed": ORDER_SEED,
    "n": len(order),
    "design": "A 全 6 + B(认证 1 + 未认证 1) + C 2 + D 2 = 12",
    "order": [{"opaque_id": by_case[c]["opaque_id"], "case_id": c, "cell": by_case[c]["cell"],
               "intended": by_case[c]["intended"], "b_certified": (c in cert_B) if cell(c) == "B" else None} for c in order],
    "sheet_sha256": hashlib.sha256(sheet_out.read_bytes()).hexdigest(),
    "r1_sha256": hashlib.sha256((BASE / "iq_R1.jsonl").read_bytes()).hexdigest(),
}
(ANCHOR / "ANCHOR-SAMPLE.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
print("sample:", [(by_case[c]['case_id']) for c in order])
print("sheet_sha256:", meta["sheet_sha256"])
