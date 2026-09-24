---
method_id: ground-efficiency-in-observed-cost-profile-ea444557e851
name: ground-efficiency-in-observed-cost-profile
description: 先用量日志确定成本主导项，再沿主导项检查现有机制并只提出可验证的最小改动；避免在未量化 prefill/decode、缓存命中和轮次增长前泛泛优化模型或提示。
status: candidate
source_model: cognilocal/qwen3.8-flash-next
source_episode_refs: episode:d8f3d445-6e86-457c-bf7f-b10c1665f75e:117:480cc809eb5533caf703
evidence_refs: learning:learn:ba2a7a43cfe6
created_at: 2026-09-22T16:47:28.646634+00:00
updated_at: 2026-09-22T16:47:28.646634+00:00
---
## Trigger
当任务要求提升 LLM/agent 仓库的模型效率、成本或 token 使用，且仓库存在请求用量日志、账单或 usage 字段时。

## Discriminator
日志能给出 tokens_in/tokens_out、缓存命中、每轮增长或调用分布，足以判断成本主要在 prefill、decode、schema、轮次还是辅助任务；若没有这些观测则不适用。

## Short path
- 聚合 usage 日志，计算输入/输出占比、缓存命中、每轮增长和长尾调用
- 按主导成本项定位现有机制是否已覆盖（缓存、schema、压缩、路由、计量）
- 只针对未覆盖且可验证的缺口提出最小改动
- 用现有 A/B 或日志指标验证 token 与完成率/行为漂移

## Stop conditions
- 已确定成本主导项，并给出与主导项匹配的最小改动和验证指标
- 缺少用量数据且无法可靠估计成本分布时停止，不提出泛化优化
- 改动会破坏授权、安全或任务完成率且无验证路径时停止

## Verification
- 对比改动前后 tokens_in、tokens_out、uncached_prompt_tokens、cache_read 等指标
- 同时检查任务完成率、失败数、行为不变量是否漂移
- 确认优化针对的是实测主导成本项而非假设瓶颈

## Counterexamples
- 没有请求日志或 usage 字段，无法判断成本主导项
- 成本主要在解码或输出质量敏感，限制输出可能损害结果
- 已有强约束（安全、授权、合规）优先于成本优化，不能先改模型路由或 schema
