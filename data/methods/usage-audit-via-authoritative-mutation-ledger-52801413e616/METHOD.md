---
method_id: usage-audit-via-authoritative-mutation-ledger-52801413e616
name: usage-audit-via-authoritative-mutation-ledger
description: 审计『注册实体（方法卡/演进/资格）是否被真正使用过』时，不做关键词变体的宽泛枚举：早期记录已显示全部生命周期操作（save_candidate/refine/record_use/record_qualification）都经过同一个注册工具，因此一次性拉取该工具的完整调用台账（事件流按工具名过滤 tool_call 事件）并按动作动词分类，使用次数即对应动词的计数；设计讨论文本中出现该动词不算使用。台账分类完备即停止，不做补充扫描。空台账只证明『该通道无记录使用』，需另查旁证（如独立 qualification）区分『未回传』与『未套用』。本集在第4次调用后已可见台账通道，却继续三次换词搜索并在台账定论后再补扫，约多耗4-6次调用。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7d3df8c3-848b-4bf3-b66b-1dbd2f791ac4:339:556be6bad200d0fefe20
evidence_refs: learning:learn:372c9eb7333f
created_at: 2026-09-23T13:36:15.360761+00:00
updated_at: 2026-09-23T13:36:15.360761+00:00
---
## Trigger
需要回答『积累的 X（方法/演进/注册实体）有没有被实际使用、回传或应用』这类使用侧审计问题，且最初的检索结果已暴露该实体的所有生命周期操作都经由同一个注册工具或 API 通道落账

## Discriminator
第一次 method 检索与首次 event_stream(record_use) 的回执已同时给出两个事实：(1) 每条实体生命周期操作都以同一工具（method_manage）的 tool_call 事件形式落在事件流；(2) 关键词 record_use 的命中几乎全是设计讨论/schema 澄清（llm_decide 提案文本），不是执行回执。由此当时即可判定：权威账本=event_stream 按该工具名过滤的调用台账，一次查询即完备，无需对 usage/applied/record_use 等词反复换措辞搜索

## Short path
- 查实体注册表（method 池/演进列表）取得清单与 active/candidate 构成——未知量：池子多大、各处于什么状态
- 沿已确认的唯一变更通道拉完整台账：event_stream 过滤该注册工具名的 tool_call 事件——未知量：哪些生命周期动词被真实执行过
- 按动作动词分类台账（保存/修订/回传使用/qualification），使用问题坍缩为对应动词计数——未知量：record_use 类调用是否为 0
- 对唯一旁路证据（如独立 qualification 记录）做一次抽查，区分『无正式回传』与『从未套用』两种口径
- 台账分类完备即停止并输出缺口结论与根因（纪律以无约束力 candidate 形态落地），不做关键词变体补扫

## Stop conditions
- 台账已按动词分类完备，使用侧计数（含 0）已确定且口径明确
- 已找到或排除旁路证据，能区分『无记录使用』与『未实际使用』

## Verification
- 已分类的台账条数与事件流中该工具 tool_call 事件总数一致，无分页遗漏（核对 coverage/complete 标志）
- 被计为『使用』的每条记录确为执行回执（action.tool_loop 或工具返回），而非 llm_decide 中的提案/讨论文本
- 零计数结论带口径限定：仅指该注册通道无记录，并已声明不排除未登记的实际套用

## Counterexamples
- 被审计的属性没有唯一变更通道（如『这个函数在仓库任何地方被调用过吗』）：必须 broad grep/宽搜索，台账法不适用
- 注册通道从未被强制执行（回传是可选纪律且无 reminder 注入）：空台账只能表述为『无记录使用』，不能断言『从未使用』，须另找行为旁证后再下结论
- 事件流存在保留期/采样/截断：须先确认台账完整性（coverage、complete、时间窗覆盖）才能支撑零计数断言
