---
title: "分段读长文档时，未读完就下\"未见\"结论"
scenario: "核验 Claude Code hooks.md 的事件表，我分段读（每次 4000 字符）到约 2 万字符就判定 MessageDisplay 事件\"不存在/存疑\"，并据此把文章一条正确论断降级。同时反向过度纠偏：把\"hook 可代批工具调用\"从 settings hook 挪到 mod 名下。"
root_cause: "把\"读到的范围\"当成了\"文档的全部\"，并用它反推外部论断的真假；缺少对\"我已覆盖哪些结构\"的清点。"
solution: "长文档必须读到决策控制表/专章这类结构化锚点之后才下\"不存在\"结论。1) 事件是否存在以 Decision control 表和 per-event 表为准，不以叙述性正文为准；2) 看到缺失不要立刻推出\"文章错了\"，先问\"是否我读的范围不够\"；3) 纠偏要双向校准，既不能放过真错，也不能把对的降级。"
evidence: "续读 evidence://v1/50ec784f5d11ec15da7a763c0ab69e1889ad359b07f03e917454b1effc3c55db 到 88000 字符后，Decision control 表明确列出 MessageDisplay(displayContent) 与 PermissionRequest(decision.behavior allow/deny)，直接推翻前一轮判断。"
tags: [verification-discipline, doc-reading, self-correction]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-18T16:53:03.269663+08:00"
updated_at: "2026-10-18T16:53:03.269663+08:00"
---

当前性验证：重跑 web_fetch https://code.claude.com/docs/en/hooks.md 后用 read_evidence 读 text_char 76000-84000 区间，应能看到 Decision control 表中 MessageDisplay(displayContent) 与 PermissionRequest(decision.behavior allow/deny) 两行；若表已改名或换 URL，则前一轮判断需重新核。