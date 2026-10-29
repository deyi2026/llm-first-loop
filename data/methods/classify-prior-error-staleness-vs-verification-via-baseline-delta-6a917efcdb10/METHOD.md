---
method_id: classify-prior-error-staleness-vs-verification-via-baseline-delta-6a917efcdb10
name: classify-prior-error-staleness-vs-verification-via-baseline-delta
description: 用户纠正上一轮的比对基线（权威远端是 lfl/main 而非 origin/main 或本地 main）后，错误原因本身仍是待判别未知量。对争议事实所在路径做旧基线 vs 新基线的 diff/祖先测试：为空、或争议提交同时在两个基线内，则旧错误与基线无关、是核对错误，须整轮重审（含用户未点名的结论）并如实声明『滞后解释不了』；diff 非空则仅对 delta 涉及的结论按新基线重核。
aliases: 基线滞后还是我核对错了, 换了基线旧结论怎么撤回, 两基线diff为空错误不在基线, 纠正比对基准后整轮复查, 上轮结论错误归因排查
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:3e24aff2-8af5-497f-882a-a249bcc66acd:458:863654c6594339a62f4e
evidence_refs: learning:learn:bcf36d919d10
created_at: 2026-10-29T10:52:54.321345+08:00
updated_at: 2026-10-29T10:52:54.321345+08:00
---
## Trigger
用户或自检指出上一轮用了错误/陈旧的比对基线（如远端被纠正、branch 基线被换），且上一轮存在多条依赖该基线的结论待重审

## Discriminator
争议事实在旧基线与新基线之间是否内容一致：git diff 旧基线 新基线 -- 争议路径 为空，或争议提交同为两者祖先。一条命令当时即可核查，直接区分『基线滞后』与『核对错误』两种成因

## Short path
- 钉死权威基线：列 remotes，按 URL 身份线索判别（复用 pin-authoritative-remote-before-sync-comparison）
- 对争议路径做旧基线..新基线 diff 与祖先测试，回答『两基线在这些事实上是否等价』
- 等价 → 判为核对错误：整轮旧结论逐条重审（含用户未点名的），逐条给出 撤回/维持 判定，并显式写出『滞后解释不了这个错误』
- 不等价 → 只对 delta 触及的结论按新基线重核，其余维持
- 对每条被撤回的结论直接读新基线上的原始文件复核，不依赖上轮转述

## Stop conditions
- 上一轮全部结论已按权威基线重审完毕，且逐条有 撤回/维持 判定
- 错误归因（基线滞后 vs 核对错误）已判定并显式写给用户，不留隐性假设

## Verification
- git diff 旧基线 新基线 -- 争议路径 输出为空，即证两基线在这些事实上等价
- 对争议提交向旧基线也做 merge-base/祖先测试，确认是否双边都已包含

## Counterexamples
- 旧基线与新基线在争议路径上确有差异（文件只在一边存在）→ 滞后就是原因，按新基线重核即可，无需扩大为整轮审计
- 没有上一轮依赖基线的结论、只是首次核验 → 方法不适用
- 旧基线 ref 已不可得（被 GC / 无本地副本）→ 无法做双基线对比，直接按新基线全量重核
