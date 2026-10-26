---
title: 头条图文编辑器：AI 助手全屏 mask 吞点击导致图注定位失败，先清浮层再定位
scenario: 用 CDP 脚本向今日头条图文编辑器按图注定位插图时，脚本稳定报 TARGET_NOT_VISIBLE_STOP：图注段已在视口内，但 elementFromPoint 命中的元素 innerText 为空。
root_cause: ""
solution: "真因是平台自身的 AI 创作助手抽屉：.byte-drawer-mask / .byte-drawer-wrapper 以 z-index 1002 全屏覆盖视口（rect 0,0,1214,755），吞掉编辑区内所有点击；它对 ESC、mask.click()、CDP 鼠标点击都不关闭，还会自动重开。可靠做法：定位前先检测该遮罩，存在则对其左侧空白处发一次真实鼠标点击（最多重试 3 次）；仍不消失就对 .byte-drawer-mask/.byte-drawer-wrapper 置 display:none!important（只隐藏平台浮层，不改正文）；之后按图注段 getBoundingClientRect 计算点击点，并保留「点击后光标必须落在图注段落」这一后置校验兜底。附带修正：底部横条若用 ts=1 的空标题，正文会落到面板外，应改用显式垂直居中的 bar() 辅助函数。"
evidence: "evidence://v1/b1619303df39e154c53fed417c739813ee238b211766b061528b29bd36753e43（遮罩 full-screen rect + pointer-events 探针）, evidence://v1/1e309ab0cbf236b83d3a4b17e4c13187a3ad50f7365ae1e31e409a3a932837c5（mask onclick 存在）, evidence://v1/1c889468ed933c61e3343ea8045732078f2d1bf3ea1dd77a918093ea971e41759（修复后图 62 一次成功）, evidence://v1/c653c1c57d376f22f41a89e18f82c7ce63e31f0e431e5fc590a0d007a25cc16f（图 63-67 依次 IMAGE_OK）"
tags: [toutiao, publish, cdp, browser, blocker, figure-upload]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-18T11:53:41.059001+08:00"
updated_at: "2026-10-18T11:53:41.059001+08:00"
---

诊断步骤：(1) 见 TARGET_NOT_VISIBLE_STOP 时先算图注段 getBoundingClientRect，若 top 在视口内却 elementFromPoint 返回空 innerText，就是被浮层遮挡；(2) 探针：列出 body 内 position:fixed 且宽高较大的元素；(3) 确认命中 .byte-drawer-mask/.byte-drawer-wrapper。当前性验证：grep -n "byte-drawer-mask" <平台页面 DOM/脚本> 或在编辑器页执行 document.querySelectorAll('.byte-drawer-mask').length，若平台改版该遮罩类名变化，则本经验需重新定位遮挡元素。