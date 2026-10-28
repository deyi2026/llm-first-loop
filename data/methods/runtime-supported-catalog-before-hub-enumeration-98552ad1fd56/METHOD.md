---
method_id: runtime-supported-catalog-before-hub-enumeration-98552ad1fd56
name: runtime-supported-catalog-before-hub-enumeration
description: 为已（初步）锁定的运行时挑选要下载的模型/工件时，把运行时自带的 supported-models catalog（README 专节、已装包的模型目录）当作候选全集与兼容性门槛：先消费它得到按任务组织的短名单，hub 枚举只用于给短名单补决策元数据（体量/许可/热度），最后分级下载+分链路实测、对不达标候选显式降级留因。本集摩擦：README 已抓到手且 TOC 已显示 Supported Models 区节时，仍先做了 omni 全家系 hub 枚举并连写三个探针脚本；这些信息本可由 catalog 定向阅读 + 一次只查短名单 id 的探针覆盖。
aliases: 选本地模型先看运行时支持表, 下载模型前先读 supported models 清单, 先短名单再查 hub 元数据, 语音栈选型先跑通 catalog 再探 HF, 别先枚举模型库再看 README
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:963f2568-3f7b-47ed-980e-eea2b5783a95:46:2a25848c42d3c5b6cf70
evidence_refs: learning:learn:507ed27f18de
created_at: 2026-10-23T13:32:06.106196+08:00
updated_at: 2026-10-23T13:32:06.106196+08:00
---
## Trigger
任务要求为某个已选定的运行时/框架（如某平台原生推理库）挑选并下载一批模型/插件，且该运行时的权威文档已经抓取或可一键抓取、内含按任务组织的 supported-models/catalog 区节。

## Discriminator
已抓取 README 的 TOC/正文已明确显示存在 Supported Models 类区节——该区节同时编码兼容性（运行时能加载谁）与任务维度（按 STT/TTS/STS 组织、语言、精度、体量、链接），当时即可作为候选全集；而 hub 全域枚举不携带任何兼容性信息，枚举出的量化变体大多运行时根本不支持。

## Short path
- 按平台/生态约束锁定运行时，抓取其 README 并定向读 supported-models 区节：未知量=该运行时到底能加载哪些候选
- 按任务需求维度（流式/语言/体量预算）从 catalog 过滤出短名单，每任务 1-3 个：未知量=谁进必下 Tier A
- 一次有界 hub 探针只查短名单 repo id 的元数据（参数量/许可/下载量）：未知量=决策表所需的体量与许可列
- 读短名单各 family 的 README 拿使用契约（采样率、收尾调用、流式档位）：未知量=落地坑
- 安装运行时后枚举已装包内模型目录，校验与 README 表版本一致；后台下载 Tier A
- 分链路实测（ASR 首字/LLM 首字/TTS 首字节与 RTF），对不达标候选显式降级并记录实测原因，产出分级清单

## Stop conditions
- 短名单内每项都同时持有 catalog（README 表或已装包模型目录）与 hub 元数据两方回执
- Tier A 全部下载完成并通过端到端冒烟；被否决/降级项均已附实测原因，不再扩大发现面

## Verification
- 最终推荐表中的每个模型 id 都能在运行时 catalog（README 表或 site-packages 模型目录）中找到对应实现
- hub 探针的 params/许可字段与下载文件的实际体量一致（至少抽查 Tier A）

## Counterexamples
- 运行时尚未选定、任务本意是跨框架全景选型 → 单一运行时 catalog 会过早收窄候选，应先做权威站点全景枚举
- 决策关键维度 catalog 不含（第三方质量榜单、显存实测）→ catalog 只定候选集，不能替代该维度取证
- README 主分支与已装 release 可能漂移、且决策依赖新近加入的模型 → 必须以已装包内模型目录枚举为准，README 表只是线索
