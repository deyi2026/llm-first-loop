---
method_id: error-names-nonargument-token-blame-parse-layer-verify-endstate-6f70908340ba
name: error-names-nonargument-token-blame-parse-layer-verify-endstate
description: 粘贴的终端记录或回执里命令报错，但错误点名的失败对象不是你实际想传的参数——典型：zsh 交互模式默认不开 interactive_comments，行尾『# 备注』被当第二个文件名传给 git apply，报 can't open patch '#'。此时先归因到 shell 解析层而非命令语义层，再用终态验证（reverse-apply check、diff HEAD、统计对账）判定意图操作是否已成功，不重跑命令；连带：给 zsh 交互用的命令模板不要写行内 # 注释。
aliases: 行尾注释被当成第二个文件名, 报错对象和参数对不上先归因 shell, 怎么确认补丁已经打上不用重跑 git apply, git apply 反向校验补丁在不在工作树, 粘贴的终端记录报错但其实命令成功了
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c2df336a-eb98-4baa-9220-9e80d36e4ee2:1891:39be2e00cb9437d2a9bb
evidence_refs: learning:learn:4019ec16dabe
created_at: 2026-11-01T11:00:34.951431+08:00
updated_at: 2026-11-01T11:00:34.951431+08:00
---
## Trigger
回执或用户粘贴的终端记录中命令报错，且错误消息点名的失败对象（引号内的文件名/token）与命令行真实目标参数不一致；常见于 zsh 交互行尾 # 注释、别名/续行拼接把杂注带进参数。同批记录里往往还有紧跟的无注释版本命令或后续 git add/commit 成功统计可交叉印证。

## Discriminator
逐 token 比对『错误消息点名的操作对象』与『命令行真实参数』：若点名的是 # /注释词等非意图 token，失败发生在命令组装层（shell 解析），与命令语义无关，意图操作很可能已由同批的无注释命令完成；若点名的是真实参数本身，则是路径/内容层问题，归因不同、动作不同。

## Short path
- 读失败命令行与错误消息，比对错误点名对象 vs 真实参数 → 判定失败属于解析层还是语义层
- 解析层成立时，查同批记录是否已有无注释版本命令成功执行的证据（后续 add/commit 统计）→ 意图操作可能已完成
- 用终态验证代替重跑：git apply --check -R <patch> 通过 ⇒ 补丁内容已在工作树；git diff HEAD --stat 为空 ⇒ worktree==HEAD
- 提交统计与目标文件实际行数对账一致后停止，不重跑 apply、不『修复』该报错
- 若 apply 报 does not apply 而 reverse-check 显示已应用 → 判定重复应用分支，同样以终态收尾

## Stop conditions
- reverse-apply check 通过且 git diff HEAD --stat 为空（或提交统计与逐文件行数对账一致）
- 错误已归因到具体层（解析层/路径层/内容冲突/重复应用）且终态确认意图操作结果

## Verification
- git apply --check -R <patch> 退出码 0（补丁内容已在树中）
- git diff HEAD --stat 为空（工作树与提交一致）
- commit 的增删行统计与各目标文件实际改动量一致

## Counterexamples
- 错误点名的是真实参数本身（如 can't open patch 'foo.patch'）→ 路径/存在性问题，应修路径而非归因注释
- error: patch does not apply → 内容冲突：先用 reverse-check 区分『重复应用』与『真冲突』，不套用解析层归因
- bash 或非交互 zsh 脚本中 # 是合法注释不会进参数；该判别仅在 zsh 交互且未 setopt interactivecomments 时成立
