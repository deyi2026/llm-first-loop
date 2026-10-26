---
title: Host 闸门前先显式 target_id 换绑：跨标签页发布流程中 bound target disappeared 的确定性恢复
scenario: 多标签页 CDP 长流程（如头条/知乎发布）中途调用 Host 侧工具（review_admission 发表闸门、browser_perceive/operate）时，Host 仍绑定旧页面 target；旧页面已关闭或导航导致 target 消失，闸门调用直接 RuntimeError 失败
root_cause: Host 浏览器绑定的 target 与实际操作页解耦；旧页面消失后绑定失效且不静默重绑（安全设计），需模型显式指定新 target_id 换绑
solution: "调 Host 闸门前先 browser_perceive(action=snapshot, target_id=<当前操作页 id>) 显式换绑（EVO-20261007-11ae668f 通道）；target_id 从 CDP /json/list 页面清单取 URL 匹配项。不要重复重试闸门调用——绑定不恢复，重试必然同错。"
evidence: "失败回执：2026-10-20T20:28 review_admission start 报 RuntimeError: bound Browser target disappeared: B1D2560E…；browser_perceive snapshot 同错。恢复回执：browser_perceive(target_id=260985191BC3545AB046C0DB9ED424EE) → {\"action\":\"rebind\",\"status\":\"ok\"}；随后 review_admission accepted=true (child=subagent_835c5f926412) → PASS → _publish24_toutiao.py confirm CLICKED → 作品管理「已发布」+公网验收 4/4 图（receipts/20261020-daily24-public-verified.json）"
tags: [browser, review_admission, CDP, 发布流程, target_id, 换绑]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-20T20:38:06.463507+08:00"
updated_at: "2026-10-20T20:38:06.463507+08:00"
supersedes: [EXPERIENCE-20260918-cdp-env-target-id-restart-web]
---

现象：跨标签页发布长流程中（open 新 tab → prepare/images → preview → 闸门 → confirm），Host 浏览器绑定仍指旧 target。旧 target 随其页面关闭/导航消失后，review_admission(action=start) 与 browser_perceive 均抛 "RuntimeError: bound Browser target disappeared: <id>; no silent rebind"，无静默重绑（fail-closed 是设计行为）。
恢复路径（2026-10-20 daily-24 头条发布实测）：browser_perceive(action=snapshot, target_id=<当前操作页 id>) 一次换绑成功（回执 action=rebind, status=ok），随后 snapshot 正常、review_admission start 受理、PASS 后 confirm 一次成功。target_id 从 CDP /json/list 的页面清单取（type=page 且 URL 匹配操作页）。
运作规则：凡是「新开 tab 承载发布/操作流程 + 中途要走 Host 闸门（review_admission / browser_operate / perceive）」的序列，在调闸门前先做一次显式 target_id 换绑到当前操作页，不要等 bound target disappeared 报错再救。与 D23-I（快照陈旧须 navigate 刷新）同族但不同层：那篇是世界版本陈旧，本篇是绑定 target 整体消失。