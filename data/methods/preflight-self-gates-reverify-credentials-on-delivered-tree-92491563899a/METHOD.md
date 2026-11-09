---
method_id: preflight-self-gates-reverify-credentials-on-delivered-tree-92491563899a
name: preflight-self-gates-reverify-credentials-on-delivered-tree
description: 收口/合并一个验证凭证绑定特定 SHA 的 lane 时，有两类隐性失效会让『凭证齐全』失真：①lane 自己新增的 push 闸会拦自己的收口——开局第一条命令的 git status 里未入库知识资产加上日志里本 lane 的闸提交，就是自家闸必拦的信号，应先跑闸的检查模式再进收口管线；②凭证绑树不绑分支：flush 补提交、merge 本身都产生新树，ratchet/baseline 类实测『已提交树』的确定性测试会出现分支绿、合并树红（main 上他人已合提交可违反基线）。push 前必须在合并结果树上重跑全量门禁；红了先在合并前 main 复现归因，继承缺陷优先选行为不变的等价重构而非登记新基线放过。
aliases: 分支绿不等于main绿, 合并后才红的ratchet基线, 收口前先过自己加的闸, 凭证绑树不绑分支, flush后已验证SHA失效, 合并结果树重跑全量ci
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:9fd8f866-77d0-4951-8e25-686ea3761026:488:e7b8b7254b06a5134b63
evidence_refs: learning:learn:dedf03adbf34
created_at: 2026-11-09T18:54:19.240269+08:00
updated_at: 2026-11-09T18:54:19.240269+08:00
---
## Trigger
收口/合并一个验证凭证（full_test/ci_gate PASS）绑定特定分支 SHA 的变更批次，且 (a) 该批次自己新增了 push/收口闸，(b) 收口路径含补救提交（知识 flush、回执补丁）或 merge 本身，随后要 push 共享 main

## Discriminator
开工 git status 已列出未入库知识资产，且 git log 已含本 lane 的闸提交 → 自家闸必拦收口，这是第一步就可见的事实；凭证回执里的 tree SHA ≠ 合并结果/flush 后的 head，且仓库存在对已提交树做绝对测量（ratchet/baseline 实测 vs 登记基线）的确定性测试 → 分支上的 PASS 不蕴含合并树绿

## Short path
- 开工即跑本 lane 自新增闸的检查模式（如 knowledge_flush --check）：未入库资产先 flush，把补提交显式记为『已验证树前进一步』并纳入重验范围
- 读 lane 权威账本确认 head/状态，git 解析 ancestry 后执行合并
- 合并完成后在合并结果树上跑全量门禁（ratchet/baseline 必须实测合并树），不复用分支上的 PASS 回执
- 若红：在合并前 main HEAD 上复现同一测试归因——红=继承的 main 既有缺陷（修法优先行为不变抽取降指标，而非登记新基线）；绿=本批次引入
- push 后 ls-remote 对齐远端 sha=本地 main，账本置终态并核对 close_reason 与实际合并一致

## Stop conditions
- 合并结果树全量门禁 exit=0，且 ratchet 类测试逐条核对实测数字≤登记基线（不只看 PASS 字样）
- 远端 ls-remote sha = 本地 main HEAD
- lane 账本已置终态且 close_reason 与实际合并内容一致

## Verification
- 在合并后树（非 lane 分支）上重跑 ci_gate/full_test 并核对退出码
- ratchet/baseline 类测试核实测值与登记基线的数字关系
- git ls-remote 与本地 main sha 比对一致

## Counterexamples
- 合并工具已在合并结果上自动执行全量门禁并出具回执 → 信任该回执，不重复跑
- 纯 fast-forward、无收口期补提交、且 main 自上次全量验证后无他人合并 → 树未变，原凭证仍覆盖当前树
- 收口补救只触碰门禁不覆盖的资产路径（如 data/ 知识卡）且回执明示零代码改动 → 记录豁免即可，无需全量重跑（但自家闸自身仍须通过）
