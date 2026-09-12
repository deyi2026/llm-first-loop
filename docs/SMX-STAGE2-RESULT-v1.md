# SMX 阶段二结果报告（闸门3，v1）

日期：2026-09-12。协议：PROTOCOL-20260911.md（sha256 302ecf72…，跑中未改动）。
数据：12 run（6 任务 × A/B，08:02–08:11 执行）；pilot 2 run（昨日）仅作管线验证，**不计入统计**。
聚合源：`.runs/AGGREGATE-final.json` + 各 run `metrics.json`（metrics.py 机械提取）。

## 1. 有效性闸门（协议 §5，预写死）

- B 组 smx 采用 4/6（T1/T3/T5/T6）= 66.7% ≥ 50% 线 → 通过。
- treatment-absent 2/6（T2B、T4B，smx_calls=0）< 3/6 无效线 → 数据集有效。
- 效应观察只在 4 个有效对（A vs 采用 smx 的 B）上进行；T2/T4 的 B run 不计入 B 组统计。

## 2. 全量指标（12 run）

| run | judge | steps | tools | errs | shell | perc_seg | tool_perc | sleep_s | smx | smx_actions | receipt_refs | wall_s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T1A | PASS | 7 | 9 | 0 | 5 | 16 | 2 | 0 | 0 | — | 0 | 28.6 |
| T1B | PASS | 9 | 9 | 0 | 6 | 6 | 2 | 0 | 1 | exec×1 | 2 | 25.2 |
| T2A | PASS | 7 | 11 | 0 | 7 | 9 | 3 | 0 | 0 | — | 0 | 20.8 |
| T2B* | PASS | 5 | 7 | 0 | 3 | 6 | 3 | 0 | 0 | — | 0 | 16.0 |
| T3A | PASS | 10 | 12 | 0 | 10 | 18 | 2 | 0.5 | 0 | — | 0 | 36.4 |
| T3B | PASS | 10 | 11 | 0 | 7 | 19 | 1 | 0 | 3 | exec×1,wait×2 | 0 | 33.8 |
| T4A | PASS | 9 | 9 | 0 | 7 | 29 | 2 | 0 | 0 | — | 0 | 18.5 |
| T4B* | PASS | 11 | 14 | 0 | 9 | 26 | 4 | 0 | 0 | — | 0 | 31.5 |
| T5A | PASS | 9 | 10 | 0 | 7 | 16 | 2 | 0 | 0 | — | 0 | 24.9 |
| T5B | PASS | 9 | 13 | 0 | 5 | 9 | 3 | 0 | 1 | exec×1 | 1 | 28.6 |
| T6A | PASS | 10 | 12 | 0 | 8 | 11 | 2 | 0 | 0 | — | 0 | 29.1 |
| T6B | PASS | 7 | 9 | 0 | 4 | 9 | 2 | 0 | 3 | bg,wait,collect | 0 | 27.9 |

\* treatment-absent，不计入 B 组统计。判定 12/12 PASS。

## 3. 预写死边界下的结论（协议 §6）

**H1（diff 回执减少重感知）——方向性支持，含 1 个持平个案。**
重感知 = perc_seg + tool_perc。有效对：T1 18→8（−56%）、T5 18→12（−33%）、T6 13→11（−15%）、T3 20→20（持平）。3/4 下降。n=4 无统计功效，仅记方向。

**H2（wait 减少轮次）——弱/混合，不宣称支持。**
两个等待型任务：T6 steps 10→7（bg+wait+collect 替代轮询，−30%）；T3 sleep 1→0（被 wait×2 替代）但 steps 10→10 持平。非等待任务 T1 steps 7→9 反升。方向不一致，记混合。

**H3（断言外包降错误率）——insufficient。**
两臂 tool_errors 均 0（12+2 run 全零），judge 失败 0/0。无反例、亦无任何可观测差异；按预写死边界记 insufficient，不推断「更可靠」。

**附带条件（同报失败率不升）：满足。** 两臂均 0 失败。

**H4（诚实成本）：不适用。** 阶段一 spot 已达标，协议规定阶段二不重测。

**wall_s（次要，如实报）：** 有效对 A 均值 29.8s → B 均值 28.9s（−3%，噪声级；T5 反升 +3.7s）。

## 4. 个案（阶段三裁决证据）

- **T1（回执替代重扫）**：B 组 1 次 smx exec，后续命令 2 次引用 receipt（receipt_refs=2），perc_seg 16→6。H1 最强个案。
- **T6（异步套件）**：唯一完整使用 bg→wait→wait→collect 的 run，steps 10→7、shell 8→4。
- **T3（持平反例）**：B 组用了 smx×3（含 wait×2），perc_seg 18→19 不降。工具在场≠收益在场。
- **T4（采用随机性）**：同一张卡，pilot T4B 用了 smx（exec×1，receipt_refs=6），全量 T4B 未用而选择自行读 judge.sh 对齐口径。采用是逐会话随机行为；另 T4 两臂 perc_seg 全场最高（29/26），主因任务本身需逐条核验清单，与 smx 无关。
- **smx show（回执重放）：全场 0 采用。**

## 5. Limitations 与混杂声明

- **B 卡附录混杂因子**：A/B 差异除工具可用性外，还含附录 4 行文本本身（注意力/启动效应与工具效应不可分离）。协议设计如此；阶段三若复测，可用「附录等长但指向无效工具」的安慰剂卡分离该因子。
- **被试 n=1**：同一模型、同一 provider 配置的被试内对照，结论不外推到其他模型/配置。
- **任务样本 n=6（有效对 4）**：无统计功效，§3 已按预写死边界限制为方向性观察。
- 保真度：11/12 组 prompt 与渲染卡逐字一致；T3B 附录注释 1 词损坏（"前台执行"→"剽窃执行"，复打卡笔误，任务正文逐字一致，判 PASS 且 smx 采用不受影响；FIDELITY-LOG.txt 已记）。trailer 12 组同构，无 A/B 交付通道系统性差异。
- 指标近似（协议 §4 已冻结声明）：字符串级管道切段、首 token 白名单分类；异议以 calls.tsv 为准（12 份在 `.runs/<run>/calls.tsv`）。

## 6. 边界外观察（非预写死，仅供阶段三参考，不构成结论）

任务全 PASS 意味着当前 fixture 无难度分离——错误率与失败率维度天花板效应，是 H3 insufficient 的直接原因。若阶段三要测 H3，需加难任务至 A 组出现非零失败/错误率后再跑。

## 7. 裁决材料索引

- 协议/冻结：`tools/smx/lab/PROTOCOL-20260911.md`、`FREEZE.json`（v2）
- 聚合：`.runs/AGGREGATE-final.json`；逐 run：`.runs/080237-T1A` … `081058-T6B`（metrics.json + calls.tsv + judge 输出）
- 保真度：`.runs/FIDELITY-LOG.txt`；审计脚本：`.runs/audit.py`、`.runs/audit2.py`
- 阶段一 PoC：`tools/smx/smx.py`、`docs/tasks/VALIDATE-20260911-smx-poc.md`

**一句话总结：管线与数据集有效（采用 4/6）；H1 方向性成立（3/4 降 15–56%，1 持平）；H2 混合；H3 insufficient；一切结论受 n=4 有效对限制，不外推。**
