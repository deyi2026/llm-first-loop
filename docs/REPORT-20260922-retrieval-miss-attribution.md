# REPORT: miss 归因分桶——oracle 改写干预实验（修正 REPORT-20260922-retrieval-ab-fused）

- 日期: 2026-09-22
- 分支: `experiment/retrieval-ab-20260922`（追加于 bbff7f4f2）
- 状态: 干预实验闭合；**前报告 §5.3 结论被修正**

## 1. 动机

前报告 §4 失败分析是观察性的（rank/sim 分布），§5.3 断言「剩余缺口 8/25 是嵌入模型语义上限」，§6 首选提升路径为嵌入模型升级（重嵌全库）。本实验用干预法检验：若 miss 主因是查询措辞与存储词面缺桥接，用 gold 记录真实词面改写查询应能救回；救不回的才支持模型上限假说。

## 2. 方法

`run_rewrite_probe.py`：25 条 paraphrase 原查询复跑（miss 集合与前报告一致：Q03/Q04/Q07/Q10/Q11/Q15/Q21/Q22）；对每条 miss 用其 gold 的 keywords/text 真实术语构造 oracle 改写（术语桥接上限测定，排除改写模型能力干扰），跑线上融合链路 + 关键词单通道。生产参数 th=0.50/topk=20，语料临时副本隔离，只读。

## 3. 结果（oracle 救回 7/8）

| miss | oracle 改写要点 | kw rank | fused rank | 判定 |
|---|---|---|---|---|
| Q03 | fail-safe 配置非法值回退 | 2 | 1 | 查询侧 |
| Q04 | honesty.py LLM调用异常前缀 | 1 | 1 | 查询侧 |
| Q07 | tool_trim 占用率裁剪 | 1 | 1 | 查询侧（Q27 control 同 gold 交叉印证） |
| Q11 | Evidence Recoverability R7-V2 | 1 | 1 | 查询侧 |
| Q15 | 声明校验 回执 如实声明（精确 keywords 串） | 1 | 2 | 查询侧（初次变体组合词 kw=13，差在 keyword top10 截断） |
| Q21 | LLMHTTPError 500 reasoning effort | 2 | 2 | 查询侧 |
| Q22 | 已知红清单 known-reds | 3 | 5 | 查询侧 |
| Q10 | 词面全命中仍不可达 | N/A | N/A | 系统侧 |

### Q10 专项

gold `scope=session`（source_session=e979d730…）。`MemoryStore.search` 设计为 `session_id=""` 仅召回 global（防跨会话污染）→ 关键词通道结构性不可达；但语义通道可见该条（rank 57）——**两通道 scope 语义不一致**。带自身 session_id 时 kw rank=1。归系统侧 scope 一致性议题，非模型上限、非查询措辞。

## 4. 结论修正

前报告 §5.3「剩余缺口 8/25 是嵌入模型语义上限」**不成立**。干预归因：**查询侧 7/8，系统侧（scope 一致性）1/8，模型上限 0/8**。bge-small-zh-v1.5 在本 goldset 上未表现出需要换模型才能跨越的上限。

## 5. 提升路径修正（取代前报告 §6 顺序）

1. **查询改写/多查询融合**（首选；与前报告把模型升级排第一相反）：抽象查询 → 2-3 个术语桥接变体，各查一遍再融合。不动索引不动模型。oracle 上限 = paraphrase fused h@5 14→21/25。生产落地涉及每查询额外 1 次 LLM 调用（延迟/成本），需单独评审；自动改写质量需新鲜评测者验证（本实验 oracle 由 goldset 构造方执行，存在构造者偏差）。
2. scope 一致性议题：语义通道是否应遵守与 store.search 相同的 session 隔离（或关键词通道按需放宽），交 design review，不擅改。
3. 嵌入模型升级：本 goldset 上无必要；若未来 miss 结构变化再评估。

## 6. 护栏（新增，`regression_gate.py`）

三通道（keyword/semantic/fused）h@1/3/5/10 + MRR + miss，基线比对 `regression-baseline.json`，任一退化 exit 2。分通道的理由：融合总分对单通道退化不敏感（本基线即例证——keyword paraphrase h@5=0 而 fused=14）。

必跑场景：嵌入模型变更、索引/向量缓存重建、SemanticRetriever 参数调整、store.search 逻辑变更。

基线（corpus=1629，2026-09-22）：
- overall keyword 5/5/5/6 mrr=0.1704 miss=24；semantic 10/16/20/22 mrr=0.4698 miss=8；fused 10/16/19/22 mrr=0.452 miss=8
- paraphrase keyword 0/0/0/1；semantic 5/11/15/17；fused 5/11/14/17

## 7. 边界外发现（如实记录）

experiment/mem-citations-20260922 线全量测试独立复跑回执：**151 passed + 1 failed**。failed = `test_manifest_and_health_identity_expose_knowledge_health`，在 citations/main 基线同样失败（`294 == 1`：monkeypatch `LFL_WORKSPACE_ROOT` 不隔离 knowledge_health 计数，读到了真实工作区 294 条 experiences）。pre-existing 环境依赖测试隔离缺陷，与修复包无关，建议单独立 issue。

## 8. 局限

- oracle 改写由 goldset 同一构造方执行（构造者偏差）；LLM 自动改写质量未测。
- n=25 paraphrase；Q10 为单例，不足以定 scope 不一致的普遍性。
