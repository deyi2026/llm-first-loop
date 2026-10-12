---
method_id: symbol-anchored-discovery-from-authoritative-record-5d918f856541
name: symbol-anchored-discovery-from-authoritative-record
description: 当任务起点是一份权威记录（人工审批/演进条目/工单/traceback），且记录文本已点名精确代码符号（函数名、错误reason、文件名、schema字段）时，把这些符号当作代码定位的provenance锚点：逐符号做定向搜索并限定项目自有src/tests路径；不要先用宽泛概念词（如'restart'）全库搜索——会撞上同名无关特性（restart_required配置热切换）；也不要无过滤内容搜索——.venv/site-packages依赖噪音会挤占命中窗口。符号全部映射到代码位置后即停止发现、进入实现。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:32d694c9-dbcd-4dc8-a941-0885c617868c:1759:c94c6fdca1891e5af713
evidence_refs: learning:learn:c3c4dceeca96
created_at: 2026-09-20T08:51:33.421854+00:00
updated_at: 2026-09-20T08:51:33.421854+00:00
---
## Trigger
任务由持久化权威记录驱动（审批回执、演进/工单条目、traceback、事件流），记录内容已出现可在代码库定向命中的精确标识符，下一步是定位并修改相关代码

## Discriminator
记录文本中是否已列出精确符号清单（如函数名rearm_wake_grants、错误码repair_failed(prefix_mismatch)、文件名schedule.json这类近唯一命中键，且这些在首次检索时即已展示），以及搜索可否限定到项目自有路径、排除.venv/site-packages/temp；满足即可把全库候选缩成逐符号的少数命中

## Short path
- 用记录ID检索权威记录确认状态，同时提取其点名的全部精确符号/文件/错误码，形成锚点清单（未知量：是否批准、要改哪里）
- 对每个精确符号做定向search_files，范围限定项目src/tests，命中即得落点文件与行号（未知量：各子任务代码位置）
- 只读命中文件的结构概览与命中行所在区段，确认现状实现（未知量：当前实现形态）
- 按记录优先级实现与验证；仅当某符号未命中或语义不符时，才退回概念词搜索或模块结构浏览
- 全部符号映射完毕且修改文件集与锚点清单一一对应后，停止发现进入收尾

## Stop conditions
- 记录点名的每个符号都已映射到具体文件/函数并读过相关实现
- 最终修改文件集合可与锚点清单一一对应，不再产生纯概念词搜出的候选

## Verification
- 最终diff涉及的每个文件都能反向追溯到记录中的某个点名符号
- 定向搜索结果中不出现.venv/site-packages依赖文件或同名无关特性占据命中窗口

## Counterexamples
- 记录只有自然语言意图描述、无任何代码符号 → 精确锚定无从谈起，需概念搜索+模块结构浏览，本方法不适用
- 点名符号是常见词（如'restart'）且项目内存在多个同名特性 → 精确命中退化为宽搜索，应先读模块结构区分特性再定位
- 点名符号属于第三方依赖内部（如SDK自带的prefix_mismatch枚举）而非本项目代码 → 未限定路径时命中全是vendor噪音，必须先限定项目路径否则锚点失效
