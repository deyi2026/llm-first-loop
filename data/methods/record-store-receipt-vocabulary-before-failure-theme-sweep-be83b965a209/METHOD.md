---
method_id: record-store-receipt-vocabulary-before-failure-theme-sweep-be83b965a209
name: record-store-receipt-vocabulary-before-failure-theme-sweep
description: 评估『某类失败是否频繁/根因为何』（如：工具经常出错是否因权限围栏）时，权威证据往往已在结构化记录库：先读当前会话 exception_log 按类别枚举真实失败，再用回执/错误文案的字面词查 experience 记录库。干净 0 命中是词表错位信号——换字面词重查一次，而不是立刻扇出到事件流换词扫描和全库 grep。本集围栏主题在记录库有 8 条当日已验证记录（根因+修复 commit+规避法），宽扫描只是重复已知信息；另附两条机械修正：repo 命令先由 pwd/rev-parse 推导路径再执行；等待异步子代理用回执声明的 wait_seconds 上限阻塞等待，勿零等待轮询、勿在子代理未结算时结束回复。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b1e2c610-ff59-483f-a50b-9ef6586aaae0:983:addadedcf89714997c48
evidence_refs: learning:learn:bf17fa97e79f
created_at: 2026-10-14T18:07:50.931841+08:00
updated_at: 2026-10-14T18:07:50.931841+08:00
---
## Trigger
用户要求评估某类重复失败的真实频率、根因或是否被机制过度限制（例：『工具是否被权限围栏搞得经常出错』），且环境同时存在结构化记录（exception_log、experience 卡）与事件流/全文检索等多种证据源可选；或首次记录库关键词查询 0 命中、正准备换一组关键词去扫第二个源时。

## Discriminator
当时已读到的当前会话 exception_log 已逐条枚举真实失败类别（本集：参数错误、子代理取消、空哨兵输出——围栏拒绝 0 次），已能局部证伪『日常被围栏频繁拒绝』；且 search_records 首查 0 命中的回执是『干净未命中、不伪造结果』，说明库可用只是词表不对。这两件事共同把下一步从『再扫一个源』缩成『换对词表再查一次记录库』。

## Short path
- 读当前会话 exception_log/tool_history，按 error_type 归类全部失败——直接得到『经常出错』在本会话的分布与围栏占比（本集为 0）。
- 用回执/错误文案字面 token（如 fenced/unauthorized/围栏）查 search_records(kind=experience)；命中已验证卡即获得根因、修复 commit 与规避路径，停止证据采集。
- 若 0 命中：换回执字面词/场景词重查一次记录库（区分词表错位 vs 库空）；仍 0 命中才扩大到 event_stream/search_files，且每个源只查一次，不再换词重扫。
- 对记录所述结论做落地核验：先 pwd/git rev-parse 推导仓库根（不用记忆中的绝对路径），确认 fix commit 在 HEAD 祖先链。
- 异步子代理：用回执声明的 wait_seconds 上限阻塞等待至结算；子代理未结算前不结束回复（避免 cancelled_on_model_final 自动取消）。
- 失败分布+根因+修复状态三件齐备即成稿，不再追加确认性检索。

## Stop conditions
- exception_log 归类完成、记录库已验证卡给出根因与修复、且 commit 祖先关系核实后，立即停止扩大检索。
- 记录库两轮不同词表均 0 命中且本会话无该类失败 → 判定『无历史记录』，转入常规现场排查，不再换词查询。
- 不把 task_applicability=not_evaluated 的记录当作当前事实，只作线索并核验其指向的代码/commit。
- 子代理 verdict 回执到手前，不发布对其审查对象的终局结论。

## Verification
- 统计口径与 exception_log 逐条对账：每条失败可归入唯一类别、总数一致，无凭印象的占比。
- 根因/修复断言有双源支撑：verification_state=verified 的记录 + git 祖先链或代码行号。
- 关键词 0 命中的回执不得被引用为『该问题不存在』的证据。

## Counterexamples
- 全新失败主题从未入库：记录库天然为空，两轮查询只是空转，应直接现场排查而非依赖历史记录。
- 问题需要『此刻』状态（围栏现在是否正在拒绝）：当前会话事件流才是权威，历史 experience 卡可能描述已修复的旧态。
- 记录卡来自不同部署形态（fleet/非 fleet）或不同工具面：词表能命中但结论不可迁移，须先核对适用条件。
- exception_log 已显示该类拒绝高频发生：『答案已在库中』前提不成立，需要实时归因与修复，而非检索历史。
