---
title: 头条编辑器光标定位用 Range 不用 End 键或坐标点击
scenario: 用 CDP 脚本向头条 mp.toutiao.com/profile_v4/graphic/publish 编辑器（ProseMirror）定位光标：需要在指定段落后新建空段插入图片，或把光标放到段落末尾。
root_cause: ""
solution: 光标定位一律走 JS Range + selectionchange 事件 + 读回验证（at_tail 判定），不依赖 End 键（只到视觉行末）与坐标点击（长文档静默失效）。失败即停并输出位置证据，不盲目重试。
evidence: docs/promotion/STATUS-20261020-daily23.md 缺陷节 D23-B/D23-C 与 _publish23_toutiao.py SET_END 实现；修复后 image 1-4 全部 IMAGE_OK（本会话工具回执）
tags: [toutiao, cdp, prosemirror, caret, publish]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-20T13:42:49.396097+08:00"
updated_at: "2026-10-20T13:42:49.396097+08:00"
---

头条图文编辑器（ProseMirror 系）里把光标放到某段末再 Enter/插图：①End 键只到当前视觉行末——两行以上段落会从中间拆段（案例：图注拆在「批准后偷｜换」处，图片夹进两半之间，STATUS-20261020-daily23 D23-B）；②Input.dispatchMouseEvent 坐标点击在长文档中多次静默失效（selection 停留旧位，image 插入连续 5 次 CLICK_NOT_IN_CAPTION，D23-C）。可靠做法：document.createRange() → selectNodeContents(p) → collapse(false) → removeAllRanges+addRange → dispatchEvent(new Event('selectionchange',{bubbles:true}))，然后读回 selection 验证 at_tail（anchorNode 是段内最后 text 节点且 offset==其长度，或 anchorNode==p 且 offset==childNodes.length），验证通过再按键。本日 4/4 成功。