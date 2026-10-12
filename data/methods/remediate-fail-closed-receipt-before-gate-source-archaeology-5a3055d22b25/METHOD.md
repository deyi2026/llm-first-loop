---
method_id: remediate-fail-closed-receipt-before-gate-source-archaeology-5a3055d22b25
name: remediate-fail-closed-receipt-before-gate-source-archaeology
description: fail-closed 门禁返回结构化 problems 回执时，回执本身就是权威判别器：错误词义已自含判定范围（如 'tracked worktree dirty' 说明 untracked 无关），且 problems 数组是枚举式的——未列出的问题（head/root mismatch）即不存在，desired 绑定其余部分仍有效。此时只针对已列问题、用已收集的本地证据（status/diff）做最小且幂等的修复，再用同一门禁命令重跑读新回执；不要在首次修复前去读门禁源码和脚本内部重新推导错误文本已说明的逻辑。共享可变状态（worktree/HEAD）可能被并发写者改变：动作必须 no-op 安全（如对已干净树 stash），行动后以新回执为准分叉——只有回执词义不明或修复后冒出新问题（如 git_head mismatch）时，才进入源码考古与 operator 指令组装分支。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8264c548-85f1-4132-ad60-06764dbeb232:761:8445a6739280ceca0e6e
evidence_refs: learning:learn:d4789b1e46c2
created_at: 2026-09-18T14:25:16.472606+00:00
updated_at: 2026-09-18T14:25:16.472606+00:00
---
## Trigger
fail-closed 预检/门禁返回结构化回执（problems 清单），问题项词义自含判定范围，修复所需本地证据可用一两条只读命令取得，且门禁本身可用廉价命令重复运行验证

## Discriminator
回执 problems 数组只含一项且为枚举式输出（若有 git_head/code_root 不匹配会一并列出）→ 单一障碍已完全定位、desired 绑定仍有效；错误文本自含范围（'tracked' worktree → untracked 文件不相关）；本地 status 显示唯一 tracked 脏文件的 diff 是连贯 WIP 修复 → 修复动作唯一确定：保留工作但移出当前代（stash/侧枝），不丢弃也不混入部署。三者同时成立时无需先读门禁源码。

## Short path
- 解析回执：确认唯一问题项及其自含范围（tracked-only），未知量=哪个文件脏、是否可丢弃
- git status --porcelain + git diff --cached 定位唯一 tracked 脏文件并判断其价值，未知量=如何不丢失地清除
- 执行幂等修复（stash 等，对已干净树为 no-op），未知量=门禁现在是否放行
- 用与门禁相同的最小 verify 命令重跑并读新回执：ok→执行原目标动作；出现新问题（如 git_head mismatch）→ 判定共享状态被并发写者改变，此时才读 gate/publish 源码并产出精确的 operator 命令
- 以最终回执 ok 且服务处于 desired generation 为准停止

## Stop conditions
- 新回执 problems 为空且目标动作（重启/部署）在 desired generation 上成功
- 回执语义无法由错误文本+本地状态确定，或修复后新回执出现词义不明的问题 → 停止自助修复，转入门禁源码/测试阅读分支
- 所需修复动作属于 operator 专属控制面（被权限拦截）→ 停止自助尝试，改为产出可精确复制的 operator 命令

## Verification
- 重跑同一门禁命令，确认 problems 为空而非猜测其已通过
- 修复动作前后各取一次 git status/HEAD：确认无残留、未覆盖并发写者、幂等动作确为 no-op
- 失败原因发生切换时，用 git log/reflog 时间戳核对是否存在并发 commit，验证对状态漂移的解释

## Counterexamples
- 回执只给笼统结论（如 'binding failed'）且不说明检查范围（dirty 是否含 untracked）→ 必须先读门禁源码与测试，本方法不适用
- 用户目标就是部署那个未提交变更 → 不应 stash 移出，应 commit 后走 publish 新代流程
- 门禁只能作为破坏性管道的一部分运行、无廉价 dry-run verify → 修复-重试循环风险高，先读源码确认判定逻辑再动手
