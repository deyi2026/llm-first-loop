---
method_id: coverage-gap-block-same-child-bounded-continuation-1afb22d2ed1c
name: coverage-gap-block-same-child-bounded-continuation
description: 委派审查/取证的子代理已达 terminal=completed 却回 fail-closed BLOCK，且回执自证是覆盖缺口（单次读取截断、点名未读区段、给出闭合轮次估计、已核部分零缺陷）而非真缺陷时，既不把 BLOCK 当终局上报，也不另 spawn 新 child：对同一 child 发一次有界续话，约束原样保留（白名单/只读/不扩权/不扩项），只让它按行号锚点分段补读点名区段后给最终裁决。真实缺陷 BLOCK、预算耗尽或工具硬限制将复现时不得续话。
aliases: 审查子代理BLOCK了怎么继续, 子代理读大文件截断没读完, 同一个child续话补读收口, BLOCK是没读到不是有缺陷, 固定只准一个子代理时覆盖缺口怎么办
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a3ee132c-76e1-4927-a5f4-8c8c375c362e:0:0a640568e53a37197e7d
evidence_refs: learning:learn:7cce299ccd8e
created_at: 2026-11-13T14:28:59.516389+08:00
updated_at: 2026-11-13T14:28:59.516389+08:00
---
## Trigger
有界轮次预算的委派子代理（如独立代码审查 child）达到 terminal=completed，但裁决为 fail-closed 的 BLOCK/NOT_VERIFIED；委派合同常固定 child 数量（如恰好 1 个），使'再 spawn 一个补查'违约

## Discriminator
终局回执文本是否同时含四要素：① 明确覆盖边界（如'仅前 693/6204 行，其余截断未读'）；② NOT_VERIFIED 点名到具体委派项而非笼统失败；③ 明示闭合路径与轮次估计（如'再需约 2 轮'）且 rounds 余量足够（3/6）；④ 已核部分零确认缺陷（P0=0/P1=0）。四者齐备=覆盖缺口型，可续话；缺任一（尤其出现真实缺陷证据）=不可续话

## Short path
- 收到 terminal=completed+BLOCK 回执后，仅用回执文本给 BLOCK 分类：覆盖缺口型（截断边界+点名未核项+闭合估计+零缺陷）/真实缺陷型/预算耗尽型
- 覆盖缺口型且余量≥闭合估计：对同一 child 发一次有界续话——工具白名单、只读域、轮次上限原样不放宽；指令限定为'按行号锚点分段补读点名未读区段（避免再次整读触发同一截断），随后给最终裁决'，禁止扩项
- 等待新终态；核验 rounds 未超上限、工具轨迹全在白名单内、此前 NOT_VERIFIED 项全部被显式裁决、P0/P1 计数齐全
- 上报最终裁决并如实披露两段过程（首轮 BLOCK 原因+续话补读范围）；绝不把首轮 NOT_VERIFIED 默化为已通过

## Stop conditions
- 最终裁决覆盖全部原委派项且含明确 P0/P1 计数（如 P0=0/P1=0）
- 续话回执出现真实缺陷证据或预算耗尽——立即停止重试，按失败如实上报，不假报 PASS
- 未读内容在委派域之外（如打包配置不在本仓）——接受为标注 NOT_VERIFIED 的边界，不烧轮次

## Verification
- 续话后回执 rounds ≤ spawn 时 max_rounds；工具轨迹逐条仍在只读白名单内
- child 总数不变（未新增 spawn），续话对象 child_id 与首轮一致
- 首轮 NOT_VERIFIED 的每一项在终稿中有 file:line 级显式结论
- 父侧汇报含过程披露（首轮截断原因、续话补读区段），未把'未检'记为'通过'

## Counterexamples
- BLOCK 附带真实 P0/P1 缺陷证据——续话等于向 child 施压改判，属裁决购物；原样上报
- rounds 已贴上限、闭合估计超余量——续话会被运行时截杀；应走'child 失败再分段'路径或如实失败上报
- 截断源于工具硬限制且 child 无分段/偏移读取能力——同工具续话必然复现截断；需任务书前置分段读取或父侧预切片
- NOT_VERIFIED 因权威源在委派域之外（外部 CI、远端 schema）——再读本仓无法闭合，标注边界后收口
