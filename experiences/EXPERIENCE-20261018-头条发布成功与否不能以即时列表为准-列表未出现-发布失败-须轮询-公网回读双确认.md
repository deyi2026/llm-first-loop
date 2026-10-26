---
title: 头条发布成功与否不能以即时列表为准：列表未出现≠发布失败，须轮询+公网回读双确认
scenario: 今日头条图文：点击「确认发布」后页面跳转，但随后查询作品管理与草稿箱都看不到新文章，导致误判为失败并整篇重发，产生两条重复
root_cause: ""
solution: "发布成功的判定改为两段：点击后轮询作品管理列表（持续数分钟或直到出现目标标题），再对 item 链接做公网回读；两者都拿不到才允许判失败并重试。重试前先复核列表历史项（标题+平台时间）避免重复。当前性验证：复现方式——在头条编辑器点一次「确认发布」，随后立即查 https://mp.toutiao.com/profile_v4/graphic/articles 计数与首行标题，再于 2 分钟后重复该查询，对比两次的\"共 N 条内容\"与首行标题；若两次不同即证实列表延迟存在。"
evidence: "2026-10-18 实测：22:43 第一次 confirm 返回 CLICKED 且页面跳转；22:44 查作品管理页（证据 evidence://v1/2328d61a03ba983c929d9ae102b02c7bc8f9a42535284fd73644880c78f841e7，共 31 条、最新为 12:59、item 链接无 HCI），草稿箱亦无该标题；据此误判失败并整篇重发；约 22:55 再查（证据 evidence://v1/e77058209bf58073acf5455040e1006d4158a84fe8df84c812af7c3cec386343，共 33 条）出现两条同名记录，平台时间 22:45 与 22:48，均\"审核中\" —— 证明第一次点击已生效，即时列表与草稿箱都不是发布成功的判据。"
tags: [toutiao, publish, idempotency, duplicate-content, verification]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-18T22:51:06.675145+08:00"
updated_at: "2026-10-18T22:51:06.675145+08:00"
---