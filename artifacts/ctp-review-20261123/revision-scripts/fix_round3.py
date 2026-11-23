# -*- coding: utf-8 -*-
import sys, pathlib
SPEC = "docs/SPEC-20261123-cooperative-target-protocol-v0.9.md"
EDITS = []
def E(o,n): EDITS.append((o,n))

E("- `[TBD-V*]`：数值空缺，依赖第 11.2 节门槛 V* 的实测结果填充。**一个编号只承载一个物理量 / 一个判据**；同一门槛需要多个独立量时拆分为 `[TBD-V4a]/[TBD-V4b]`，或改用条目号（如 `[TBD-P2a]`、`[TBD-F2]`）；\n- `[TBD-G]`：数值或方案空缺，依赖工作组裁决（需要决定，不需要实测）。",
"- `[TBD-V*]`：数值空缺，依赖第 11.2 节门槛 V* 的实测结果填充；同一门槛的多个独立量拆分为子项（如 `[TBD-V4a]` 角点数 / `[TBD-V4c]` 漏检率上限）；\n- `[TBD-<条目号>]`（如 `[TBD-P2a]`、`[TBD-M2]`、`[TBD-F2]`）：数值空缺，依赖该条目的计量实测数据填充；\n- `[TBD-G]`：数值或方案空缺，依赖工作组裁决（需要决定，不需要实测）；其子项写作 `[TBD-V3α]`、`[TBD-FB]` 等形式，仍属裁决类。\n\n**一个编号只承载一个物理量 / 一个判据**——禁止同一编号同时代表两种量纲（例如\"角点数\"与\"可见比例\"）。")

E("| 级间位姿差阈值 [TBD-F3：k×RSS，k 默认 2] | F-3 | V8 只验证不校准；修订走 VC-1 | 工作组 |\n| V3 落带判据的带外率上限 / 样本量 [TBD-V3α / β] | 11.2-V3 | P2 计量 | 工作组 |",
"| 级间位姿差阈值 [TBD-F3：k×RSS，k 默认 2] | F-3 | V8 只验证不校准；修订走 VC-1 | 工作组 |\n| V3 落带判据的带外率上限 / 样本量 [TBD-V3α / β] | 11.2-V3 | P2 计量 | 工作组 |\n| 跨厂商一致性重复次数 [TBD-V6a] | 11.2-V6 | 统计功效估算（重复次数与 95% 通过率判据匹配） | 工作组 |\n| 回退率上限 [TBD-FB]（F-3 阈值第二约束） | F-3 / PROP G3 | P2 台架回退率实测 | 工作组 |")

p = pathlib.Path(SPEC); t = p.read_text(encoding="utf-8")
for o,n in EDITS:
    c = t.count(o)
    if c != 1:
        print(f"[ABORT] match={c}: {o[:50]!r}"); sys.exit(2)
    t = t.replace(o,n)
p.write_text(t, encoding="utf-8")
print(f"[OK] {len(EDITS)} edits")
