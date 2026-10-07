---
method_id: verify-load-bearing-citations-at-type-matched-carrier-cf9489cf557d
name: verify-load-bearing-citations-at-type-matched-carrier
description: 当本轮要依据一条自己上轮引用、但本会话尚未读到原文的断言（如'某实验已否决某形态'）做裁决时，先按断言类型匹配权威载体类别，再发起检索，而不是按渠道串行扫库。本仓库可观察事实：文件搜索命中显示代码注释以实验 ID 标签（# T23、# EVO-…）承载实验/任务结论，记录库内容则是 lesson/experience 卡——因此'实现/实验史'类断言的类型匹配载体是实现相邻的代码注释、设计文档与测试，文件内容检索一跳直达。结构化渠道（records/docs/archive）的 miss 回执只证明该渠道没有，不构成继续换下一渠道的命令。类型匹配载体未命中时，把引用降级为未证实并明示修正，而不是扩大扫描。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9571992a-d742-4a48-824b-b1f635b8674f:1650:49930440c2fff781e9bb
evidence_refs: learning:learn:6c5f85db53cb
created_at: 2026-10-07T14:22:38.267638+08:00
updated_at: 2026-10-07T14:22:38.267638+08:00
---
## Trigger
本轮裁决依赖一条来自先前轮次、对结论 load-bearing 的断言（如'09-24 实验已否决列表注入'），其原文在本会话尚未读到；且首个渠道检索已返回明确 miss 回执，下一动作倾向于继续换渠道逐个扫库（records→docs→archive 轮流试）时。

## Discriminator
断言类型与当时已见载体类别的匹配：miss 之前，search_files 命中已显示本仓库用带 ID 的代码注释承载实验/决策结论（factory.py 中 '# T23: …'、'# EVO-20260814: …'、'# M48/P6 (design §5.3): …'），而记录库可见内容为 lesson/experience 卡且对该断言已回执未命中。'某实验否决了某实现形态'属于实现史断言，其类型匹配载体是代码注释/设计文档/测试，不是记录库；miss 回执只是单渠道负证据。

## Short path
- 先分类 load-bearing 断言（实现决策/实验结果/用户历史/流程事件），列出各类型在本环境的权威载体类别，再决定检索去向
- 实现/实验史类断言：直接用文件内容检索命中实现相邻文件（注释、设计文档、测试，带实验 ID 标签），一跳读取原文
- 从原文提取确切边界（被否决的形态、触发条件、对照证据/run ID），据此把新提案与被否决形态逐维 diff
- 类型匹配载体未命中时不串行扫其余渠道：把引用降级为'未证实'，在结论中明示修正或放弃该依据
- 原文边界一旦取得并完成 diff，即停止检索

## Stop conditions
- 已在类型匹配载体中读到原文，取得被否决形态/结论及其证据引用（file:line 或 run ID）
- 类型匹配载体全部未命中：引用降级为 unverified，输出修正说明，不再做渠道扫描

## Verification
- 裁决文字引用原文位置（file:line 或 record ref），而非对上轮的记忆复述
- 新提案与被否决形态的每条边界差异都能指回原文引文或对照 run ID
- 最终输出中所有仍无原文支撑的引用被显式标注为未证实

## Counterexamples
- 断言是用户历史/教训/偏好类：记录库才是类型匹配载体，不应改道代码搜索
- 代码注释可能与当前 runtime/schema 漂移：注释只作指针，终局结论仍需以现行权威面（测试、生效配置、活跃记录）校验
- 断言对当前决策不构成依据：不值得花检索去验证，标注未证实即可继续
- 该环境没有'代码注释承载实验结论'的观察证据（无 ID 标签命中）：此时按既有归档渠道扫描才是正确路径
