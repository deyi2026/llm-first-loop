---
title: browser_operate 在知乎创作中心等页面上无法 click 按钮（无障碍名带不可见前缀），link 正常
scenario: "需要在知乎创作中心（/creator/manage/creation/article）删除指定的一行文章。该列表页无复选框/批量操作，三行的「更多」「编辑」「数据」「分享」按钮无障碍名完全相同，且所有按钮的无障碍名统一带一个不可见前缀字符（快照中显示为 name=\" 更多\"，text=\"更多\"）。"
root_cause: browser_operate 的 click 按无障碍名（accessible name）做精确 grounding。知乎在其交互控件的无障碍名前加了不可见前缀字符（疑似 U+200B），模型侧无法在工具调用参数中复现该码位，导致 name 永远匹配不上；而该页按钮又全部同名，即便能匹配也无法定位到具体行。两重限制叠加，使「按名点击指定行」不可行。
solution: "结论：这条路对当前工具不可行，应改为请用户手动操作，或换用能按 CSS selector / nth-child / href 定位的执行通道（如 playwright_exec，需用户 confirm）。具体证据：(1) projection_kinds=checkbox+radio 投影返回 0 个（共 974 个对象），截图亦无全选/批量删除；(2) browser_operate click 的 target 只接受 kind+name(+role)，三行同名无法定位；(3) 按钮类元素一律 target_not_found/match_count=0，而 link 类（如 name=\"文章\"）返回 match_count=1，说明不是全局匹配失效，而是按钮名带了无法复现的不可见前缀字符。"
evidence: "browser_perceive 投影 checkbox/radio = 0/974；browser_operate click name=\"文章\" kind=link → match_count=1 status=completed；click name=\"更多\"/\" 更多\"/\"回到顶部\" kind=button（含与不含 role 两种）→ 全部 halt_reason=target_not_found, match_count=0。"
tags: [browser_operate, grounding, zhihu, 工具边界, accessibility-name, 不可逆操作]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-10T19:59:10.860801+08:00"
updated_at: "2026-10-10T19:59:10.860801+08:00"
---