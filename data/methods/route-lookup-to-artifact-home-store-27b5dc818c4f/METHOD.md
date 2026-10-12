---
method_id: route-lookup-to-artifact-home-store-27b5dc818c4f
name: route-lookup-to-artifact-home-store
description: 多存储环境下查证外部断言前，先按 artifact 类别路由到本会话已实证存有该类别的存储：治理记录（提案/回执/method 候选全文）用 search_records 按 kind+id 取；代码行为用工作区按 API 名内容搜索后读实现。某存储对某类别 miss 一次后，不再用同类别的其他标识符重试该存储，除非出现新的机制性理由。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:863879fe-d8f5-48d9-bbdc-6ddc6eaf4b8b:90:51c6d909d857156a06a6
evidence_refs: learning:learn:7a02e79bb673
created_at: 2026-09-19T04:33:36.295475+00:00
updated_at: 2026-09-19T04:33:36.295475+00:00
---
## Trigger
需要逐条核证审计/评审意见中的事实性断言，涉及多种 artifact（治理提案、执行回执、候选全文、源码实现、文档）且初始不确定各自存放位置。

## Discriminator
knowledge-at-time 均满足：search_records(kind=method/evolution/evolution_exec) 已分别精确返回候选全文、提案与 skipped/unverified 回执；而 0674fcc3 的文件搜索已 miss；模型自己也已写下“候选存储在记录系统内”。这些当时已可见的事实足以把“记录型 artifact 在文件工作区”分支排除。

## Short path
- 先发三次 kind 明确的 search_records（提案全文、执行回执、候选 exact 全文），每次解决一个未知量——本集已做，保留。
- 对哈希类断言做且仅做一次文件搜索测试；miss 即记录“该哈希无法在工作区独立核验”，语义核对直接使用记录系统已返回的候选全文，不追哈希进其他存储。
- 跳过对 method ref / EVO id 的文件搜索；改为按 API 名（record_use / task_benefit / record_qualification / evolution_complete）内容搜索定位源码，逐文件读取，每读对应一条待核断言（如 store.py 硬编码 not_evaluated → 断言1；evolution_complete 非 executing 拒绝分支 → 断言6）。
- 若记录检索被截断且需要全文，用已证明能返回 exact 全文的同类记录查询模式细化检索，或向 docs/文件镜像做一次性探测——而不是用 EVO id 搜文件。
- 全部断言各自获得“已核证/无法核验”归属后即停止取证，进入修订与结论输出。

## Stop conditions
- 每条待核断言已映射到回执行/代码行，或显式标注“不可核验”（如本集对 0674fcc3 的诚实弃核）。
- 某存储对某 artifact 类别从未命中、而另一存储已精确服务过该类别时，停止向该存储发同类查询。

## Verification
- 结论只引用本会话实际取回的证据：记录被截断时明示边界，不得宣称“全文坐实”（本集 evolution 记录两次均在阶段1处截断，阶段3 对比的证据边界应在成稿时声明）。
- 复核同 (存储, artifact类别) 组合的 miss 后重试次数为 0，除非附带新的机制性理由。

## Counterexamples
- store.py 显示 method 存在文件态 seed overlay（_load_path/runtime_path 拷贝）：若任务中候选尚未登记进记录系统、仅以 seed 文件存在，文件搜索反而是正解——判别依据是“该类别本轮实际被哪个存储服务过”，不是“永远别搜文件”。
- 记录检索存在硬截断且无 exact 全文查询路径时，向 docs/文件镜像做一次性探测是正确动作（本集 search_docs 试探即属此类新存储首探，不是重复摩擦）。
- 标识符同时出现在两类存储回执中时，命中/miss 路由推断不成立，应先探测成本低的一侧。
