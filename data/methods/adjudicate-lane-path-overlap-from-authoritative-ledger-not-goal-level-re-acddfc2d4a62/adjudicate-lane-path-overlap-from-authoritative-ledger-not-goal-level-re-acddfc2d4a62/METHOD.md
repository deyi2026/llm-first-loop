---
method_id: adjudicate-lane-path-overlap-from-authoritative-ledger-not-goal-level-re-acddfc2d4a62
name: adjudicate-lane-path-overlap-from-authoritative-ledger-not-goal-level-receipt
description: 受管协调中为路径级『零重叠』复核选择正确裁决面：coordination_status 类聚合回执按 Goal 级汇总（任务计数、checkpoint 摘要、待补证据行），结构上不含各在途 Lane 的 paths 声明，是否截断都不改变这一点；『主代理已核对无重叠』属二手断言，同样不能作裁决面。此时不再水合同一回执或在工作区换词重搜，直接定位宿主侧权威 lanes 账本，机械提取非终态 lane 的 id/status/paths，与本 lane 原路径+新增路径全集逐一求交：零重叠才发带 expected_version 的 CAS lane_update；任一重叠即回报冲突并停止，不强占。版本维度由 CAS 参数自带核验，无需读回。
aliases: lane 路径冲突在哪份账本查, 改占用路径前怎么复核重叠, coordination_status 没有 paths 怎么办, 在途 lane 占了哪些文件, 零重叠复核要逐 lane 证据
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:37596905-cd68-421a-ad2d-d6dcf2ffd14f:22:d84b6730db9752a200c6
evidence_refs: learning:learn:77b1864b4874
created_at: 2026-11-19T01:27:47.806275+08:00
updated_at: 2026-11-19T01:27:47.806275+08:00
---
## Trigger
即将执行会变更路径占用面的受管 CAS lane_update（扩 paths/更新 head），任务要求先完成路径级冲突复核，而 coordination_status 之类聚合回执只给 Goal 级行、未暴露逐 lane paths。

## Discriminator
聚合回执的行结构本身就是判别事实：每行只有 goals/tasks 计数与 checkpoint 摘要、无 paths 字段（截断附 recovery handle 也补不出逐 lane 路径）；用户转述的『已核对无重叠』是二手断言。路径级零重叠只能由逐 lane 记录 paths 的权威账本承载。

## Short path
- 读聚合回执做 Goal 级争用扫描，并确认其是否暴露逐 lane paths（本类回执结构上不暴露）。
- 未暴露即升级：只读定位宿主侧权威 lanes 账本（审计目录按文件名一次 find），不在 workspace 反复换词搜、不继续水合同一聚合回执。
- 机械提取全部非终态 lane 的 id/status/paths。
- 本 lane 原 paths+新增 paths 全集与各 lane 逐一求交；任一重叠 → 不强占，回报冲突并停止。
- 零重叠才发 CAS lane_update（expected_version、head_sha、完整 paths），以回执版本号前进收口。

## Stop conditions
- 求交出现任一重叠：立即停止并报告冲突，不改 lane、不抢占。
- 权威账本不可定位/不可读：明确报告『无法完成路径级复核』，不凭聚合回执或二手断言宣称零重叠。
- CAS 回执返回新 version 且 status/head/paths 与意图一致：本轮裁决收口。

## Verification
- 重叠结论可溯源到逐 lane 对照（lane id ↔ 是否命中具体路径），而非『无争用』的聚合印象。
- lane_update 回执 version 前进且 head_sha/paths 与提交值一致。

## Counterexamples
- 聚合回执本身已逐 lane 列出 paths：直接在回执上求交即可，不必另读账本文件。
- 未核维度只是 lane 版本而非路径：expected_version 的 CAS 写入本身就是核验器，直验其余前提后直接写，跳过读回发现。
- 本轮不涉及路径占用变化（纯状态/进度账本更新）：Goal 级回执已足够，无需账本级提取。
- 涉及他人 lane 归属/占用争议：本方法只做只读求交与停让，不扩展为替他人改账本。
