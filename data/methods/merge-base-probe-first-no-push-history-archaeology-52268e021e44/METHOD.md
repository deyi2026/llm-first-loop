---
method_id: merge-base-probe-first-no-push-history-archaeology-52268e021e44
name: merge-base-probe-first-no-push-history-archaeology
description: 向拓扑关系未知的远端 ref 同步本地批次前，先用一次廉价结构探测定历史关系（merge-base + 远端提交数/根父检查），再选方案：空 merge-base + 单根快照 tip ⇒ 历史无关，按文件级 delta 组装增量提交、嫁接到远端根提交后 fast-forward 推送；有共同祖先 ⇒ 正常 range-diff/push。拓扑一旦确定，不要再翻 search_evidence/event_stream 找『上轮推送命令』：旧流程预设的远端状态可能已被重置，其结论通常被当前结构事实推翻（本集考古结果即被弃用，两次检索零决策增量）。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:179b3184-5b65-4276-8ed8-58ad424043e6:1689:fbcb701567cf1a3375a6
evidence_refs: learning:learn:d799900a6fa5
created_at: 2026-10-12T14:41:24.278147+08:00
updated_at: 2026-10-12T14:41:24.278147+08:00
---
## Trigger
需要把本地提交/批次同步到远端 ref，但无该远端与本地是否共享历史的证据（远端可能被重置为快照仓库）；或对待推范围的无界对比返回异常庞大的提交列表。

## Discriminator
当时已可见：①status 回执中远端 tip 主题是快照式『llm-first-loop v0.6.31』，而本地 main 在其上的 v0.6.31 追记提交——同版本标签、两套 SHA 体系，提示历史无关；②随后机械回执确认 NO-MERGE-BASE 且远端 ref 仅 1 个无父根提交。任一事实即可把候选空间从『枚举全部待推提交 + 考古推送历史』缩成『单次拓扑探测 → 文件级 delta → 嫁接远端根』。

## Short path
- 读 status/远端 tip；未知量=本地与远端的历史关系。注意 tip 主题是否快照式且与本地版本提交不同 SHA。
- 一次结构探测：git merge-base HEAD <remote/ref>；为空或远端仅单根提交 ⇒ 判定孤儿快照仓库，跳过无界范围枚举。
- 按已知批次范围取文件级 delta（如 git log --name-only <batch-range>）并核对快照存在性；未知量=哪些文件进增量提交。
- 版本面：读约束性测试（如 test_version_consistency.py）取得必须同步 bump 的权威文件清单与 tag 校验，而不是逐个猜文件。
- 增量文件嫁接到远端根提交之上 fast-forward 推送；代码小修先读守卫测试确认放行格式再改，用既有 .venv 跑测试。
- 远端 CI 全绿即停止；不再检索历史会话寻找推送先例。

## Stop conditions
- merge-base 探测返回共同祖先 ⇒ 切回正常 range-diff/push 流程，拓扑调查结束。
- 拓扑 + 文件级 delta + 版本面清单三事实齐备即行动，不再对 search_evidence/event_stream 做推送方式考古。
- 远端 CI/权威校验通过且本地测试通过（本集：三 workflow 全绿 + 19 passed）即收官。

## Verification
- 推送为 fast-forward 且新提交的 parent 是远端原根提交，未使用 force。
- 推送后核验远端 Release/CI(tag)/CI(main) 全绿，证明快照增量未破坏公开面；本地版本一致性测试先于推送通过。

## Counterexamples
- 远端与本地共享历史（merge-base 非空、ahead/behind 有限）：走正常 branch/push/PR 流程，不得嫁接或强推。
- 存在对该镜像的显式常设约定（如指定快照生成脚本、main 受保护必须走 PR）：跟随具名约定，结构推导让位于 standing procedure。
- 任务本身就是『查明上次如何发布/推送』的审计请求：event_stream 考古即任务本体，不适用本方法。
