---
method_id: vague-referent-resolve-via-git-provenance-7d1fd5a73e86
name: vague-referent-resolve-via-git-provenance
description: 用户以含糊指称（如“完善后的方案/最新设计”）引用未给路径的交付物时，最近一次语义匹配提交的 git log/show diffstat 已权威枚举目标文件与 commit hash。此时跳过仓库级文件名搜索（只会命中大量不相关的同型文档），沿 commit→分支→git show <commit>:<path> 读全内容。工件常在非当前分支/链接 worktree：先 git branch --contains 定位，再直接按 commit 读，避免 ls 试探与宽枚举。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d4b773f7-7796-4ff1-a76a-310f94b7feff:132:fc6a1644fe7ced5db5be
evidence_refs: learning:learn:fa6cbc4aaa78
created_at: 2026-09-25T11:17:24.842529+00:00
updated_at: 2026-09-25T11:17:24.842529+00:00
---
## Trigger
用户指令以指称性短语（“完善后的方案”“最新那份设计”）引用某交付物但未给出路径；且仓库近期存在 commit message 语义匹配的 docs/refinement 提交（可含 --all 分支上的提交）。

## Discriminator
最新匹配提交的 diffstat 已显式列出目标工件的确切路径集合与 commit hash——目标文件集已被权威枚举，仓库级文件名搜索只会返回不相关命中；若该 commit 不在当前分支，其内容仍可经 git show <commit>:<path> 直接读取，无需先把它弄进工作区。

## Short path
- git log（必要时 --all）按 commit message 语义匹配用户指称，读取候选提交的 diffstat；未知量：目标交付物是哪组文件？
- 以 diffstat 的路径+commit 为唯一候选集，git branch --contains <commit>（或 git worktree list）定位文件所在分支/worktree；未知量：工件是否在当前 worktree？
- 不在当前 worktree → 直接 git show <commit>:<path> 逐文件读取，先 wc 估算长度规划分段，减少截断后的补读往返；未知量：完整内容。
- diffstat 命中的全部文件读完即停止一切发现动作，进入产出（重写/整合为用户要的文档）。
- 产出的新文档提交到包含源工件的同一分支，与源保持 provenance 一致。

## Stop conditions
- diffstat 命中的全部文件均已完整读取，且其内容语义与用户指称吻合
- 已确认指称对象不在 git 历史中（未提交草稿、会话产物、外部资源）→ 转入 search/ls 宽发现

## Verification
- 最终产出文档中的每条事实都能映射到某个 <commit>:<path> 的已读内容，无凭 diffstat 文件名臆测的细节
- 新提交落在包含源工件的分支上；diffstat 命中文件无一遗漏未读

## Counterexamples
- 指称对象从未入库（工作区未跟踪草稿、仅存在于会话 evidence）→ git 图上没有这条边，必须宽发现
- 任务目标本身就是盘点仓库文档全景/找相似文档 → 宽搜索是目标而非弯路
- diffstat 命中的文件已被后续提交大幅改写且用户要的是当前版 → 应跟随该路径的最新提交而非最初 diffstat 的快照
