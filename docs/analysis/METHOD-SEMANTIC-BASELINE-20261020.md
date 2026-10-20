# 方法卡语义检索基线（2026-10-20）

## 摘要

对 `data/methods` 全库 1248 张卡做了一次 30 条冻结查询的四通道对照，用于回答“method 范围语义检索是否该保留、融合是否成立”。

结论：**按预注册规则保留语义通道**（hit@1 33.3% vs 现行 keyword 0%，p95 271ms ≤ 3s），但现有证据**不能**证明它优于朴素二元组词法（两者 hit@1 完全相同，8/8 不一致对，McNemar p=1.0）。同时发现一个可复现的融合缺陷：把当前 keyword 结果并进 RRF 会挤掉语义 top-1，生产融合路径 hit@1 26.7% < 纯语义 33.3%。

## 1. 背景

- `a4fc072ae` 起 web/learning 的 `[semantic.web] method=true`，method 检索候选池 = 全部非 retired 卡。
- 该提交信息称“本机 bge 全库 1242 卡 2s，基准 5/5 top-1”，但仓库内没有对应的查询集或结果文件；本文把它视为一次未留痕的手工抽查，不作为质量证据。
- 既有 `evals/retrieval_ab/` 有 memory 范围 30 条 goldset（`sweep-p0-baseline-topk20-th050.json`：paraphrase hit@1 = 5/25 = 20%）与 experience 范围 7 行 qualification；缺的是 method 范围的冻结集。本文补这一块。

## 2. 语料与查询集

- 语料：`data/methods` 1248 张卡，status 分布 candidate 1194 / hold 28 / active 23 / qualified 1 / retired 2；语义候选 1246（排除 retired）。
- 样本：分层随机 30 张（seed 20261020）：candidate 23 / hold 3 / active 3 / qualified 1。
- 查询：每卡 1 条中文任务式查询，仅参考 description 撰写，不复用卡名英文词。
- 冻结：查询先写入临时文件（07:57），首跑 07:59；入仓 08:12，入仓后复跑，排序与首跑完全一致。结果文件的 `goldset.sha256` = `ff516896…a2ecab`。

## 3. 通道

| 通道 | 实现 | 说明 |
|---|---|---|
| keyword | `MethodStore.list(q, 5)` | 生产现状；中文连续段作为一个 term |
| keyword-bigram | 中文切成重叠二元组后走同一 list | 诊断通道，不是生产实现 |
| semantic | `SemanticRetriever.search(..., keyword_results=[])` | bge API，返回 512 维；全库向量缓存 100% 命中（initial_missing=0） |
| prod | `list(q,20)` + `search(keyword_results=...)` | 与 `RecordSearcher._search_method` 同参数（limit=5） |

## 4. 结果（n=30）

| 通道 | hit@1 | hit@3 | hit@5 | hit@10 | MRR | p50 / p95 |
|---|---|---|---|---|---|---|
| keyword | 0.0% | 0.0% | 0.0% | — | 0.000 | 88.1 / 99.1 ms |
| keyword-bigram | 33.3% | 56.7% | 70.0% | —（仅测到 5） | 0.473 | 125.6 / 137.0 ms |
| semantic | 33.3% | 53.3% | 60.0% | 73.3% | 0.464 | 125.0 / 270.6 ms |
| prod | 26.7% | 50.0% | 56.7% | 70.0% | 0.411 | 126.2 / 272.1 ms |

按 status（hit@1 / hit@3）：

| status | n | keyword | bigram | semantic | prod |
|---|---|---|---|---|---|
| candidate | 23 | 0 / 0 | 30.4 / 47.8 | 34.8 / 56.5 | 26.1 / 52.2 |
| active | 3 | 0 / 0 | 33.3 / 100 | 66.7 / 66.7 | 66.7 / 66.7 |
| hold | 3 | 0 / 0 | 33.3 / 66.7 | 0 / 0 | 0 / 0 |
| qualified | 1 | 0 / 0 | 100 / 100 | 0 / 100 | 0 / 100 |

hold / qualified 样本各 3 / 1 张，不能据此下分组结论。

## 5. 发现

1. **现行 keyword 对自然中文查询为零命中**：`_search_terms` 把整段中文当一个 term，30 条里 0 条命中目标。6/30 的 keyword 结果非空，全部来自查询里的英文 token（`action_id`、`fixture` 等）的偶然匹配。因此“混合检索”在当前实现下实际上是“语义 + 偶发英文噪声”。
2. **融合会挤掉已命中的语义 top-1**：prod 与 semantic 在 30 条中有 4 条排序不同，全部变差、0 条变好。其中两条目标原本是语义第 1，被 keyword 结果挤到第 8 和第 2，直接使 hit@1 从 10/30 降到 8/30。
3. **语义与二元组词法打平**：hit@1 均为 10/30；不一致对 8/8，McNemar 精确 p=1.0。语义没有显著优于一个朴素的 CJK 二元组基线。hit@1 的 95% Wilson 区间：语义 19.0–51.3%，prod 14.2–44.4%，重叠。
4. **召回不是主要瓶颈，精度被近义卡稀释**：语义 hit@10 = 73.3%，hit@1 = 33.3%。抽查 5 例未命中，top-3 都是相关但不同的处方卡，说明同库存在大量近义卡互相挤占 top-1，而不是语义完全找不到。
5. **延迟不构成风险**：语义 p95 271ms，远低于预注册的 3s 线；全库向量缓存已 100% 覆盖，不存在冷缓存导致的漏检。

## 6. 对照预注册规则

规则（goldset 文件头）：`semantic hit@1 ≥ keyword hit@1 + 20pp 且 p95 ≤ 3s → 保留`；`semantic hit@1 < keyword 或 p95 > 5s → 回退`。

- 33.3% vs 0%，差 33.3pp；p95 271ms → **按规则保留**。
- 但规则里的 keyword 基线结构性为 0，不是有意义的对照；真正有意义的 bigram 对照打平。结论应表述为“保留，但语义质量尚未被证明优于朴素词法”。

## 7. 建议（未执行，按需审批）

1. **P1 融合加可信度门槛**：仅当 keyword 命中覆盖 ≥2 个查询词（或命中分数过阈值）时才并入 RRF，否则走 semantic-only。本集可把 prod 从 26.7/56.7 拉回 33.3/60.0 的水平；这是对 `_search_method` / `SemanticRetriever.search` 的小改，需要代码审批。
2. **P1 CJK 分词**：把 `_search_terms` 的中文处理换成 bigram 或 jieba。bigram 单通道已达 33.3/56.7/70.0，说明词法侧还有可利用信号；改完用本 harness 复测，不假设一定变好。
3. **P2 语料去重/合并**：95.7% 是 candidate，近义卡互相挤占 top-1；hit@10 与 hit@1 的 40pp 差距主要在这里。
4. **P2 模型升级或 reranker**：在前两项之后再评估；当前 512 维 bge 证据不支持直接换更大模型作为第一优先级。

## 8. 偏差、局限与更正

- **流程偏差**：查询集在首跑前冻结于临时文件，但入仓晚于首跑；入仓后复跑排序一致，结果文件记录了 goldset sha256。首跑数字仅作探索，对外引用以入仓后复跑为准。
- n=30、每卡 1 条查询、无 pooled relevance 判定；“命中=目标卡本身”会低估语义（近义卡）。区间宽（±16pp），组间差异均不显著。
- 只测中文查询；未测英文、跨语言、冷缓存、并发和 reranker。
- bigram 是诊断通道，不代表生产实现；RAG 的 RRF 权重未做调参扫描。
- **更正上一轮三处说法**：① 说“没有 harness”不准确——`evals/retrieval_ab/` 已有 memory/experience 两套评测，缺的是 method 冻结集；② candidate 数应为 1194/1248（95.7%），不是 1193；③ 说“invalidated 仍进检索是半通缺口”过重——当前库 invalidated=0，该设计点在本语料上没有实测影响。

## 9. 产物与复现

- `evals/retrieval_ab/method-goldset-20261020.json`：30 条冻结查询 + 预注册规则。
- `evals/retrieval_ab/run_method_semantic_baseline.py`：四通道 runner（把 `data/methods` 复制到临时目录后再预热，不写生产缓存）。
- `evals/retrieval_ab/method-semantic-baseline-20261020.json`：原始结果（goldset sha256、配置、逐查询 rank/延迟）。
- 复现：`.venv/bin/python evals/retrieval_ab/run_method_semantic_baseline.py`。
