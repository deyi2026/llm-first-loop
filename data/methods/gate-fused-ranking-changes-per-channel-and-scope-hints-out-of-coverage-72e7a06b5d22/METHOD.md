---
method_id: gate-fused-ranking-changes-per-channel-and-scope-hints-out-of-coverage-72e7a06b5d22
name: gate-fused-ranking-changes-per-channel-and-scope-hints-out-of-coverage
description: 在多通道融合排序（如 keyword+semantic RRF）的检索栈里给某一通道新增信号字段（别名/同义词/弱提示）时：①新字段先做记账定性——弱提示只进 lexical、绝不进 term_hits/coverage/df，因为它不证明卡片覆盖了任何 query 词项，否则可借 coverage 分档加分伪造 headline 提升；②回归门禁用被改通道自身的分通道指标，融合 prod 指标会靠语义分把通道内抢位回归拉回 top-1 从而掩盖它；③引用基线数字前重读最新 baseline 工件（ran_at+goldset sha）防并发提交漂移；④headline 提升逐 query 做机制归因，剔除副作用路径后重测再报数。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:cf1db8d6-5f5a-449e-9226-c1bdc6b0fa97:427:15799ba5a4ef69bc3cfb
evidence_refs: learning:learn:9125d33f0e88
created_at: 2026-10-23T00:29:39.987023+08:00
updated_at: 2026-10-23T00:29:39.987023+08:00
---
## Trigger
多通道融合（关键词+语义 RRF 等）的检索/排序栈中，为其中一个通道新增信号字段（别名、同义词、弱提示词）并用冻结基准做 on/off 评测；或需要引用既有 baseline 数字作为对照上报时。

## Discriminator
动手前已可见两个事实：评测工件本身按 keyword/bigram/semantic/prod 分通道报告 hit@k/MRR，prod 是融合值，语义分可把被改通道的回归拉回 top-1；且评分代码内已有 coverage 分档加分（如 +50）与字段权重表——任何进入 term_hits 的新字段都可能靠凑满覆盖档位买成绩，而不证明真实覆盖。

## Short path
- 引用对照数字前，重读最新 baseline 工件，用 ran_at+goldset sha256 钉当前口径，防并发提交造成的基线漂移（旧日期文件里的数字不是当前基线）。
- 为新字段写一行记账定性：它证明什么？若只是弱提示（不证明卡片覆盖 query 词项），只进 lexical hint（权重低于 desc 基础值），并明确排除出 term_hits/coverage/df。
- on/off 评测先看被改通道自身的 hit@1/MRR 与逐 query rank；融合 prod 指标只作参考，不作回归门禁。
- 对 headline 提升的每个 query 做增益归因：若 rank 提升来自新字段凑满 coverage 档位等副作用路径，先移除该路径再重测，只报修后数字。
- 对被改通道 top-1 发生换主的查询单独复跑，确认无抢位后停止。

## Stop conditions
- 被改通道逐 query 无回归（或该权衡已被任务方明确接受）
- headline 增益在剔除副作用路径后仍成立，且两次独立运行逐位一致
- 旧代码读新数据的兼容性已回读验证

## Verification
- 同一冻结 goldset、同语料的分通道 on/off diff（不只看融合 prod 通道）
- 对排名变化的 query 逐条检查 per-query rank 与增益来源路径，确认无 coverage 凑档副作用
- 所引基线数字与最新 baseline 工件的 ran_at/goldset sha 一致

## Counterexamples
- 单通道系统（无融合）：端到端指标即通道指标，分通道门禁是多余开销
- 新字段本身就是权威覆盖证据（如人工标注同义词典、verified 映射表）：此时允许进 coverage/df，排除反而丢信号
- 任务目标明确是端到端质量、并接受通道内权衡时，通道回归不构成否决条件
