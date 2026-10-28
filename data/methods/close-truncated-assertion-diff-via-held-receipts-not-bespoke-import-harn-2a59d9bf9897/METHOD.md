---
method_id: close-truncated-assertion-diff-via-held-receipts-not-bespoke-import-harn-2a59d9bf9897
name: close-truncated-assertion-diff-via-held-receipts-not-bespoke-import-harness
description: 归因一个比较型测试失败、且断言完整差异被截断（如 unittest maxDiff 类提示）时：先把会话早前已持有的 provenance 回执（对该工件的 git diff、pytest 断言预览片段）拼起来钉住差异实体，把残余未知量缩成『是否唯一差异』；再用一次不导入项目代码的 stdlib 键级对比（或让该单用例以解除截断方式重跑一次）闭合归因，而不是在临时解释器里搭导入被测模块的 harness——环境不匹配时这类 harness 会连挂多次。闭合后把修复方向（更新测试期望/规范化工件/重装）作为语义决策上交，不静默改任何一侧。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:4262a65a-bd51-4405-bed5-57af83e2e1ab:994:014cf908df654740fa3c
evidence_refs: learning:learn:81f8af30d4f3
created_at: 2026-10-22T09:56:38.672451+08:00
updated_at: 2026-10-22T09:56:38.672451+08:00
---
## Trigger
需要归因一个既有测试失败：断言是两个 dict/配置工件的相等比较，pytest 输出截断了完整差异（提示 Set maxDiff 之类），而本会话早前回执中已持有对该比较工件的 diff/provenance 展示

## Discriminator
测试源码已显示断言比较的是两个可命名的权威来源（如『生成器输出 vs 磁盘工件』），且早前回执（对该工件的 git diff + 断言预览片段）已把差异钉到具体键值（例如某环境键=会话临时路径）——即差异实体已知，残余未知量只剩唯一性

## Short path
- 读失败测试源码，指出断言比较的两个权威来源（生成器输出 vs 磁盘工件）
- 盘点已持有回执：该工件的早前 diff + 断言预览片段 → 钉住差异键值，把未知量缩为『是否唯一差异』
- 用一次不依赖项目代码导入的 stdlib 键级对比（only-in-a / only-in-b / differing-shared-keys 三清单）或让该单用例解除截断重跑，闭合唯一性
- 归因闭合即停：把修复方向（更新测试期望 / 规范化工件 / 重装服务）列为语义决策交所有者拍板，不再追加验证性调用

## Stop conditions
- 键级对比给出完整三清单且确认只剩一个差异键 → 归因闭合，停止再验证
- 发现差异值必须执行项目代码才能得到 → 转入先解决权威运行环境，不再绕开导入
- 早前 diff 覆盖的版本与测试实际比较对象不一致 → receipt 降级为线索，必须做一次真实全量对比

## Verification
- 『唯一差异键』主张必须有完整键级对比回执支撑（三清单显式列出），而非由截断片段推断
- 确认所引用的早前 diff 与测试比较对象指向同一工件、同一语义版本
- 修复未拍板前，两侧（测试期望与工件）均未被改动，树保持归因前状态

## Counterexamples
- 差异值由生成器逻辑计算（哈希、路径展开等），不跑代码无法得到 → 必须执行被测代码，正确动作是先解决项目权威解释器/环境，而非绕开导入
- 测试模块在项目 venv 中可直接导入、一次单测重跑（提高 verbosity/解除截断）即可展示全量差异 → 直接重跑更短，无需 receipt 考古
- 早前 diff 是相对旧提交的，而测试用当前配置现场生成期望值 → 该 diff 不能直接当闭合证据
- 断言截断可能隐藏多个差异而已持有 receipt 只覆盖一个 → 不得据此下『唯一差异』结论
