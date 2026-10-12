---
title: sanitize_slug 中文标题修复真实验证：同日中文经验不再塌缩冲突
scenario: "sanitize_slug Unicode 修复（commit 9e8f3abd9）上线时只有单测证据；生产语义是\"中文标题经验同日不再塌缩冲突丢经验\"，且修复当天 experiences/ 已有修复前塌缩的 EXPERIENCE-20261010-untitled.md——若修复未生效，当天任何中文标题保存都会与其同 slug 冲突被拒。"
root_cause: ""
solution: 在已存在当日 untitled 文件的真实条件下保存不同中文标题经验：应落盘为 EXPERIENCE-YYYYMMDD-<中文slug>.md，不与 untitled 冲突、不覆盖。历史塌缩文件（18 个）内容完好无需迁移，仅文件名丢标题。旧契约保持：同日同标题（同 slug）仍 FileExistsError，重试安全。
evidence: "本会话 2026-10-10 21:54 两次 save_experience（中文标题）均返回 success 且文件名含中文 slug；ls experiences/ | grep untitled | wc -l = 18 与 docstring 记录一致；commit 9e8f3abd9（回归测试 test_sanitize_slug_preserves_cjk_and_keeps_ascii_legacy）"
tags: [experience-store, sanitize-slug, unicode, cjk, live-verification]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-10T21:55:50.251731+08:00"
updated_at: "2026-10-10T21:55:50.251731+08:00"
---

修复语义三层：(1) sanitize_slug 用 \w 保留 Unicode，纯中文标题不再塌缩为空；(2) save() 的空 slug 兜底从固定 "untitled" 改为 untitled-{title_sha256前8位}，纯符号标题也互相区分；(3) 同日同 slug 仍是 FileExistsError 不覆盖（重试幂等契约不变）。真实验证当晚完成：experiences/ 已存在修复前塌缩的 EXPERIENCE-20261010-untitled.md（内含一条真实中文标题经验），修复后同日保存两条不同中文标题经验均成功落盘、untitled 未被触碰。当前性验证：ls experiences/ | grep 20261010 应同时看到 untitled 与两条中文 slug 文件并存。