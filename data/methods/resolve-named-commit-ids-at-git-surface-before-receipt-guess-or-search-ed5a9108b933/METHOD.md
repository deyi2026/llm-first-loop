---
method_id: resolve-named-commit-ids-at-git-surface-before-receipt-guess-or-search-ed5a9108b933
name: resolve-named-commit-ids-at-git-surface-before-receipt-guess-or-search
description: 交接/状态记录已逐字列出交付工件标识（commit SHA、分支名、worktree 路径）时，回答“实现了什么/在哪/是否生效”应直接在 git 对象库解析这些标识（git show、branch --contains、log main），而不是：①按命名约定猜治理工件路径（回执/报告）去 read——尤其当记录本身把该工件标为 pending；②在确定性404后转内容/文件名搜索——仓库内 .releases 快照会以旧版本大量命中制造噪音。收尾补两个放置事实：代码所在 ref 与当前 checkout 的分歧、运行时配置是否启用。一次 git 解析把“内容/位置/激活”三问收口。
aliases: 状态里给了commit号还去猜回执文件名, 复盘做了什么先git show, 404回执让search别真去全库搜, 交接记录带SHA直接查git对象, 描述已交付功能看提交不看releases快照
status: candidate
source_model: deepseek/deepseek-flash
source_episode_refs: episode:7e91da8b-4d11-4df5-84fc-7666790cb2fb:1378:43407b08ece1b7d89518
evidence_refs: learning:learn:acf932bd5551
created_at: 2026-11-09T18:17:53.912127+08:00
updated_at: 2026-11-09T18:17:53.912127+08:00
---
## Trigger
用户要求描述/复盘/核对已交付工作（“实现了什么功能/改了什么/代码在哪”），而任务状态或交接记录已逐字给出交付工件标识（commit SHA、分支名、worktree 路径）；记录可能同时把部分收尾工件（合并回执、评审）标记为进行中/未决，且记录快照可能落后于当前 git 真值。

## Discriminator
记录中存在可直接解析的权威标识（git SHA/分支名）——真值自带解析面，无需中间检索；被读路径的失败回执是确定性“文件不存在”（含“此前已登记不存在”提示）而非瞬态错误；若已做内容搜索，命中大面积集中在 .releases/<旧sha>/ 等快照目录即陈旧镜像噪音，不是当前代码。

## Short path
- 从记录提取每个交付工件的确切 SHA/分支名；未知量：各工件实际内容
- git show <sha>（提交正文+--stat）直接读对象库，取得功能描述的第一手材料
- git branch --contains <sha> 与 git log main --oneline 确定代码现在在哪个 ref，并与当前 HEAD 分支对比，得出“在 main 不在当前 checkout”或反之
- 仅当确需治理工件状态时，对 receipts 目录做一次列目录学习真实命名约定，绝不按猜测文件名逐个 read
- 读运行时配置（.env/部署面）确认功能是否已启用，随后停止

## Stop conditions
- 功能内容（git show）、所在 ref（branch --contains）、运行时激活（配置面）三问均已有权威面证据
- 记录标 pending 的治理工件经目录列举确认尚不存在后，不再反复猜路径或对其做全局搜索

## Verification
- 最终描述引用的每个 SHA 都能被 git show 独立复现
- “在/不在某分支”的断言用 git branch --contains 复核
- 引用的代码内容来自 ref 定位读取（git show <ref>:<file>）而非 .releases 快照命中
- 激活/未启用结论由配置文件直接读出，而非推断

## Counterexamples
- 记录只有散文描述、无任何具体标识（无 SHA/分支名）——没有可直接解析的锚点，真正的检索发现才是必要步骤
- 目标工件是普通文件而非 git 对象——直接读文件即可，git 面无关
- SHA 属于本地不存在的仓库/远端——git show 失败即转询问用户或拉取，不硬套
- 用户问的就是“治理回执写没写/评审过没过”——权威面是 receipts 目录与流程账本本身，列目录一次即可，代码提交不回答该问题
