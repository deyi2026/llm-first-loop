---
title: search_files「无匹配」不能当存在性反证（实测假阴性）
scenario: 在 llm-first-loop 工作区用 search_files 按文件名 glob 找文档，返回「无匹配」。
root_cause: ""
solution: search_files 的「无匹配」不可作为文件不存在的证据（glob 匹配语义与 find 不一致，且对部分目录静默失效）。判断存在性用 execute_command 跑 find/ls；search_files 只在命中时采信，未命中换 shell 复核。审查类任务中，凡以「search_files 未命中」推出的否定结论都应降级为「未核验」。
evidence: find 三文件全命中 vs search_files 同 pattern 无匹配；审稿报告「方法论备注」记录探针过程（recovery_ref=ac7043018e1a…）
tags: [search_files, false-negative, find, 存在性判断, 审查纪律]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-12T22:11:28.658471+08:00"
updated_at: "2026-10-12T22:11:28.658471+08:00"
supersedes: [EXPERIENCE-20260930-search-files-find]
---

本回合两次实证：(1) search_files(pattern=*card-lifecycle*) 与 *I3-schedule-rebet* 均返回「无匹配」，但 find 确认 ./docs/design/DESIGN-20261012-card-lifecycle-governance-v1.md、./docs/governance/card-lifecycle.md、./docs/promotion/PLAN-20261012-I3-schedule-rebet.md 都存在；(2) 独立审稿人（子代理）用确然存在的 docs/governance/card-lifecycle.md 做探针同样得到「无匹配」，并将全部依赖 search_files 的核验项降级为「无法核验」。
正确做法：存在性判断一律用 execute_command 的 find/ls；search_files 命中可用，未命中不可作为不存在证据；审稿报告里据此把「文件不存在」类断言改写为「检索通道未命中」。
适用边界：当前工作区版本实测；换工具版本需复测探针。