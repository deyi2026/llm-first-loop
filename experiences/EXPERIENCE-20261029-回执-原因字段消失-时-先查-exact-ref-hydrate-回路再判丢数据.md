---
title: "回执\"原因字段消失\"时，先查 exact-ref hydrate 回路再判丢数据"
scenario: "工具回执只给出汇总状态（如 halt_reason=action_receipt_status:rejected）而无原因码；需要判断这是生产者未产生、投影阶段丢弃，还是可通过引用回取。"
root_cause: 紧凑投影为控体积只透出白名单字段，生产者写入的 reasons 与 retry.reason 被丢弃；但完整 receipt 已持久化且 receipt_ref 出现在回执里，通过已装配的 receipt_store.hydrate 可回取。
solution: "按五段链路逐段取证：①生产者（含拒绝码唯一事实源）→②落 receipt 的字段位置（completeness.reasons / retry.reason）→③汇总层只投影状态→④紧凑投影是否透出原因与是否透出 receipt_ref→⑤是否存在 exact-ref hydrate 回路（查工厂装配处 injected hydrator）并用 live 调用实测 hydrate。若⑤成立，定性为\"可观测但不可发现\"的可用性缺陷（P2），修法是新增投影字段而非改写已钉住的词表；不可定性为数据丢失。"
evidence: "live 复现：navigate http://127.0.0.1:8931/t2.html 得 halt_reason=action_receipt_status:rejected + receipt_ref=browser-operation-receipt://v0.1/a5d57f4e…；browser_perceive hydrate 该 ref 返回 completeness.reasons=[\"navigate_host_blocked:ip_blocked:127.0.0.1（私网）\"]。代码：browser/action.py:737-756（生产者）、_compact_projection :1834-1950（投影）、factory.py:1471（hydrate 装配）。"
tags: [receipt-observability, projection-vs-producer, browser-tooling, root-cause]
source:
  session: 本会话 2026-10-29 深挖 navigate 拒绝原因
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-29T10:07:19.319049+08:00"
updated_at: "2026-10-29T10:07:19.319049+08:00"
---