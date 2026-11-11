---
title: 改图面文案会改画布高度——图尺寸必须从 manifest 动态读，不能在台账/核对脚本里写死
scenario: 推广班次改图面卡片文案（把卡片小标题改成更准确的说法、把「正则」扩成「正则与作用域分级函数」）后重出 PNG，画布高度随之变化（1000×1194 → 1000×1223），而台账与图注核对里写死了旧高度。
root_cause: ""
solution: 图面文案改动后必须重出 PNG 并从 manifest 读回新尺寸写进台账/核对断言；画布高度按最底部元素实际下缘设定，不写死。把台账图尺寸行与图注核对脚本改成读 receipts 的 fig-manifest.json，而不是在脚本里写死数字。d77 实测：改文案后 fig330 由 1194 变 1223，若沿用写死尺寸，caption_check 与台账会假失败。
evidence: docs/promotion/figures/_d77.py（改文案后重出图，fig330 高度 1194→1223）；图尺寸回执 receipts/d77-fig-manifest.json；台账图尺寸行改为读 manifest 的修正见 _d77_ledger.py 与 docs/promotion/20261111-daily-77-sources.md
tags: [配图, manifest, 尺寸, 图面口径, 推广班次]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-11T13:54:13.433317+08:00"
updated_at: "2026-11-11T13:54:13.433317+08:00"
---