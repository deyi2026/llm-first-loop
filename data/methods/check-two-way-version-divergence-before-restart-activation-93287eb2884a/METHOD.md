---
method_id: check-two-way-version-divergence-before-restart-activation-93287eb2884a
name: check-two-way-version-divergence-before-restart-activation
description: 长驻服务上次重启失败、线上长期跑旧版本（快照已给出 desired≠live 且待重启激活）时，『重启上新版本』不是无害动作：若两版是分叉历史（live 上有 desired 没有的提交），直接重启等于静默回滚掉线上独有修复。下发重启前，先用一次双向 commit 祖先检查把『重启会不会丢改动』变成二值事实：live 不是 desired 的祖先（反向 log 非空）即分叉，先合流+回归再重启；live 是严格祖先才可直接重启。只看单方向 diff/log 会漏掉 live 独有提交，是把分叉误判成普通滞后的常见原因。
aliases: 重启会不会把线上已修好的东西冲掉, 先合并再重启还是直接重启, 线上和要发的版本各走各的怎么办, 重启前确认线上没有独享提交, 直接重启丢线上修复
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:740daef3-4e29-412a-83b6-9f8f36ef85a8:16:4829b34e852ea4f5f8d2
evidence_refs: learning:learn:a4f080422c45
created_at: 2026-10-26T16:10:06.730699+08:00
updated_at: 2026-10-26T16:10:06.730699+08:00
---
## Trigger
长驻服务存在待执行的重启激活（restart_required/pending），且已观察到线上运行版本≠desired 版本、上次重启失败或长期未激活，线上在旧版本上独立运行过一段时间

## Discriminator
版本身份是一对可比的 commit 标识（live≠desired 已在手）：一次双向祖先检查（git merge-base --is-ancestor live desired，或两个方向各自 log 计数）即可判定重启是否等价于回滚；早前只看单方向（live..desired）得出的『两版之间无相关改动』结论不覆盖 live 独有提交

## Short path
- 从 runtime 快照/服务控制回执取 live 与 desired 版本标识及上次重启结果，确认 live≠desired 且激活曾失败
- 重启前先跑双向祖先检查：live 是 desired 祖先 → 无分叉，重启即纯激活，走常规验证
- live 非祖先 → 列出 git log desired..live 的 live 独有提交，逐条判定是否需保留
- 需保留 → 先分支合流/合并（冲突按两侧语义取舍）并跑回归，把合流产物作为新 desired 再发布重启
- 确认丢弃（有意回滚）→ 直接重启，但向用户写明回滚了哪些 live 独有改动

## Stop conditions
- 双向检查确认 live 为 desired 的严格祖先：直接重启并按常规端点验证激活
- live 独有提交已逐条裁决，且（合流+回归通过）或（明确记录的有意回滚清单）成立
- 部署无 commit 身份可比（配置/产物直发）：改用生效配置链或产物清单核对，本方法不适用

## Verification
- git merge-base --is-ancestor <live> <desired> 的退出码，加上 git log --oneline <desired>..<live> 的条数
- 合流后抽查 live 独有修复的关键文件/测试仍然存在，回归绿之后才允许重启
- 重启后线上版本==新 desired，且至少一项原 live 独有修复的行为可观察生效

## Counterexamples
- live 只是落后（严格祖先），属正常发布滞后：直接重启即可，双向审阅纯属浪费
- live 独有提交是被明确废弃的坏改动（有意回滚部署）：直接重启正是目的，只需记录回滚清单而非合流
- 激活走配置重载而非代码版本：commit 祖先与激活内容无关，应改查配置生效链端点
- live 独有提交只是从未对外生效的本地实验 WIP：先向 owner 确认意图，盲目合流反而引入风险
