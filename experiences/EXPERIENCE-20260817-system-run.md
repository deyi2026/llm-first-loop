---
title: 轮次耗尽注入的 system 消息破坏前缀缓存：run 后消费标记修复
scenario: DeepSeek 前缀缓存：达到 max_iterations（轮数上限）注入决策/终止 system 消息后，同会话后续请求缓存命中率骤降且持续（用户续发消息也 MISS）。排查耗尽路径注入消息是否破坏 system 前缀。
root_cause: "轮次耗尽注入的 [轮次决策请求]/[已达轮数上限] 是 role=system 消息但未纳入 _INJECTED_SYSTEM_PREFIXES（对比 [预算预警]/[轮数预警] 有 skip）→ 注入后被 history._append_or_merge 合并进请求 system 区 → 请求前缀从注入点分叉 → 之后所有 run 持续 MISS；[已达轮数上限] 含动态轨迹每次耗尽不同，多次耗尽多次分叉。engine 调用 skip_injected_system=not provider_inject_notices，默认 provider 下为 True，但这两条消息不匹配 skip 判定。"
solution: "run 收尾把耗尽注入 system 消息标记 metadata.consumed=True（run 内 AI 决策轮仍可见，决策语义保留）；history.build_history_messages 两条构建路径（精简 total_chars<=max_chars / 超长）都加\"skip_injected_system 且 consumed 的 system 消息跳过\"——下个 run 不进请求 system 区，前缀恢复稳定。注意 history 有两条构建路径，修改需两处同步（首次只改超长路径未生效）。"
evidence: "commit a9c0069；用户观察\"超过最大限额不处理时缓存命中下降\"；history.py 两路径（452 精简/563 超长）差异导致首次修复放错路径，32 passed 验证"
tags: [缓存命中, 前缀分叉, 轮次耗尽, system注入, MISS收敛]
source: {}
status: archived
record_kind: experience
verification_state: legacy_unclassified
created_at: "2026-08-17T14:52:30.412088+08:00"
updated_at: "2026-09-11T19:33:32.133104+08:00"
superseded_by: "runtime:prompt-authority-p1c"
last_verified_at: "2026-09-11T19:33:32.133104+08:00"
---