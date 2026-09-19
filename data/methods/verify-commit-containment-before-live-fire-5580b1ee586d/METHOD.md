---
method_id: verify-commit-containment-before-live-fire-5580b1ee586d
name: verify-commit-containment-before-live-fire
description: 部署/发布回执把服务内容钉死在精确 commit（code_root+git_head）时，“改动是否已上线”本质是提交包含性问题：先用 git（status/log/与回执 head 做 diff 或 ancestry）核验，再决定走 restart 实弹还是 commit→merge→operator publish。工作区文件的存在（ls/read/grep 命中）无法区分“已提交”与“仅工作区未提交”，不能作为部署包含证据；也不要在已有这条窄 provenance 时先做全目录内容搜索去定位实现。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:e8e83cd1-6d33-4a6b-b29b-56131638f5d7:206:fd2426ff3d786cf948f4
evidence_refs: learning:learn:aea433f0654b
created_at: 2026-09-18T19:07:58.183474+00:00
updated_at: 2026-09-18T19:07:58.183474+00:00
---
## Trigger
已拿到含 code_root 与 git_head 的部署/发布回执，目标是验证某近期改动是否在该部署面生效（restart/实弹/按钮级确认），或需要定位该改动的实现位置。

## Discriminator
回执当时已钉死精确 code_root+git_head——“目标改动是否被该 commit 包含”是一个 git 提交问题，一条命令可答；而内容搜索/读工作区文件看不见未提交改动，既答不了这个问题，也不是包含性证据。（事后佐证而非依据：diff 与提交列表中均无该任务文件，实现仅以工作区文件存在。）

## Short path
- 读部署回执，取 code_root 与 git_head；未知量：目标改动是否已进入该 commit？
- 在改动开发树执行 git status --short 与 git log --oneline -- <任务文件>（或与回执 head 做 diff/ancestor 判断）；未知量：改动已提交且被包含吗？
- 若未提交/未包含：完整提交（复查全部 untracked 文件）→ 合入部署分支 → 请操作员 publish；未知量：新 commit 何时成为部署面，由 publish 回执回答；此时不安排 restart 实弹。
- 仅当 git 证据确认包含后，才 restart/实弹，对回执 head 指向树内的路由/面板做验证。
- 若实弹异常（如 404），只在回执 git_head 对应的树内核对该路由是否存在，不引用其他工作区文件当部署真值。

## Stop conditions
- git 输出明确显示回执 head 包含目标改动（diff/ancestry/log 命中任务文件）→ 停止提交核验，转入实弹验证。
- git 输出显示改动未提交或未被包含 → 取消本轮 restart 实弹计划，转入 commit→publish 路径。
- 已在与回执 head 一致的来源上完成验证 → 停止，不再追加确认性动作。

## Verification
- 用 git show <回执head>:<被测文件> 或 git diff 输出确认被测文件/路由确实存在于部署 commit 中。
- “deploy 包含 main/该改动”的结论必须由显式 git 命令输出支撑，不能由 ls/read_file/grep 工作区文件推出。
- 提交前读取完整 git status（含 untracked），不以截断（如 head -20）的输出下“无漏文件”结论。

## Counterexamples
- 本地开发服务器以工作区代码热重载运行、无 commit 钉定：工作区即 live 真值，读盘/内容搜索是正确首步，不应套用本方法。
- 目标只是阅读定位实现且没有任何部署回执等 provenance 指针时，先做定向内容搜索不属此反模式。
- 改动提交与回执 head 的包含关系已由先前 git 输出确认：直接实弹，无需重复查提交状态。
