---
method_id: receipt-state-first-verify-refs-not-tree-on-resume-adc543cfb7fd
name: receipt-state-first-verify-refs-not-tree-on-resume
description: 中断恢复时，先把 hydration 回执中的状态字段（分支名、commit SHA、退出码、远端 ref）当作定位器，直接做 ref 级权威验证，而不是在当前工作树枚举文件或遍历全部 worktree。本 episode 的回执已同时给出 '[feature-branch 5e4b2a74d]' 与 '当前 checkout 已切回 main' 两条事实，此时在 main 工作树里搜目标 manifest 必然落空；直接验证三元组（本地 head、远端 ref、提交内容）即可省去多次文件搜索与全量 worktree 枚举。附带纪律：对 gate 失败下全称因果断言前，必须核对前一 SHA 的逐项 check 历史。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:855926d8-3b7a-4a6d-9c5e-34631b59df2b:738:41d6cf9b17915eff60ce
evidence_refs: learning:learn:4a4775f0cc61
created_at: 2026-09-19T10:58:52.688357+00:00
updated_at: 2026-09-19T10:58:52.688357+00:00
---
## Trigger
任务中断后恢复执行（如用户仅说'按建议执行'），已 hydration 到含分支名/commit SHA/退出码/当前 checkout 状态的命令回执，且待办动作依赖定位先前产物或仓库状态

## Discriminator
回执是否已含状态定位字段：本例中同一行输出同时给出分支名与 commit SHA（[fleet-reclaim-fence-20260919 5e4b2a74d]），且时间戳更晚的另一条回执显示当前 checkout 已切回 main@ba4a866b。这两条当时已知事实足以判定目标文件不在当前工作树（它只存在于另一分支的提交中），把'全仓/worktree 找文件'缩成'验证本地 head、远端 ref、提交内容三元组'。未使用后续才取得的推送/gate 结果倒推。

## Short path
- list_evidence 并 hydrate 最近的 execute_command 回执，提取分支名、SHA、退出码、当前 checkout（未知量：上个会话留下了什么状态）
- 由回执状态直接做 ref 级验证：分支本地 head、远端 ref（ls-remote）、确认快进关系（未知量：本地与远端是否处于预期提交）
- git show --stat 核验提交内容与先前陈述一致（未知量：提交是否只含预期变更）
- push 后远端回读并逐字符比对 SHA（未知量：远端是否已更新到位）
- gate 轮询至终态；对每个 FAILURE 取 --log-failed 根因，并核对 changed set 成员关系与前一 SHA 的逐项 check-runs 历史后再归因（未知量：失败是本次引入还是早已存在）
- 权威验证完成即停止并汇报，不再延伸到无关文件或 worktree 枚举

## Stop conditions
- 本地 head、远端 ref、提交内容三者一致且经远端权威回读验证（如 ls-remote 精确匹配）
- gate 各检查终态已取得，失败项已用 changed set + 前一 SHA 的 check 历史完成归因，不再继续枚举与该未知量无关的文件/worktree

## Verification
- 远端回读 SHA 与本地逐字符一致
- git show --stat 显示提交只含预期文件，与先前对用户的陈述相符
- 对 gate 失败的任何因果断言，须有前一 SHA 对应 check-runs 的历史证据支撑，防止把既有失败误归因于本次提交（本 episode 即纠正了此类全称断言）

## Counterexamples
- 回执不含分支/SHA/退出码等状态字段（例如只有无定位信息的文本输出）时无法定位产物，文件系统与 worktree 发现是必要手段
- 目标 artifact 尚未提交、仅存在于工作树时，commit 回执定位不了它，必须树内搜索
- 任务需要的是文件当前内容而非其在某提交中的存在性时，仍需 checkout 或 git show <sha>:<path> 读取——但那是 commit 域的定向读取，不是全树枚举
