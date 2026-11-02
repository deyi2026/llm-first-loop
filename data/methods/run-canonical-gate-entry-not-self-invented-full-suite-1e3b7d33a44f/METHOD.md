---
method_id: run-canonical-gate-entry-not-self-invented-full-suite-1e3b7d33a44f
name: run-canonical-gate-entry-not-self-invented-full-suite
description: 需要对项目做『全量测试/全量验证』级确认（收尾门禁、发布前验证、验收声明）时，第一个未知量不是『测试红不红』，而是『本项目的权威全量口径是什么』。仓库已有 canonical 门禁脚本与准入契约（scripts/、近期 commit、契约文档可查，口径含非显然参数：marker 排除集、dist 模式、环境钉子）时，自组等效命令会因口径差产生成片假信号（本例自创命令 240 红 vs 权威口径真红 1），把验证回合烧在假失败分诊上。先解析并直接运行权威入口；若已自创命令拿到意外大片红，第一假设是口径错配而非代码坏了。
aliases: 全量测试别自己拼命令, pytest 一大片红先怀疑口径不是代码, 跑全量以 ci_gate.sh 为准, loadfile 和 marker 差出来的假红, 全量口径不能自创
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bc422278-b7a4-4c97-9380-4dc56a6da24f:7923:c64efef7d990bd0d74c8
evidence_refs: learning:learn:f773bd47864a
created_at: 2026-11-02T13:38:35.523146+08:00
updated_at: 2026-11-02T13:38:35.523146+08:00
---
## Trigger
需要对项目做『全量/整套』级测试或验证结论，而验证命令未在本会话明确指定；或自己临时组装的测试命令返回了与近期门禁状态不符的大片失败

## Discriminator
动手前即可查到的事实：仓库存在权威全量入口与口径契约——scripts/ 下的门禁脚本、近期 commit/准入契约文档中定义的非显然参数（marker 排除集、--dist 模式等），且近期回执显示该入口曾是全量绿基线。这些意味着口径本身是合同的一部分，自创等价命令不被合同承认

## Short path
- 第一未知量：本项目权威全量口径是什么？在 scripts/ 与近期 commit/准入契约文档中定位 canonical 门禁入口及其参数（marker、dist、环境钉子）
- 直接运行该入口，exit code 即全量结论，不另组等效命令
- 若红：只在该口径内做新增 vs 存量归因（可配合基线复现法），不再换参数自创口径重跑
- 若此前已用自创命令拿到大片红：先假设口径错配，用权威入口重跑一次再决定是否分诊
- 停止：权威入口 exit=0 且留下可引用回执（通过数/跳过数与该口径一致）

## Stop conditions
- 权威入口 exit=0，回执可作为全量结论引用
- 确认仓库确无任何 canonical 入口：先把口径固化成脚本（marker/dist 写死），再以它为全量口径运行并登记

## Verification
- 回执通过/跳过数与权威口径一致（marker 与 dist 实际生效，非静默裁剪）
- 自创命令与权威结果的差集已被解释（marker 依赖、跨文件污染），而不是未审计地采信其中一个

## Counterexamples
- 内循环开发期只跑单文件/单模块——窄命令是正确姿势，canonical 门禁留给全量确认时用
- 任务目标本身就是设计或迁移测试口径——『发明口径』即是任务，但仍应产出固化脚本而非每次临场组装
- 权威入口在本环境确认不可用（依赖缺失、平台不符）——先修入口或显式记录偏离与理由，不得静默换成口径不同的替代命令
