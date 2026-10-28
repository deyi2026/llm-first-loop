---
method_id: verify-named-integration-point-premise-via-command-token-search-1a9718b67635
name: verify-named-integration-point-premise-via-command-token-search
description: 工具替换/接入提案常隐含『目标接入点以某形态存在』的前提（如『CI 里有 tsc --noEmit 步骤』）。该前提是可本地证伪的事实断言，应作为第一未知量，先于工具对比：用前提句中的命令 token 在仓库 manifest 面（package.json scripts、scripts/、CI yml、Makefile）做一次定向内容搜索，读命中处上下文确认真实形态（flags、外层契约、是否唯一闸门），再以真实形态重锚提案——替换可行性取决于新工具对命中处实际 flags/语义的支持，而非对想象步骤的支持；前提证伪时先报『前提为假』+实际接线证据，再给修订建议。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a33fbd45-6151-492f-b5eb-5fc45e989f08:34:423e6636046adc75f482
evidence_refs: learning:learn:8c74eabdd9e7
created_at: 2026-10-21T11:16:18.604113+08:00
updated_at: 2026-10-21T11:16:18.604113+08:00
---
## Trigger
当一份工具替换/接入提案（含自己上一轮写的提案）或被评审的设计锚定到一个具名接入点（CI 步骤、package script、构建钩子），而该接入点的存在与形态来自记忆或上轮转述、本会话未读过其证据；或对抗评审/一致性提问要求回答『配置/依赖如何接线』时。

## Discriminator
前提句里含有可直接 grep 的命令 token（如 `tsc --noEmit`），且本会话已读的 manifest（如 package.json 的 scripts 段）不含对应 script——说明前提尚未在本会话兑现。仓库 manifest 面小而有界，一次内容搜索即可裁决，无需全目录枚举。

## Short path
- 从提案/设计文本抽出接入点前提句及其命令 token，把『接入点是否存在、以何形态存在』列为第一未知量（先于基准对比与参数调优）
- 用该 token 在 manifest 面（package.json、scripts/、CI yml/yaml、Makefile）做定向内容搜索；避免 filename 泛搜撞上 .releases/ 类快照刷屏
- 读命中处上下文：确认实际命令形态（如 -b 增量模式）、外层契约（指纹校验等）、以及它是否该功能唯一闸门
- 以真实形态重锚提案：新工具对命中处实际 flags/语义的支持未验证即视为不支持，据此裁决替换/并存/搁置
- 前提被证伪时，输出『前提为假』+ file:line 实际接线证据，再重写建议；真实接线暴露的缺口（如缺 typecheck script）单独列为可立即执行项

## Stop conditions
- 命中 call site 的存在性、实际 flags 与外层契约均已确认，且建议已按真实形态重锚
- manifest 面全量内容搜索无匹配且覆盖完整（回执为整库无匹配而非 partial read），可下『接入点不存在』结论

## Verification
- 最终建议中每一处『替换/修改 X』的指称都对应一条本会话读过的 file:line 证据
- 否定性结论（『不存在该步骤』）基于全量 manifest 搜索的无匹配回执，而非部分读取外推
- 对『新工具支持命中处实际形态』的任何依赖，未实测则显式标注 unverified 并按不支持处理

## Counterexamples
- 接入点形态在本会话刚被读过（如刚读完 CI yaml 看到该步骤原文）——前提已验证，重复搜索冗余，直接复用既有 evidence
- 提案是纯新增可选路径、不触碰既有接线（如新增一个本地加速 script）——无替换对象，语义/性能对比才是关键，接入点验证价值低
- 绿地项目无任何既有 wiring——不存在可证伪前提，方法不适用
