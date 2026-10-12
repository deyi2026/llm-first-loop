---
title: "知乎编辑页二态：/write 可合成粘贴，/p/{id}/edit 只认 insertText/按钮"
scenario: "知乎专栏 CDP 自动化：/write 新建页 与 /p/{id}/edit 已存草稿页 对注入行为不一致"
root_cause: ""
solution: 新文章全流程在 /write 完成（合成 paste 正文+图片+声明+发布）；改已发布文章的小段文字在 /edit 用「selectNodeContents + CDP Input.insertText」替换后点「更新」；不要在 /edit 尝试合成 paste 或 Cmd+V
evidence: "receipts/20261012-daily10-submit.json tail_fix_round 节；19:33–19:47 会话内 /write 合成粘贴成功（LEN 2786/2579、2 图 loaded）与 /edit 合成粘贴 LEN=0 的对照回执；尾注替换 insertText 前后 grep 断言均通过"
tags: []
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-12T19:51:05.331596+08:00"
updated_at: "2026-10-12T19:51:05.331596+08:00"
---

知乎 /write 接受合成 ClipboardEvent paste（text/html+text/plain、图片 File paste 均可），声明菜单项在 Popover；/p/{id}/edit 的 DraftJS 拒合成 paste，真实剪贴板+Browser.grantPermissions+Cmd+V 也不行，但 CDP Input.insertText 与按钮点击正常。锚点用 div[data-block=true]（不是 p）。已发布文章编辑页保存键文案是「更新」。另有一次教训：编辑补丁因目标串差两字断言失败，被误读为成功，错误措辞上线两站——写后必须 grep/shasum 复核（回执 tail_fix_round 节有完整记录）