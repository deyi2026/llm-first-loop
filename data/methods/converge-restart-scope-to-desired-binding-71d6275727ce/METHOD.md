---
method_id: converge-restart-scope-to-desired-binding-71d6275727ce
name: converge-restart-scope-to-desired-binding
description: 部署新 generation 后决定重启/收敛范围时，范围必须匹配 desired 绑定的覆盖面（部署级 manifest/git_head 身份），而不是按本次 diff 的运行时影响面自行收窄。控制器的逐目标差距标志（restart_required / live_git_head_mismatch）就是权威范围计算：对每个 flagged 目标核对 idle/busy 门后逐个执行，并以 action 终态（succeeded + verify head==desired）而非受理回执作为完成判据。本集教训：按'改动只影响 web 检索路径'只重启了 web，feishu/learning 停留旧 head，被用户抓出后返工补齐，另付一次参数名试错与多段翻页快照的成本。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:152a76d5-3fea-40cf-8a6d-00de8ac369c2:1035:044b0401a0c985ed5111
evidence_refs: learning:learn:d5ce84601448
created_at: 2026-09-24T12:12:08.529448+00:00
updated_at: 2026-09-24T12:12:08.529448+00:00
---
## Trigger
发布/部署新的 generation 或 desired 绑定之后，需要决定哪些服务/目标执行重启或收敛动作，且绑定是部署级（多个目标共享同一 manifest/git_head/generation 身份）

## Discriminator
status 回执已按目标暴露 live_git_head_mismatch / restart_required 等逐目标差距标志，且 desired 部署身份（git_head/generation）绑定覆盖全部目标——权威 gap 计算当时已存在，无需按 diff 影响面重新推导范围；受理回执也明确写着'受理≠完成，终态是异步事实'

## Short path
- 发布后读 status 的 per-target 差距标志（restart_required / live_git_head_mismatch），据此直接列出待收敛目标集合，不做 diff 影响面推理；翻页读快照时优先定位决策字段而非消化 generation_lag 之类背景历史
- 对每个 flagged 目标核对 idle/busy 门：confirmed_idle 立即执行，confirmed_busy 进两阶段等待，不放弃不强推
- 按回执确认的参数名（target 而非 restart_target）逐个发起 restart，收到 accepted/action_id 后不宣布完成
- 轮询 service_control(action=status, action_id=...) 至终态 succeeded/failed；waiting_for_idle 视为共享锁短暂排队，等一个短窗口后复查而非重发新动作
- 以 verify_evidence 中新 pid、head==desired，且 status 差距标志清零作为闭合；全部 flagged 目标闭合即停

## Stop conditions
- 所有 flagged 目标的 action 终态为 succeeded 且 verify_evidence 显示 head 与 desired git_head 一致
- 复查 status：restart_required / live_git_head_mismatch 全部清零，identity generation 一致
- 目标 confirmed_busy（active run locks）时转入两阶段等待，不得视为已失败也不得强行重启

## Verification
- action status=succeeded 且 detail/verify_evidence 同时给出新 pid 与 git_head==desired
- 复查一次 status 确认 per-target restart_required 清零，由控制器自身验证闭合
- 未查询到终态（succeeded/failed）前不得在回复中把受理/运行中动作表述为已完成

## Counterexamples
- 部署系统支持按服务选择性绑定（desired 只覆盖单一目标）时，范围跟随绑定即可，重启未绑定目标不必要甚至有害
- 控制器对 worker 已自动 rolling 收敛（同源成为常态）时无需手动重启
- hot-reload/解释器级生效的系统里 head mismatch 不等价于行为陈旧，重启判据需另行验证
- 异步受理回执（accepted/running/waiting_for_idle）不得当作完成证据——此点与既有 fresh-read-authoritative-record 方法互补而非重复：本卡核心是范围决策（绑定面 vs diff 面），不只是终局断言前重读
