---
method_id: git-first-when-vcs-identifiers-are-named-9269c9624595
name: git-first-when-vcs-identifiers-are-named
description: 当用户消息/已见工件中已出现版本库对象的精确标识符（commit SHA、分支名、tag），且任务未知量是这些对象的可机判事实（是否包含、是否祖先、改动面、拓扑关系）时，第一跳直接用 git 按 ID 查询，而不是按叙述关键词枚举 evidence/record 库。本集在用户首条消息已给出两条 SHA（993f9c2f8、14352cc6f）及“插件分支未含修复”断言的情况下，仍对同一类事实做了 4 次库关键词搜索（'restart CLI recovery…'、'端口 回滚 身份' 等）全部未命中，而 git 三两条命令即可全部判定。库搜索只留给 git 答不了的 narrative 未知量。
aliases: 都给了 SHA 还在翻记忆库, git show 那个 commit 就行, 这提交在不在这个分支里, merge-base 判祖先关系, 有提交号直接查
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:fd840981-a906-404c-8c80-1c3452e1c66a:27:d026d218ee73538ff3ba
evidence_refs: learning:learn:f7e2e19e08bd
created_at: 2026-10-09T18:09:14.931364+08:00
updated_at: 2026-10-23T05:53:11.088202+08:00
---
## Trigger
未知量关于版本受控对象（提交/分支/worktree）的状态或相互关系，且对话中已出现这些对象的精确标识符（如 7+ 位 hex SHA、分支名、tag）。

## Discriminator
存在可直接机读的 VCS 标识符，且未知量可化为 git 谓词（branch --contains / merge-base --is-ancestor / show --stat）；此时按叙述关键词搜库的期望命中≈0，首跳应直连版本库而非 evidence/record 库。

## Short path
- 从对话中提取全部精确标识符，把用户断言转成待判定谓词清单（如：14352cc6f 是否为插件分支祖先；事故提交存在于哪些分支）
- 逐谓词用对应 git 命令按 ID 直查（branch --contains、merge-base --is-ancestor、show --stat、worktree list），每条命令绑定一个明确未知量
- 仅当某未知量是 git 无法回答的 narrative（决策理由、会话历史）或本地对象缺失时，才转 evidence/record 库检索
- 取得拓扑事实后直接进入实际变更与验证，不回查已判定谓词、不补充同义关键词搜索

## Stop conditions
- 用户断言的每个拓扑谓词都已有对应 git 回执验证或证伪
- 对同一库未出现换措辞的重复搜索；库检索仅剩 narrative 类未知量（或为零）

## Verification
- 复盘库检索调用：凡标识符可解析的未知量，库搜索调用数应为 0（本集为 4 次全 miss 的可消除浪费）
- 每个关键拓扑断言能指出产生它的具体 git 命令回执（如 'p1b 不含 993f9c2f8' ← contains/merge-base 输出）

## Counterexamples
- 未知量是‘当初为何这么改/上轮结论依据’等 narrative——git 只存结果不存理由，此时 evidence/record 库才是正确首跳
- 本地仓库不存在或缺该对象（如 mirror 未同步 fix 分支）——git 直查会失败，须先从记录/远端定位
- 用户只给模糊指称（‘那个重启修复’）且无任何标识符——关键词搜索是合理第一步
- 标识符指向非 VCS 资源（evidence://、record ID）——权威在库不在 git，不得套用
