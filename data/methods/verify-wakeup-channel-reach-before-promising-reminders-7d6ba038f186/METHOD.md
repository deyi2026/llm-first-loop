---
method_id: verify-wakeup-channel-reach-before-promising-reminders-7d6ba038f186
name: verify-wakeup-channel-reach-before-promising-reminders
description: 向用户承诺"到点提醒/自动续跑"之前，先读调度工具 Schema 的交付语义并核对当前 run 语境：默认到点仅通知（不推送）、wake=true 仅限当前真实用户顶层 run 签发一次性同会话续跑、后台续跑不能递归再唤醒，observed_only 类投递结果表示只落在会话观察层。若通道在当前语境无法到达用户，就不要承诺提醒；改用耐久产物（落盘输出+EXIT 码）加"用户到点 ping、我先查落盘 EXIT 再汇报"的替代约定。只有确认语境可签发 wake 或有推送成功证据时才承诺到点提醒。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:64924088-0141-4a3a-87ee-81f09678620d:637:02fa26c6df96aa7a7d24
evidence_refs: learning:learn:3f8dd77e2b69
created_at: 2026-10-10T13:46:47.023553+08:00
updated_at: 2026-10-10T13:46:47.023553+08:00
---
## Trigger
即将注册定时提醒/闹钟并向用户承诺"到点会提醒或自动续跑"，尤其当前 run 是后台任务或非真人触发的顶层 run；或复盘出现"到点未提醒"的用户纠正。

## Discriminator
调度工具 Schema 自述的能力边界（默认到点仅通知、wake 仅真人顶层 run 可签发、后台续跑不能递归再唤醒、失败时区分 committed/uncertain）与既有提醒的投递结果类（observed_only=未推送到用户也未续跑）在设置/承诺之前即可读取——这些事实足以把"这条通道在当前语境能否到达用户"从很多猜测缩成一次判定。

## Short path
- 承诺提醒前先读调度工具 Schema 的交付/失败语义；未知量：当前 run 语境下该通道能否真正到达用户
- 用 run 语境（真人顶层 vs 后台）加历史投递结果类对通道能力分类；未知量：能否推送或续跑
- 若通道只到会话观察层（如 observed_only）→ 不承诺提醒，改为耐久产物约定：输出落盘+EXIT 码，用户到点 ping 后先查落盘 EXIT 再汇报
- 仅当确认当前是可签发 wake 的真人顶层 run 或有推送成功证据时，才注册并承诺到点提醒
- 承诺措辞以可核验动作表述（查什么文件、看什么标志），而非空泛的"我会提醒你"

## Stop conditions
- 已核实通道在当前 run 语境可到达用户（可签发 wake 或有推送成功回执），可正常承诺
- 通道不可达已确认，且替代约定（落盘+EXIT+用户 ping）已建立并告知用户

## Verification
- 承诺前复读 Schema 交付/失败语义原文，确认与当前 run 语境（顶层/后台）匹配
- 查询既有提醒的投递结果类（observed_only/pushed/续跑是否成功）作为通道能力的机械证据
- 替代约定中写明到点核验动作与完成判据，保证唤醒/被 ping 的一方知道查什么

## Counterexamples
- 当前就是真人触发的顶层交互 run 且历史投递成功推送/续跑——此时正常注册提醒即可，不必降级为 ping 约定
- 等待时长远短于会话寿命、通知在同一会话内本就可见——简单通知已足够，不需耐久产物机制
- 环境存在已验证的其他推送通道（别的能力面）——按其自身交付语义使用，不套"一律不可靠"的结论
