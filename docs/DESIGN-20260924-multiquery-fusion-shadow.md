# 多查询融合生产接入评审：影子模式（建议①执行）

- 日期: 2026-09-24
- 上游: `docs/REPORT-20260924-retrieval-multiquery-fusion.md`（融合权重消融后结论）
- 代码: `src/llm_loop/memory/multiquery_shadow.py`（探针）、`RecordSearcher._search_memory` 挂点、`factory.py` 装配
- 测试: `tests/unit/test_multiquery_shadow.py`（12 用例：零行为契约/JSONL 契约/防递归/错误安全/env 校验）

## 为什么是影子模式

- dev 增益实质（h@1 5→9、MRR +50%、miss 8→4），但"值不值接入"卡在成本体感：每查询 +1 次 LLM 改写 + 2 次额外语义检索。
- 生产查询分布 ≠ goldset；上线前需要真实分布上的延迟与排序置换数据。
- 影子模式旁路测量，返回值与 off **逐字节一致**（测试锁定），可长期挂在生产采集。

## 启用与观测

```bash
RETRIEVAL_MULTIQUERY_MODE=shadow   # off（默认）| shadow；非法值 fail-safe 回 off
```

- 前置：语义检索可用（semantic_available）+ 主 LLM client；否则探针不装配（零行为）。
- 观测文件：`<data_dir>/retrieval_shadow.jsonl`，每次生产 memory 语义检索一条：
  - `latency`: `rewrite_s`（LLM 改写，10s 超时）/ `search_s`（2 变体检索）/ `total_s`
  - `primary_top` / `fused_top`（各 top10）、`overlap_at_5`
  - **保位护栏设计项**：`primary_top1_in_fused_top1/top3`（orig top1 被融合挤出的频次）
- 融合形态：等权 list-RRF(k=60)——held-out 消融（8 条）已否证精细加权/一致性重排的增益，等权即候选生产形态。

## 安全契约

1. 探针全异常捕获（含 LLM 网络/解析失败）：错误只记 JSONL error 行，绝不向上抛。
2. 落盘失败静默（单行小对象追加写，读侧容错）。
3. 变体检索经 `_skip_shadow=True` 内部复用 `_search_memory`，防递归。
4. `mode=off`（默认）时探针不构造，`_search_memory` 行为与改动前一致。

## enforce 决策门（影子数据收齐后）

| 维度 | 通过标准（占位，影子数据回来后修正） |
|---|---|
| 改写延迟 | p50 ≤ 2s、p95 ≤ 5s；失败率 < 5% |
| 检索延迟 | 变体检索 2× ≤ 原语义检索 2×（共享嵌入缓存） |
| top1 置换 | `primary_top1_in_fused_top1=false` 比例 → 决定保位护栏（如 orig top3 强制保留）是否随 enforce 上 |
| 增益确认 | 影子期无法直接测 gold；靠 evals 侧 goldset 复验 + 影子排序置换率间接评估，或配 canary 反馈 |

## 遗留

- enforce 路径未实现（本轮明确不做，避免半成品开关）；影子数据 ≥ 1 周或 ≥ 500 条后评审。
- 改写用主 LLM client 同配置；如成本敏感可换轻量模型（改 `make_llm_rewriter` 装配即可，接口不变）。
- 生产语料持续增长时影子日志会积累，轮转策略留部署面。
