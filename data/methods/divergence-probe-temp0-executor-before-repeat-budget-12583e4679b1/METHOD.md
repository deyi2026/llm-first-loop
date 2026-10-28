---
method_id: divergence-probe-temp0-executor-before-repeat-budget-12583e4679b1
name: divergence-probe-temp0-executor-before-repeat-budget
description: 为 LLM 执行器跑批/A-B 实验安排『每条件 N 次重复』之前，先用 1-2 次同参对拍做分歧探针：温度 0（贪心）下若逐位/逐 check 完全一致，重复调用零信息，repeats=1，省下的预算转投新样本或口径校准。本集实测：batch 5 族 × 3 次重复位串完全相同（10 次重复调用白跑）。同族校准还有两条：批量 vs 单题呈现口径需对拍后才能定主口径（本集 H02/H03 分数随口径翻转）；finish=length 且 content 为空属于预算耗尽，应倍升 max_tokens 重跑，而非记为能力失败，否则按难度偏置丢样本。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:31e64fa8-0da2-4a1c-afd1-a74ed4fcd805:2285:040556be53747ef06efe
evidence_refs: learning:learn:aec298fda785
created_at: 2026-10-19T13:38:16.417709+08:00
updated_at: 2026-10-19T13:38:16.417709+08:00
---
## Trigger
为 LLM 跑批/A-B 臂计划『每条件 N 次重复』以估计方差或防抖动，且采样配置为 temperature 0/贪心；或跑批台账把 finish=length 且 content 为空的调用计为失败

## Discriminator
安排重复预算时已可读到采样配置为 temp=0/贪心——贪心解码本应确定，唯一存疑的是端点侧非确定性，用 1-2 次同 prompt 同参调用对拍即可证实或证伪（本集证实：重复调用逐 check 位串完全相同）。该事实在花掉约 10 次零信息重复调用之前就能以极低成本取得，足以把 N 次重复缩为 1 次。

## Short path
- 读 harness/env 确认采样配置（temp=0/贪心）与计划重复数；未知量：该执行器在此端点是否真随机
- 取 1 个代表 case 连发 2-3 次同参调用，逐位/逐 check 比对；未知量：分歧是否存在
- 全同 → repeats=1，省下的调用转投新题补集或口径探针；出现任何分歧 → 重复有信息量，保留
- 用 2-3 题对拍批量 vs 单题呈现口径；若分数不等价，改用与真实使用一致的口径为主口径，旧口径结论降级为参考
- 把 finish=length 且空 content 的回执归类为预算耗尽：倍升 max_tokens 重跑该条，不计入能力失败率

## Stop conditions
- 分歧探针出现任何不一致输出（重复携带信息，停止削减重复）
- 端点、模型或 harness 采样配置发生变更，旧确定性结论作废，需重新对拍
- 温度>0 或端点文档声明服务端非确定性/多副本路由时，单对全同不足以定论

## Verification
- 任何配置变更后重跑一次同参对拍，再恢复 repeats=1 的预算策略
- 复核最终结果台账：失败调用中不存在『finish=length + 空 content 且未重跑』的条目
- 抽查主口径分数与按部署/真实使用口径逐题作答的分数一致

## Counterexamples
- 温度>0 或 top-p 采样、目的就是估计方差——重复是实验目的本身，不得用此法删除
- 端点带服务端缓存或路由到不同推理副本，一对全同可能是缓存假象而非确定性证明，需跨时间多探几对
- 本地免费组件的重复调用无预算成本，不值得先花探针成本再决定是否重复
- 重复的目的是测端点稳定性/超时率而非输出方差时，位串全同不等于重复无价值
