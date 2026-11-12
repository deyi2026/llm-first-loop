---
title: 接管跨会话发布任务：用 info/v2 快路径独立复核公网终态 + 跨会话 Goal 收口路径
scenario: 接管一个来源会话已在跑或已停的「文章发布→公网验收→STATUS 收口」任务时，需要在不重复发布的前提下确认外部副作用终态，并把仍 active 的 Goal 收口。
root_cause: 交接快照只给「Goal active、无可核验开放 Task」，来源会话自身对发布状态的结论是「模型自述」，需一条不依赖来源会话登录态与记忆的独立复核通道；跨会话写 Goal 需显式 cross_session 授权参数与证据引用。
solution: "① 先核来源会话是否还在跑：读 data/event_logs/<sid>/*.jsonl 的最后事件时间与 run.end 的 reason（max_iterations=撞轮数上限，非发布失败）；② 公网终态不依赖来源会话的 CDP 登录态：用 web_fetch 走 https://m.toutiao.com/i<PGC_ID>/info/v2/ 快路径即可独立取回公网正文，核对标题逐字、平台时间、AI 声明、话题标签与关键数值段；③ 冻结稿一致性用本地 shasum -a 256 与 receipts/*-admission.json 的 frozen_md_sha、receipts/*-closeout.json 的 publish_sha256 三方比对；④ Goal 归他会话时，checkpoint_goal + update_goal 传 cross_session=true + reason + evidence_refs 即可通过跨会话写入门（空任务图靠自报 evidence_refs 过终局证据门）；⑤ 发布类产物的 Git 事实先查 .git/info/exclude，docs/promotion/ 常被排除，不必为收口硬造提交。"
evidence: "本会话实测：① 16:5x web_fetch https://m.toutiao.com/i7707162229884125730/info/v2/ 返回标题「登录墙、限流、反爬撞上来：AI 交付的不是你要的那件事」+平台时间 2026-11-12 14:34 +「内容由AI生成」+3 标签+关键数值段；② 本地 shasum -a 256 docs/promotion/20261112-lfl-daily-80.md = 554d4c1d9ae25242cfd126ff87cb5a91b1bafd6212fd427ea480eb7084a5f6ab，与 receipts/d80-admission.json.frozen_md_sha、receipts/d80-closeout.json.publish_sha256 三方一致；③ checkpoint_goal/update_goal 带 cross_session=true+reason+evidence_refs 回执 success（goal→complete）；④ git check-ignore -v 命中 .git/info/exclude:32 docs/promotion/。"
tags: [接管, 跨会话, 发布终态复核, toutiao, goal收口]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-12T16:53:17.118056+08:00"
updated_at: "2026-11-12T16:53:17.118056+08:00"
---