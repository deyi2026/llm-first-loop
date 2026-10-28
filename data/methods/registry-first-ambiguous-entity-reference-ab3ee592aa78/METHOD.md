---
method_id: registry-first-ambiguous-entity-reference-ab3ee592aa78
name: registry-first-ambiguous-entity-reference
description: 用户用口语化标签（如『本地那个判断模型』）指代某实体且指代不明确时，先查该实体类的权威注册表（model_catalog/服务清单），而不是全仓文本搜索：自然语言标签在语料中只会命中 fixture 文案与 site-packages 噪音。注册表无匹配实体时，把标签视为功能描述查 records/memory 定位实际承担该功能的机制；仍无法唯一化时，用有界候选列表向用户澄清，并同时先给出与指代无关即可成立的结论。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:772ada61-13b9-4021-9c80-9d2916e05c61:7:a9a5d2e78f5a6038b05b
evidence_refs: learning:learn:ca53369dbc8d
created_at: 2026-10-15T20:07:23.967299+08:00
updated_at: 2026-10-15T20:07:23.967299+08:00
---
## Trigger
用户请求以口语化/含指示词的标签（『本地那个X模型』『那个服务』）指代某实体，指代对象不明确，且环境对该实体类存在权威注册表（模型目录/服务清单/配置中心）

## Discriminator
待解未知量是『指代哪个实体』而非『术语出现在哪』：首次全仓内容搜索的命中被 site-packages 测试串与 fixture 文案主导，这一回执本身即证明该自然语言标签不是 artifact 名，此搜索分支应终止，改查实体注册表获得候选全集与属性

## Short path
- 识别未知量为实体指代 → 直接查询该实体类的权威注册表（如 model_catalog），得到本地实体全集与关键属性（尺寸/能力/角色）
- 注册表无匹配『判断/分类』类实体 → 把标签降级为功能描述，查 records/memory 定位实际承担判断功能的机制（如 _is_simple_task 词面路由规则）
- 需要时做一次有边界的术语核查（限定 docs/、排除 venv 与 .releases 副本），确认术语仅为 fixture 措辞而非实体名
- 候选集仍不唯一 → 向用户给出≤4 个具体候选澄清，同时先交付与指代无关即可成立的结论（如两类东西构不成替代关系的类型学判断）

## Stop conditions
- 注册表全量 + records 已把候选缩到有界集合，且已区分『指代无关结论』与『待澄清项』
- 术语被证实只存在于 fixture 文案/第三方测试串中，非实体名，停止同族语料搜索
- 某次搜索回执已被噪音主导（site-packages/eval 结果占满）后，不再对同一关键词发起更多内容搜索

## Verification
- 答案中列出的本地实体与注册表实测一一对应、覆盖全量无遗漏
- 每个澄清选项都对应一个已核实的具体实体或机制（有 provenance），而非猜测名称
- 指代无关结论的依据（模型类型/能力/历史失败实证）均来自本集工具回执

## Counterexamples
- 实体类没有运行时注册表（如指某个脚本或文档文件）→ 全仓搜索才是正确第一跳
- 标签本身是独特标识符（如 judge_model_system_instruction）→ 语料搜索直接命中，无需先查注册表
- 注册表可能滞后于未登记的 WIP 本地改动 → 须以 records/语料补充，不能只信注册表
- 指代物在系统之外（用户记忆中的外部模型）→ 注册表枚举只覆盖内部候选，仍必须问用户，不可强行内部归因
