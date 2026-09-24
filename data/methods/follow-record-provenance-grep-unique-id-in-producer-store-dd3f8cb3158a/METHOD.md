---
method_id: follow-record-provenance-grep-unique-id-in-producer-store-dd3f8cb3158a
name: follow-record-provenance-grep-unique-id-in-producer-store
description: 索引/记录类查询（search_records）只返回带唯一 ID 与时间戳的截断预览、而任务需要完整正文与当前状态时，不要转向无关通道（event_stream）或枚举目录（猜目录名、ls 全仓、逐层 ls data/）。最早扩散点就在预览到手之后：应沿记录自身的 provenance 链（kind→生产工具→其写入的 session/evidence store）用唯一 ID 做定点 grep 取全文与状态。本集靠此最终命中会话文件，但之前已烧掉 event_stream、目录猜测、全仓 ls/find、data/ 两段全量枚举等约十余次无信息调用。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7d3df8c3-848b-4bf3-b66b-1dbd2f791ac4:102:39b7ca17f360865dabbf
evidence_refs: learning:learn:55b96b54d2de
created_at: 2026-09-23T12:57:23.350662+00:00
updated_at: 2026-09-23T12:57:23.350662+00:00
---
## Trigger
1) search_records/索引命中记录但正文被截断，任务需要完整载荷（如建议全文+执行方案）才能行动；2) 需核实某条记录的当前状态（如人工审批是否落库）；3) 记录携带唯一短 ID 与精确落库时间戳。

## Discriminator
命中记录自带近似唯一的标识（EVO 短 ID）+ kind/生产工具（submit_evolution）+ 精确时间戳。这意味着全文必然存在于生产工具当时写入的 store（session 日志或 evidence 库，路径在最早的 search_files/ls 结果中已可见），唯一 ID 即可把『答案可能在任何地方』缩成『在这类 store 里 grep 这个 ID』；状态问题则归同一记录接口所有，不归工作区事件流。

## Short path
- 用同一记录接口按精确 EVO ID 查询状态（未知量：审批是否落库），不切 event_stream 等无关通道
- 在生产者 store（data/sessions/、data/evidence/）内 grep 唯一 ID，定位载荷文件（未知量：全文在哪）
- 只解析命中的 submit_evolution 写入条目，抽出完整正文与执行方案（未知量：要执行什么）
- 编辑目标按其声明的唯一真相源路径直读结构（如规则文档标题行自指的 docs/ai_rules.md），不再枚举目录（未知量：改哪里）
- 执行改动+跑验证+登记 executed，收到回执即停

## Stop conditions
- 全文已从 ID 匹配的生产者记录中取得，且标题与预览一致
- 当前状态由记录接口确认，时间戳与人工回执一致
- 编辑目标是声明的真相源文件，测试/登记回执已落

## Verification
- 提取的正文包含同一唯一 ID 与预览可见的同名标题
- 状态字段的时间戳与回执时间对得上（如 12:25:48Z≈20:25 本地）
- grep 命中数少且集中于单一 store；若多处命中，取最新时间戳并核对 evidence_ref

## Counterexamples
- 预览已包含执行所需全部信息——直接行动，不追全文
- 记录接口本身支持按 ID 水合全文——直接水合，跳过 grep
- 载荷只存于外部系统（web 面板数据库）不在磁盘——一次限定范围 grep 未中后，宽发现才是正当的
- 唯一 ID 在大量备份/镜像文件中重复出现——grep 也需按 store 限定范围，否则同样扩散
- 状态查询有专门的 state/审批队列接口——直接查它，而非从会话载荷里倒推状态
