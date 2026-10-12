# 检索多查询融合原型实验（建议①执行）

- 日期: 2026-09-24
- 上游: `docs/REPORT-20260922-retrieval-miss-attribution.md` 建议①（查询改写/多查询融合）
- 产物: `evals/retrieval_ab/run_multiquery_fusion.py`、`auto-rewrites-goldset25-20260924.json`、`multiquery-fusion-20260924-175007.json`

## 实验设计

- **盲改写**：无继承上下文子代理仅见 25 条 paraphrase 查询文本生成 2×25 个关键词风格变体；禁读 goldset/语料（其 execute_command 被租约围栏拒绝，轨迹可查）；产物事后校验 25 键×2、无 gold-id 字面泄漏。
- **融合口径**：每条查询 = [原查询, 变体1, 变体2]，各自走生产 `search_once`（fused 三通道），再对 3 个结果列表做 RRF(k=60) 融合。
- **对照口径**：同 run 内单查询基线（同语料、同预热状态），不跨日比对。
- **预热**：显式补齐语料向量后再测量（原因见"过程发现 A"）。
- 语料 1761 条（09-22 基线时 1629）。

## 结果（paraphrase 25 条）

| 指标 | 单查询基线 | 多查询融合 | Δ |
|---|---|---|---|
| h@1 | 5 | 9 | +4 |
| h@3 | 10 | 15 | +5 |
| h@5 | 14 | 16 | +2 |
| h@10 | 17 | 19 | +2 |
| MRR | 0.336 | 0.505 | +50% |
| miss(top-20) | 8 | 4 | −4 |

分桶：SAVED 1 / IMPROVED 2 / OK-KEEP 13 / REGRESSION 1 / NO-GAIN 1 / STILL-MISS 7。
变体诊断上限（任一单列表 best rank）h@5 = 19；oracle 上限 21（miss-attribution 报告）。

### 剩余损失归因

1. **融合稀释（3 条）**：Q04（变体 rank4 → fused 11）、Q21（5 → 6）、Q17（4 → 6）——变体已把 gold 送进 top5，被等权 list-RRF 摊薄。
2. **主动伤害（1 条）**：Q02 orig rank4 → fused 9（REGRESSION）——变体引入的干扰项加权盖过 gold。
3. **硬 miss（4 条）**：Q07/Q10/Q11/Q22 任何列表 top-20 均无 gold。Q10 为 session-scope 结构性 miss；其余为 bge-small-zh 嵌入上限（与 miss-attribution 报告"模型上限"桶一致）。

## 过程发现

**A. 冷启动超时回退（修正一个 interim 误判）**：同日多次空变体自检给出单查询 h@5 = 9~12 的抖动，曾 interim 归因为"语料漂移"。实测否证：bge 端点确定且批不变（cos=1.0）；真因是 `SemanticRetriever._embed_cached` 逐条惰性嵌入且每条 persist 整个缓存 JSON，语料增长后首批查询在生产 `timeout_s=1.0` 下超时→静默回退 keyword（mode=keyword），逐步预热后恢复。预热后单查询 h@5 = 14，与 09-22 基线（语料 1629）持平——**语料 +132 条的真实漂移影响 ≈ 0，此前 9~12 全是冷启动伪影**。regression_gate 因先 `bge_batch` 全量文档而天然免疫；生产环境每次语料增长后同样存在该静默降质窗口（已另提演进建议）。

**B. 口径差异**：已入库的 `auto-rewrite-validation-20260922.json`（8 条新查询、变体单独 best rank 口径）结果弱（1 救回/1 退化），不与融合口径矛盾——融合下变体无需单独命中，只需贡献排名。

## 结论与建议

- 原型级证据支持建议①推进：h@5 +2 温和，但 h@1/MRR 增益显著，且 miss 减半；主要剩余损失在**融合权重**而非改写质量。
- 下一步优先级：
  1. 融合权重变体（orig 加权 RRF / 一致性重排）——先把 19@5 诊断上限吃进来；**必须在 held-out 上验证**（建议复用 auto-rewrite-validation 的 8 条 N-queries），goldset 已兼作 dev set，继续在上面调参有过拟合风险。
  2. 生产接入需单独评审：每查询 3× 嵌入/检索成本与延迟（miss-attribution 报告 §5 已列）。
  3. 基线治理：regression-baseline 建议按语料快照版本化，评测脚本一律预热（本次已固化进 `run_multiquery_fusion.py`）。

## 局限

- goldset 25 条兼作开发集；单次正式 run；变体由单一模型一次性生成（未做多模型/多样性采样）。
- 盲性为"声明 + 工具围栏轨迹 + gold-id 泄漏检查"三层保证，非密码学保证。
