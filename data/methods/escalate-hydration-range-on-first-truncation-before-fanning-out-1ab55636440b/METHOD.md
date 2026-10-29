---
method_id: escalate-hydration-range-on-first-truncation-before-fanning-out-1ab55636440b
name: escalate-hydration-range-on-first-truncation-before-fanning-out
description: 跨会话靠水合 evidence 恢复现场时，水合回执的 range 元数据（applied_limit/count/complete/next_start）是分页契约而非装饰：第一条回执若显示 count==applied_limit 且 complete:false，说明默认页宽只是预览。此时应立即对同一 ref 提高上限或按 next_start 续页取全文，再水合其余 ref；带着已知不足的同一默认上限去逐条水合更多 ref，只会攒一堆截断片段、随后还得整体重取。
aliases: 证据水合只拿到一小段, 回执默认200字符不够看, 先补齐全文再水合下一条, 截断就放大limit重取同一条, 跨会话恢复别拿预览当全文, 翻页参数给多少合适
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:25e48ad9-7d56-4793-9a70-4c63d9502373:113:56e1819a53434b65c521
evidence_refs: learning:learn:5a106b5a3c6e
created_at: 2026-10-28T22:50:13.449811+08:00
updated_at: 2026-10-28T22:50:13.449811+08:00
---
## Trigger
新会话/跨会话恢复（如 task_state 丢失、用户给极简续跑指令），需按 evidence ref 水合带分页 range 参数的多段回执（尤其 execute_command 现场探测输出）以重建上轮现场后再动手。

## Discriminator
首条水合回执的 range 元数据已显式声明截断：count==applied_limit（如 200）、complete:false、next_start 非空——即该页只是预览、blob 实长更大。此事实在任何后续水合动作之前已在手，足以把『逐条默认水合所有 ref』缩成『先对当前 ref 扩页取全』。

## Short path
- 水合最新一条 ref 时显式给足 limit（如 2000–4000 字符）；未知量=该现场探测到底输出了什么
- 若回执 complete:false：立即对同一 ref 提高上限或按 next_start 续页，直到 complete:true 或已覆盖所需锚点区间
- 用首条实际长度（本集为 467–1959 字符级）校准同类回执的典型体量，再并行水合其余 ref，limit 一次给足
- 全文齐后才执行建议/下结论；不把 200 字符预览片段当作回执全量证据使用

## Stop conditions
- 目标 ref 已 complete:true，或 next_start 之后的区间与当前未知量无关
- 只需辨认回执对应哪条命令/退出码时，命令行前缀预览已足够，停止扩页
- 所有待恢复事实均已从完整或明确锚定的区间取得

## Verification
- 重取后 range.complete==true，且同一 ref 不再出现第二次因 limit 不足的部分读取
- 进入执行/结论阶段前，所依据的每条回执内容均来自完整读取或显式锚定区间，而非默认页预览

## Counterexamples
- 只需确认某回执跑的是哪条命令：200 字符预览已含命令行头部，扩页纯属浪费
- blob 本身数百 KB 且只需一个锚点：盲目全额拉取会爆上下文，应按 next_start 定点续读而非整体放大 limit
- 水合工具无 range 参数、总是整段返回全文：没有截断契约可读，本方法不适用
- 首条回执本就 complete:true：默认上限已覆盖全文，无需校准或扩页
