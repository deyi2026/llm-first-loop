---
method_id: verdict-conjunction-report-missing-when-poll-receipts-schema-frozen-29859fbc00eb
name: verdict-conjunction-report-missing-when-poll-receipts-schema-frozen
description: 裁决规则是命名字段的合取（如 PASS 需真实终态 ∧ 关键计数为零 ∧ SHA 匹配），部分必需字段只能来自对一个单次授权、禁止重复 start 的子任务的有限轮询时：若回执连续多轮 schema 冻结、只含部分合取项（SHA + 绿色代理字段如 qualification=PASS）而结构性缺失终态与计数，则跑满契约轮数后逐合取项报告 satisfied/missing，结论按合取规则如实输出——绝不用代理绿色字段顶替未观测合取项，绝不重发 start 或另派探针。
aliases: 轮询跑满还是拿不到终态字段, qualification PASS 不等于审查通过, 回执缺 P0 P1 计数怎么收口, 单次授权审查收不到结果不要重发, 终态缺失如实报告不补写
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:72f66d73-0b75-4deb-8f7a-b37f86ad070e:0:56d2b3826c4f8c5ff341
evidence_refs: learning:learn:1645d34d77aa
created_at: 2026-10-24T07:45:58.247488+08:00
updated_at: 2026-10-24T07:45:58.247488+08:00
---
## Trigger
任务书以命名字段合取定义最终裁决，且部分必需字段只能通过对子任务回执的有限轮询获得；start 为单次授权非幂等动作，明令禁止重复发起或另派替代探针。

## Discriminator
连续≥2轮 status 回执逐字节 schema 相同且不含终态/问题计数字段——缺失属该回执类型结构性不提供，而非'尚未到达'；且回执中的绿色字段（qualification=PASS）语义只覆盖准入/身份合取项，不是子任务终态裁决。此判据自第2轮回执即成立，无需等到上限才预判缺失项不会出现。

## Short path
- start 一次并保存 child_id；被拒、SHA 漂移或认证错误则立即停止不重试
- 按契约 wait+status 轮询；每轮对回执做 schema diff：本轮是否出现终态/计数等裁决字段
- 连续两轮 schema 冻结且缺裁决字段 → 判定该回执通道结构性不提供缺失合取项；仍按契约跑满轮询上限（不得提前结束父 Run 触发级联取消），但不再期待字段稍后出现，也不加发额外探针
- 到上限后按合取规则收口：逐项列 satisfied（如 SHA 匹配、qualification=PASS）与 missing（如终态、P0/P1/P2），任一必需项无回执支撑即不构成 PASS
- 缺失就明说缺失：不补写、不用代理字段推定、不重复 start、不另派审查

## Stop conditions
- 任一回执出现真实终态（completed/failed）与计数 → 按合取规则裁决并停止
- 轮询达契约上限且回执仍缺裁决字段 → 输出逐项 missing 报告并停止，不再发起新调用
- start 被拒、回执 SHA 漂移或认证错误 → 立即停止

## Verification
- 报告中每个'已满足'字段可指回一条真实回执；每个'缺失'字段明确标注'回执未提供'
- 结论与合取规则逐项对照：无回执支撑的必需合取项不得使结论为 PASS
- 确认全程仅一次 start、无派生子代理、父 Run 在非终态期间未被结束

## Counterexamples
- 回执 schema 本含终态字段且当前为 pending：字段会随轮询到达，应继续轮询而非提前按缺失收口
- 契约允许其它证据源（更丰富的 status 形态、日志文件、evidence 分页水合）：schema 缺口应触发切换证据源，而非直接报缺失
- start 幂等且契约允许重发：回执不收敛时应按契约重发一次，而非机械跑满上限后报缺失
- 裁决规则本就是单字段（qualification=PASS 即 PASS）：绿色字段即裁决本身，不存在代理顶替问题
