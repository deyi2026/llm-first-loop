---
method_id: bind-gate-verdict-scope-to-true-delta-before-consuming-pass-f1449caafaf4
name: bind-gate-verdict-scope-to-true-delta-before-consuming-pass
description: 硬准入/审查门签发 PASS 后，先核对 reviewer 回执自述的审查范围与待执行操作的真实 delta（如 push 实际会发送的 commits）是否一致，再消费该判定。为让门受理而做的工作区整备（stash 他人未跟踪文件等）只解决『门是否接受』，不解决『判定对象是否是你的操作』。范围不匹配的 PASS 对目标操作无效：即使文本是 PASS 也不得放行，应按缺陷通道上报并原样恢复整备过的他人文件。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a33fbd45-6151-492f-b5eb-5fc45e989f08:87:c50aa101976c1b45a5c0
evidence_refs: learning:learn:d9a9106295b8
created_at: 2026-10-21T12:39:35.601723+08:00
updated_at: 2026-10-21T12:39:35.601723+08:00
---
## Trigger
对非幂等对外操作（git push、发表等）设有独立 reviewer 硬准入门；门在需要整备工作区后才受理，或 reviewer 回执中带自述审查范围/delta 描述；即将依据 PASS 执行该操作。

## Discriminator
两份当时即可得的事实并排比较：(1) reviewer 回执自述 scope（如 'No code, no config, no deletions'、'merge_base=HEAD/空 delta'）；(2) 独立可算的操作真值——git ls-remote 权威远端 vs 本地 HEAD 得出的待发送 commit 集合。两者不一致即证明 PASS 绑定的对象不是本次操作（审了别的 workline 的未提交文件，或审了空 delta）。此判别在受理阶段即可预先钉死，无需等 PASS 出来才倒推。

## Short path
- 启动门前先用一条命令钉死真值：ls-remote 权威远端引用 vs 本地 HEAD，列出本次操作实际会发送的 commit 集合（此事实与门是否受理无关，先行取得并保留）
- 门以不透明理由拒绝时（如 untracked_file_too_large / artifact_exceeds_N），把每次拒绝理由当作策略信息增量，用最小可逆手段整备工作区直至受理；不把『受理』当终点
- 拿到判定后第一件事：将 reviewer 自述 scope 与第 1 步钉死的真值逐项比对，回答唯一未知量——这个 PASS 授权的是否就是本次操作
- 范围一致（reviewer 列举的文件/commit 恰等于待发送 delta）⇒ 消费 PASS 执行；范围不一致 ⇒ PASS 视为无效，不执行操作，按缺陷通道上报证据，并原样恢复整备过的他人文件

## Stop conditions
- reviewer 回执列举的文件/commit 与真值 delta（ls-remote 与本地 HEAD 差集）完全一致——PASS 有效，执行操作
- 确认范围不匹配——停止执行与重试门，上报缺陷并恢复工作区，等待门修复后重新过门

## Verification
- 用 git log <remote-ref>..HEAD --stat 复核待推送内容，与 reviewer 报告的 scope 逐项对齐
- 对任何 'merge_base=HEAD'/空 delta 声称，用 ls-remote 显示的落后 commit 数直接证伪
- 确认临时 stash 已全部恢复（他人 workline 文件字节级原样），未遗留隐藏状态

## Counterexamples
- 门的审查范围按定义就是当前工作区全量、且操作对象也是当前工作区（如 full_test）——范围天然一致，无需展开绑定检查
- 门以可执行理由快速拒绝（尚未产生 PASS）——只需修理由重试，此时没有可绑定的判定
- 单人单线仓库、无他人未跟踪文件，门冻结的 delta 即你的 delta——绑定检查退化为一次常规 ls-remote 核对，不应演成多轮探查
