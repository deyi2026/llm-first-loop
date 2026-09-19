# PROPOSAL: Harness Evolution 评估方法改进（预算对齐基线 / held-out / pass@1）

- 日期：2026-09-16 ｜ 状态：提案，待人工审定 ｜ 作者：LFL 会话（用户指令）
- 动机论文：*Rethinking the Evaluation of Harness Evolution for Agents*（AI2+UW，arXiv 2607.12227 v2）
  - 摘要已核对原文：同反馈/推理预算下与 test-time scaling 基线对照 + held-out 泛化评估；结论 = 自动 harness evolution 不能稳定胜出、泛化有限
  - 具体数字（86.0 vs 75.8、迁移 +0.6 等）出自新闻稿转述，**未逐条核对论文正文**，引用时须注明

## 0. 问题定义（为什么 LFL 需要这套）

LFL 的 method/experience/EVO 循环在结构上就是论文批评的 "Agentic Harness Evolution"：
每次改进的验收都发生在**激发它的那批任务**上。现有验收（定向测试+全量回归）能防"改坏了"，
防不了"增益是过拟合 + 隐性多花预算"。缺三样东西：同预算对照、隔离任务集、首试指标。

## 1. 三条改进

### P1 预算对齐基线（成本最低，先做）
任何 method/EVO 的 promotion（`method_manage` qualification、EVO 登记）必须附同预算对照：
- 对照组 = 不含候选改动的**同一版本** harness；候选组 = 仅叠加该改动
- 预算钉死：同模型/温度档、同轮数 K（默认 3）、同每轮 token 上限
- 必报三元组：`pass@1 / pass@K / 总 tokens`

证据分级（替代单一门槛）：
| 级 | 判据 | 可支撑动作 |
|---|---|---|
| A 强证据 | held-out Δpass@1 > 0，预算相同 | promotion |
| B 效率证据 | Δpass@K > 0 且 tokens 不升 | promotion（标注效率型）|
| C 局部证据 | 仅激发任务提升 | 记录，**不得据此 promotion** |

### P2 held-out 隔离任务集
- 20–30 个任务冻结存放（`evals/heldout/`），对优化循环不可见：不入 method/experience
  discovery 语料、不入 memory 写入期语料（加索引排除清单），eval runner 一次性注入
- migration 只在 held-out 上度量；激发任务上的收益一律标 C 级
- 任务集变更 = 显式 re-freeze 事件，旧结论不自动迁移

### P3 pass@1 观测点
- 评估侧：所有 A/B 报告单列 pass@1，禁止只报 best-of-K
- 生产侧：self_eval 增加首试指标（工具一次调用成功率、fix_loop 首轮通过率、
  单轮任务完成率），作为 harness 健康常规信号

## 2. LFL 域内 held-out 任务设计（论文的空白区）

论文自己指出 Terminal-Bench 类任务 harness 非瓶颈。LFL 的 held-out 应集中在
**harness 就是瓶颈**的域，且复用现有 evals 基建（browser_smc_*、retrieval_ab、embedding_stage2）：

| 域 | 任务形态 | 现有基建 |
|---|---|---|
| 长会话压缩存续 | 超长 session 强制压缩后：最近 N 条用户指令逐字在场 + Goal objective 在场 + 任务可继续（今天上线的锚钉即此类，单测已有，缺端到端会话级） | test_task_anchor_pin_compaction |
| 证据分页恢复 | 长 evidence 续读，偏移单调、不回吐第一页 | read_evidence 语义 |
| 多代理修复 | fix_loop max_rounds=1 通过率 | fix_loop |
| 跨会话记忆 | 检索命中旧会话结论且不串扰 | retrieval_ab 语料 |
| 中断恢复 | 会话中断后接管，事实不丢 | handoff/schedule |

## 3. 落地路径

- **v0（1–2 天）**：上表抽 6–8 任务 × K=3 × 两组（baseline/candidate）≈ 36–48 run；
  runner 沿用 mirror 运行时 + 现有 A/B 目录格式；先拿锚钉行为当第一个被测候选
- **v1**：冻结 held-out v1；`method_manage` qualification schema 增加"对照证据 ref"字段（可空=C 级）
- **v2**：self_eval 接 pass@1 常态观测；EVO 登记模板强制引用对照

## 4. 不做的事

- 不把论文结论外推成"harness 无用"——域不同，LFL 长会话/多代理/恢复恰是 harness 瓶颈区
- 不用对优化循环可见的任务做 migration 声明
- 不为过门槛临时调 K / 换模型档 / 改任务集
- 不把新闻稿数字当原文结论引用
