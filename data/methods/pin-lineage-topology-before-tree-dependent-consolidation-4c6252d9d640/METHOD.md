---
method_id: pin-lineage-topology-before-tree-dependent-consolidation-4c6252d9d640
name: pin-lineage-topology-before-tree-dependent-consolidation
description: 多轮测量任务进入汇总/验收时，若台账头部记录的采集基线 HEAD 与部署/状态回执内嵌的 git_head 不一致，先把『当前代码是哪棵树』当唯一先决未知量：用一次有界拓扑测量（双向 rev-list 计数 + merge-base）把候选线分类为沉没分支 / ahead-behind / 互不包含，再按『树相关 / 树无关』分流合并。树无关项（磁盘、worktree 清点、文档计数）直接收；树相关数字必须带实测 head 标注，未裁决分叉登记为阻塞级决策项（选项+推荐+不决策后果），树相关修复任务置 blocked。防止把 mirror 工作区默认当『当前代码』，导致整轮结论建立在旧树上事后作废。
aliases: 先搞清线上跑的是哪份代码, 别把本地目录默认当线上代码, 汇总测量数字前先核对代码版本, 代码线对不齐先裁决再修, 测试红数要标是哪条代码线测的
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:8cdc10d0-aa2b-4b38-b050-e87862e63307:319:5690cbd19fedf7f8d4ad
evidence_refs: learning:learn:aa23daf2d5ea
created_at: 2026-10-28T00:27:03.774601+08:00
updated_at: 2026-10-28T00:27:03.774601+08:00
---
## Trigger
接受/汇总并行测量结果（测试红数、lint 计数、『当前代码』类判断）要写回台账或据此排期时，环境同时存在多个代码 lineage：台账/文档头部记录的基线 HEAD+采集时间戳、部署回执内嵌的 git_head+进程启动时间、本地 main、mirror 工作区、.releases 快照副本。

## Discriminator
第一份台账回执已在同一页展示 ≥2 个互不相同的 head 标识（如头部基线 HEAD 与总览行里的 live/desired head 各不相同），且基线采集时间早于最近一次部署重启——这本身即证明『当前代码』身份未定，任何树相关数字的合并都被它门控。

## Short path
- 读台账头部与最新部署回执，只回答一个未知量：所有 lineage 引用是否指向同一 head。
- 不一致 → 做一次有界拓扑测量：对候选 head 两两双向 rev-list 计数 + merge-base，分类为沉没分支 / ahead-behind / 互不包含，不做全量枚举。
- 给每条树相关数字标注实测时的 head；跨树比较的结论显式标『基线相对』，不得冒充当前事实。
- 树无关项（磁盘占用、worktree/文档清点、归档清单）直接合并，不为它们做基线动作。
- 分叉未裁决 → 写成阻塞级决策项（选项+推荐+不决策的后果），树相关修复任务置 blocked 并注明依赖，停止继续执行代码类工作。

## Stop conditions
- 全部更新后的数字均带 head/树标注，分叉要么已归并、要么已升级为带选项的决策项。
- 树相关修复任务已显式 blocked 并指向该 lineage 决策项，不再以 open 状态排队。

## Verification
- 每个 closed 项的关闭回执中 git_head 与该结论所声称的树一致。
- 拓扑结论可用记录在案的 rev-list/merge-base 命令原样复现。

## Counterexamples
- 单 lineage 环境（工作区 = 本地 main = 线上 head 一致）——先钉基线是纯开销。
- 汇总项全部树无关（worktree 磁盘占用、文档篇数、归档校验清单）——直接合并。
- 任务对象就是 mirror 工作区自身（清理/清点类任务），线上 head 与结论无关。
- 分叉仅单向 fast-forward 且部署回执确认工作区领先线上——工作区即当前代码，只需记录发布滞后，不必阻塞修复。
