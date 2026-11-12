---
method_id: resume-truncated-payload-at-cut-via-recovery-handle-2fe836ae5c7a
name: resume-truncated-payload-at-cut-via-recovery-handle
description: 子代理回答/长审阅正文在结算回执中被句中截断、而回执或紧邻 transport 块已给出带分页字段的恢复句柄（evidence_ref + next_start/complete）时，补读的首个读取应从截断边界开始：start 取已见字符长度、limit 按仍缺的用户点名字段选大，沿 next_start 链式续读，取到点名字段即停。不要从 0 重读已见头部（本集首探针 start=0 limit=200 纯浪费一次调用），也不要重发生产该回执的查询。
aliases: 被截断的回执从哪里接着读, 子代理回答只显示一半怎么办, 接着断点补读不要从头翻, 审稿正文截断后补全后半段, 恢复句柄从截断偏移开始读
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c098ec3f-654d-4621-b92f-9bd99e394118:0:d0ae7c1fa5dc6c04a25b
evidence_refs: learning:learn:2ea356d72ab8
created_at: 2026-11-12T13:08:22.925360+08:00
updated_at: 2026-11-12T13:08:22.925360+08:00
---
## Trigger
工具回执把长载荷（子代理回答、审阅正文、长报告）截断在中途，且同回执或其 transport 元数据暴露带 range 分页语义的恢复句柄（如 evidence_ref、next_start、complete:false），同时用户点名的必需字段（如逐条发现/计数明细）可证不在已见头部。

## Discriminator
截断点（已见字符数）已知 + 恢复句柄存在且带分页 + 点名字段不在已见内容 ⇒ 唯一未知量就是未见余段；下一次读取的 start 应等于截断偏移而非 0，limit 应按剩余未知量选大。

## Short path
- 终态后把用户点名字段清单与各回执已有字段做差集，确定哪些只存在于被截断正文
- 查询一次结算/child 面，记下回答被截断处的可见字符长度与恢复句柄
- 以 start≈可见长度、较大 limit 直接读恢复句柄，沿 next_start 链式续读
- 捕获到点名字段（计数+逐条内容）即停，即使尾部 complete:false 属与交付无关内容
- 汇报时引用 blob/range sha256 证明补读跨度的完整性

## Stop conditions
- 点名字段已从补读跨度取得且带完整性引用
- 恢复句柄耗尽（complete:true）仍无该字段 → 如实报缺失，不重发生产查询、不猜测补全
- 发现字段其实在已见头部 → 立即停止补读

## Verification
- 补读响应的 range.start 不小于此前可见长度（未重读已知头部）
- 引用的逐条发现与载荷正文枚举一致，且 range_sha256/blob_sha256 已记录在案

## Counterexamples
- 载荷完整显示、未被截断 → 直接引用即可，不补读
- 无恢复句柄但原工具支持显式 range/limit 参数 → 改用原工具参数化重查
- 终端态作业日志的结论块在尾部 → 先用大偏移尾探针定位尾端，顺序续读反而更慢
- 被截掉的只是与交付无关的样板/噪音 → 不追读
