---
method_id: resolve-index-hit-base-root-before-broad-search-8768aa0839e1
name: resolve-index-hit-base-root-before-broad-search
description: 当搜索/索引工具返回（相对）路径命中，而当前工作根的直接探测已证明该路径不存在时，真正的未知量不是『文件在机器哪里』，而是『命中的 base root 是哪个』。应在小闭集（git worktree 列表、兄弟 checkout 目录）内消解这一歧义并逐根 stat 验证，而不是 find / 全盘盲扫、重试同一相对路径或枚举大量无关近期文件。本集中该矛盾在很早的两次回执中就已同时出现，足以把搜索从『全文件系统』缩到『少数几个候选根』。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5d5ca284-3a97-4bd1-8ff4-ad803e0987fd:85:22acaf8e8509c2b50a8a
evidence_refs: learning:learn:d8b3cbd8cbd6
created_at: 2026-09-17T17:13:56.907077+00:00
updated_at: 2026-09-17T17:13:56.907077+00:00
---
## Trigger
多根/多 worktree 环境下，文件名或索引搜索给出路径命中，但按当前根访问该路径失败，或工具回执明确提示该路径已登记不存在（TTL），此时尚未确定命中所属的根

## Discriminator
当前 git toplevel 下对该目录的探测明确返回 No such file 或 directory，而搜索索引仍命中同一路径——两条当时已存在的事实互相矛盾，直接推出『文件存在但索引 base 不是当前根』，无需预知真实位置

## Short path
- 发现矛盾后，把唯一未知量定为『索引命中的 base root』，不再按当前根重试相对路径
- 枚举候选根的小闭集：git worktree list + 列出当前项目的兄弟 checkout 目录（如同名前缀目录）
- 在每个候选根下对命中的相对路径做 stat/ls，第一个存在的根即为真实落点
- 用 git -C <该根> branch/HEAD/status 刻画落点上下文（是否 detached、是否 untracked、改动集合），判断风险（如被他人 worktree 清理波及）
- 位置与上下文核实后立即停止发现，进入汇报/建议

## Stop conditions
- 命中路径在某候选根下 stat 成功，且该根的 git 上下文（分支/HEAD/tracked 状态）已核实并能解释文件为何在此
- 候选根小闭集穷尽仍无命中：停止枚举，转向重建索引或向用户求证

## Verification
- 解析出的绝对路径可 stat 存在，且其相对部分与索引命中一致
- 该根的 git status 改动集合与文件出现原因自洽（如纯新增 untracked 目录）

## Counterexamples
- 单 checkout、无 worktree 的环境：同样的矛盾更可能是索引过期或路径笔误，应重试原路径或问用户，而非寻找其他根
- 搜索工具本身返回绝对路径：不存在 base 歧义，直接读取即可
- 文件确实已被删除（git 历史可证）：正确动作是查历史或向用户确认，而不是去别的根找
- 索引命中的语义相关性未知：base root 只解决『在哪』，是否为目标文件仍需内容核对，不能仅凭位置收尾
