---
method_id: identical-truncation-author-provenance-first-dda883f6db50
name: identical-truncation-author-provenance-first
description: 当从权威存储取回的目标正文被截断、且第二个独立视图在同一位置给出逐字相同的截断文本时，将截断判定为展示/存储层属性：对该存储换参数重查、或横向枚举其他存储（文件搜索、其他流），都不会返回更多内容。此时先核对内容出处：若 action_trace/上游记录显示该条目是本会话自己提交的（全文在自身上下文/提交记录中），且可见头段已含可执行语义核心，则直接基于头段+自身修订上下文执行，对截断尾句显式标注不臆测补全。只有当作者是外部方、或头段缺少可执行语义时，才需要先沿出处恢复全文。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:863879fe-d8f5-48d9-bbdc-6ddc6eaf4b8b:18:2fb05fb7e9c902d0ad3d
evidence_refs: learning:learn:8939b4557dcf
created_at: 2026-09-19T03:09:11.708717+00:00
updated_at: 2026-09-19T03:09:11.708717+00:00
---
## Trigger
任务要求按某条已批准/已提交内容的全文逐项执行，但取回的记录正文被截断；尤其是该条目由本会话此前自己提交的情况。

## Discriminator
两个独立视图（search_records 与 event_stream）在同一字符处返回逐字相同的截断文本 → 截断是展示层属性而非查询参数问题；同一事件流中还包含本会话自己提交该条目（含修订对照）的 action_trace → 全文的权威出处是自身先前提交，不在待枚举的文件或其他流中；且头段已含可执行核心（'强制披露+人工门'+阶段1条款）。

## Short path
- 按唯一 ID 各取一次记录与事件流：未知量=批准状态是否属实（accepted 与人工回执一致）
- 观察两视图同一位置逐字截断 + action_trace 显示作者是本会话：未知量=全文从哪恢复 → 判定展示层截断、出处即自身提交上下文
- 不再对同一存储换参重查、不做文件系统枚举；以头段语义核心+自身修订对照为可执行正文，截断尾句显式不臆测
- 直接落地为 method candidate（save_method_candidate），不登记 evolution_complete（其验证门槛是下一次真实使用）
- 汇总双源核实与遗留说明，停止

## Stop conditions
- 批准状态已由权威记录/事件与人工回执双源一致确认
- 可执行正文的来源已明确（头段核心+自身提交上下文），截断部分已显式声明不臆测
- 批准内容已持久化为 candidate 并取得 content_hash 回执

## Verification
- 状态核实走双源：人工回执 + 存储记录/事件流一致
- 落地回执含 content_hash，可事后校验正文未被篡改
- 最终答复显式声明全文依据与截断遗留限制，未伪造被截断的尾句

## Counterexamples
- 条目由外部作者（用户/他人）提交，且截断尾部包含必须遵守的条件或限制 → 必须先从权威源恢复全文再执行，不能凭头段语义推进
- 两次视图截断位置不同，或截断点在任何可执行语义之前 → 可能是查询/检索参数问题，对同一存储换参重查是合理的
- 头段只有标题、无任何条款语义 → 头段不足以执行，应沿出处边恢复全文；出处不明时才横向枚举存储
