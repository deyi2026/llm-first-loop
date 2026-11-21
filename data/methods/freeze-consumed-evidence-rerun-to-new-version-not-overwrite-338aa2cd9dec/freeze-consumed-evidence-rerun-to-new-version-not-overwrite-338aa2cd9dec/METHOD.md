---
method_id: freeze-consumed-evidence-rerun-to-new-version-not-overwrite-338aa2cd9dec
name: freeze-consumed-evidence-rerun-to-new-version-not-overwrite
description: 已被 checkpoint、QA 或对外报告采信的证据制品（校准/评测 JSON、运行日志）视为 append-only：代码 patch 后即使只是确定性重跑、diff 仅元数据字段，也必须写入新版本文件，不得就地覆写旧制品。目录中既有的 v1/v1.2 版本命名与 .sha256 sidecar 惯例意味着『文件名+内容哈希』就是证据身份，就地覆写等于篡改 provenance。覆写已发生时的修复：补冻结新旧两份及 sidecar，披露字段级 diff 与确定性等价核验，并把『凡已采信版本立即固化』立为后续规则。从未被外部引用的中间产物仍允许就地覆写。
aliases: 重跑把旧结果文件覆盖了怎么办, 改完代码补跑实验要不要换版本号, 已经汇报过的实验数据还能动吗, QA 看过的结果被重跑覆盖, 旧证据冻结副本怎么存
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:dc9cbbb4-590e-40e1-b360-158e5ef5619b:409:fd825cfce784d344ddcb
evidence_refs: learning:learn:e96c5b548e14
created_at: 2026-11-19T10:00:35.145856+08:00
updated_at: 2026-11-19T10:00:35.145856+08:00
---
## Trigger
需要对一个已进入外部记录链（checkpoint / QA / 提交清单 / 报告引用）的证据制品做重跑、再生成或补数据，且该版本首跑之后代码已发生过 patch。

## Discriminator
制品的文件名+内容 SHA 已被外部消费：目录已按版本命名（v1/v1.1/v1.2）且存在 frozen 副本与 .sha256 sidecar 惯例；同时自首跑以来代码有变更——重跑产物不可能是同一证据身份，按目录自身惯例应落新版本号，而不是覆写旧文件。

## Short path
- 写前先判定：目标制品是否已被 checkpoint / QA / 提交清单引用过。
- 已引用 → 先冻结旧版（副本+.sha256 sidecar），重跑写入新版本号文件；未引用 → 允许就地覆写。
- 若发现覆写已发生 → 立即补冻结新旧两份，逐字段 diff 确认测量数据确定性一致、差异仅元数据字段（如 code_sha256）。
- 在交接/报告中如实披露该瑕疵，并把『凡已采信版本立即固化』立为后续规则。
- 收尾用 shasum 核对提交清单中每个被引用制品的磁盘 SHA 一致后停止。

## Stop conditions
- 所有被外部记录引用的证据制品均有稳定 SHA、冻结副本与 sidecar，且此后未再发生就地覆写。
- 等价性核验若发现测量数据并非一致，立即停止『等价』表述并重开诊断，不得宣称确定性重跑。

## Verification
- 覆写前后做字段级 diff：宣称等价必须由 diff 支撑，不得口头断言。
- shasum -a 256 逐文件核对提交清单中的 SHA 与磁盘实际内容一致。
- 披露文本与实际 diff 范围一致，既不夸大也不缩小。

## Counterexamples
- 从未被外部引用的调试/探针中间产物：覆写是正常迭代循环，逐版本复制只是噪音。
- 原生不可变（CAS、append-only 日志）或原生版本化的存储：规则自动满足，无需再手工冻结副本。
- 外部消费之前的同一制品调试期重跑：允许覆写；判据是『是否已被外部记录采信』，不是『是否重跑过』。
