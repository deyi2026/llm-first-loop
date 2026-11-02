---
method_id: closed-line-status-from-final-acceptance-doc-5d4cad025c9f
name: closed-line-status-from-final-acceptance-doc
description: 被问某条已具名能力/工作线「完善得如何」时：先由 goal/coordination 状态判别该线是 in-flight 还是已收口。已收口（活动 goal 均属其他线/会话）⇒ 状态的权威载体是该线的终验收/收口文档，最近的 git 收口提交信息会直接点名它；用线名词根做文件名检索+git log 定位，跳过通用关键词文档扫与重复 goal 核对。报告须继承文档的「已交付×验证深度」不对称与未验证边界清单，线外遗留单独列出，不拍平成单一等级。
aliases: 问进展先查终验收文档, 完善得如何怎么答, 收口线进度汇报, 没有进行中目标时报进展, git收口提交指路验收文档
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e96054d1-d0eb-4746-93ca-d1f9d169b214:131:ca6da3bb097a3933507d
evidence_refs: learning:learn:d7f312079eb1
created_at: 2026-11-01T20:52:05.637910+08:00
updated_at: 2026-11-01T20:52:05.637910+08:00
---
## Trigger
用户询问某条可具名工作/能力线的完成度或进展（如『X 和 Y 完善得如何』），且 goal/coordination 回执显示该线不在 in-flight 集合（唯一活动 goal 属于其他线或会话）

## Discriminator
进入检索前已知两件事：所问线名可具名（词根可直接做文件名检索）；coordination 回执已显示唯一 in-flight goal 属于别的线 ⇒ 该线状态已沉淀在收口产物里，终验收文档就是为回答此问题而写的权威载体。此时通用关键词扫 docs 既不必要也不命中（本集 miss 回执列出的全是别的线的安全文档）。

## Short path
- 查 goal/coordination 状态：所问线是否 in-flight？是⇒转读活任务 checkpoint/回执，不走本路径
- 已收口⇒用线名词根（如 desktop / browser tooling）做一次文件名检索，拿到设计书+merge 回执簇，确认该线制品命名
- git log --oneline：最近收口提交的信息会点名交接书/终验收文档——据此做精确文件名检索定位该文档，而非再做关键词扫
- 读终验收文档：提取部署基线标识、逐能力交付与证据等级、未验证边界清单、线外遗留
- 按侧组装答案：交付完整度与验证深度分开陈述，明示哪些是裁决接受而非实测、哪些边界不得当已验；停止

## Stop conditions
- 终验收文档已读，且其部署基线与当前已知部署一致，边界与遗留提取完毕
- git log 显示收口提交之后仍有触及该线的提交/部署变更⇒停止照搬文档结论，转读增量或复验

## Verification
- 收口提交信息点名的文档与实际读到的文档一致，防读到同名旧版
- 文档自述的真值源（设计书/过程档案）与文件名检索命中的簇互相印证
- 该线收口提交之后无新提交；文档内 live 证据日期不早于其声明部署基线的启动时间

## Counterexamples
- 所问线有活动 goal（in-flight）：状态以 checkpoint/活回执为准，旧终验收文档已过期
- 收口后又合入补丁或更换部署：文档结论过期，需按增量提交重新裁决
- 用户问的是『现在这台机器上某动作是否真的好使』，或该能力从未做过收口验收：记录文档不代替当次实测，应走逐动作最小实测+事后状态断言
- 线只有零散 commit、没有验收/交接文档：无可引权威产物，按覆盖面如实估计并声明证据缺口
