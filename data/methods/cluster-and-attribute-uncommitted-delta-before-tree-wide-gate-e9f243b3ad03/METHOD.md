---
method_id: cluster-and-attribute-uncommitted-delta-before-tree-wide-gate-e9f243b3ad03
name: cluster-and-attribute-uncommitted-delta-before-tree-wide-gate
description: 多任务 goal 中，准备把某批已登记工作送入裁决覆盖整个工作树的门（全量测试/准入/发布）前，先用一次全量 git status（含 untracked）+ diffstat 把未提交变更按关注点聚类，并与任务台账对账：diffstat 总量或簇构成明显超出在办任务范围，即存在『已完成但未登记』的无主批次。未知簇先做最小身份验证（跑自带测试/读文档头）判定完整工作/半成品/纯产物；完整工作建任务、纯产物归类为噪声、归属不明的并入审核清单而非留给审核员猜。全部簇有归属后，多批合并送同一门（一次独立审核+一次全量），因为门的裁决本来就覆盖全树，分开过门只会多跑且让无主变更夹带未审入场。
aliases: 全量测试前先对账工作树, 树上多出来的改动算谁的, 未登记的改动批次怎么过门, 恢复会话时盘点未提交变更, 无主变更夹带进全量测试, 任务台账和 git status 对不上
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c5f52ba4-0dd0-440d-ab8e-d4b02bb2ed41:2305:11de8d2e97dd88b94140
evidence_refs: learning:learn:ee659d790145
created_at: 2026-10-26T08:01:09.235667+08:00
updated_at: 2026-10-26T08:01:09.235667+08:00
---
## Trigger
从 task state/frontier 恢复或收口某批工作、即将触发全工作树范围的验证门（全量测试、review_admission、发布准入）时；或 git status 显示的变更集文件数/关注点明显多于台账在办任务的范围。

## Discriminator
最早一次 git status --porcelain + diffstat 就暴露的事实：diffstat 显示 55 files / +2379 行，远超在办任务（判定器负控批）的合理范围；且未跟踪清单里出现成套的 impl+test+doc 簇（如 run_eval code_source 的三个 test 文档与实现改动），形态是『完整特性批』而非零散跑批产物——即树上存在台账外的无主工作，这一事实在逐个 diff 单文件之前就已经可见。

## Short path
- 恢复时读 task state + frontier，列出台账认为在办的任务及其文件范围（未知量：台账认为树上有什么）。
- 一次全量 git status --porcelain（含 untracked）+ diffstat，按关注点聚类，每簇标注：台账内 / 已知跑批产物 / 未知簇（未知量：树与台账是否一致）。
- 对每个未知簇做最小身份验证：跑簇自带测试、读其文档头或 grep 实现入口（未知量：该簇是完整工作、半成品还是产物）。
- 判定为完整工作的未知簇：注册为独立任务，acceptance 对齐其已有测试；纯产物簇归类为噪声；归属不明的小簇显式写进审核任务书。
- 全部簇有归属后，多批合并送同一门：一个独立审核子代理覆盖全部分批（含污染/归属专项），通过后一次全量测试。
- 门接受/演进入队即停；需要用户拍板的决策项单独枚列，不混进门流程。

## Stop conditions
- 每个未提交簇都有明确归属（台账任务 / 跑批产物 / 显式豁免），且共享门已被接受或入队。
- 未知簇经最小验证确认为已登记任务的运行产物（reports、日志、usage 记录），归类后不再深挖。

## Verification
- 独立审核报告能对每个簇点名归属，无『归属待查/建议补归属』类残留项。
- 全量测试绿，且门所钉 candidate SHA 对应的树中不存在不属于任何任务的可执行变更。
- 新增登记任务的 acceptance 与其簇内已有测试一一对应。

## Counterexamples
- 未跟踪簇只是已登记任务的跑批产物（report.json、日志、usage.jsonl）：登记为噪声即可，不为产物开任务。
- 门是范围门（只跑某子目录或单测文件），裁决不覆盖全树：无需全树对账。
- 树上存在并行协作者故意保留的 WIP：不应吸收进自己的门，正确动作是隔离（worktree/分支），而非注册接管。
- 两批紧迫度或风险耦合差异大（一批可能 FAIL 拖死另一批的时间线）：分批过门，不合并。
- 簇是极小的机械噪声（格式化、lockfile）：批量归类，不逐簇处理。
