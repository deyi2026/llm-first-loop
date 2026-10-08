---
method_id: reconcile-open-gap-claims-via-topic-matched-status-records-de2f9b31bf77
name: reconcile-open-gap-claims-via-topic-matched-status-records
description: 外部评审/对比审查把某些项断言为『开放缺口/待办 P0』时，不要直接据此建任务，也不要用截断的 git log 反推实现状态。对每条 claim：先在已到手的目录清单里找主题匹配的带日期记录（本仓库 DESIGN/AUDIT/PLAN 文档头部自带 Status 声明与 commit 引用），读头部即裁决 已实现/部分/仅设计；git 只用于验证正向声明（哈希存在、声明路径确有改动）。『截断日志里没出现某文件名』永远推不出『未实现』。把『这做没做』从开放式考古压缩为一次头部读取+一次哈希验证，防止按过时的外部审查重复建设。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ae8c5d92-6fe9-45af-bd9c-ef4912bb21e4:15:ed3e1417fcfd6c681e08
evidence_refs: learning:learn:d08690f66c5d
created_at: 2026-10-07T23:11:18.088488+08:00
updated_at: 2026-10-07T23:11:18.088488+08:00
---
## Trigger
外部评审/评估/计划文档断言本仓库存在若干开放缺口（如 P0 待办），下一步要据此创建 goal/任务清单或核查实现状态；docs 目录清单已在手或一条 ls 即可获得。

## Discriminator
对每条被断言『未做』的项，目录清单中已存在文件名主题精确匹配该缺口关键词的带日期 DESIGN/AUDIT/PLAN 文档，且此类文档头部显式携带 Status（COMMITTED/IMPLEMENTED 等）与 commit 引用——在进入任何 git log 考古之前，这份匹配清单就已经可见（knowledge-at-time 成立）。

## Short path
- 从已获得的目录清单中，为每条外部缺口 claim 列出主题匹配的带日期文档（解决未知量：哪条记录有资格裁决这条 claim）
- 只读每篇匹配文档的头部/Status 段（约30行）→ 得到 已实现/部分/仅设计 裁决与声明的 commit 引用（未知量：实现状态）
- 一次 git 检查验证正向声明：哈希存在/声明路径确有改动（未知量：文档状态是否与仓库真值一致）
- 汇总 closed vs open，只为 open 项规划；无匹配记录的 claim 显式标记『需直接查代码』，不默认当待办

## Stop conditions
- 每条外部 claim 都有『Status 头 + git 可验证 commit/路径证据』双重支撑的裁决
- 所有无主题匹配记录的 claim 已被标记为 unresolved（需代码级核查），未混入待办清单

## Verification
- 每个『已实现』裁决同时引用文档 Status 声明和至少一个 git 可验证的 commit/路径
- 清查目录清单：不存在『头部未读、却主题匹配某条 open claim』的带日期文档

## Counterexamples
- claim 是全新提案，工作区无任何主题匹配记录——无既存状态可对账，直接作为新工作项处理
- 缺口是行为/runtime 缺陷：文档 Status=COMMITTED 不证明行为正确，必须取测试/遥测证据
- 记录日期之后有已知 commit 改动或回退了同一代码——文档状态可能过时，此时 git diff 优先于文档头
- 仓库文档没有 Status 头约定——文件名/日期匹配本身是弱证据，需直接检查代码
