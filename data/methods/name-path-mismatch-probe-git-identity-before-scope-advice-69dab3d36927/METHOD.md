---
method_id: name-path-mismatch-probe-git-identity-before-scope-advice-69dab3d36927
name: name-path-mismatch-probe-git-identity-before-scope-advice
description: 环境变量带着角色名（workspace/root）但值指向与角色矛盾的路径（如主仓 .releases/<sha>），而 cwd 又是另一个目录时，各目录的真实身份（主仓/live worktree/无版本）与变量的真实语义都是未知量：路径外观像静态快照不等于它不是 git worktree。先对每个候选目录各做一次 git 身份探测（rev-parse --git-dir、dirty 计数、worktree list），再用作用域受限 grep 读该变量的消费方源码拿权威语义，之后才给 scope 指向/文件归属建议。本集此前未做此探测，把 release worktree 误判为静态快照、给出『两层』框架；验证后建议方向整体翻转——不应把 scope 从有版本 worktree 改指到无版本目录。
aliases: 这个目录是不是 git 仓库怎么查, 变量名和实际路径对不上, 工作区该指向哪个目录, 快照目录会不会是 worktree, 按目录名猜用途被坑
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:6e7b4358-a1b8-4e23-a99c-931d6e86bee2:412:5e4c3831778c1a407e4e
evidence_refs: learning:learn:4797c3a426ae
created_at: 2026-10-28T11:16:35.830991+08:00
updated_at: 2026-10-28T11:16:35.830991+08:00
---
## Trigger
需要就『哪个目录应承担某角色』给建议（改 workspace/scope 指向、文件归属迁移），且一次 env/pwd 探测已暴露：角色命名变量的值与当前目录不一致，或其路径模式与角色名明显矛盾

## Discriminator
env 探测回执里 PWD 与角色变量值不同、且该值位于 .releases/<sha> 这类与『workspace』角色名矛盾的路径模式下——这一条事实即可证伪『目录身份已知』的默认假设，直接导出对每个候选根的一次廉价 git 身份探测；路径命名外观不是版本控制身份的证据

## Short path
- 一次 env/pwd 探测列出全部候选根；发现角色变量值 ≠ cwd 且路径模式与角色名矛盾 → 把『各目录身份』立为第一未知量
- 对每个候选目录做一次 git 身份探测（rev-parse --git-dir --abbrev-ref、status --porcelain 计数、必要时 worktree list），把 主仓/detached worktree/无版本 三种身份缩成确定事实
- 用作用域受限 grep 定位该环境变量的消费方源码，读 docstring/分支逻辑取得变量权威语义（变量名 ≠ 语义，如 dual-root 下该变量实指 code root）
- 身份与语义均确定后才形成建议：无版本目录 vs 有版本 worktree（dirty=0 可能是被有意保护的性质）直接决定 scope 指向与文件归属的方向
- 核对建议中每条目录性质主张都对应一条直接探测回执，停止

## Stop conditions
- 每个候选目录的版本控制身份与角色变量的真实语义均已由直接探测或消费方源码确认，建议所需事实齐备即停，不再做目录清点式侦察

## Verification
- git -C <候选目录> rev-parse --git-dir 指向主仓 .git/worktrees/<id>，且主仓 worktree list 含该目录 → worktree 结论双向互证
- 建议文本中每个目录性质主张（有/无版本、dirty 数量、角色语义）都能回溯到一条具体探测回执或源码行

## Counterexamples
- PWD 与角色变量值一致、路径模式与角色名无矛盾 → 无 mismatch 判别信号，直接进入常规分析，不做身份探测
- 问题只涉及文件内容而不涉及目录角色/scope 指向 → git 身份探测无信息量
- 权威文档或本 run 早前回执已确认某目录非 git 管理 → 不重复探测
