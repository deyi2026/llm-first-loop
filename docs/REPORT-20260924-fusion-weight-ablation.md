# 融合权重消融（建议②：orig 加权 RRF / 一致性重排）——held-out 验证

- 日期: 2026-09-24
- 上游: `docs/REPORT-20260924-retrieval-multiquery-fusion.md` 下一步优先级 1
- 产物: `evals/retrieval_ab/run_fusion_weight_ablation.py`、`fusion-weight-ablation-20260924-175813.json`

## 设计

- **集合**: dev = goldset 25 paraphrase（已兼作开发集）+ 09-24 盲变体；held-out = 09-22 的 8 条 N-queries + 其盲变体（此前只跑过"变体单独 best rank"口径，未参与任何融合调参）。
- **策略**（共享同一次检索收集，离线计算）: equal（对照）/ ow{1.5,2,3,5}（orig 加权 RRF）/ vote（RRF 分 × 出现列表数）/ ow2vote（组合）。
- **预声明决策规则**: dev 按 (h@5, h@1, MRR) 字典序选最优 → held-out 上相对 equal 的 Δ 做方向性验证（n=8 只看方向）。

## 结果

| 策略 | dev h@1 | dev h@5 | dev MRR | held h@1 | held h@5 | held MRR |
|---|---|---|---|---|---|---|
| equal（对照） | **9** | 16 | **0.505** | 1 | 1 | 0.219 |
| ow2 | 8 | 16 | 0.474 | **2** | **2** | **0.269** |
| ow2vote（dev 最优） | 6 | **17** | 0.432 | 1 | 1 | 0.225 |
| 其余 | ≤7 | ≤16 | ≤0.47 | — | — | — |

equal 完整复现上次 run（9/16/0.505）✓。dev 最优 ow2vote（h@5 17）在 held-out Δ=0/0/+0.006——**增益未复现，不采纳**。

## 归因

1. **vote 系统性反噬（否决）**: dev 上 ow2vote 把 5 条 equal rank=1 的头部压到 2-5（Q08/Q09/Q23 1→2、Q03 2→5、Q25 3→4）——共识乘法奖励"orig+变体同时出现的干扰项"，惩罚只在 orig 命中的 gold；变体列表的系统性偏差被 vote 放大。held-out N05 同型（ow2=3 → ow2vote=6）。
2. **ow2vote 的 +1 来自 Q02**（9→5，上次 REGRESSION 条目，orig 加权保护 orig 已命中项）——正是设计目标，但代价大于收益。
3. **事后观察（非采纳依据）**: 纯 ow2（无 vote）在 held-out 有 2 条实质改善（N02 22→11、N05 6→3），dev h@5 持平、h@1 −1、MRR −0.031。n=8 不足以支持切换；记为后续假设。
4. held-out 5 条硬 miss（N03/N04/N06/N07/N08）任何列表 top-20 均无 gold——bge-small-zh 嵌入上限，与融合权重无关（与 miss-attribution 报告"模型上限"桶一致）。

## 结论

- **等权 list-RRF(k=60) 保留为当前最优**；融合权重（加权/一致性）方向本轮证伪，19@5 诊断上限与 16 之间的 gap 需要非权重机制（候选：选择性融合——仅当变体列表自身置信度高时才参与；per-query 自适应）。
- 生产接入维持独立评审状态（每查询 3× 嵌入/检索成本），若接入以等权 RRF 起步。
- held-out 集完成了其设计职责：拦截了 dev 上的 +1 诱惑（这正是"goldset 兼作 dev set"风险的实际发生形态）。

## 局限

- held-out n=8 且偏难例（equal 基线 h@5 仅 1/8），方向性验证的统计功效有限。
- 变体仍为单一模型一次性生成；策略空间未覆盖非 RRF 族（如 score-level 融合）。
