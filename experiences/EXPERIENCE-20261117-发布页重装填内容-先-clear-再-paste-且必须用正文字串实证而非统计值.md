---
title: 发布页重装填内容：先 clear 再 paste，且必须用正文字串实证而非统计值
scenario: "LFL 推广第 95 期在正文改稿后重装填头条发布页：先跑 publish 的 prepare 阶段，脚本回执打印 NONBLANK_EDITOR_STOP（编辑器非空守卫）并**直接返回**，正文没有换掉——而 prepare 阶段输出的 chars/imgs/captions 与上一版完全相同（7356/8/4），肉眼无法从这些统计值看出内容没换；若就此提交，发出去的会是旧稿。随后先跑 clear（清空编辑器与标题）再跑 prepare，chars 才变成 7382（+26，与 3 处措辞修订吻合），并另用 CDP 直查编辑器 innerText 确认「method:<id>」「撰写与制图阶段」在、「游离」不在，才算实证。"
root_cause: ""
solution: "改稿后重装填内容必须按 clear → prepare → title → ai → verify 顺序走，不能直接 prepare（prepare 的非空守卫会静默跳过粘贴）；并且不要用 chars/imgs 这类统计值当「内容已更新」的证据，要用正文字串实证（CDP 直查编辑器 innerText 里新串命中、旧串消失）。本次用 /tmp/d95_editor_check.py 输出 {has_method_id:true, has_scope_phrase:true, has_old_detached:false, nonws:7382} 作为实证。"
evidence: docs/promotion/receipts/d95-toutiao-local.json 中 prepare 阶段的 NONBLANK_EDITOR_STOP 记录（chars 7356/imgs 8/captions 4，与改稿前完全相同）；clear→prepare 后 verify 回执 chars=7382；CDP 直查输出 has_method_id=true、has_old_detached=false
tags: [promotion, d95, 发布链路, 编辑器, 实证]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-17T23:10:35.087750+08:00"
updated_at: "2026-11-17T23:10:35.087750+08:00"
---