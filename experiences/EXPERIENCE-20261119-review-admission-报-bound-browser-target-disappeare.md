---
title: review_admission 报 bound Browser target disappeared 时，用 browser_operate 换绑到现存发布页可恢复准入
scenario: "LFL 推广发表流程：review_admission(action=start, kind=article_publish) 连续两次抛 RuntimeError: bound Browser target disappeared: 08C76C50… ; no silent rebind。根因是 browser host 的 binding_page_id 指向一个已被关闭的标签页（browser_perceive action=pages 回执里该 id 已不在 7 个 page 清单中），而审查器绑定的是 host-bound page。"
root_cause: ""
solution: "用 browser_operate(do=navigate, target_id=<当前发布页 target_id>, url=<同一 URL>) 触发一次换绑——该调用只执行换绑（回执 do=rebind、navigated=false），不导航、不刷新，编辑器已注入的正文不受影响。换绑后 review_admission start 即可正常受理。校验：browser_perceive action=pages 确认 binding_page_id 已变为新 target_id；再实测 confirm 前编辑器正文未被清空（PRECONFIRM UNCHANGED）。"
evidence: "回执 evidence://v1/1542ac9df333b72a2dfec1c016a51582b7bad69df797d32eac7f95f2aef66b2 （do=rebind, navigated=false）；evidence://v1/c05142a7f1d290158d395a62f32821cd89350c88f7b112a0d851191b9a08b88b（准入第 3 次受理 PASS）；evidence://v1/dfbf9e328d24fb587363d535ffa4f6170def28096cb6d8557d3e94c5d705a16b（pages 清单无 08C76C50…）；_pages_d99.py 输出 20 页。"
tags: [review_admission, browser, cdp, 头条, 准入]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-19T16:55:34.566078+08:00"
updated_at: "2026-11-19T16:55:34.566078+08:00"
supersedes: [EXPERIENCE-20261106-review-admission-宿主绑定页可能已失效-先换绑再启动-且准入应在预览浮层-确认发布, EXPERIENCE-20261020-host-闸门前先显式-target-id-换绑-跨标签页发布流程中-bound-target-di]
---