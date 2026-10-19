# S1 卡自检（§10.3-1 / §10.3-5 / 等长）

- 日期：2026-10-19
- 对象：`cards/gold.md`（744 字符，CJK 388，sha256 4c9d22ca…）、`cards/filler.md`（719 字符，CJK 356，sha256 2967e0c8…）
- 方法：`ngrams(text, 8)` 与 `pool_p28.jsonl` 的 120 个 question 逐条比对；重合率 = |Q8 ∩ C8| / |Q8|（与 `build_pool_p28.py` 口径一致）。

## 结果

| 检查 | gold | filler | 门槛 |
|---|---|---|---|
| 8-gram 最大重合率 | 0.0 | 0.0 | ≤0.3 |
| 含 URL / `http` | 0 | 0 | 不得含实例原文 |
| c1 正则命中 | 无 | 无 | 不作为卡自引 |
| 六节结构 | 全 | 全 | 同结构 |
| 字符数差 | — | — | 3.36% <10% |

- filler 的目标行为关键词扫描：`链接/澄清/提问/选项/昂贵/发布/抓取/文章/正文/意图` 均为 0。
- 与 S0 已记录回复的最大共享 8-gram 比例：两卡均 0.0103（信息性，非 §10.3-5 判据）。
- 人工过卡：gold 只含通用行为规则，未复制任何实例 URL、标题或 S0 回复原文；filler 为无关的 CSV 场景。

## 复现

```python
import json, re
from pathlib import Path
root = Path("evals/methodcard_rsi_v1")
pool = [json.loads(l) for l in (root/"s0_p28/pool_p28.jsonl").read_text().splitlines() if l.strip()]
def ngrams(t, n=8):
    t = re.sub(r"\s+", " ", t.strip())
    return {t[i:i+n] for i in range(max(0, len(t)-n+1))}
def overlap(q, c):
    q8, c8 = ngrams(q), ngrams(c)
    return len(q8 & c8)/len(q8) if q8 else 0.0
for n in ("gold","filler"):
    c = (root/f"s1_gold_filler/cards/{n}.md").read_text()
    print(n, max(overlap(p["question"], c) for p in pool))
```
