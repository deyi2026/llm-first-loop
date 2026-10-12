---
method_id: close-named-loose-ends-via-owning-guard-first-9684842ebd1a
name: close-named-loose-ends-via-owning-guard-first
description: 收口此前登记的遗留缺陷时，每项描述已自带命名锚点（具体台账/文件/守卫测试名）。正确次序：先用最独特的锚点词一次搜索定位『拥有该断言』的守卫测试与配套治理产物，先跑 focused guard 判定已修/仍开（相邻测试绿不算关闭证据），全量级断言用一次后台全量收口；对仍开项按产物自身治理规则修复。机制探索（conftest 隔离原理、同义命名的其他 ledger、evals 噪音文件）只在 owning guard 仍红且需归因时展开。本集因跳过此序，产生误猜 injection_ledger、.ledger.lock 噪音搜索、错路径 grep 等约十次无信息调用。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7d3df8c3-848b-4bf3-b66b-1dbd2f791ac4:996:c1622ff63c5911ee0ced
evidence_refs: learning:learn:aa61e7aa4f3b
created_at: 2026-09-23T15:08:59.575712+00:00
updated_at: 2026-09-23T15:08:59.575712+00:00
---
## Trigger
任务为核实/收口此前会话登记的具体遗留项，且每项描述中含命名锚点（artifact 名、文件名、测试/门禁名，或『台账缺条目』类明确指向）。

## Discriminator
缺陷描述中存在低频独特锚点 token（如 rule_presence、runtime_env_access、convergence_receipt），一次文件名/内容搜索即可同时命中 owning guard 测试、治理产物与工具脚本；若只有高频词（ledger）则命中噪音，应换更独特的组合词而非扩大枚举。

## Short path
- 核对树状态（git log/status）：报告的提交与工作区是否与现实一致
- 对每个遗留项取最独特锚点名做一次搜索，直接得到 owning guard 测试及配套治理产物（ledger/audit 脚本/基线登记）
- 先跑各 owning guard 的 focused 测试判定已修或仍开；相邻/同步类测试通过不构成关闭证据
- 启动一次全量（前台超 60s 即转后台），验证范围外是否另有红
- 对仍开项按其产物自身治理规则修复（如跑 audit 脚本重盘点补行；按 env 门禁的显式审查登记路径加 baseline 签名）
- 复跑 focused guard + 全量全绿即停止

## Stop conditions
- 每个遗留项的 owning guard 转绿，且一次全量 EXIT=0
- 锚点搜索证明该 artifact/守卫已被移除或更名，遗留项失效，登记后停止
- 机制探索仅在 owning guard 仍红且修复需归因时进行，归因完成即回到 focused 验证

## Verification
- focused owning guard 全绿（如 rule presence 契约 18/18、env 门 6/6）
- 一次全量单元测试 EXIT=0
- 修复方式与产物自身声明的治理规则一致（台账版本变更须重盘点；env 门要求显式审查后登记 baseline）

## Counterexamples
- 遗留项只有症状级描述（『当时全量红了』）而无任何命名锚点——应先跑全量或宽发现，锚点搜索无目标
- 锚点词为高频常见词（如 ledger 命中大量 evals 快照 .ledger.lock）——须换更独特组合词或限定目录内容搜索，而非顺着噪音继续枚举
- owning guard 已绿但全量出现新的无关红——属新缺陷，不得并入本遗留项收口，应另立事项
