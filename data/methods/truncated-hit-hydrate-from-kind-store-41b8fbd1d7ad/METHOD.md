---
method_id: truncated-hit-hydrate-from-kind-store-41b8fbd1d7ad
name: truncated-hit-hydrate-from-kind-store
description: 当检索回报命中记录但内容在句中被截断、而任务需要全文作写入/执行依据时：把回执视为带稳定 id/kind 的封顶投影，直接到该 kind 的 durable 落盘存储按 id 取全文，并用记录元数据（status/human override/impact）交叉核验授权。不要换关键词重查同一索引——同一记录+同一显示上限必然返回同一截断投影；也不要为找'已被定位对象的存放处'启动全库内容扫描。本集 search_files 60s 超时、空 rg、3 次同义变体重查共耗约 7 步，而 ls data/audit + 按 id 读 jsonl 两步即得全文。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0e1e3567-343d-44ae-b119-9a2d6a9ee4c5:51:a9a805c894cb1f88fb25
evidence_refs: learning:learn:336cd4f67266
created_at: 2026-10-13T03:24:18.049703+08:00
updated_at: 2026-10-13T03:24:18.049703+08:00
---
## Trigger
record/检索工具回执出现'命中但内容句中截断'（断词断句收尾或明确标注片段），而下游动作需要该记录完整正文作为唯一依据（写入、执行、逐字引用）。

## Discriminator
回执含稳定记录 id/kind 且内容断在句中——这证明完整对象已存在于 record store，截断只是显示层封顶；因此下一跳应指向该 kind 的 durable 存储（按 kind 命名的落盘文件或记录 ref 的 ranged 读），而非同索引换词重查或全库扫描。

## Short path
- 确认截断是显示层事实（断词/断句收尾、无 complete 标志），锁定稳定 id；当前未知量=该记录全文
- 沿 record 体系的有界路径定位 kind 的落盘存储：一两次 ls（如 data/、data/audit）即可，不启动 search_files 或无范围 rg 内容扫描
- 在 kind 存储中按稳定 id 精确读取全文与元数据（status、human override、impact_files 等）
- 用元数据与用户回执逐项交叉核验状态与授权，成立后才执行下游写入/执行动作
- 执行后按既有门禁机械校验（写后复读/守卫测试），发现阶段到此为止

## Stop conditions
- 已从 kind durable 存储取得与批准 id 一致的全文，且 status/授权字段与用户回执互相印证
- 定位 store 的有界尝试（≤2-3 次 ls/路径探测）失败，此时才升级为更宽的发现手段

## Verification
- store 记录的 id/status/批准时间与用户回执逐项一致，无 rejected/rolled_back 等冲突字段
- 写入内容与批准草案逐字一致，写后复读/哈希校验通过
- 若 store 是可能落后于实时状态的落盘快照，状态字段另用权威实时查询核验，全文与状态分开取证

## Counterexamples
- 回执内容已完整（自然收尾或带 complete/range 到末尾标志）——没有缺失对象，直接使用，不进 store
- search 返回的是 miss（'未找到匹配，不伪造结果'）——索引里确实没有该内容，此时换源或扩大范围是正当路径
- 记录只在 API 层暴露、无落盘文件可读——应走记录 ref 的 ranged/hydration 读取，而非 ls 文件系统
- store 文件可能过期且记录状态有并发写者（审批状态刚变更）——全文可从文件读，但授权/状态必须以实时权威查询为准，不得凭旧文件放行涉权动作
