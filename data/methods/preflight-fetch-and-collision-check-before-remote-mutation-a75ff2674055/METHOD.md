---
method_id: preflight-fetch-and-collision-check-before-remote-mutation-a75ff2674055
name: preflight-fetch-and-collision-check-before-remote-mutation
description: 对共享 git 远端执行变更性操作（push、rebase/checkout 到新远端 head）前，先做廉价预检：一次 fetch 刷新比较基线，把本地 untracked 清单与远端 incoming 路径求同名交集；冲突文件先备份、用 git show 物化远端内容比对，确认仅空白级差异才移除后 rebase；push 遭分支保护拒绝时不重试直推变体，立即转 分支→push→PR→checks→merge。可避免：凭缓存 tracking ref 断言远端状态、把 rev 语法喂给普通 diff 产生假差异、在未知保护规则下反复直推。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5adf278f-405b-44db-95e5-3d3b94e1b8d9:536:61c144ff83b355984182
evidence_refs: learning:learn:496f2cc42fe5
created_at: 2026-09-19T12:16:45.966312+00:00
updated_at: 2026-09-19T12:16:45.966312+00:00
---
## Trigger
本地配置多 remote/镜像、存在他人并行提交线索，git status 显示相对远端 tracking ref 的 ahead/behind，且工作区有成组 untracked 文件；任务要求把本地提交推上远端受保护分支或 rebase 到更新的远端 head

## Discriminator
git status 的 ahead/behind 只相对上次 fetch 缓存的 remote-tracking ref，未经 fetch 不构成远端真值；status 已列出的 untracked 文件一旦与远端新提交同名，将直接阻断 rebase/checkout。这两点在最初的 remote -v && status 输出中已可见，足以把『直接推送』缩为『先 fetch + 同名冲突预检』

## Short path
- 进入仓库后单步执行 git fetch <remote> && git remote -v && git status -sb：解决未知量『远端当前真值与真实分歧（是否既 ahead 又 behind）』
- git diff --name-only <remote>/<branch> HEAD 与 git ls-files --others --exclude-standard 求交集：解决未知量『哪些 untracked 会被 incoming 提交覆盖』
- 备份交集文件，用 git show <rev>:<path> 物化远端版本再比对：解决未知量『差异是否实质』（普通 diff 不认 rev:path 语法，会全量假报 DIFF）
- 仅空白/行尾级差异→备份后移除冲突 untracked 并 rebase；存在实质差异→停止自动移除，升级为合并决策
- push 被分支保护拒绝（required status checks / 规则违反）→不重试直推变体，立即 branch→push 分支→gh pr create→轮询 checks→CLEAN 即 merge；auto-merge 未启用则用轮询循环兜底
- 合并后 fast-forward 本地正仓；部署推进若属 operator-only 边界（命令被 fence 拦截），停止并交给用户确切命令与预期输出（代次+1、新 head）

## Stop conditions
- 目标提交已通过 PR 进入受保护远端分支，本地 tracked 干净且与远端一致
- 同名 untracked 与远端版本存在实质内容差异（非空白级），自动移除不安全，转人工/三方合并
- 剩余步骤落在 operator-only 权限边界内（如部署 publish），已向用户提供可复制命令与预期输出

## Verification
- git status -sb 不再显示 ahead/behind，tracked 无未提交变更
- 远端分支 log 含目标提交/merge commit，PR required checks 全绿
- 移除冲突 untracked 前备份目录已建立且文件数与交集数一致
- 部署 verify 仅剩 git_head 单项差距且对应操作员命令已交付

## Counterexamples
- 单人单 remote 且本会话刚 fetch 过：基线已新鲜，直接 push 即可，预检冗余
- untracked 与远端 incoming 路径无交集：跳过备份与内容比对步骤
- 仓库规则/贡献文档已明确禁止直推 main：从一开始就走分支+PR，不应先尝试直推
- 离线或远端不可达：无法 fetch，只能基于本地 ref 判断，方法不适用
- 同名文件差异达数百行实质内容：不能靠字节数断定等价，应直接按内容冲突走合并流程
