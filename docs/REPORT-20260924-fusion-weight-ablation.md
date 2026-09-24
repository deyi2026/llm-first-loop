# 融合权重消融：orig 加权 RRF / 一致性重排（建议①后续）

- 日期: 2026-09-24
- 上游: `docs/REPORT-20260924-retrieval-multiquery-fusion.md` 下一步 1（融合权重 + held-out 验证）
- 产物: `evals/retrieval_ab/run_fusion_weight_ablation.py`、`fusion-weight-ablation-20260924-190027.json`
- 语料 1765（上一实验 1761）；`equal` 对照精确复现上次结果（h@5=16, h@1=9, MRR=0.505），run 可信。

## 设计

- 数据：dev = goldset 25 paraphrase + 09-24 盲变体；held-out = 09-22 的 8 条 N-queries（含变体文本），全流程 held-out 前不触碰。
- 策略（同一进程预热后收集全部 3-列表完整 id，离线扫参，零重复嵌入）：
  `equal` / `ow{1.5,2,3,5}`（orig 列表 RRF 权重>1）/ `vote`（融合分×出现列表数）/ `ow2vote`。
- 预注册决策规则：dev 按 (h@5, h@1, MRR) 字典序选最优 → 该策略在 held-out 上相对 equal 做**方向性**验证（n=8 不谈显著）。

## 结果

DEV(25)：ow2vote h@5=17（唯一超 equal 的策略）但 h@1 9→6、h@3 15→13、MRR 0.505→0.432；equal/vote 完全并列；ow2/3/5 h@5=16 持平但 h@10 19→17。

HELD-OUT(8)：

| 策略 | h@1 | h@3 | h@5 | h@10 | MRR |
|---|---|---|---|---|---|
| equal | 0 | 0 | 1 | 2 | 0.058 |
| ow2 | 0 | 1 | 2 | 3 | 0.085 |
| ow2vote(dev-best) | 0 | 0 | 1 | 3 | 0.065 |

**dev 最优 ow2vote 在 held-out 增益不复现**（Δh@1=0, Δh@5=0, ΔMRR=+0.007）。

## 机制归因（per-query）

orig 加权与等权各自修复对称的失败模式，两集合比例不同导致不可迁移：

- **加权修复"主动伤害"型**（变体干扰压过 orig gold）：dev Q02 9→5；held-out N02 21→9（仍>5）、N05 6→3（→h@5）。
- **加权伤害"变体优先"型**（变体 rank1、orig>1，等权把 gold 推到 1）：dev Q08/Q09/Q23 1→2，即 h@1 −3 的全部来源。
- `vote` 乘法对只在单列表出现的 gold 是惩罚性的（N05: ow2=3 但 ow2vote=6）；等权下与 equal 逐条相同，无独立增益。
- held-out 5/8 硬 miss（N03/N04/N06/N07/N08 任何列表 top-20 无 gold）与权重无关，是嵌入/召回上限。

## 结论

1. **保持等权 list-RRF(k=60) 为生产默认**：预注册规则下 dev 最优不能迁移到 held-out；ow2vote 的 +1 h@5 以 h@1 −3、MRR −7pp 为代价；纯 ow2 在 held-out +1 h@5 但 dev h@1 −3——两集合信号方向不一致，n=8 不足以改默认。
2. 融合公式的边际收益已接近榨干：dev 17/19@5 诊断上限，剩余 4 miss 均为"任何列表无 gold"。
3. 下一个真正能动的杠杆不在融合权重，而在**变体有效性（held-out 上变体几乎零贡献）或嵌入模型升级（bge-small-zh 上限）**；生产接入仍需按 miss-attribution §5 单独评审 3× 检索成本。

## 局限

- held-out n=8 且偏难（5 条硬 miss）；变体为 09-22 旧生成物，未对 N-queries 重采样。
- 单次正式 run；策略网格为手工设定非穷举。
