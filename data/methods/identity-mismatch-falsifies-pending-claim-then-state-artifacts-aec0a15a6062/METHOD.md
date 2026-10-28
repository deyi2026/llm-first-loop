---
method_id: identity-mismatch-falsifies-pending-claim-then-state-artifacts-aec0a15a6062
name: identity-mismatch-falsifies-pending-claim-then-state-artifacts
description: 核验交接报告声称的『异步动作仍 pending（如 waiting_for_requester_exit、新代码尚未生效）』时，先跑报告自荐的状态检查并只提取当前身份字段（generation/git_head/pid），与报告给的预期身份比对：不一致即当场证伪 pending 前提，立即转读小型权威状态工件——desired-state 部署记录、各 target runtime manifest、按 action_id 命名的动作台账——并按 mtime 取最新动作重建实际序列。不要对噪声主导的截断回执重复翻页同一区间，也不要在当前状态未定前先取『如何处置等待』类知识卡。时间序逻辑：权威身份已越过动作目标代，该动作不可能仍在等待。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:7f2be023-db54-4395-9854-c784b5295062:0:a73a12960e80d62002a5
evidence_refs: learning:learn:c8b1d511d1b8
created_at: 2026-10-20T10:42:01.901393+08:00
updated_at: 2026-10-20T10:42:01.901393+08:00
---
## Trigger
交接/完成报告声称某受管异步动作（重启、部署、回滚）仍处 pending，并附带预期身份（generation/git_head）与 durable action_id，要求核验当前状态；控制面 status 回执被大量累积审计条目（如数百条 generation_lag 历史）挤占而截断

## Discriminator
status 回执虽截断，但已暴露当前身份字段；观察身份（更高 generation、不同 git_head）与报告预期身份不一致，且该不一致在取任何后续动作前已可见——pending 声称与已移动的权威身份在时间序上互斥，这一条事实即足以把『如何处置等待』的问题换成『实际发生了什么』

## Short path
- 跑报告自荐的状态检查，只提取当前身份字段（generation/git_head/pid），把累积审计噪声当历史忽略
- 身份比对：观察身份==预期身份 ⇒ 接受报告结论并停止；不一致 ⇒ pending 前提存疑，进入下一步
- 不重新翻页同一截断区间（同 offset 再读是零信息）；直接读小型权威状态文件：desired-state 部署记录 + 各 target runtime manifest，确认 desired 与 live 身份是否一致
- 读按 action_id 命名的 per-action 台账取该动作真实终态（status/updated_at/detail），并按 mtime 列同目录最新若干条，重建实际发生的动作序列（失败、回滚、重试）
- 当 desired=live=台账结果互相印证、前提证实或证伪可交付即停；根因（如就绪判定预算）仅在用户需要时再查

## Stop conditions
- 部署记录、runtime manifest、动作台账三者一致给出当前身份与动作终态，pending 前提已有裁决
- 回复中已显式更正报告的过时声称，且裁决不依赖噪声回执作为证据

## Verification
- 最终裁决逐条引用权威工件字段：部署记录 generation/git_head、manifest pid/started_at、action 记录 status/updated_at/detail
- 确认未把累积审计条目（generation_lag 历史堆积）当作当前状态；确认身份字段来自 versioned 权威来源而非可能过期的缓存——缓存疑点只触发进一步向专用记录求证

## Counterexamples
- status 回执短小干净且身份字段与预期一致 ⇒ 直接接受报告结论，无需转向状态工件或台账
- 系统只在聚合状态通道保存权威状态、无专用小文件 ⇒ 对该通道做键控过滤/翻页是唯一路径，此法不适用
- 回执中的身份字段可能缓存过期 ⇒ 不一致只是转向验证的信号，须以专用记录确认后才能下结论，不能单凭截断回执判死
- 动作确以 requester 会话退出为推进门禁且身份未移动 ⇒ 前提成立，应按 session-exit 卡注册验证唤醒后让行，不必翻台账找矛盾
