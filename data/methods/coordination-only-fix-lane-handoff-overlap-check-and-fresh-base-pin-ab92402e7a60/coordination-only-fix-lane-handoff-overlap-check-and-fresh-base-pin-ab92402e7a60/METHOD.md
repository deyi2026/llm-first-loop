---
method_id: coordination-only-fix-lane-handoff-overlap-check-and-fresh-base-pin-ab92402e7a60
name: coordination-only-fix-lane-handoff-overlap-check-and-fresh-base-pin
description: 受托为他人开发做『只协调、不改码』的修复Lane交接时：以共享协调注册表时间窗回执（逐lane列paths）为占用裁决面，将任务点名文件与各在途lane求交；base以本会话fresh fetch+rev-parse的origin/main为准，与任务给定值核对一致后才钉入登记；lane锁定恰好这组paths，既防后续碰撞也防误占policy-only等兄弟lane；经合同工具建Goal+Lane并取得CAS归属后记checkpoint交接。交接回执必须区分『已亲验』与『未读』：用一次廉价grep核对报告中最可证伪的片段，其余明确列为开发者首步核对项，不假称已核；协调者零代码修改、不push/merge。该模式在多agent仓库高频复现，固化它可避免lane冲突与失真交接。
aliases: 给别的开发开修复lane前怎么查占用, 只协调不改代码的交接流程, 转交bug修复前登记goal和分支, 开新lane时base提交怎么定, 协调回执里已核对和没核对怎么写
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:b81d97a3-af1f-463a-9f1f-ac9cf885c32b:195:d58c449e32700c6ac906
evidence_refs: learning:learn:1ef8de3227fe
created_at: 2026-11-17T01:50:02.503363+08:00
updated_at: 2026-11-17T01:50:02.503363+08:00
---
## Trigger
任务文本把本轮限定为『只做协调』：核对具名文件是否已被其他Lane占用→无冲突则建立独立Goal/Lane并返回base/分支建议/CAS归属→开发由另一主体执行；且存在共享Lane注册表（时间窗内全量列举各Goal/Lane及paths）作为占用裁决面。

## Discriminator
三个动手前即可判别的事实：(1)注册表回执按Lane逐条列出paths声明，目标文件与活跃Lane的交集可机械求出（本集唯一重叠来源是已收口的旧Lane）；(2)fresh fetch后origin/main tip与任务给定base逐字相等，可安全钉入；(3)自己的读回执只覆盖缺陷矛盾的一半（状态集合定义grep命中），双条件具体行未读——这条边界必须写进交接而非掩盖。

## Short path
- 一次批量只读git操作：fetch origin main、rev-parse tip并与任务给定base比对；只拉取具名目标文件的存在性与近期历史，不做全仓枚举
- 核对主树对目标文件无脏改；顺手用一次廉价grep核对缺陷报告中最可证伪的片段（如状态集合定义），如实记录哪些行未读
- 读协调注册表时间窗全量回执，把具名paths与每个在途/已收口Lane的paths求交；兄弟Lane（如policy-only）按其声明paths归类
- 交集仅含已收口Lane时：按任务原文登记Goal（开发者/模型/收口闸）与Lane（base_main_sha、分支建议、恰好锁定的paths），取得lane id+version的CAS归属
- 记checkpoint；最终回执给出无冲突证据、已验/未验分界清单、以及边界声明（协调者不改代码、不动兄弟Lane、不push/merge）

## Stop conditions
- 目标paths与某个活跃Lane的paths声明相交：不登记，转冲突协调并如实回报，不得强行建Lane造成双归属
- fresh fetch的origin/main与任务给定base不一致：先回报差异并对齐，不得静默钉入一个没人要求的基点
- 任务改为要求你本人开发：本方法的协调交接边界失效，转入正常修复工作流（RED先行等）

## Verification
- 登记的base_main_sha等于本会话内rev-parse出的origin/main现值，而非陈旧本地引用或仅凭任务文本
- Lane锁定的paths集合恰等于任务点名文件（不得是超集，避免误占兄弟Lane的变更面）
- 交接前已拿到CAS归属回执（lane id+version），而非仅口头宣告
- 最终回执包含显式的『未核验项』清单交给开发者，而不是宣称整份缺陷报告已确认

## Counterexamples
- 具名paths与活跃Lane相交时不得套用：此时登记会制造并行双写，正确动作是冲突裁决而非『先登记再说』
- 任务把开发指派给你本人时不得套用：『零代码修改』的协调边界不再适用，套用会把可动手的修复任务空转成纯登记
- 缺陷报告的决定性片段无法用一次廉价读取核验（需真实跑失败路径或依赖外部系统状态）时不得半核验：整份转交并声明未验，半验不缩小任何未知量
- origin/main已越过任务给定base时：rebase决策属于开发者与请求方，先回报SHA差异，不要自行替人选新base登记
