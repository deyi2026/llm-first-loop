---
method_id: attribute-delegate-work-by-action-log-not-ambient-mtime-eae61bb181a2
name: attribute-delegate-work-by-action-log-not-ambient-mtime
description: 委托执行者（子agent/后台job）以 truncated/failed/refused 收场后，要判断"它实际改了什么"时：先读回执自带的工具轨迹/动作日志，看是否存在写类调用；不要用磁盘 mtime、产物新鲜度做归因。多轮任务共用同一目录时，mtime 只能证明"有人改过"，会把上一轮的产物误记到本轮委托者头上（本集曾据此误判"主体工作已完成"，白跑验证、发出注定被拒的续话、推迟重派）。归因看日志，核验看磁盘：磁盘只用来确认日志声称的突变确实现存。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:59688c5b-5ae5-42ee-9d63-23685fb569d6:115:a603463f67866ba60274
evidence_refs: learning:learn:ec5aa9d78fc0
created_at: 2026-10-17T20:22:53.276568+08:00
updated_at: 2026-10-17T20:22:53.276568+08:00
---
## Trigger
子agent/后台任务以截断、失败或租约失效收场，或任何需要回答"这个执行者完成了什么/改了哪些文件"的时刻；尤其当工作目录存在多轮、多个写入者留下的历史 mtime。

## Discriminator
回执中的[工具轨迹]（工具名序列）里是否出现写/突变类调用；以及目录 mtime 是否分裂成多个时间簇、其中较新簇是否落在该执行者的运行窗口内。纯 search/read/execute(只读) 轨迹 ⇔ 该执行者不可能造成任何磁盘突变，新 mtime 必属他人/前轮。

## Short path
- 收到截断/失败回执后，先解析其[工具轨迹]，标记是否有 edit/write/突变型 execute_command；未知量=该执行者产生过磁盘突变吗
- 轨迹全为 search/read ⇒ 判零改动；把目录中较新的 mtime 归因于此前轮次，不运行验证去"确认它的成果"，也不发起以其"接近完成"为前提的续话
- 直接重派（任务书附行号锚点、分批验证、预算约束）或父级接手剩余项
- 对再次截断的委托者重复第1步：以其轨迹中的写调用清单限定需要磁盘核验的产物范围
- 合并全部改动后做一次终局验证（生成守卫+seam 渲染），停止

## Stop conditions
- 动作日志给出明确突变清单（或明确为零），且磁盘核验与其一致
- 归因结论已足以决定重派/接手/收尾三选一

## Verification
- 写调用数与该执行者引起新 mtime 的文件数对账：零写调用 ⇔ 不应有归它的新改动
- 对日志声称的每处突变在磁盘确认现存（日志归因，磁盘验现状）
- 若归因将改变下一步，用时间线交叉验证：改动时间是否落在该执行者租约窗口内

## Counterexamples
- 回执不含工具轨迹：无日志可审，应改为委派前建 hash 基线、事后 diff 归因
- 子agent经 execute_command shell 重定向写文件：轨迹无 edit_file 仍有突变，判据须覆盖一切可致突变的调用及其输出，不能只认写工具名
- 存在租约回滚/effect fence：日志声称的写可能已被回滚，归因用日志、现存状态必须查磁盘
- 干净 checkout 且唯一写入者：mtime 即可近似归因，先审日志属过度流程
