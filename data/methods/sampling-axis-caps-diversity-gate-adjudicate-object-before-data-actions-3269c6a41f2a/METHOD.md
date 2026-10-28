---
method_id: sampling-axis-caps-diversity-gate-adjudicate-object-before-data-actions-3269c6a41f2a
name: sampling-axis-caps-diversity-gate-adjudicate-object-before-data-actions
description: 状态工件的多样性门槛（如 failure-mode ≥2 种、判别动作不单一）判 FAIL 而数量条件已过时，先读工件自述的候选池抽样条件与 mode 分布：若抽样轴在逻辑上只蕴含一种 mode，则观测种类数是轴的确定函数，同轴加样本、调门槛数值、人工构造补种都改变不了结论。决策点应改写为门槛适用对象裁决：判『进库资格』则把多样性不足降为 scope 受限标注（窄卡）而非否决；判『泛化声明资格』则换抽样轴重抽。辅以零成本核 instance 可重放性；换轴试点允许有信息量的负结果。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:e47f7009-17d2-450f-91a7-d4daf1887e55:1512:2397f27ae13d46688e4b
evidence_refs: learning:learn:7185950b1da4
created_at: 2026-10-21T11:19:30.660837+08:00
updated_at: 2026-10-21T11:19:30.660837+08:00
---
## Trigger
治理/验收状态工件（pool_status、GATE 结果）的多样性条件判 FAIL，而计数条件（instances≥N）已过，需要给下一步建议（补数据/降级/换轴/改门槛）时

## Discriminator
工件内自述的抽取条件（如『候选按某单一事件被调用抽取』，pool_status.json 覆盖检查注记）与实测分布（全部 instance 同属一种 failure mode、判别动作文本不同但语义同一）并置：观测多样性 ≤ 抽样轴蕴含的多样性，与样本量 n 无关。这是当时已显示在回执里的事实，不需要任何新采集。

## Short path
- 读状态工件，一次取三组字段：各门槛条件测量值、候选池抽取条件自述、instance 的 mode/判别动作分布
- 判定抽样轴与被测多样性维度的蕴含关系：轴是否在逻辑上只覆盖一种 mode（是→种类数已封顶）
- 若封顶：先排除『同轴扩样本』与『人工构造补种实例』两类动作，把决策点改写为门槛适用对象裁决（进库资格 vs 泛化声明资格）
- 按裁决分支：进库资格→降级为 scope 受限窄卡保留证据；泛化资格→换抽样轴（如按返工/纠正事件）而非加样本
- 零成本核既有 instance 可重放性（是→配对消融资产；否→锁为回归样例）；可选换轴 30 条试点，预先写明两种结果的解释

## Stop conditions
- 已从自述+分布确认轴封顶，且门槛适用对象已裁决，分支建议即停，不再枚举更多文档或候选
- 换轴试点已跑完或已裁决不做

## Verification
- 抽样条件自述与实测分布一致（如 78 条候选全部来自该条件、24 条陷阱全部同一 mode）
- 换轴预测可证伪且预先声明：≥2 种 mode→抽样协议缺陷成立；仍 1 种→单点失败的有信息量负结果
- 最终建议引用上游设计条款时沿工件内引用（design §x + 日期）定位原文，而非猜测关键词

## Counterexamples
- 分布已显示多种 mode、只是各自样本不足：轴未封顶，扩样本可能有效，本方法不适用
- 被测多样性维度与抽样轴正交（如按任务领域抽样、测失败模式多样性）：轴不决定该维度，需另行分析
- 门槛是纯计数条件且抽样轴不限制计数：直接补样本即可，无需裁决适用对象
