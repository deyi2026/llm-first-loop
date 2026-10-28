---
method_id: tracker-complete-resume-pivot-to-uncommitted-delta-12efcb26afd0
name: tracker-complete-resume-pivot-to-uncommitted-delta
description: 『继续』类极简指令且存在活动 goal/tracker 时：tracker 回执算术（total−done−open）把未知压到个位数终态任务，用一次定向 event/history 查询归类即可，不重复轮询同一只读状态工具；checkpoint 已『evidence verified』的完成断言无需重读产物全文验证。真续点是 git 未提交 working-tree delta：按『本 goal 产物 vs 外来改动』分类后，把『继续』转成分批收口提交+goal 收官。与 resume-continuation-via-named-provenance（无活动 goal、上游未合并 commits 口径）互补而非重复。
status: candidate
source_model: workbuddy/hy4-preview
source_episode_refs: episode:e3d65611-a839-42fc-bf6f-fae957ddf6cf:1350:7c96977c72d55151fa56
evidence_refs: learning:learn:554fd5737009
created_at: 2026-10-15T08:11:43.777741+08:00
updated_at: 2026-10-15T08:11:43.777741+08:00
---
## Trigger
极简续跑指令（如『继续goal』）且存在活动 goal；tracker/frontier 显示 0 open 且 goal_completion_ready=true，但任务总数与 done 数不等（存在终态未明的残余任务），同时 git status 存在未提交改动

## Discriminator
tracker 回执自身的算术：total=7、done=6、open=0 ⇒ 恰好 1 个任务处于非 open 非 done 终态，一次按该任务 ID 的定向 event 历史查询即可归类（本例=重复建单后取消）；且 checkpoint 已显式『evidence verified』，故产物内容不需要为确认完成而重读；git status 的 33 行输出本身就是未落盘工作的完整清单，行级摘要用 git diff --stat 取得

## Short path
- 读一次 goal/tracker 状态，提取 total/done/open 算术、checkpoint 断言与 completion_ready 标志，不重复轮询
- 若 (total−done−open)>0，对残余任务 ID 做一次定向 event/history 查询归类终态（cancelled/failed/重复建单），算术闭合（如 6 done + 1 cancelled = 7）
- git status / diff --stat 各一次，枚举未提交改动，对照 checkpoint 点名的工件路径分成『本 goal 产物 vs 外来改动』两类
- 把续点表述为收口计划：定向复绿 → 按 pathspec 显式分批提交（goal 工作与外来改动不混批，绝不 git add -A）→ checkpoint + goal 收官
- 提交粒度等同属用户偏好而非事实未知的问题，直接交用户裁决，不再做发现类动作

## Stop conditions
- 残余任务终态已归类且任务图算术闭合
- 未提交改动已完成 goal 范围分类；剩余不确定项属用户偏好（如分类改动是否与代码同批提交）而非可查事实

## Verification
- 状态类只读工具在结果未变时不重复调用（本例 frontier 以相同参数被调 4 次，属 post-sufficiency 重复）
- 不为确认 tracker 已 evidence-verified 的完成而重读产物全文/整段设计文档；用 git diff --stat 取行级摘要替代
- 最终答案显式给出任务图算术与未提交清单来源，并把收官表述为待执行计划而非已完成的终局断言

## Counterexamples
- tracker 仍有 open/ready 任务：续点是执行这些任务，收口提交不是当前动作
- checkpoint 无 evidence 验证断言或产物可疑：抽查产物内容是必要的，重读不算浪费（该断言正是本方法的判别前提）
- 无版本库或工作树已干净：delta 轴不存在，续点完全由 tracker 决定
- event/history 不可查：残余任务终态应报告 unknown，不得由总数算术凭空推断其性质
