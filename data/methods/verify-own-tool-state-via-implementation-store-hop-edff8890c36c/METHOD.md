---
method_id: verify-own-tool-state-via-implementation-store-hop-edff8890c36c
name: verify-own-tool-state-via-implementation-store-hop
description: 需要核实某个由本系统自身注册工具产生状态流转的资源（如 submit_evolution 提交的提案是否 accepted）时，若常规渠道（search_records/event_stream）只回内容不带状态字段：沿“状态写入者=该工具的实现代码”这条 provenance 边走一跳，从代码常量中取得唯一权威 store 路径（如 audit_dir/evolution_suggestions.jsonl），再对目标 id 做一次精确 grep。一次实现读取+一次定点查询，替代对 data/audit/*.jsonl 的全量 grep（含超时）、全工作区 search_files、以及目录逐个试探（submissions/drafts 目录只存载荷不含状态，是死端）。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f1523846-ee16-4c78-9f53-7abf782eac2b:68:524e98aec9db4552c9d3
evidence_refs: learning:learn:d6ecb85c53d1
created_at: 2026-09-30T00:15:32.893503+08:00
updated_at: 2026-09-30T00:15:32.893503+08:00
---
## Trigger
用户要求核实某项当前状态（回执称新状态 accepted，要求自行核实），该状态由会话自身注册的工具（如 submit_evolution）写入；首次记录/事件查询命中提案内容但未暴露 status 字段，搜索空间开始向全审计目录/全工作区扩散。

## Discriminator
状态的写入者是已知且在仓内的：工具 schema 从第 0 轮就在上下文中（submit_evolution 注册于 src/llm_loop/introspection/），其实现声明唯一权威存储路径（EvolutionStore → evolution_suggestions.jsonl）。代码是实现状态的 provenance 边，比任何内容搜索都更早、更精确地把候选位置缩到一。

## Short path
- 明确未知量：目标 id 的当前 status 字段存在于哪个记录文件、由谁写入
- 沿工具名一跳到实现文件（src/llm_loop/introspection/evolution.py），读取 store 路径与状态机取值
- 在该 store 文件内精确 grep 目标 id，提取 status 与 decided/reviewed_at 时间戳
- 与用户回执（时间+新状态）互证一致后立即停止发现，进入执行链（v2.2 supersedes v2.1）

## Stop conditions
- 已从实现代码声明的权威 store 中取得目标 id 的 status 与时间戳，且与人工回执一致
- 记录/事件渠道本身已直接返回目标状态字段（无需进入本方法）
- 工具实现不在仓内：改用该外部系统的官方查询接口，而非本地文件 grep

## Verification
- grep 命中的文件路径与实现代码中声明的 store 常量一致（非碰巧同名）
- status 字段与 reviewed_at/decided 时间戳和回执内容相互印证
- 替代关系（新提案 supersedes 旧提案）从记录正文确认，用于决定执行哪条链

## Counterexamples
- search_records 或 event_stream 已直接给出目标 status 字段：读取即停，不要再去读实现源码
- 状态由纯外部系统（外部面板/数据库）写入，本地 store 不存在或可能滞后：应走该系统自身查询通道（对应 fresh-read-authoritative-record 场景），不适用本地实现跳转
- 任务只需提案正文/原则内容而非状态流转：记录系统检索已足够，读实现属冗余动作
- 对同一 store 已有直接引用边（此前已 grep 过该文件）：直接复用路径，不重新推导
