---
title: "微信公众号群发被\"未认证\"阻断：确认框走完不等于发布成功"
scenario: "微信公众号 mp.weixin.qq.com 图文编辑器：点\"发表\"弹群发通知确认框，走完\"继续发表\"后弹窗消失，看似成功，实则文章未发出"
root_cause: "平台在账号未认证时不真正下发群发请求，前端确认流程却走完，UI 层没有任何错误反馈，形成\"假成功\"。"
solution: "【成功判据】不能以\"对话框消失/URL 未变\"判断发表成功。必须独立回读发表记录页确认目标标题出现在列表中；同时检查编辑页 URL 的 type 参数（type=77 为草稿态，type=10 为已发表）。草稿箱列表（type=10&action=list_card）是异步渲染，直接取 innerText 会返回空，需等待或换判定方式。【平台硬门槛】账号\"未认证\"时群发会被静默拦截：确认框照常弹出、按钮照常可点、点完弹窗照常关闭，但发表记录里不会新增条目。这类阻断无法用技术手段绕过，必须先完成微信认证。当前性验证：下一次发布前先在编辑页执行 document.querySelector('.weui-desktop-list') 附近查找含\"未认证\"的叶子节点，返回其 innerText；若为\"未认证\"则不要尝试群发，直接向用户索要认证。"
evidence: "回执 evidence://v1/5926dd51（发表记录页仅第19期）+ evidence://v1/30dfa5be（编辑页 type=77, 账号\"未认证\"）"
tags: [浏览器自动化, 微信公众号, 发布验证, 假成功]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-19T16:43:56.771759+08:00"
updated_at: "2026-10-19T16:43:56.771759+08:00"
---