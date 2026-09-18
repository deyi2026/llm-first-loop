---
title: Playwright 浏览器断言三坑：content() 双引号序列化、aria_snapshot 折叠按钮文本名、事件 delta 基线须在动作前采样
scenario: 用 Playwright 对 loopback fixture 做浏览器级断言：页面 marker/href 子串匹配、AX 同名污染计数、以服务端 append-only 事件日志为效果 oracle 的 before/after delta
root_cause: ""
solution: marker/href 断言用 DOM 属性提取或引号归一化；同名污染计数走 CDP Accessibility.getFullAXTree；事件 delta 基线在每次条款 goto 后、任何交互前采样
evidence: main 98178202/b11f03cb/a994aa30；browser_smoke.py 11/11（污染检查改 CDP 后由 FAIL got 1 → PASS）；run_qualification.py 修基线后 11/11；receipt evals/browser_smc_gt_qualification_v01/results/run_20260917T222212Z/summary.json
tags: [playwright, browser-assert, accessibility-tree, event-oracle, eval-fixture]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-18T06:22:50.517611+08:00"
updated_at: "2026-09-18T06:22:50.517611+08:00"
---

三个坑都在本轮实测中踩到并修复：
1) page.content() 是 Chromium 序列化输出，属性引号统一为双引号；拿源码风格的 "attr='v'" 单引号子串做 marker/href 断言必然假阴性。修法：DOM 级提取（locator(...).evaluate_all 取 getAttribute）或先 replace('"', "'") 归一化。
2) aria_snapshot()（及 AOM 视图）会把按钮内文本折叠进按钮名，同名只计 1 次；FC2-B name-pollution 探测（button + 同名 StaticText/InlineTextBox 子节点）必须走 CDP Accessibility.getFullAXTree 按 name.value 计数（实测同一页面 3 次 vs aria_snapshot 1 次）。
3) 服务端事件日志做效果 oracle 时，delta 基线必须在动作前采样；若在断言时才 setdefault 基线，动作产生的事件会被算进基线，delta 恒空——halt/零副作用条款会假通过。