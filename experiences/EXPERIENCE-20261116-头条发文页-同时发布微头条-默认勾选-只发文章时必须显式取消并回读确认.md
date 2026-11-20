---
title: 头条发文页「同时发布微头条」默认勾选：只发文章时必须显式取消并回读确认
scenario: "LFL 推广班 d92（2026-11-16 晚班）在头条发文页准备发布一篇长文时，宿主审稿（第 3 次准入 child=subagent_c0852b7961c9）把「同时发布微头条」处于勾选状态列为 P2：若不取消，点「确认发布」会同时对外发出一条微头条，而本号的排期口径是「每天 3 篇图文」，多一条微头条属于未计划的对外副作用。DOM 实测该控件是 .form-tuwen_wtt_trans input[type=checkbox]，当时 checked=true（x/y 坐标读数为 0，因为自定义控件把原生 input 藏起来了，不能用它的 rect 做点击）。"
root_cause: ""
solution: 发布前把「同时发布微头条」显式取消勾选，并回读 checked=false 作为准入与确认发布的前置条件；本班用 _d92_publish.py micro 阶段做（读 checked → 若为真才点击 → 回读），并在最终确认前的 PRECONFIRM 闸里再读一次。注意：原生 checkbox 的 getBoundingClientRect 常为 0×0，需点可见的包裹层而不是 input 本身。d92 实测：取消后 checked=false，作品管理页与公网页面只见图文一条，未出现微头条。
evidence: "准入 #3 REVISE 的 P2「同时发布微头条 checked」；编辑器 DOM 实测 receipts/d92-toutiao-local.json（micro_before/micro_after checked=false）；作品管理页截图文本 11-16 20:39 审核中 一条卡片"
tags: [头条发布, 微头条, 发布前自检, 对外副作用]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-16T20:41:32.793056+08:00"
updated_at: "2026-11-16T20:41:32.793056+08:00"
---

教训=头条发文页「同时发布微头条」默认是勾上的，只发文章时必须显式取消并回读。运作规则：①「确认发布」之前读 .form-tuwen_wtt_trans input[type=checkbox].checked；②若为 true 则点可见控件取消（原生 input 被自定义样式隐藏，rect 常为 0×0，要点包裹层/用 JS 设值后 dispatch change）；③回读 checked=false 写进会话回执；④这条要和「发布前自检」的其他项一起作为 PRECONFIRM 闸的前置条件。