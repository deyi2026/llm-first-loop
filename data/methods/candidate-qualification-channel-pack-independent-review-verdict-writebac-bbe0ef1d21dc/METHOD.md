---
method_id: candidate-qualification-channel-pack-independent-review-verdict-writebac-bbe0ef1d21dc
name: candidate-qualification-channel-pack-independent-review-verdict-writeback
description: 库里堆着上千张 status=candidate 的方法卡、没有任何 usage 账本、也没有既定的定性通道时，别在会话里逐张空想『这卡有没有用』。正确顺序是：先核 store 侧写回执的真实规则（谁持有真实 episode ref、verdict/promotion 的合取、隐私闸），再用一个 repo-owned harness 把『读卡 + 生成自包含评审包（含 rubric、新鲜度/usage 事实、holdout 污染题面）』与『校验评审结论并产出应执行的 method_manage 调用』拆成两个阶段，评审包交给独立评审子代理出结论，父会话持真实 episode ref 落库并做 lifecycle 流转，最后用可核计数（qualified 卡数 / 有回执卡数 / usage 账本是否存在）复验通道闭合。harness 必须 proposal-only（永不写库），且写回执阶段对『verdict=mixed|insufficient + promotion=pass』这类自相矛盾组合一律拒。
aliases: candidate 卡批量分诊 通道, qualification 通道先建 harness, 独立评审子代理出 qualification 结论, 写回执要真实 episode ref, verdict 与 promotion 矛盾必拒, 静态棘轮先跑绿再冻结审查指纹
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:cab051cc-c0ca-4a09-b848-6d4a00ec0ffe:853:705e616bde3dc6bfc6d1
created_at: 2026-10-30T07:11:12.039281+08:00
updated_at: 2026-10-30T07:11:12.039281+08:00
---
## Trigger
知识库里有一大批 status=candidate 的方法卡待定性（无 usage 账本、无历史回执），需要先分诊再对少量相关卡出正式 qualification 结论；仓内没有现成的定性通道。

## Discriminator（当时已知即可判定）
- store 侧：写 qualification 回执需要**真实 episode ref**（模型自造 ref 被拒），而父会话在真实回合里才有 episode；子代理有 episode 但只应出结论。
- 卡侧：candidate 卡没有任何 usage 账本 → 『用得多不多』不可证；必须靠新鲜度/来源事实 + 独立评审判断。

## Short path（顺序即纪律）
1. 先核 store 侧真值（读代码，不靠先验）：谁写回执、episode ref 怎么解析、verdict/mechanism/task_benefit/promotion 的取值与合取、隐私闸在入库哪一步。
2. 建 repo-owned harness，分两阶段：**pack**（读卡 → 产出自包含评审包：卡正文 + 新鲜度/usage 事实 + 评审 rubric + holdout 污染题面 + 独立评审指令书）与 **verdict**（解析评审结论 → 机械校验 → 产出应执行的 method_manage 调用文本）。harness 永不写库、不写 data/methods/、输出只落 /tmp。
3. 独立评审子代理出结论（执行方模型与评审方模型分离；评审方未参与产物产出）。pack 里放 rubric 与冲突题面，避免评审方被污染。
4. 父会话持真实 episode ref 落库 + lifecycle 流转（qualified / hold / activate）。
5. 复验通道闭合：可核计数（qualified 卡数、有回执卡数、usage 账本是否存在）+ harness 自身单测 + 独立复跑。

## 硬规则（实测确认）
- proposal-only：harness 只产出应执行的调用文本，写库由持有真人回合的父会话做。
- verdict 与 promotion 矛盾组合（verdict=mixed|insufficient 且 promotion=pass）必拒。
- holdout 污染题面（评审材料里混入不该出现的题面切片）必拦。
- 落库字段不得夹带隐私/密钥样式；入库前扫描。
- 卡片正文不得被 harness 改写。

## Pitfalls（本轮真实踩到）
- **静态棘轮先跑绿再冻结审查指纹**：代码闸的独立审查 PASS 之后，全量测试才暴露新文件的 ruff F401，被静态诊断棘轮门禁 DENY → 修复改指纹 → 原 PASS 回执失效 → 必须重新窄复审并重跑全量。便宜确定性的静态段（ruff / check_static_diagnostics）应先在候选树上跑绿，再冻结指纹送审。
- 评审回执必须落盘（含审查人 id、verdict、P0/P1/P2、采纳/拒绝清单及理由、被审产物 SHA），否则不得声称『已审查通过』。
- 全库规模（上千卡）不适合单轮全评：按业务相关性选高频卡先做，剩余批量归档/hold 单独排期。

## Evidence
- 产物：scripts/qualification/method_candidate_qualification.py + tests/test_method_candidate_qualification_harness.py（22 单测）；本轮 25 张 candidate 卡走通 pack → 独立评审 → verdict → 落库 → lifecycle 全链。
