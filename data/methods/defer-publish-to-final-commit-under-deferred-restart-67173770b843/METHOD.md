---
method_id: defer-publish-to-final-commit-under-deferred-restart-67173770b843
name: defer-publish-to-final-commit-under-deferred-restart
description: 任务同时要求部署与继续改代码时，restart 受理回执的 deferred_effect（本轮 run 结束才生效、pending=true）意味着 run 内先后不影响生效时刻，而 desired generation 会被本 run 内任何后续提交的 publish 取代：开头执行的 publish+restart 周期必然空转，还容易制造『已部署』错觉。正确顺序是把部署批到最后一次提交之后单次 publish+restart，受理即停、下轮查终态；早 publish 仅在需要崩溃对冲或后续步骤依赖新代码运行态时正当，且须写明其将被取代。
aliases: 先部署还是先改完代码, 改代码和上线的先后顺序, 部署做早了白做一遍, 任务清单第一项是部署后面还要提交, 换代被后面的提交顶掉, 会话结束才重启部署排最后
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bc422278-b7a4-4c97-9380-4dc56a6da24f:8900:3de30c9a81913afab898
evidence_refs: learning:learn:18affdd6b2f2
created_at: 2026-11-02T17:04:14.594104+08:00
updated_at: 2026-11-02T17:04:14.594104+08:00
---
## Trigger
一个 run 的任务清单同时包含『部署/更新生效』与『本 run 还计划改代码并提交』（用户常把部署排在第 1 项），且 restart 受理回执出现 deferred_effect.condition=requester_run_end、pending=true

## Discriminator
restart 受理回执的 deferred_effect 字段：生效时刻=本轮 run 结束、期间 status 仍读旧 generation，与 run 内动作先后无关；叠加『本 run 仍有计划提交』这一任务书事实，即可在第一次 restart 受理时判定中途 publish 的 generation 必被后续提交取代，无需任何事后知识

## Short path
- 开局 status 只记录 live/desired 差距与 restart_required，不立即 publish；先解决未知量：本 run 是否还有计划提交（任务书已写明有）
- 先完成全部代码项：实现、canonical 门禁、commit、push
- 最后一次提交后单次 publish（git_head=final HEAD）并受理 restart
- 受理回执即停：deferred 生效，下一轮用 action_id 查终态；全程不把任何中途 generation 的受理回执当部署完成证据

## Stop conditions
- 最终 publish 回执的 git_head == 本 run 最后一次提交且 restart 已受理（或显式声明留待后续 run 生效）
- 若确需早 publish 作崩溃对冲：已在完成声明中写明该 generation 将被后续提交取代、不得作为部署完成证据

## Verification
- 最终 publish 回执的 git_head/generation 与 git log HEAD 一致
- 本 run 未出现第二次 publish（除非留痕的对冲性早发）
- 完成声明未引用被取代 generation 的 restart 受理作为『已部署』依据

## Counterexamples
- run 内后续步骤依赖新代码的运行态行为（如实测新护栏的线上回执）→ 必须早 publish 并安排会话结束后的核验或定时唤醒，不能批到最后
- 纯部署 run、本 run 无后续提交 → 早发晚发等价，早发还有崩溃对冲价值，无需批处理
- run 中途崩溃风险高且用户希望已提交部分尽快上线 → 早 publish 是正当对冲而非空转
