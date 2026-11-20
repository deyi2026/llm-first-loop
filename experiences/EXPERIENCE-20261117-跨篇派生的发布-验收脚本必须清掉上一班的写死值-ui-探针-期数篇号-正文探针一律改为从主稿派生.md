---
title: 跨篇派生的发布/验收脚本必须清掉上一班的写死值：UI 探针、期数篇号、正文探针一律改为从主稿派生
scenario: "LFL 推广第 95 期（d95，2026-11-17 晚班）把上一班（d94）的发布/验收脚本直接 sed 派生：_d94_publish.py → _d95_publish.py。sed 只替换了文件名里的篇号（daily94→daily95、d94→d95），但脚本内部**写死的作品管理页卡片探针** `const t='计划改到一半'`（d94 标题前 6 字）原样留下；同类写死值还有：_d95_public_verify.py 的正文探针列表（含「游离 HEAD」「1,917」「3e0202b5」等 d94 内容探针）、reviewpkg 系列的「第 94 期，午班 13:00 班」。若不逐个核对就跑到 pageman/public_verify，作品管理页会按 d94 的标题去匹配卡片 → 定位到**上一篇**的稿子，风险是误判状态、误取 pgc id、误改已发布内容。"
root_cause: ""
solution: "派生跨篇脚本后，必须做一次「写死值全量扫描」再运行：(1) 列出上一班脚本里所有非 ASCII 字符串、期数、篇号、图号、探针文本；(2) 逐个判定该值是「从稿件派生」还是「上一班专属写死值」；(3) 写死值一律改为从主稿派生（例：作品管理页卡片探针改为从稿件标题首段切片注入 JS 字符串，而不是写死字面量）；(4) 派生后用 grep 反查旧值残留为 0（注意：命中上一班自己的历史回执属正常，不算残留）。本次 d95 把探针改成 `__TITLE_PREFIX__` 占位 + 用 TITLE[:6] 注入，并把 public_verify 的 KEYS 换成 d95 专属探针（并逐个验证 20 个 key 确实出现在正文里）。"
evidence: "docs/promotion/_d95_publish.py:129（sed 后仍为 const t='计划改到一半'，本班改为从 TITLE 派生注入）、docs/promotion/_d95_public_verify.py:20-30（d94 的 KEYS 列表含「游离 HEAD」「1,917」「3e0202b5」）、docs/promotion/_d95_reviewpkg*.py（期数写死为「第 94 期，午班 13:00 班」）；处置记录见 /tmp/d95_patch_publish.py 的断言式替换与最终 grep 复查（残留仅落在 d94 自己的历史回执里）。相关既有卡：experience:EXPERIENCE-20260903-parallel-line-drift-callsite-enumeration（并行线导致旧 callsite 清单漂移）、experience:EXPERIENCE-20261102-引用自己仓库的行号必须 grep -n 实测"
tags: [promotion, d95, 派生脚本, 写死值, 发布链路]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-17T23:10:34.386500+08:00"
updated_at: "2026-11-17T23:10:34.386500+08:00"
---