---
method_id: event-stream-first-for-runtime-emitted-verdict-tokens-cac4ae68dcc7
name: event-stream-first-for-runtime-emitted-verdict-tokens
description: 查找某个标记/判定 token 的历史出现位置时，先按该 token 的生产者选择搜索介质：由活会话运行时发射的判定（探测的 VISIBLE/MISSING、sentinel 回复、会话内决策文本）只存在于事件流，应以 event_stream 内容查询直达；仓库/配置/测试类 token 才用文件内容搜索。文件搜索 0 命中不是『不存在』的证据，而是介质选错的信号，不应升级为目录级枚举补救。事件流返回的带时间戳配对事件（秒级相邻的相反判定）还直接支撑单变量归因，替代结构性假设枚举。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:abda90a9-c633-4664-b777-2ef993c8f7d9:32:3aef8c3043dc445ff608
evidence_refs: learning:learn:8ae00e58c02c
created_at: 2026-10-05T22:48:05.809689+08:00
updated_at: 2026-10-05T22:48:05.809689+08:00
---
## Trigger
需要定位一个由运行时会话发射的 token（探测/哨兵判定字符串、会话内 llm_decide 内容等）的历史出现位置，而当前默认动作是对文件系统做内容搜索或目录枚举。

## Discriminator
进入搜索前已可见：该 token 类的全部已知实例（如 6 次 SUBJECT_BINDING_MISSING）均以 event_stream 中 `action.llm_decide llm_response content=<token>` 形态出现，带 session id 与时间戳，文件系统中从未出现该类实例——其生产者是会话运行时，不是仓库文件。

## Short path
- 按生产者给 token 分类：会话运行时发射 → 事件流；配置/代码/测试/schema 标识 → 文件搜索
- 会话类 token 直接用 event_stream 按 token 内容查询，一次取回全部实例（含配对事件、session id、时间戳）
- 需归因时仅读取配对事件指向的具体 session 记录，diff 各臂可观测属性（channel/进程/model/tools_count）；只差一个变量即归因于该变量的瞬态行为，再决定是否需要最小确认矩阵
- 文件搜索 0 命中时立即改判『介质错误』转事件流，不做 ls/全库 grep 级枚举补救

## Stop conditions
- 事件流已返回该 token 的实例与 session 标识，足以进入归因/引用，不再扩大文件枚举
- 目标事实已由配对事件 diff 加必要最小复测（n≥10 矩阵 / echo 逐字探测）验证

## Verification
- 事件流返回实例的形态与已知实例一致（llm_decide content + session id + 时间戳）
- 归因结论须满足：配对事件除单一变量外其余可观测属性一致，且事后最小复测不与归因矛盾

## Counterexamples
- token 本身是仓库工件（配置开关名、测试名、schema 常量）——文件搜索才是正确介质
- 探测框架按设计把结果落盘为结果文件/报告——应搜盘而非查事件流
- 事件流无内容查询能力、已轮转或无目标会话记录——回退到持久化日志/落盘产物
