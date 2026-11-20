---
method_id: external-human-approval-pending-budget-repolls-then-ledger-report-blocke-f70d2cfcc166
name: external-human-approval-pending-budget-repolls-then-ledger-report-blocker
description: 异步等待/审批类回执返回完整阻断状态（请求已创建、id已知、仍pending、原因=外部决定者未行动）时，当前未知量已被完全回答；状态下次何时变化由外部决定，不受本端控制，重复相同轮询的期望信息增益≈0。回执里『可继续等待』只是许可选项，不是自动重发指令；本集任务未定义轮询预算，两次逐字相同的重等直到环境重复调用护栏(repeat_guard)介入才终止。正确顺序：首次等待拿到完整状态后先自设horizon（固定小次数或TTL的占比）并计数；耗尽且无状态变化，立即把状态写入task_state账本（id、时间、TTL、恢复条件、下一步链），向用户汇报精确阻断与恢复触发器后停下；只有外部状态变化才作为继续执行的信号。边界：任务已定义等待参数+次数上限、或pending带可计算进度差异时另行处理。
aliases: web审批面板还没人处理要等多久, 干等人工签批的止损点, pending主管批准先汇报还是先空转轮询, 『可再次等待』不代表要一直发, 卡在外部进展上先让出等信号, 等待N次无变化先落状态再交回
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:b81d97a3-af1f-463a-9f1f-ac9cf885c32b:374:65824dbf2bada26b256f
evidence_refs: learning:learn:785c578401fc
created_at: 2026-11-17T07:29:23.288486+08:00
updated_at: 2026-11-17T07:29:23.288486+08:00
---
## Trigger
escalation_wait/审批等待类工具回执同时满足：①请求已创建且request_id已知；②状态仍pending且回执明示原因=人工未处理（外部决定者未行动）；③回执给出『可再次等待』与『向用户说明/改期』两个出口；④任务未定义等待参数与次数上限。

## Discriminator
阻断原因完全取决于外部人的面板操作——其发生时机agent既不能影响也不能预知；首次等待回执已携带完整当前状态与合法出口，因此下一次逐字相同的轮询不缩小任何未知量。『可再次等待』的措辞是选项而非重发指令。

## Short path
- 等待/审批轮询一次，取得含状态、原因、出口的完整回执
- 用回执的原因判定阻断是否外部人依赖、任务是否定义轮询预算；未定义则自设horizon（固定1-2次或TTL占比）并开始计数
- horizon内的重发若与上一回执逐字相同，计为重复调用并扣减剩余horizon
- horizon耗尽仍pending：立即写task_state账本（request_id、提交时间与TTL、当前状态、恢复条件、下一步链、source_refs回指回执）
- 向用户汇报精确阻断+恢复触发器后停止；收到外部状态变化（已批准/过期）才按新状态继续执行

## Stop conditions
- 回执状态发生变化（issued/批准/拒绝/过期）→按新状态执行，终止等待循环
- 自设horizon用尽→落账本+汇报+停止
- 环境重复调用护栏（如repeat_guard）出现→零次再发相同轮询，立即转账本与汇报

## Verification
- 每次重发前与上一回执做diff：状态、进度、TTL剩余均无变化→判为重复并计入horizon
- 落账本前核对必含字段齐全且source_refs能回指具体回执（请求回执、等待回执）
- 最终汇报逐项覆盖『汇报精确回执与阻断』：点名阻断、责任方、恢复触发器

## Counterexamples
- 任务书已定义等待参数+次数上限（如异步子代理结果轮询）：属bounded-blocking-polls卡辖域——按上限消耗预算原样重发，不因本卡提前汇报
- 轮询间存在可计算进度差异（如『第2/5步完成』、TTL剩余锐减）：回执持续产出新信息，按回执指引继续，本卡不适用
- 用户明示『原地等到批准』且给出时限：horizon已由用户定义，等待即任务本身，按时限执行，到点才转汇报
