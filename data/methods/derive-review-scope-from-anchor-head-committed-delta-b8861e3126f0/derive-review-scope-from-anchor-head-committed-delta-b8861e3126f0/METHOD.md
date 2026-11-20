---
method_id: derive-review-scope-from-anchor-head-committed-delta-b8861e3126f0
name: derive-review-scope-from-anchor-head-committed-delta
description: 对已混入其他已合 PR 的候选提交启动 patch 范围审查/准入时，待审文件集合必须取『审查锚点（远端分支 SHA）→候选 HEAD』的已提交差异全集，而不是 PR 作者最初编写的文件列表：合并树里已含其他 PR 的文件，两集合必然分叉（本集 10 vs 18），沿用作者列表即触发 no-delta/范围失真。被拒后重发的第一未知量是『哪些文件真正构成待审增量』，由版本控制差异机械回答，不从会话记忆、PR 描述或旧回执里取。
aliases: 合并后审哪些文件才算数, 门禁报无有效改动怎么修, PR 自带列表与实际提交对不上, 重跑审查前先圈定真实改动集, 远端分支到合并点的差异当审查范围
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:e092bd5c-6885-4927-8c8f-245f5b2f463f:1:f580afe8086d78933b79
evidence_refs: learning:learn:f2b0e3935420
created_at: 2026-11-18T21:57:59.215323+08:00
updated_at: 2026-11-18T21:57:59.215323+08:00
---
## Trigger
对已发生合并的候选提交启动 patch 范围的审查/准入闸（review_admission 类），且上下文出现过 no-delta/范围失真类失败，或手头只有 PR 作者最初编写的文件列表；尤其任务书已点名上次失败原因时。

## Discriminator
决策时已可见的判别事实：①任务书明确记载上次失败原因=『把 PR 原始文件列表当提交清单导致 no-delta』；②caller 给出的新列表被声明为与远端分支 SHA→HEAD 的变化精确对应，且条数与作者列表不等（18≠10）。两者把范围候选从『多个可能列表』缩到唯一答案：已提交差异全集，merge 后作者列表必然失真。

## Short path
- 钉死两个版本身份：审查锚点（远端 PR 分支 SHA）与候选 HEAD SHA；未知量=待审增量文件集合
- 取锚点→HEAD 的已提交差异完整文件列表作提交清单（caller 已给出精确列表时直接采用，并核对条数与声明一致）；弃用 PR 作者原始列表
- 按任务书一次性发起 start（patch 范围+该列表），不先做任何探查性工具调用
- 读 accepted 回执：核对 effective 范围与 paths_ignored=false、回执内列表与提交列表逐条一致；落账 child_id 与 candidate_sha256（注明是材料哈希、非 git SHA）
- 按回执 waiting_protocol 以 status 轮询至终态，出终态报告

## Stop conditions
- accepted=true 后进入轮询；终态回执（qualification 定值）一到即出报告停止，pending 时不得结束
- start 被拒：原样上报 reason 后立即结束，不重复 start、不扩展调查
- 全程不执行被闸动作（push/改文件/合并 main/部署），除非任务另有授权

## Verification
- 回执 paths_ignored=false 且回执内文件列表与锚点→HEAD 差异集合逐条相等（不是子集也不是超集）
- candidate_sha256 与 child_id 已落账，并已注明 candidate_sha256 是审查材料哈希、与 git SHA 是两类身份，不得混用
- 终态报告只引用回执字段；回执未返回的明细（如逐级问题计数）如实标注缺失，不虚构

## Counterexamples
- 审查对象未经合并、作者列表恰等于已提交差异（无其他 PR 混入）：两集合相同，直接用作者列表即可，无需强制重算
- 任务要求只审子集/切片（如仅本轮新增的重点文件）或范围为 full/tree 类：待审集合不由差异全集定义
- 闸从 SHA 自动推导范围且回执标注清单被忽略（paths_ignored=true）：手列列表不生效，应修锚点/版本身份选择而非列表本身
