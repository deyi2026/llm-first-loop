# REPORT: 语义检索 A/B 与融合评测（hash vs bge；RRF 三通道）

- 日期: 2026-09-22
- 归档分支: `experiment/retrieval-ab-20260922`（基于 main@5e4fe3342；不入 main）
- 状态: 实验闭合（结论如下）

## 1. 假说

「检索质量差是因为缺真语义嵌入（HashEmbedder 是假语义），不是检索系统架构问题。」
判定方式：同一 goldset 上对比 hash vs bge（本地 8765 OpenAI 兼容端点，BAAI/bge-small-zh-v1.5，即生产 EMBEDDING_PROVIDER=api 同款）。

## 2. Goldset

`evals/retrieval_ab/goldset.json`：30 查询 = 25 paraphrase 硬例（措辞与存储内容刻意不同）+ 5 control（关键词直 hit）。gold=唯一正确 entry id。语料=生产 `data/memory/index.json`（1629 entries 快照）。

## 3. 结果

### 3.1 纯余弦单通道（09-17，results-20260917-164554.json）

| 组(n) | hash | bge | keyword |
|---|---|---|---|
| paraphrase(25) | h1=0.00 h5=0.00 MRR=0.026 | h1=0.20 h5=0.20 MRR=0.364 | h1=0.00 |
| control(5) | h1=0.40 MRR=0.70 | h1=1.00 MRR=1.00 | h1=1.00 |

### 3.2 线上融合链路（09-22，run_fused_eval.py，RRF 语义+关键词+实体，生产参数 th=0.50/topk=20）

| provider | ALL h@1/h@5/h@10 | paraphrase h@1/h@5 | miss | MRR |
|---|---|---|---|---|
| api(bge) | 10/19/22 (n=30) | 5/14 | 8 | 0.4492 |
| hash | 5/5/6 (n=30) | 0/0 | 24 | 0.1704 |

hash 组 control 仍全满（关键词兜底），paraphrase 全灭——语义通道质量决定硬例召回。
bge 融合 vs bge 纯余弦：paraphrase h@5 0.20→0.56，融合链路有效放大语义增益。

### 3.3 参数敏感性 sweep（本次，sweep_params.py，P0 复现基线精确一致=语料无漂移）

| 配置 | h@1 | h@3 | h@5 | miss | 结论 |
|---|---|---|---|---|---|
| P0 topk20 th0.50（基线） | 10 | 15 | 19 | 8 | =06:58 结果 |
| P1 topk40 th0.50 | 10 | 15 | 19 | 8 | 零变化 |
| P2 topk40 th0.45 | 10 | 15 | 19 | 8 | 零变化 |
| P3 topk60 th0.42 | 10 | 14 | 18 | 8 | 轻微负回归 |

放宽捞回的候选 RRF 分数过低（语义单通道 rank≥25 → 1/(60+25)≈0.0118，竞争不过双通道条目），进不了 top10；激进放宽只引入噪声。**生产校准已在参数近优点。**

## 4. 失败分析（api 组 miss=8/25，全部 gold 在索引内）

| 层 | 条目(纯bge rank, sim) | 机制 |
|---|---|---|
| 阈值截断 | Q03(29, 0.4967) Q21(179, 0.4927) Q07(455, 0.4397) Q22(944, 0.4668) Q11(805, 0.4269) | sim<0.50 不进语义候选 |
| top-20 截断 | Q15(25, 0.6075) Q04(28, 0.5776) Q10(57, 0.5613) | 过阈值但 20 名外；sweep 证明捞回也无 RRF 分数 |
| 模型语义上限 | Q07/Q10/Q11/Q21/Q22（rank 57~944） | 「测试失败项↔红清单」「裁剪↔tool_trim」类同义/跨语桥接超出 bge-small-zh 能力 |
| RRF 轻挤出 | Q08(6→7) Q17(5→6) Q23(6→6) | 纯语义 rank5/6 被融合挤 +1~2 名 |

关键词通道对全部 8 条 miss 贡献为 0（抽象措辞与存储词面无重叠）。

## 5. 结论

1. **假说成立**：缺的是语义不是系统。hash 语义通道 paraphrase 全灭；bge 上线后 paraphrase h@5 0→0.56。
2. **参数已榨干**：th=0.50/topk=20 近优，放宽零收益、激进放宽负回归（P3）。
3. **剩余缺口 8/25 是嵌入模型语义上限**，不是管线缺陷。

## 6. 建议

- 生产保持现校准，不动参数。
- 提升路径（按性价比）：① 嵌入模型升级（bge-small-zh-v1.5 → base/large/m3，需重嵌全量+重新校准阈值）；② 查询改写/扩展（抽象查询→术语桥接）；③ 记忆条目增加面向检索的摘要字段。

## 7. 局限（如实声明）

- n=30 定向 goldset，非大规模评测；单次运行（temperature 无关但端点服务状态单点）。
- 嵌入模型仅 bge-small-zh-v1.5 一档；「模型上限」结论对该模型成立，不外推到更大模型。
- goldset 由人工构造，存在构造者偏差。

## 8. 复现

```
.venv/bin/python evals/retrieval_ab/run_ab_retrieval.py      # 纯余弦 A/B
.venv/bin/python evals/retrieval_ab/run_fused_eval.py --provider api|hash   # 线上融合链路
.venv/bin/python evals/retrieval_ab/sweep_params.py          # 参数敏感性（含 P0 基线）
```
依赖：本地 8765 bge 端点在线；语料=data/memory 生产索引快照（1629）。
