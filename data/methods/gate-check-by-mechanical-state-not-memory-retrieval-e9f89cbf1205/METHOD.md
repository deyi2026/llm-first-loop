---
method_id: gate-check-by-mechanical-state-not-memory-retrieval-e9f89cbf1205
name: gate-check-by-mechanical-state-not-memory-retrieval
description: 高成本/难撤回动作（全量测试、push、发布）受成文闸门约束时，不要依赖经验库语义检索来'想起'闸门：检索词常按任务主题组织，命中不了按失败模式落档的 lesson（本集：改 src/ 后直接跑全量漏闸，用户指正后 76 次调用才补救完）。改为在动作发生点机械判定：受闸路径 git status --porcelain 非空 + 即将执行受闸动作 + 无覆盖当前产物 SHA 的回执或豁免 → 先派只读独立审查，PASS 才继续。触发判据由动作类型与仓库状态驱动，不由检索命中率驱动。
aliases: 又忘了跑全量前要独立审查, push 前这道闸检索想不起来, git status 非空先别推, 改了 src 先派个审查
status: candidate
source_model: workbuddy/hy4-preview
source_episode_refs: episode:e3d65611-a839-42fc-bf6f-fae957ddf6cf:1211:355aef2687544d8d4222
evidence_refs: learning:learn:6cfcf1ac62d8
created_at: 2026-10-15T07:58:14.780061+08:00
updated_at: 2026-10-23T05:53:14.027612+08:00
---
## Trigger
仓库存在成文过程闸门（如'代码全量测试前/push 前/发布前须独立子代理审查'类规则），当前任务即将执行该类高成本/难撤回动作，且事前的经验/记忆检索未必命中相关 lesson 卡

## Discriminator
三条当时即可机械观察的事实同时成立：① git status --porcelain 在受闸路径（src/ tests/ scripts/ tools/ webui/ 等）非空；② 下一步动作就是受闸动作本身（跑全量/推送/发布）；③ 回执目录中无覆盖当前被审产物 blob SHA 的既有回执，且书面豁免类（用户明示豁免/纯注释文案级/既有回执且 SHA 未变）均不成立。三者齐备即闸必须先走，判定不需要任何检索命中作前提

## Short path
- 写码完成、即将跑全量测试/push/发布的那一刻：跑 git status --porcelain <受闸路径>，并查回执目录是否已有覆盖当前 blob SHA 的回执
- 非空且无回执无豁免 → 立即固定被审对象（文件清单+工作区 blob SHA），spawn 只读独立审查子代理（任务书+SHA），此步优先于一切其他后续动作
- 绑定该 child_id 等待结算：wait/query 同一 id，不重复加载 skill、不重跑 setup、不在未结算时派第二个审查 child
- 按三态 verdict 分支：REVISE→修订+窄复审；PASS→才执行受闸动作；回执落盘（verdict+findings+被审 SHA+豁免记录）
- 豁免成立时在回执或答复中明示豁免类别与依据，然后继续原任务

## Stop conditions
- 受闸路径 porcelain 为空，或 diff 仅注释/文案级 → 闸不适用，记录判断后直接继续
- 既有回执覆盖且产物 SHA 未变，或用户明示豁免 → 记录依据后继续
- 回执已落盘且 artifact_sha256 与被审工作区 SHA 一致 → 审查分支结束，回到原任务主链

## Verification
- 回执中的 artifact_sha256 == 被审工作区 blob SHA
- 事件轨迹中 spawn 审查发生在全量测试/push 启动之前（时序可审计）
- 豁免情形在回执或答复中如实记录类别与依据；无落盘回执不得声称'已审查'

## Counterexamples
- 仓库没有成文闸门规则的新环境：无判据来源，不应凭空发明审查流程
- 纯文档或注释级改动（属豁免类）：机械非空判据须叠加 diff 类型过滤，否则误拦正常任务
- 既有回执覆盖且 SHA 未变、或用户明示豁免：条件③不成立，直接继续，重派审查是浪费
- 用户明确指令与闸门结论冲突：以用户指令为准但如实记录分歧，不机械 BLOCK
