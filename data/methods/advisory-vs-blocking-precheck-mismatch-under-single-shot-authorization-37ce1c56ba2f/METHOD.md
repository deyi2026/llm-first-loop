---
method_id: advisory-vs-blocking-precheck-mismatch-under-single-shot-authorization-37ce1c56ba2f
name: advisory-vs-blocking-precheck-mismatch-under-single-shot-authorization
description: 单次授权的变更类调用（update/restart/publish）前先做一次只读复核；当复核结果与用户陈述的前置状态矛盾时，先按授权文本自带的分支条款给矛盾分类再决定动作：身份/CAS类字段（expected_generation、git_head、admission_barriers 非空）不符=阻断性，立即停；运行时状态类字段（busy/idle）不符且授权已声明其处理语义（如 waiting_for_idle 不重试、由 worker 等锁释放）=告知性，照授权执行唯一一次调用，不等待、不追问、不重试；受理≠成功，回报真实 action_id 并逐字记录差异，授权外的验证调用留给请求方。该分类一步免除两类绕路：run 内等锁/轮询，以及针对非阻断矛盾的澄清往返。
aliases: 复核显示目标在忙但授权说空闲, 只许调一次但前置状态对不上, 执行前快照与用户陈述矛盾还继续吗, busy 和用户说的 idle 不一致要不要等锁, 单发变更调用前先决条件冲突裁决
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0a37a89a-ded5-4f58-8502-1934aeaf0919:65:b1191f175c8d6a824122
evidence_refs: learning:learn:b3001a11fa26
created_at: 2026-10-24T17:56:32.015574+08:00
updated_at: 2026-10-24T17:56:32.015574+08:00
---
## Trigger
用户/上位指令授权恰好一次变更类控制调用，指令同时内嵌用户外部观察到的前置运行时状态（如目标 confirmed_idle、barriers 为空）与逐分支预案（CAS drift→立即停；waiting_for_idle→不重试由 worker 等锁），而执行方即将取得的实时快照可能与用户陈述不一致

## Discriminator
矛盾字段在授权条款中的映射位置：落在停止条款或身份/CAS 参数（generation、git_head、barriers 非空）上=阻断性；落在已被系统语义吸收的状态字段（busy/idle，且授权明示 busy 路径处理方式）上=告知性。另一条时点信号：会话内更早快照已显示与用户陈述相反的状态（如 confirmed_busy），说明外部陈述可能过期，这本身就要求先复核而非直接执行

## Short path
- 发起唯一一次只读 status 复核；未知量=授权的 CAS 关键事实与目标状态当前是否仍如所述
- 回执截断时用锚点字符偏移水合只读裁决字段（目标 target 的 idle_state/barriers/generation），不宽枚举、不重读已见段落
- 把复核结果逐条映射到授权条款：身份类全符、状态类矛盾落在已声明的 busy 分支→判定矛盾为告知性、可执行
- 以授权与回执逐字参数执行唯一一次变更调用；busy 不等待、不重试、不追问
- 回报真实受理回执（action_id、desired generation、受理≠成功），逐字记录复核与用户陈述的差异；不再发任何验证调用

## Stop conditions
- 已取得变更调用真实受理回执并向用户报告差异与 action_id
- 复核出现身份类矛盾：expected_generation/git_head 与当前 desired 不符，或 admission_barriers 非空
- 变更回执命中授权声明的停止分支（如 CAS drift 拒绝）
- 授权文本未声明该矛盾分支的处理语义→停下询问，不得猜测系统行为

## Verification
- 受理回执的 generation/git_head/action_id 与授权参数逐字一致
- 最终答复中的差异描述与复核回执原文一致（状态字段原文引用，不转述软化）
- 确认全程只有一次变更调用、未触碰未授权 target、受理后无追加验证或重试调用

## Counterexamples
- 被矛盾的字段本身就是执行先决条件（授权写明『须 confirmed_idle 才执行』或 barriers 非空）→停止回报，不得借『系统会自己等』继续
- 授权没有声明 busy/waiting 分支语义→busy≠idle 是歧义而非告知性差异，先问再动
- 复核发现 expected_generation 与当前 desired 存在真实 drift→唯一一次调用必然被 CAS 拒绝，应停并报告而非消耗它
- 纯只读授权下任何状态矛盾只构成报告内容，不构成发起调用的理由
