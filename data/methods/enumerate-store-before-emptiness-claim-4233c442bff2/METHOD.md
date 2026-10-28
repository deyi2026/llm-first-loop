---
method_id: enumerate-store-before-emptiness-claim-4233c442bff2
name: enumerate-store-before-emptiness-claim
description: 检索 0 命中只证伪查询词，不证伪存储。本集两次用自造短语搜 evidence 均 0 命中，误报『evidence 是空的』并怀疑重启；改为一次 list_evidence 即见 29 条、抽读两条即证实扫描内容仍在，真正原因是 prompt 侧压缩（prefix_broken、history 压扁）。方法：在做『数据不存在/丢失』断言前，先用枚举工具直接检验存储条数并抽读正文；归因用进程/会话元数据（started_at、session_id、recovery 计数）；后续检索改用存储自身词汇（回显标题、命令文本、label/source 字段），不再换自造短语重搜。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:881d9c3f-2c5a-47a8-b605-9596af0a61b1:57:d09907947218fa35d6d0
evidence_refs: learning:learn:df16c5bfd0d7
created_at: 2026-10-17T07:56:31.593421+08:00
updated_at: 2026-10-17T07:56:31.593421+08:00
---
## Trigger
对内部 evidence/session/memory 存储做语义或关键词检索返回 0 命中，且即将据此向用户断言『内容不存在/丢失/为空』，或把感知到的缺失归因于重启/清理等外部机制时

## Discriminator
miss 回执的措辞以查询为前提（『未找到匹配 "<query>" 的…Evidence』），只证伪查询词、不证伪存储本身；同时该存储配有枚举类工具（如 list_evidence），一次调用即可返回总条数、时间戳与 source 标签；且存储正文多为原始命令回显/标题文本，与自造的任务抽象短语无词面重叠，0 命中是必然而非数据缺失信号

## Short path
- 第一步只解决『存储里有没有东西』：调用枚举工具拿总条数+时间戳+source 标签，而不是继续换查询词重搜
- 若条数非空，按时间戳/source 挑 1-2 条直接 hydration/read，验证正文是否即用户所指内容
- 需要归因（是否重启）时比对元数据：进程 started_at 与全部条目时间戳、session_id 是否变化、recovery/backup 计数
- 解释『为何此前以为空』时查 prompt 侧指标（context_usage 的 history/tool_results、prefix_stability），区分存储丢失与上下文压缩
- 后续如仍需检索，改用存储自身词汇（回显标题、命令文本、label/source 字段），禁用自造抽象短语

## Stop conditions
- 枚举回执条数非零且抽读正文与目标内容一致：『丢失/为空』分支立即关闭，不再补搜
- 归因链闭合：全部条目时间戳晚于进程启动时间、session_id 未变、recovery pending=0
- 枚举回执显示存储确为 0 条时，才转入『真正丢失/被清理』假设并查清理与备份记录

## Verification
- 任何『非空/未丢失』断言必须引用枚举回执的总条数与至少一条已 hydration 的正文
- 任何归因断言必须引用具体元数据字段（started_at/session_id/pending_count），不得以『搜不到/没印象』代替
- 若结论包含具体数字（计数类输出），需定位到对应条目的正文后才可复述，抽样未覆盖的数字显式标注未核实

## Counterexamples
- 检索回执本身显式报告与查询无关的总体计数（如『存储共 0 条』）时，回执已是直接证据，无需再枚举
- 存在按确定性 key 的查找且 key 已知时，key miss 即较强缺失证据，全量枚举反而更贵
- 目标内容预期在外部系统而非本存储时，枚举本存储不能证明任何缺失
- 枚举代价无界且检索工具已返回覆盖性命中清单（已知相关项全部命中）时，停止变体词重搜即可，不必全量枚举
