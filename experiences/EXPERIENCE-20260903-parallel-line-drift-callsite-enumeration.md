---
title: 并行线导致旧 callsite 清单漂移：实施前按当前树重枚举
scenario: "给被多线并行改动的核心服务方法（如 DuplicateGuardService.synthesize_blocked_receipt）加必填参数时，基于早期 grep 的行号/调用清单直接编辑，全量门跑出 2 条新增红（TypeError: missing required keyword-only argument）"
root_cause: ""
solution: 签名变更后的 callsite 枚举必须用「定义处全项目反查 + 逐条看完整调用形态（多行调用 grep 单行号会漏）」双确认；并行线同文件重构后行号/形态都会漂移，编辑前以当前树实测为准；修完肇因后 src 变更必须重跑全量权威门（不能只跑定向测试）
evidence: ""
tags: [插桩, callsite-枚举, 多行调用, 行号漂移, fail-open]
source: {}
status: active
qualification: 2026-09-18 batch2/3 per-file review: retained（methodology self-evident：步骤可机械复现或含实测细节；evidence 内嵌正文）
record_kind: lesson
verification_state: unverified
created_at: "2026-09-03T16:37:28.249878+08:00"
updated_at: "2026-09-11T19:55:09.647912+08:00"
---



当前适用性说明：历史案例使用 DuplicateGuardService 作为当时的签名变更对象；可迁移原则是“当前定义 + 当前 callsite 才是真值”，不是复活该历史服务。