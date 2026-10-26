---
title: CDP dispatchKeyEvent 修饰键位：Shift=8 不是 1（1 是 Alt）——用错位表现为按键静默无效
scenario: 通过 CDP Input.dispatchKeyEvent 发送带修饰键的组合（Shift+方向键、Cmd+A 等）到页面
root_cause: CDP Input.dispatchKeyEvent 的 modifiers 是位掩码：Alt=1、Ctrl=2、Meta=4、Shift=8；Shift 误传 1（Alt）导致事件带错误修饰键。
solution: "传 modifiers 时按位掩码：Shift=8、Meta/Cmd=4、Ctrl=2、Alt=1，组合相加；键盘\"无反应\"时先核修饰键位再怀疑焦点/编辑器。当前性验证：Runtime.evaluate 挂 keydown 监听读 event.shiftKey，Input.dispatchKeyEvent(modifiers=8) 后应为 true。"
evidence: 本会话工具轨迹：/tmp/d22_patch2.py 等多次尝试 modifiers=1 无效果；修正为 8 后 Shift 组合键在其他页面行为正常；今日知乎 Draft.js 场景最终用 Range 法（docs/promotion/receipts/20261020-daily22-zhihu-published.json patch_round）
tags: [cdp, keyboard, modifiers, debugging]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-20T09:27:08.067398+08:00"
updated_at: "2026-10-20T09:27:08.067398+08:00"
---

2026-10-20 第 22 期：知乎编辑页补丁时所有 Shift 组合键选区失败，排查发现我把 Shift 当 modifiers=1 传——CDP 里 1 是 Alt。正确位：Alt=1、Ctrl=2、Meta/Cmd=4、Shift=8、组合相加（Cmd+Shift=12）。用错位时按键"静默无效果"（无报错），极易误判为焦点问题或编辑器不响应。另：本日同场景下即使位正确，Draft.js 仍不响应合成键盘选区（见配套教训 Range 真选区法）；本教训独立成立于任何监听键盘的页面（如浏览器快捷键注入）。当前性验证：连 CDP 后在任意页面 Runtime.evaluate 监听 keydown 读 event.shiftKey/metaKey/altKey，再用 Input.dispatchKeyEvent(modifiers=8) 发 Shift+X，回读 shiftKey 应为 true。