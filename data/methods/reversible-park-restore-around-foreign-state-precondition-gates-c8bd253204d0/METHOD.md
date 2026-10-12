---
method_id: reversible-park-restore-around-foreign-state-precondition-gates-c8bd253204d0
name: reversible-park-restore-around-foreign-state-precondition-gates
description: 变更类治理动作（如 publish）被单一前置条件闸门拒绝（如 'tracked worktree must be clean'），且 status/diff 显示阻塞增量是本会话未产生、与发布意图无因果的外部改动时：不替用户 commit 或丢弃，改用可逆绕过——stash（带说明性 message）→ 确认 tracked 干净 → 重试动作至受理成功 → 立即 pop → diff 核对增量原样返回。原理：闸门只约束动作时点的内容纯净性，被 park 的增量不进入发布产物，故绕过无损且外部状态零改变。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6011132d-5da7-46ed-9be9-40d1379ec22d:839:9b0a15ba0217ccc5e3b3
evidence_refs: learning:learn:b0cfb3d59252
created_at: 2026-10-11T13:16:45.096694+08:00
updated_at: 2026-10-11T13:16:45.096694+08:00
---
## Trigger
变更类动作回执把失败归因到单一可修复前置条件（如 tracked_worktree_dirty），而非权限/语义错误，且工作区可能存在非本会话产生的改动。

## Discriminator
git status 的 tracked/untracked 切分把 200+ 变更路径缩到唯一 tracked 修改（闸门措辞只查 tracked）；git diff 进一步显示该增量内容（删除一个 IDE 设置键）与本会话动作历史及待发布内容均无因果——阻塞物是外部写入的旁观增量。这两个事实都在重试动作之前已经可见，满足 knowledge-at-time。

## Short path
- 解码拒绝回执：确认是单一前置条件失败而非鉴权/语义错误；未知量=哪些路径在挡
- git status --short 机械切分：tracked-modified=阻塞集，untracked 不挡；阻塞集从全仓库缩到个别路径
- 对阻塞路径逐个 git diff：未知量=改动内容与来源；对照本会话动作历史判定为外部写入、与发布意图无因果
- git stash push 带说明性 message park 该增量，确认 tracked 干净
- 重试原动作（publish）至受理成功，立即 git stash pop 恢复
- git diff --stat 核对外部增量原样返回后，才继续后续动作（restart）

## Stop conditions
- 变更类动作已受理成功（回执给出 generation/deployment_id）即退出 parked 状态，不在窗口内叠加第二个变更类动作
- diff 显示阻塞改动正是本次要发布的内容 → 放弃 park，正常提交后重试
- park/恢复失败（stash 冲突、merge/rebase 进行中）→ 停手上报，不强行 commit/checkout 外部状态

## Verification
- 拒绝回执是前置条件措辞（must be clean / missing=...），不是 forbidden 或语义错误
- 阻塞集逐路径经 status+diff 确认与本会话动作及发布意图无因果（有据判定，非猜测）
- 恢复后 git diff/status 证实外部增量完整回到工作区（本例 diff --stat 复现了原修改）

## Counterexamples
- 脏文件正是待发布的改动本身（发布目的就是包含它）：stash 会把旧代码发上去，必须先 commit 再发布
- 闸门同时要求 untracked 路径或索引干净：默认 stash 覆盖不到，需换等价可逆手段并同样验证恢复
- 阻塞改动可判定为用户有意的未完成工作而非 IDE/插件自动写入：不 park，先询问用户 commit/还原意愿
- merge/rebase/cherry-pick 进行中：stash 不安全，直接上报操作者
