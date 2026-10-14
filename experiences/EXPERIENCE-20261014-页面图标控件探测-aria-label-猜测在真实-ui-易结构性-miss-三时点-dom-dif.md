---
title: 页面图标控件探测：aria-label 猜测在真实 UI 易结构性 miss——三时点 DOM diff 找共体控件 svg path 实测特征
scenario: Playwright 页面自动化的停止/取消类图标控件探测，无真机期按 aria-label 推测实现，真机可用后验收
root_cause: ""
solution: 三时点 DOM diff（空闲/生成中/取消后）定位共体控件的真实特征（svg path d 前缀）；以实测特征为主探测路径、推测选择器降为兜底；桩测试锁定特征命中/兜底/全 miss 三形态；真机终验以「取消后图标回发送形态+文本停止增长」双重证据确认点击生效
evidence: reports/phase6/m5/REALPAGE_COMPOSER_DOM_DIFF.json（三态 DOM diff 证据）；reports/phase6/m5/REALPAGE_TEFFECT_v5.json（升级后终验）；~/Project/lfl-web-providers e74fd98（svg 特征探测 + W5/W6 桩测试）
tags: [playwright, page-automation, stop-button, svg-path, dom-diff, deepseek, best-effort]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-14T07:35:26.025565+08:00"
updated_at: "2026-10-14T07:35:26.025565+08:00"
---

Phase6 候选 1 真机抽查：M2 期「停止按钮 aria-label 选择器」在无真机环境下按推测写成三个 aria-label 选择器；真机可用后实测发现当前 deepseek UI（2026-10-14，Chrome 154）停止控件根本无 aria-label、无文本——它是 composer 主按钮（div[role=button].ds-button--primary--filled--circle），生成期仅 svg path d 从发送图标（M8.3125 前缀）切换为停止方块（M2 4.88 前缀）。aria 选择器全程 miss（生成期 26s 计数 0）→ 取消后释放点击从未发生（页面继续生成到自然完成）。定位方法：空闲态 vs 生成态 vs 取消后三时点 dump composer 容器全部 button/div[role=button] 的 tag/label/text/class/svg path d，diff 出「同一 DOM 身份、仅 svg 切换」的共体控件。升级：以实测 svg path 前缀为主探测/点击路径（JS evaluate 限定 textarea 上溯 4 级容器内），aria-label 保留兜底，失败记 0 语义不变；终验生成期命中 1、取消后发送图标回归+文本停止增长。适用边界：图标 path 可能随 UI 更新漂移（best-effort 回 0 是设计），path 前缀特征必须来自实测 dump 而非猜 DOM。