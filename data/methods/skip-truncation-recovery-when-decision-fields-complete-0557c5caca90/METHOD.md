---
method_id: skip-truncation-recovery-when-decision-fields-complete-0557c5caca90
name: skip-truncation-recovery-when-decision-fields-complete
description: 用户给出一次性祈使指令（如『X 也要重启』）时，唯一待解未知量是『是否存在准入屏障/能否执行』，不是『回执数据全貌』。若 status 回执的可见部分已完整呈现决策字段（如 admission_barriers=[]），而截断仅发生在重复型审计噪音子结构（generation_lag 历史列表）内部，恢复截断尾巴不可能改变动作选择——跳过证据恢复直接执行。对控制面工具的首次变更调用，先读一次 get_tool_schema（或按参数失败回指点名的缺失字段一次性补全），再受理→轮询终态→凭 verify 证据收口。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e729d08f-6ec8-459b-b3be-a3eb65be8025:1686:eaa69213da507b5467ea
evidence_refs: learning:learn:e8e579e31eb6
created_at: 2026-10-13T22:50:39.644441+08:00
updated_at: 2026-10-13T22:50:39.644441+08:00
---
## Trigger
祈使式控制指令（重启/发布/切换某目标）+ 前置 status/审计回执被截断，且截断点位于辅助性噪音子结构内，而非决策字段本身

## Discriminator
截断位置与决策字段完整性的关系：决策相关字段（admission_barriers 等）是否已在可见部分完整出现且为空；截断是否只切断了同构重复列表（审计 lag 记录）的后半段。若决策字段完整、无屏障，尾部内容属不可行动噪音，恢复它不改变任何分支

## Short path
- 识别指令为祈使句：待解未知量只有『有无准入屏障』，不是审计数据全貌
- 读 status 回执时只看决策字段：admission_barriers 完整且为空、截断仅在审计尾巴 → 不做截断恢复调用，直接进入执行
- 控制面工具首次变更调用前读一次 get_tool_schema（若已失败则按回执点名的 missing 字段一次性补全），避免参数契约失败重试
- 提交动作拿 action_id，牢记受理≠完成
- 轮询 status(action_id=...) 至终态，要求 verify=confirmed_ok 且 generation/git_head 匹配 desired
- 汇报终态证据，附相邻目标状态一句话供用户决策

## Stop conditions
- status(action_id) 返回 succeeded 且 verify_evidence 确认目标进程存活、head/generation 与 desired deployment 一致
- 或返回 failed 终态 → 转入 verify_acknowledge/release 屏障处理，不重复提交同一动作
- 决策字段在可见部分已完整且无屏障时，不再为审计噪音尾巴发起任何恢复读取

## Verification
- 终态回执含 verify=confirmed_ok + 目标 pid + git_head，三者与 desired deployment 一致
- 复盘确认：为截断尾巴付出的恢复调用没有改变任何决策（若改变了，说明截断点其实在决策字段内，本方法误用）

## Counterexamples
- 截断恰好切掉决策字段本身（如 admission_barriers 被截半、屏障/override 信息在尾部）→ 必须先恢复完整再决策
- 用户的询问对象就是被截断的数据（『现在哪些目标在 lag？』）→ 恢复尾巴就是任务本体，不是噪音
- 变更调用非幂等且参数失败有副作用 → 不可先试错再按回执修正，必须先读 schema；反之若参数校验在执行前拒绝且无副作用，试错一次与先读 schema 成本相当，本条不适用
