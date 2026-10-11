---
method_id: usage-audit-via-ledger-coverage-then-routing-config-f9d00d66f8cb
name: usage-audit-via-ledger-coverage-then-routing-config
description: 用户问某组件/Bot 的 token/费用用量或'为什么这么省/贵'时，先找该组件的结构化账本（usage db/账单表），不读 raw 会话记录。用 totals+kind 分布判定账本覆盖面：若调用数远小于实际活动且 kind 单一，说明这是子系统账单，其余成本去向由路由/覆盖配置决定（摘要走订阅、模型档位、裁剪策略），直接读 patch/override 层求证，并交叉核对配置声明与记录实际值。回答按账本口径给数字，如实声明账本盲区。避免 runtime/ps/无关目录的泛侦查和会命中 node_modules 噪声的宽 grep。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:136b8530-addf-4ead-941f-0a53520c54d8:364:2cb2325f9236599910f9
evidence_refs: learning:learn:345409402028
created_at: 2026-10-11T20:30:49.337148+08:00
updated_at: 2026-10-11T20:30:49.337148+08:00
---
## Trigger
用户提出关于某组件/Bot 的 token/费用消耗或'为什么这么省/贵'类问题，需要对成本给出有据解释；系统存在组件数据目录或可能的用量账本。

## Discriminator
两条当时可见事实：(1) 最初的失败回执本身已给出会话根目录约定（~/.dsh/sessions/<workspace-slug>/），一次 ls 即可同时确认 workspace 清单与组件数据目录，无需再做 runtime status、ps、storages 等泛侦查；(2) 账本 totals/kinds 回执显示仅 11 次调用跨 43 分钟、kind 全为 memory——调用数远小于实际活动量且类型单一，证明该账本只是记忆子系统的账，主对话成本必然由配置路由到别处，答案应在路由/覆盖配置里而非继续挖账本或压缩的会话日志。

## Short path
- 从失败/引用回执中的路径约定出发做一次 ls，同时确认 workspace 清单与组件数据目录（bot/），确定'这个BOT'的真实主体
- 在组件数据目录中直接找结构化账本（usage*.sqlite 等），跳过 raw transcripts、runtime status、ps、无关 storages
- 对账本做 totals 与 per-kind 两次查询；若 kind 单一且次数远小于活动量 → 判定为子系统账单，停止从账本或会话日志挖主对话成本
- 直接读该组件的覆盖/路由配置（profile patch/override 层），求证未入账成本中心的去向：summarization provider、模型档位、pruning 阈值
- 按账本口径作答，交叉核对配置声明 vs 记录实际值（如 reasoningEffort 声明 max 实记 high），如实声明账本盲区后停止

## Stop conditions
- 已从账本取得全部记录调用口径（n/input/cache_read/output/单价），且配置已解释其余成本中心去向
- 账本 kinds 覆盖全部调用类型且次数与活动量一致 → 这是全量账单，直接按账本作答，无需追路由配置

## Verification
- 最终数字与账本查询回执逐项一致（11 次调用、input 11350 / cache_read 4992 / output 232）
- 每个'省 token'机制都能在配置或账本中指出具体证据行（patch 的 summarizationProvider/glm-5.3、tool-result-pruner thresholdChars、flash 档模型）
- 对账本不含的数据面（主对话 usage 行为 0）显式声明'拿不到'，不混入结论或估算

## Counterexamples
- 账本即全量账单（kinds 覆盖全部调用类型、次数与活动一致）时，直接计算即可，追路由配置是多余动作
- 不存在结构化账本且用户只要粗估时，用配置单价×调用频次直接估算，不做账本考古
- 问题不是成本/用量而是行为异常或 bug 时，账本覆盖判断不适用，应走 root-cause 类流程
