---
method_id: admission-gated-command-run-verbatim-standalone-9ffd75920b0a
name: admission-gated-command-run-verbatim-standalone
description: 在带独立审查准入闸的 Host 中执行强保护动作（git push、对外发表、全量测试）时，PASS 资格绑定到精确的命令/产物指纹。必须逐字、单条执行被准入的命令：不用 && 把 push 与验证命令合并，不改参数，也不复用一次 PASS 覆盖多个目标（每个 remote/动作单独准入）。合并或改写会让命令指纹漂移、Host 无法绑定资格而阻断，被迫重核状态再重试，多烧一轮。事后验证用独立的下一条命令完成。
aliases: push 和验证用 && 连起来 被拦, 准入 PASS 后原样单条跑, 一次 PASS 别覆盖多个 remote, 命令指纹漂移得重核一轮, command:<hash> 绑定资格
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d643a7c4-20a9-438d-a61f-dd25be27bf55:1247:9b0d171b281da514b209
evidence_refs: learning:learn:8c450f47454a
created_at: 2026-10-17T06:47:25.061848+08:00
updated_at: 2026-10-17T06:47:25.061848+08:00
---
## Trigger
即将执行的动作处于审查/准入闸保护之下，且准入回执（或闸规则）显示资格绑定到具体 command/产物指纹（target 字段含 command:<hash>）

## Discriminator
admission start 回执的 target 已包含被批准命令的哈希，说明资格是逐命令绑定；据此在首次执行前即可推断：任何把该动作与其它命令 && 合并的复合串都是不同指纹，必然无法绑定、注定被阻断——无需等阻断回执来教训（该事实在尝试前已可见）

## Short path
- 一条合并的 git 状态命令解决全部未知量：worktree 是否干净、HEAD、各 remote 的 ahead/behind 与 ls-remote 实测 tip
- ff 安全核验：tracking ref == ls-remote tip 且 tip 为 HEAD 祖先，记录每个 remote 的待推区间与提交数
- 按 canonical→次要 顺序逐 remote 走闸：admission start 绑定精确命令 `git push <remote> main` → 等待 → status 确认 PASS
- 逐字、单条执行已准入的命令，不与任何验证或辅助命令合并、不改写参数
- 用独立命令做事后权威验证（ls-remote <remote> refs/heads/main == 本地 HEAD），全部对齐后停止

## Stop conditions
- 所有目标 remote 的实测 tip == 本地 HEAD（权威读数一致、ahead/behind 归零）
- 闸返回 BLOCK/REVISE 时停止执行该命令，先处理审查发现；push 失败先 dry-run/fetch 分叉诊断根因，禁止盲目重试

## Verification
- 推后用独立 ls-remote 实测远端 tip 等于本地 HEAD
- 实际执行的命令与准入回执绑定的命令逐字一致（无合并、无改写）
- 若仍遭 compound_protected_shell 阻断：按回执指引重核 PASS 后以同一目标单命令重试一次即成

## Counterexamples
- 无准入/指纹绑定的普通环境：`git push && git ls-remote` 合并执行更省一轮，不应拆分
- 只读或非保护命令：批量 && 合并仍是高效默认，此方法不适用
- 准入按设计绑定的就是某条复合命令字符串（回执指纹即该复合串）时，应逐字执行那个复合串而非自行拆分
