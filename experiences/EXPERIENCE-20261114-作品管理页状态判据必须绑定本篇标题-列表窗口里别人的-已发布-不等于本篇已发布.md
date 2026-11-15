---
title: 作品管理页状态判据必须绑定本篇标题：列表窗口里别人的「已发布」不等于本篇已发布
scenario: "LFL 推广晚班（d86，2026-11-14 20:00 班）在今日头条图文发布后轮询作品管理页状态。稿件已于 20:36:12 提交成功（session 记录 phase=submitted，页面跳作品管理页）。第一版轮询脚本按「页面上任意一张卡片的状态」判定，首轮就把上一班（d85，13:47 已发布）的卡片读成「STATUS=已发布」；第二版改为「标题后 160 字符窗口内是否出现『已发布』」，仍误判——因为窗口跨到了下一张卡片（d86 本体是『审核中』，下一张是 14:45 已发布）；两版都会导致把未过审的稿子误报为已发布。"
root_cause: ""
solution: "状态判据必须绑定本篇标题：取 body.innerText 中本篇标题的索引，从该索引起切一段，用正则取其中第一个「日期 时间 状态」三元组（\d{2}-\d{2} \d{2}:\d{2}\s*(已发布|审核中|审核未通过)），以该三元组的状态为本篇状态；不要用「窗口内是否出现某状态词」这种存在式判据。另外每次轮询必须先 location.reload() 再读——不刷新会读到旧渲染态（第一版轮询读到的甚至是 d83 的卡片）。复核落点：两个作品列表视图（/profile_v4/graphic/articles 与 /profile_v4/manage/content/all）都读到本篇时，才可认为稿件确已入列；草稿箱无该稿可排除「只存草稿」。"
evidence: "实测三版轮询（d86）：v1 按任意卡片判定→首轮误判「已发布」；v2 用 160 字符窗口含下一张卡片→仍误判；v3 用标题后首个「日期 时间 状态」正则→连续 7 轮（20:40:50–20:43:02）稳定读出「TS=11-14 20:36 STATE=审核中」，与 /graphic/articles 与 /manage/content/all 两个视图的实见文案一致（内容数 117→118）。脚本：docs/promotion/_d86_poll3.py；证据：docs/promotion/receipts/d86-poll-final.json、docs/promotion/receipts/d86-toutiao-local.json（phase=submitted，t=2026-11-14T12:36:12Z）。"
tags: [头条, 发布, 状态判据, 轮询, 推广收口]
source:
  note: d86 晚班实测
  work_unit_id: daily86-publish
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-14T20:43:17.550952+08:00"
updated_at: "2026-11-14T20:43:17.550952+08:00"
---