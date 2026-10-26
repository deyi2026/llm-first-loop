---
title: 掘金发布：顶栏「发布」只开面板，提交需点面板内「确定并发布」
scenario: 在掘金编辑器里点顶栏「发布」后以为已提交，实际只是开/收发布面板；创作者中心「近期发布」没有该文章
root_cause: 顶栏「发布」是面板开关，语义与提交按钮同字但不同动作；页面上两个按钮同名同形易混淆。
solution: 掘金发布是两步：顶栏「发布」按钮 → 面板展开后（分类/标签/摘要/封面在此设置）→ 面板内「确定并发布」才是提交。判据：点顶栏「发布」后弹层里「确定并发布」按钮的 offsetWidth 为 0（面板收起），必须先让面板可见再点它。成功标志是跳转到 juejin.cn/published 且弹出「《标题》发布成功！」，随后创作者中心「近期发布」首位出现该文。发布后编辑器标签页会被关闭/重定向，属正常。
evidence: "evidence://v1/1ee9a34a4eeb3c58e5cf4b34a4dd7be9d2c3d6e0d4c1f6a5b3e2d9c8b7a6f5（发布前创作者中心仅 10-14/10-15 两篇）→ evidence://v1/23d9a2b7c1e4f5a6b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0（发布成功弹层 + 创作者中心首位）"
tags: [掘金, 发布流程, 浏览器操作]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-20T18:00:30.420611+08:00"
updated_at: "2026-10-20T18:00:30.420611+08:00"
---

当前性验证：复现路径 — 用 CDP 打开 https://juejin.cn/editor/drafts/new?v=2 ，填入正文后执行 Runtime.evaluate 取 .publish-popup 内 button 文本；若返回数组含「确定并发布」且其 offsetWidth===0，说明面板处于收起态，需先点击顶栏「发布」再点该按钮。当前性验证：发布后执行 Runtime.evaluate 读取 https://juejin.cn/creator/home 的 innerText，匹配「近期发布」段内是否出现新标题，可作为提交是否真正生效的判据。