---
method_id: group-worktree-batches-by-in-diff-id-tags-not-history-lookup-be7684a1e126
name: group-worktree-batches-by-in-diff-id-tags-not-history-lookup
description: 用户用短 hex/提案号标注混批未提交改动并要求拆分提交时，先在已可见工件中定位这些 token：git status 里它已作为文件名成分（如 test_evo_<id>_….py 被跟踪修改）出现，即说明它命名的是特性/提案而非 commit，应跳过 git show 等历史查询（否则触发 unknown revision 失败）。随后以 diff 注释中的批次标签（EVO-…-<id>、退役/落地标记）和新测试文件头为分组键逐文件归属，模糊文件单独读 diff；归属齐后只跑两组直接相关测试（含前端），绿后按映射分批 add+commit，不混入无关未跟踪文件。文件数以 status 回执为准，不以口述计数为准。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0db9f81d-904e-4748-9ffe-692f23789e9a:420:78de2bbbfee02a37d351
evidence_refs: learning:learn:606eeb45f753
created_at: 2026-09-23T18:15:10.020067+00:00
updated_at: 2026-09-23T18:15:10.020067+00:00
---
## Trigger
用户/上游用短标识符（hex、EVO/工单/提案号）描述工作区里混在一起的改动批次，并要求按批次拆分提交或解释归属

## Discriminator
第一步 git status 输出中，该 token 已作为被跟踪文件名的成分出现（test_evo_<id>_…py 处于修改状态），即 token 命名的是特性/提案而非 commit；且分组证据（diff 注释里的 EVO-…-<id> 标签、未跟踪新测试文件头 docstring）全部在 worktree 内，无需查历史

## Short path
- git status 核对全部改动/未跟踪文件（以回执为准）；发现标签 token 已出现在文件名中，即判定为提案/特性 ID，跳过 git show/历史查询
- git diff --stat + 读未跟踪新测试文件头（docstring 常列出各特性条目），确定两个批次的语义（哪个是回退、哪个是实施）
- 逐文件 grep diff 中的批次标签（EVO-…-<id>、退役注释）得到 文件→批次 映射；无标签的模糊文件单独读 diff 内容归属
- 只跑两组直接相关测试（各批次测试文件+被改既有测试+前端对应测试）；新跑结果优先于时间戳更早的后台 junit 报告
- 按映射分批 git add+commit，排除无关未跟踪文件；提交后核对两 commit 文件集互斥且并集等于原改动集

## Stop conditions
- 所有改动文件都唯一映射到某批次，无剩余模糊文件
- 两组直接相关测试（Python 与前端）均为绿
- 各批次 commit 完成，且未混入任何无关未跟踪文件

## Verification
- commit 后用 git log --stat / git status 复核：两个 commit 的文件集互斥、并集等于原修改集
- 批内 diff 注释标签与 commit 语义一致（回退批次以删除/退役注释为主，实施批次以特性编号注释为主）

## Counterexamples
- 标签确实是 commit sha（git revert 工作流、git show 成功返回）：此时历史才是归属来源，不应改用 diff 标签分组
- diff 中没有任何批次标签/注释（纯净无标注改动）：退化为逐文件语义审阅或向用户确认归属，不要强行 grep
- 用户要求按目录/模块而非按 ID 批次拆分：标签虽存在但不是用户要的分组键，需按用户的分组维度重新归属
