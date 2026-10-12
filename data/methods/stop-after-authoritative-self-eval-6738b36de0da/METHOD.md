---
method_id: stop-after-authoritative-self-eval-6738b36de0da
name: stop-after-authoritative-self-eval
description: 当用户只要求自我评估时，把首个权威评估结果视为足够证据：直接汇报指标、样本量、来源、落盘状态，并明确 N/A 或小样本限制。不要为了补齐指标而执行无关工具调用或重复评估；只有用户明确要求根因、偏差定位、提交演进，或首次结果失败/缺少必需指标时，才做定向补充。
status: candidate
source_model: cognilocal/qwen3.8-flash-next
source_episode_refs: episode:f7469d7b-59d1-494b-955f-c9153320141e:4:ca5ec859c0735c5c2898
evidence_refs: learning:learn:bd081d5834e4
created_at: 2026-09-20T17:39:13.157518+00:00
updated_at: 2026-09-20T17:39:13.157518+00:00
---
## Trigger
用户要求做自我评估/指标快照，且评估工具已返回指标、样本量、来源或 N/A 状态。

## Discriminator
首个评估结果已包含用户请求的指标集合（含 N/A 和样本量）并显示评估已落盘；用户没有要求定位偏差、提交演进或重新采样。

## Short path
- 调用一次自我评估工具
- 检查返回是否覆盖用户请求的指标、样本量、来源和落盘状态
- 直接汇报指标，并把 N/A、小样本、口径限制如实说明
- 若用户未要求进一步调查，停止；如需补充，先询问或按明确请求定向调用

## Stop conditions
- 权威评估结果已覆盖用户请求的指标
- 用户未要求根因分析、偏差定位、提交演进或扩大样本
- 额外调用只会制造无关样本或重复评估，而非回答当前请求

## Verification
- 最终答案引用评估结果中的指标、样本量和来源
- 对 N/A 或小样本指标明确说明限制
- 没有未经请求的架构/日志/重复评估调用

## Counterexamples
- 用户明确要求定位诚实率偏差或提交演进建议
- 首次评估失败、缺少必需指标或指标互相矛盾
- 用户要求扩大样本量或重新评估特定工具效率
