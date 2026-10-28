---
title: 批量入库未跟踪知识资产：安全扫描要在 add 之后扫 staged 全集，提交信息要按类核对
scenario: 工作区积累 540+ 条未跟踪知识资产（method 卡/经验卡/文档）需一次性入库，且仓库配有 pre-commit security_scan 护栏（拦截本地绝对路径等）。批量 add 后做敏感筛查并提交。
root_cause: 筛查口径与索引状态错位：`git add` 之后再用 `git ls-files --others --exclude-standard` 取待入库集合，已 staged 文件已从 untracked 集合消失，扫描结果返回 0 命中（假阴性），而护栏在 commit 时按 staged 内容扫描，导致连续两次被拦截。另一处错位是 `git add -A <多个目录>` 把三类资产混成一个提交，commit message 只写了其中一类。
solution: "1) 批量入库的敏感/规则筛查必须与提交索引同口径：add 之后用 `git diff --cached --name-only -z | xargs -0 grep ...` 扫 staged 全集；或 add 之前扫「未跟踪 + 已修改」并集。判定\"clean\"前必须确认扫描集合 == 提交集合。2) 命中时的定位：用护栏报出的文件名 + 仓库既有脱敏惯例（`/Users/<name>` → `$HOME` 或 `<user>`）做最小泛化，保住路径结构去掉身份；不要用豁免放行。3) 提交内容核对：`git show --stat --oneline <sha> | tail` 与 `git show --name-only` 按顶层目录分组，与 message 逐项对齐；不符就用 amend 改 message，而不是重做提交（内容已过护栏扫描，重做要再冒一次拦截风险）。4) message 里的量化表述（如\"N 处替换\"）要按实际计数写，先统计再落笔。"
evidence: "本次 session 实测：git add -A 后扫 untracked 返回 \"(clean)\"，但 commit 被 security_scan 连拦 2 次（先 scope-search 卡、后 falsify/scope/experience 三文件）；改扫 `git diff --cached --name-only -z | xargs -0 grep` 后命中 3 文件，泛化后 541 文件扫描通过（回执 \"✅ 通过（541 个文件无敏感/错误内容）\"）。git show --name-only 核实单提交含 518 data + 19 experiences + 4 docs，与初版 message 只写 methods 不符，故 amend。最终 7 文件 12 处泛化，worktree porcelain 0 行。"
tags: [git, security_scan, 批量入库, 敏感扫描口径, commit-message, 假阴性]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-28T09:12:07.456458+08:00"
updated_at: "2026-10-28T09:12:07.456458+08:00"
---