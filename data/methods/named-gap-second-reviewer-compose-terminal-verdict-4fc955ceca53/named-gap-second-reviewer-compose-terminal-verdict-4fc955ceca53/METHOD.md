---
method_id: named-gap-second-reviewer-compose-terminal-verdict-4fc955ceca53
name: named-gap-second-reviewer-compose-terminal-verdict
description: 全新独立只读 Reviewer 返回终态 BLOCK，但裁决文本明确『已核层全过＋唯一缺口=具名文件未取证』、child 已 completed（预算耗尽）时：不要重跑全量审查，也不要续话已收口的 reviewer（租约已失效必拒，且续话破坏『全新独立』与终态裁决严肃性）。把缺口本身写成新任务书，spawn 第二个全新独立只读 reviewer 定向只补缺失证据，并要求复核冻结 SHA/tree 与首审一致；按机械条件合成终判：缺口恰被裁决＋无新 P0/P1＋同一冻结 SHA→终态 PASS；有新 P0/P1 或漂移→FAIL/HOLD。区别于子代理中途死亡后的重分段：这里子代理正常完成，裁决文本自身已含分诊信息。
aliases: reviewer说证据不够只差一个文件没读, 审查BLOCK后怎么补证, 两次独立审查结论怎么合并, 子代理轮次用完判了BLOCK, 续话旧reviewer被租约拒绝
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:b81d97a3-af1f-463a-9f1f-ac9cf885c32b:456:92b50a80682ba19b5b50
evidence_refs: learning:learn:c4de481e9191
created_at: 2026-11-17T08:16:15.180347+08:00
updated_at: 2026-11-17T08:16:15.180347+08:00
---
## Trigger
独立审查任务收到子 reviewer 的终态裁决 BLOCK，裁决文本显式区分『已核层全过』与『唯一具名证据缺口』，且 child_outcome=completed、轮次/工具预算已耗尽

## Discriminator
当时回执里已有的两条事实：①裁决文本自带结构——代码层 P0/P1=0 已核＋缺口精确具名（如『测试文件未取证，不足以整体判 PASS』）；②rounds/tools 耗尽、child_state=completed。二者合计说明缺的不是审查结论而是单一未取证文件，用一个更窄的新审查即可闭合，无需全量重审或复活旧会话

## Short path
- 解析 BLOCK 裁决文本，列出已核层结论与具名缺口（哪个文件/证据未取证）
- 不续话、不重试已 completed 的 child，也不重跑全量审查
- 以缺口为唯一范围 spawn 新的全新独立只读 reviewer：任务书含冻结 SHA/路径、零写入、只补缺口证据
- 要求第二审复核冻结 HEAD/tree 与 changed_paths 与首审一致，防止候选漂移导致不可合成
- 机械合成终判：缺口恰被裁决＋无新 P0/P1＋同一冻结 SHA→PASS；否则 FAIL/HOLD
- checkpoint 记录两个 child_id、各自裁决与合成依据，再报告

## Stop conditions
- 第二审已覆盖具名缺口且冻结 SHA 与首审一致→合成完成，停止发现
- 第二审发现新 P0/P1 或冻结漂移→判 FAIL/HOLD 并停止，不追加第三轮审查
- 具名缺口被证明无法独立取证（权限/环境硬阻）→如实上报用户，不换通道反复重试

## Verification
- 两份裁决引用同一冻结 SHA/tree 与相同 changed_paths
- 首审已核层未被第二审发现推翻（无新 P0/P1）
- 第二审确为全新独立只读：新 child_id、未参与开发、零写入
- 合成结果如实记录两审各自 P0/P1/P2 与缺口关闭证据，不得只报最终 PASS

## Counterexamples
- BLOCK 原因是代码层 P0/P1 缺陷→回修复循环换 SHA 重审，不是补证审查
- 缺口弥散或无法具名（环境/权限导致大面积未核）→应全量重审而非定向复审
- child 仍在 running、尚未发终态裁决→用 agent_message steer 纠偏即可，无需新 reviewer
- 任务不要求独立裁决、父会话自己能低成本核实该证据→直接父会话核实，不必开新 child
