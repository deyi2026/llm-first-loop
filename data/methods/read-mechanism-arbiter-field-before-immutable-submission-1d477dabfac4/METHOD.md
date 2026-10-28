---
method_id: read-mechanism-arbiter-field-before-immutable-submission-1d477dabfac4
name: read-mechanism-arbiter-field-before-immutable-submission
description: 症状≠机制：把症状性观察（如短 history、计数骤降）当作某机制的实例证据写入不可撤回提交物前，必须先读能唯一仲裁竞争机制的专用权威字段（epoch/counter/round/changed 类）；若断言依赖的主信号曾被记录为阴性、或仲裁字段尚未读取，断言须降级为'未定因观察'。本集把'短 history'当压缩实例提交 evolution，提交后的边界检查才读到 compaction_epoch=0、last_request.round=5，被迫多轮文档补救并向用户公开更正；将这一次廉价仲裁读取前置，即可首发即正确。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:881d9c3f-2c5a-47a8-b605-9596af0a61b1:119:59a98631ac9edf00f659
evidence_refs: learning:learn:74b63c79ab8a
created_at: 2026-10-17T08:18:24.976721+08:00
updated_at: 2026-10-17T08:18:24.976721+08:00
---
## Trigger
准备把基于症状的因果断言（例：'短 history = 压缩已发生'）写入不可撤回/难撤回的提交物（evolution 提案、发布文本、正式报告），且运行时存在能唯一区分竞争机制的专用权威字段（epoch/计数器/round/changed 标志），或断言所依赖的主信号在既有记录中已被标为阴性

## Discriminator
断言成立要求专用信号已被读取且为阳性；只要存在一个廉价仲裁字段未读（如 epoch、round、prefix_changed），或文档已记录'主信号本次未见'，则症状存在≥2个候选机制（如程序压缩 vs run 边界组装口径），断言不得作为提交物中的实例证据，必须降级为未定因观察

## Short path
- 起草提交物时逐条列出其中的因果断言、其依赖信号、以及该症状的竞争机制集合（如 压缩 vs run 边界）
- 对每条断言检查两件事：专用信号是否已读且阳性？是否存在尚未读取的仲裁字段（epoch/round/changed）？
- 存在未读仲裁字段时，提交前做一次廉价权威读取；若回执截断且关键字段落在省略区，先完整 hydration 读到字段值，不凭可见片段外推
- 按仲裁结果改写提交内容：确认机制则保留实例证据；仲裁阴性则降级为'未定因观察'并登记，必要时把提案适用面扩大到全部竞争机制后再提交
- 提交后的工作单元边界检查仅作复核，不再承担首次事实裁决

## Stop conditions
- 提交物内每条'实例/证据'类断言均可指回一个已完整读取的仲裁字段值
- 确认不存在任何仲裁字段且断言已显式标注为推测/未定因
- 提交物为纯行为/格式内容，不含对运行时机制的因果断言

## Verification
- 重读提交正文：不存在仅凭症状支撑的机制断言
- 截断回执中被省略的关键字段已通过完整读取确认，而非由可见段推断
- 提交后无需追加'人工审阅时请以修正为准'类补救编辑，也无需向用户公开更正已提交内容

## Counterexamples
- 专用信号已阳性确认的历史事件（机制唯一且已验证），提交前无需重复检查
- 提交物可低成本撤回或编辑（非 immutable），事后检查+修正的顺序可接受且代价更低
- 仲裁字段自身语义/作用域未核（如 epoch 是 run 级还是会话级未知）时，应先把字段语义列为未核验点，不得把语义未知的字段当作裁决依据
- 纯静态分析任务，无运行时状态可查
