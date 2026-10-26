---
title: 浏览器工具语义层对三平台发布按钮无可寻址 name，须用 CDP 真实鼠标坐标点击
scenario: 在微信/知乎/头条三个平台页面上用浏览器工具做「点发布」这类精确点击
root_cause: ""
solution: |
  三个平台的发布按钮在浏览器工具的语义层里都被标成 generic、没有可寻址 name，用 kind+name / name_normalized / grounding_ref 三种寻址都会 target_not_found；而工具给出的候选清单里「看起来最像」的那个元素往往不是真正的按钮（知乎那次候选里是页面说明文字与工具栏杂项）。可靠做法：先用 CDP 读出真实按钮的 outerHTML/innerText 与坐标，再在该坐标上发 Input.dispatchMouseEvent 真实鼠标事件；发布资格仍由 review_admission 的 PASS 背书，不要因为寻址失败就绕过闸门。
  当前性验证：对任一平台 tab 跑 `python3 docs/promotion/_cdp_eval.py <tab_id> <probe.js>` 读 [role=button]/button 元素的 innerText 与 outerHTML，确认目标按钮文本仍存在且带 button/a 语义；同时用浏览器工具 snapshot 看该按钮是否仍无可寻址 name（无 name 即应继续走 CDP 路径）。
evidence: "evidence://v1/d3a6c5b347e53ace77485087375260198d39fc8238c3ad4a619c357a45ececb4, evidence://v1/ccbcbf06cb302399bfeb452c320be98ece77bf9552a405df6c49fd9d8f1b3ef9f"
tags: [浏览器工具, 寻址, CDP, 发布, 三平台]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-25T14:47:00.437383+08:00"
updated_at: "2026-10-25T14:47:00.437383+08:00"
supersedes: [EXPERIENCE-20261020-browser-operate-name-addressing-100-object-window]
---