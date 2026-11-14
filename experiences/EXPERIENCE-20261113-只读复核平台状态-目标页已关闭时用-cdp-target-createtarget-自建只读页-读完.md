---
title: 只读复核平台状态：目标页已关闭时用 CDP Target.createTarget 自建只读页，读完即关
scenario: "LFL 推广晚班收口时需只读复核已发表作品在头条作品管理页的审核状态（d84，2026-11-13 20:00 班）。跨班后上一班用于发布的编辑器 target（6F2D…）已被关闭：宿主 browser_perceive 的 binding_page_id 仍指向这个已不存在的 target，CDP /json 列表里也没有作品管理页（只剩一篇旧公开文与消息页）。沿用旧 target_id 的复核脚本直接扑空，拿不到列表状态。"
root_cause: 把平台状态复核绑死在「上一班留下的 target」上；target 是会话级临时资源，跨班必然失效，必须能在无既有目标页时自建只读入口。
solution: 改用 CDP browser 级连接（/json/version 的 webSocketDebuggerUrl）发 Target.createTarget 新开标签页直达作品管理列表页 → 轮询等 readyState=complete 且 innerText 长度>300 → Runtime.evaluate 只读 DOM 文本取状态 → 读完立刻 Target.closeTarget 关闭自建页。全程不点击、不提交、不修改任何平台内容；平台状态回执落 receipts/d84-platform-status-2000.json（status=已发布，closed_new_tab=true）。
evidence: "本班实证：第一次复用旧 target_id 的 _d84_status_recheck_2000.py 无作品管理页可读；改用 Target.createTarget 后读到 d84「已发布」（展现 200，20:01:33 CST）。回执 receipts/d84-platform-status-2000.json（closed_new_tab=true，errors=[]）；公网复验 receipts/d84-public-verify-2000.json（verdict=PASS，114/114 可比行绑定）。"
tags: [cdp, read-only, toutiao, promotion, cross-session]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-13T20:03:23.078475+08:00"
updated_at: "2026-11-13T20:03:23.078475+08:00"
---