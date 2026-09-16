# embedding_stage2: hash vs bge 检索质量 A/B

**目的**: 验证判断"缺的是语义，不是系统"——同一套检索系统（SemanticRetriever
RRF 多信号融合，代码零改动），只换 embedder（hash n-gram → bge-small-zh-v1.5），
对比检索质量差值。

## 实验设计

- **语料**: data/memory/index.json 全量 1488 条真实记忆（content+keywords，
  复刻 `_candidates` 构造）
- **标注集** `ab_labels.json`: 40 条查询
  - **A 类（语义改写）×20**: 从条目含义出发用不同词汇提问，词面重叠由
    hash_cos(q,target) 实测落盘（mean 0.30，即 hash 视角下目标≈普通文档）
  - **B 类（词法对照）×10**: 含专名/精确词（err1214、kvcache.ai 等）
  - **C 类（噪声）×10**: 语料中无对应条目（React/红烧肉/签证等）
  - 近重复防护: 3-gram Jaccard>0.6 的条目记为 alternates，命中任一算对
- **两臂**:
  - `hash`: src `HashEmbedder(128)`（当前生产 EMBEDDING_PROVIDER=hash）
  - `bge`: bge-small-zh-v1.5 @ 127.0.0.1:8765（候选向量复用 stage1 缓存）
- **两口径**:
  - 纯语义通道（余弦排名，隔离 embedder; `run_ab.py`）
  - 端到端 RRF（真实 `_search_memory` 链路: query.split() 关键词 seed +
    RRF 语义+关键词+实体; `run_ab_e2e.py`，向量缓存预填内存不落盘）

## 结果

| 指标 | hash(现状) | bge(真语义) |
|---|---|---|
| **A类 纯语义 Recall@5** | **0%** | **50%** |
| A类 纯语义 MRR@10 | 0.000 | 0.300 |
| A类 端到端 Recall@5 | **0%** | **45%** |
| B类 纯语义 Recall@5 | 90% | 90% |
| B类 端到端 Recall@5 | 100% | 100% |
| C类 过阈值返回占比 | 100% | 50% |
| C类 top1 均分 | 0.471 | 0.521 |

关键中间事实：
- A 类 20 条改写查询，**关键词通道 seed 命中 0/20**（子串匹配零信号）
  → 语义通道是改写查询的唯一召回来源
- hash 臂 mode 分布 `semantic:29` 为假象：hash 向量在 0.22 阈值下大量
  假阳性过线；bge@0.50 有 5 条正确降级为 keyword（噪声拦截生效）
- bge 失败 10 条人工核验：target 的 bge_cos 多在 0.48-0.60（语义已识别），
  但被"主题相关、不对题"的竞争条目（0.55-0.68）挤出 top5；top1 多数
  语义上不是正确回答 → 是真检索失败，非标注歧义

## 结论

1. **"缺的是语义不是系统"成立（核心）**: 系统代码两臂完全一致（RRF/
   实体/降级/阈值机制零改动），唯一变量 embedder 使改写查询端到端
   Recall@5 从 **0% → 45%**；hash 的字符 n-gram 对无词面重叠的改写
   结构性失效，且 0.22 阈值下噪声查询 100% 假阳性返回。
2. **两个诚实限定**:
   - bge 非银弹: 同域密集语料（1488 条全是 LFL 开发记忆）上改写查询
     只有 ~50%；剩余失败是"主题相似不对题"的排序问题，需 query 改写/
     混合排序/更强模型，不是换 embedder 能解决的。
   - 收益集中在改写场景与噪声拦截: B 类（词面可匹配）hash 端到端已
     100%（关键词通道兜底），切换 provider 不是全面碾压，是补盲区。
3. **上线最后一公里**: 本地 8765 服务已具备（bge-small-zh-v1.5），
   需把 provider 从 `EMBEDDING_PROVIDER=hash` 切换并接入该端点
   （`APIEmbedder` 本就兼容 OpenAI 格式，`EMBEDDING_API_KEY` 占位符
   无碍——本地端点免认证）。

## 复现

```bash
.venv/bin/python evals/embedding_stage2/run_ab.py       # 纯语义通道
.venv/bin/python evals/embedding_stage2/run_ab_e2e.py   # 端到端 RRF
```

依赖: 本地 embedding 服务 `127.0.0.1:8765`（模型 bge）在线。

产出: `ab_results.json`（纯语义明细）、`ab_e2e_results.json`（端到端明细）。
