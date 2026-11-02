---
method_id: restage-and-verify-at-gate-input-surface-index-not-worktree-bd6a5ef77252
name: restage-and-verify-at-gate-input-surface-index-not-worktree
description: 提交期安全/卫生扫描按暂存 index 内容拦截后，在工作区修掉命中内容并不等于门禁会放行：已暂存文件的后续工作区修改不会自动进入 index，按原 index 重提会再次被拦。修复必须重新 git add，且复验必须用拦截器本体对 staged 内容（--staged / git grep --cached）执行，而不是 grep 工作区文件。通则：门禁消费哪个表示（index / 工作区 / 已推对象 / 部署产物），修复与验证就落在同一表示上。
aliases: 改了文件提交还是被扫描拦, git add 后又改文件 重提被拦, MM 状态 提交门禁还拦, 提交扫描要查暂存区不是工作区, 门禁拦了 工作区改完还要重新 git add
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:fb9d2fd4-22ec-46f0-9f10-3dd3f2341da5:1267:46bc5497af1cf8b464bf
evidence_refs: learning:learn:1bf7375aa342
created_at: 2026-11-01T10:10:02.078360+08:00
updated_at: 2026-11-01T10:10:02.078360+08:00
---
## Trigger
commit 脚本/门禁在提交期以确定性内容规则（本地绝对路径、密钥模式等）拦截某文件；该文件在拦截前已被 git add（git status 首列为 M），随后你在工作区修改了命中内容准备重提

## Discriminator
拦截发生在 commit 执行链上 ⇒ 执行面是暂存 blob 而非工作区文件；且此前回执已显示该文件处于已暂存态（M 首列），编辑工作区只会产生 MM 分歧。因此『grep 工作区零命中 + 测试通过』不构成门禁放行的证据——这两条事实在修复前就已可见。

## Short path
- 以拦截器的输入面枚举命中：git grep --cached '<拦截模式>'（或扫描器 --staged）拿 index 命中清单，而非 grep 工作区文件
- 读扫描脚本/规则确定修复策略（字符串拼接、改写或登记豁免），保持运行时语义不变
- 工作区修改后立即 git add 该文件，让修复进入执行面；status 应回到单列 M，不得停在 MM
- 用拦截器本体对 staged 内容复扫（scan_rc=0）+ 跑该文件相关测试
- 核对三态一致性（HEAD/index/工作区）后再重提

## Stop conditions
- 拦截器本体对 staged 内容复扫通过（零命中）且相关测试全绿
- git grep --cached 对目标模式零命中（仅剩已登记白名单形态，如系统公共目录）

## Verification
- 用扫描器本体（--staged 模式）复验，而不是用等价 grep 扫工作区
- git grep --cached '<拦截模式>' 零命中，且 git status 该文件无 MM 分歧

## Counterexamples
- 拦截器读的是工作区路径（按文件路径跑的本地 linter/hook）或已推送 commit 对象、部署产物——验证面应移到那个表示，本地 re-stage 不是关键动作
- 拦截源于瞬时错误（网络/超时）而非确定性内容规则——应重跑归因，而非改内容再暂存
- 命中文件本不打算进本次提交——用 git restore --staged 移出提交集，而非编辑后再 add
