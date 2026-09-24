---
method_id: resume-from-durable-anchors-before-evidence-enumeration-7ba3085d7153
name: resume-from-durable-anchors-before-evidence-enumeration
description: 会话因超时/中断后收到『继续』类指令时，先沿两条持久锚点对账恢复状态：已落盘的计划工件（如 SPEC/任务清单，evidence 已返回 verified_current 指针）与 VCS 提交历史/工作区状态。用『计划项 vs 已提交』差值直接定位续作点；不要先 list_evidence 全量枚举，也不要 hydration 内容已展示过的快照（如 get_goal 结果）。仅当两条锚点无法解释中断点缺口时，才扩大到 evidence 枚举。收益：把恢复期『任意可能状态』缩为两条已验证 provenance 边。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:fc0ed66c-e669-41c4-94d7-7e05031bbac6:285:c66a406035856fc32dff
evidence_refs: learning:learn:1cadea6a9f3a
created_at: 2026-09-22T17:28:06.980225+00:00
updated_at: 2026-09-22T17:28:06.980225+00:00
---
## Trigger
中断恢复场景：用户发出『继续』类指令，此前会话在执行中被打断；环境中同时存在指向计划工件的 verified_current evidence 指针，以及可查询的 VCS 提交/状态

## Discriminator
恢复第一跳 search_evidence 即命中计划工件指针（freshness=verified_current，预览含状态行与分项清单 R1..Rn），且 get_goal 输出已直接显示目标状态。这两条当时已知事实表明：恢复状态由『读该工件 + 对账 git 提交』即可确定，无需枚举上百条 evidence、无需重复读取已展示输出、无需转向宽泛文件搜索

## Short path
- 查 event_stream/get_goal 尾部，确认中断点（最后动作）与目标状态——未知量：工作停在哪一步
- 沿已获指针读计划工件——未知量：任务项清单与各自标记的完成状态
- git log/status 对账——未知量：哪些计划项已提交、工作区是否干净、差值是哪个未完成项
- 若中断点停在验证步，只重跑该步对应的具体测试/命令一次，闭合该循环
- 差值确定后直接进入下一个未完成计划项的实现，恢复阶段到此结束

## Stop conditions
- 计划工件与 VCS 对账已解释全部进度差值，且中断点对应的验证已闭合
- 下一个待办计划项已被唯一确定，无剩余未知量

## Verification
- 最终产出（提交/答复）对应计划工件中的下一个未勾选项，而非恢复期临时发现的旁支
- 恢复阶段不存在对已展示内容的重复 hydration（如 get_goal 结果二次读取）
- 恢复阶段调用数不超过『锚点读取 + 对账 + 闭合中断验证』所需

## Counterexamples
- 全新任务，无计划工件、无 VCS——锚点不存在，必须走发现/枚举路径
- 计划工件 freshness=unverified 且代码已演进超过工件记录——工件清单不能当锚，须先核对当前代码真实状态
- 中断发生在未提交的半成品修改中——脏工作区 diff 才是首要锚，仅看提交历史会误判进度
- evidence 库中存在从未落盘到文件系统的独特观察事实——这些 ref 本身就是必需的 provenance 边，跳过 hydration 会丢失事实
