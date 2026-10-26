---
title: "头条/知乎 md2html 转换前需把 ### 提升为 ##：转换器只认 ##，且平台小标题数闸门按 h1/h2 计数"
scenario: "文稿用 ### 写 4.1/4.2/4.3 三个子小节，经 md2html 转换后 ### 未变成标题（只渲染成加粗），导致平台侧小节数只有 6，不满足脚本内 sections>=7 的闸门，preflight 判为 invalid。"
root_cause: "md2html 转换器只把 ## 映射为标题，### 降级为加粗文本；平台发布脚本的章节数闸门按 h1/h2 计数，二者叠加导致闸门不通过。"
solution: |
  1) 投稿前先把 md 中所有 ### 子标题提升为 ##（或让转换脚本显式映射 ### → <h2>）；本站 md2html 仅把 ## 转成 <h1>/<h2>。
  2) 若脚本内有 sections>=N 或 h2_count==N 的硬断言，改稿后要同步更新 N，否则 prepare/preflight 会静默失败。
  3) 结构改动后必须整篇重新 paste（清空编辑器 → 重新粘贴），因为已插入的图片会随清空一起消失，需要重新逐张补插。
  4) 更省事的做法：先在 md 侧定稿并跑一次 convert 自查 h2 数与图注数，再进平台，避免平台内返工。
evidence: "article.md 将三处 ### 改为 ## 后，convert 输出 h2 数由 6 变 9，toutiao preflight 由 invalid 转为 valid（sections 9、chars 4570、7 图注）。"
tags: [md2html, heading, publish, preflight, toutiao]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-17T00:44:01.711599+08:00"
updated_at: "2026-10-17T00:44:01.711599+08:00"
---