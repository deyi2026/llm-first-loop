---
method_id: resume-continuation-via-named-provenance-and-git-delta-948a229d7f50
name: resume-continuation-via-named-provenance-and-git-delta
description: 极简续跑指令（如 'X 继续'）且无活动 goal 时，不要对同一 evidence 库反复换措辞搜索。首次 search miss 的回执通常已显式列出项目最新权威文档参考；schedule/wakeup evidence 常已点名续跑备忘；而版本库 unmerged commits 是『还剩什么』的真值账。沿这三条已点名的 provenance edge（最新停点文档、被点名备忘、git cherry/diff 量化 delta）重建状态，把『继续』转成『N 条未吸收 commits + 冲突面』的量化事实后再执行，可省去重复查询，并让分批移植有客观依据。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:32d694c9-dbcd-4dc8-a941-0885c617868c:934:f2ef065cb2f23088db80
evidence_refs: learning:learn:5a3bd9a37e30
created_at: 2026-09-20T00:54:28.515431+00:00
updated_at: 2026-09-20T00:54:28.515431+00:00
---
## Trigger
用户发出极简续跑指令（项目代号 + '继续'），当前无活动 goal，需要先重建项目状态才能行动。

## Discriminator
首次 search_docs miss 的回执已显式列出该项目最新文档参考（含最新停点/裁决文档）；且 schedule evidence 命中的续跑清单已点名具体备忘项并给出优先级——状态来源在当时已被收窄到一两个；同时 git 分支 unmerged commits 是剩余工作的真值。

## Short path
- 收到续跑指令且无活动 goal → 先读 miss 回执已列出的最新项目文档，取得停点与下一步命名（未知量：上次停在哪）
- 用项目 token 检索一次 schedule/续跑 evidence，只取被点名的那份备忘，不换措辞重查（未知量：续跑计划原文）
- git 真值账：log main..branch 全量清单、git cherry 等价性标记已在 main 的 commits、merge-base 双边 diff 得冲突文件集（未知量：剩余工作量化）
- 以量化 delta 建 goal+worktree，按 commit 分组批量执行；已在 main 的等价项显式跳过并记录
- 门禁/PR/检查通过即停

## Stop conditions
- 续跑状态已被权威来源完全量化：未吸收 commits 数、已在 main 的等价项、双边冲突面均已确定
- 备忘指定的下一步为纯等待/机械步骤（如等 PR 检查后 merge）时按字面执行，不再展开新发现

## Verification
- 最终执行范围与 git cherry 未吸收清单一一对应；已在 main 的等价 commits（如 B1）被显式跳过且有记录
- 汇报中的分批数与冲突数与 merge-base 双边同改文件集一致

## Counterexamples
- 会话 evidence 已含完整 kickoff 计划且有直接 evidence_ref → 直接读该项按字面执行即可，无需再展开 git delta 移植
- 续跑对象无版本库或是外部服务状态 → git 真值账不适用，只剩文档/备忘两条边
- miss 回执的参考列表与所指子项目语义无关（同名不同物）→ 该 edge 不可信，需语义判断或直接问用户
- 指令本身含糊且无任何点名备忘/文档参考 → 宽 evidence 搜索或向用户澄清才是正确动作
