# -*- coding: utf-8 -*-
import sys, pathlib
SPEC = "docs/SPEC-20261123-cooperative-target-protocol-v0.9.md"
PROP = "docs/SPEC-20261123-CTP-tbd-resolutions-proposal.md"
DES  = "docs/DESIGN-20261123-physical-world-sensing-calibration-v1.md"
EDITS = []
def E(p,o,n): EDITS.append((p,o,n))

E(SPEC,
"| V5 | 投影标定 | 前提自检不满足时必须判\"粗对齐\"并打降级标记；混入毫米级通道即不通过 |",
"| V5 | 投影标定 | 前提自检不满足时必须判\"粗对齐\"并打 degradation_flag = `coarse`（C-5）；\"混入毫米级通道\"定义为：该观测被 F-2 用于 NEAR 交接、或计入 V2 精度统计——实现必须以 degradation_flag 支撑该判据，无标记即判不通过 |")

E(SPEC,
"b) 物理测试：认证样本公差（V3）、跨厂商一致性（V6）；",
"b) 物理测试：批次抽检落带（V3）、跨厂商一致性（V6）；认证样本仅作 V6 基准与定带输入；")

E(DES,
"| V5 | 投影标定 | 前提自检不满足时必须判\"粗对齐\"并打降级标记；混入毫米级通道即不通过 |",
"| V5 | 投影标定 | 前提自检不满足时必须判\"粗对齐\"并置 degradation_flag = coarse；\"混入毫米级通道\"= 该观测被 F-2 用于 NEAR 交接或计入 V2 统计（SPEC C-5 字段支撑） |")

E(DES,
"| V2 | 定位精度 | 合作通道在 0.2–2 m、入射角 ±60°、规定光照内：平移 ≤ 2 mm (3σ)、旋转 ≤ 0.5° (3σ) |",
"| V2 | 定位精度 | 合作通道在 0.2–2 m、入射角 ±60°、规定光照内：平移 ≤ 2 mm (3σ)、旋转 ≤ 0.5° (3σ)；不确定度声明须给出 k 与 1σ 值 |")

E(PROP, "- 文档编号：PROP-20261123-CTP-TBDG-0.1", "- 文档编号：PROP-20261123-CTP-TBDG-0.2")

E(PROP,
"- 数据位可见比例：取 V4 实测\"误读率 = 0\"区间的**上确界向下取整**（保守侧归整到 5% 粒度）；宁可漏检、不可错读（C-4b）决定归整方向永远向安全侧。",
"- 数据位可见比例：取 V4 双向判据（误读率 = 0 且漏检率 ≤ [TBD-V4c]）通过区间的**上确界向下取整**（保守侧归整到 5% 粒度）；宁可漏检、不可错读（C-4b）决定归整方向永远向安全侧——注意 V4 已禁止\"永不输出\"平凡通过，阈值不能靠压低比例来满足误读约束。")

files = {p: pathlib.Path(p).read_text(encoding="utf-8") for p in (SPEC, PROP, DES)}
for p,o,n in EDITS:
    c = files[p].count(o)
    if c != 1:
        print(f"[ABORT] {p} match={c}: {o[:50]!r}"); sys.exit(2)
    files[p] = files[p].replace(o,n)
for p,t in files.items():
    pathlib.Path(p).write_text(t, encoding="utf-8")
print(f"[OK] {len(EDITS)} edits applied")
