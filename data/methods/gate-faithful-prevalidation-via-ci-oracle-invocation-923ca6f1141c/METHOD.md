---
method_id: gate-faithful-prevalidation-via-ci-oracle-invocation-923ca6f1141c
name: gate-faithful-prevalidation-via-ci-oracle-invocation
description: 预判『CI/门禁会绿』或执行将触发 CI 的 push 前，必须用 CI 配置显式点名的检查命令本体（含其 scoped 参数与冻结版本语义）本地复跑，而不是用看似等价的裸工具全项目运行替代。等价命令可机制性分歧：全项目模式受 exclude 配置约束，而门禁对 changed 文件 scoped 运行会绕过 exclude，产生假 PASS，直到独立审核或 push 后 CI 才暴露，迫使追加修复提交+二次审核+重推。workflow 里点名的 gate 命令就是真值 oracle 的 provenance edge，沿它一步即可替代一切等价性假设。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:33d3039e-2906-4f07-9dc7-517532290686:372:a9a02a0e7dc0867f7fb6
evidence_refs: learning:learn:b5c9dd54f227
created_at: 2026-10-14T18:41:55.532390+08:00
updated_at: 2026-10-14T18:41:55.532390+08:00
---
## Trigger
即将断言『CI/门禁会通过』或执行将触发 CI 的 push/merge/tag，且流水线判定由某个具体检查器调用产生（workflow 步骤显式命名 gate 脚本/wrapper/带参命令），而现有本地验证是用自构等价命令（如裸跑同一 linter/类型器）完成的

## Discriminator
CI workflow 已显式写出权威判定命令及调用方式——它可与裸工具运行机制不同：changed 文件 scoped 调用绕过全项目 exclude、工具版本被冻结 pin。这条已可见的命名命令（真值 oracle 的 provenance edge）在断言 PASS 之前就足以把『我验证过了』缩成『我用 CI 自己的口径验证过了』

## Short path
- 读 CI workflow，提取权威 gate 命令、参数与工具版本 pin（未知量：CI 实际按什么口径判定？）
- 预验直接本地运行该命令本体，替代任何等价裸工具运行（未知量：CI 口径下是否真绿？）
- 若失败：按诊断做最小修复，重跑同一 gate 命令至 PASS
- 仅 gate 命令本体 PASS 后才对外断言会绿/执行 push；独立审核也以同一 oracle 复核，而非审核者自选口径

## Stop conditions
- gate 命令本体在本地以同参数、同 pin 版本退出 PASS
- gate 依赖本地不可得资源（网络凭据/真实 LLM/专有 runner）时：显式声明未验证增量，降级为部分预验，禁止宣称等价 PASS

## Verification
- 本地运行的命令串与 workflow step 的 run 行逐字一致
- 工具版本与 CI 冻结版本一致（而非 latest）
- changed 集/scoping 语义一致：确认 scoped 调用是否绕过全项目 exclude
- 最终 PASS 回执来自 gate 脚本本体，而非对单文件的裸跑抽查

## Counterexamples
- CI 直接裸跑工具且共用默认配置（无 wrapper、无 scoped 特殊语义）时，本地同命令已天然 faithful，无需此方法
- gate 需要本地不可得资源时无法同构复现：应标注未验证，而不是用等价命令伪造 PASS
- 开发中途的快速 sanity check（单文件 lint/单测）不必每次跑全量 gate；本方法只约束对外断言会绿或预 push 的终验节点
