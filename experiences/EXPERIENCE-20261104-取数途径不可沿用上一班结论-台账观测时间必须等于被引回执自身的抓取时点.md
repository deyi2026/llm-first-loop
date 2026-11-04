---
title: 取数途径不可沿用上一班结论；台账观测时间必须等于被引回执自身的抓取时点
scenario: 写稿时把上一班/历史的环境结论（例如「arXiv 直连被网络出口拦截」）当作本班事实写进正文与尾注，而本班环境实际可用；或伴生台账里引用某回执的行，其「观测时间」与该回执自身记录的抓取时点不一致。
root_cause: ""
solution: 取数途径必须当班实跑确认再落笔；伴生台账引用某回执文件某行时，观测时间一律等于该回执自身记录的抓取时点；跨班沿用的环境结论要复核后才可写。
evidence: "receipts/d59research/arxiv_queries.json（6 个查询 ok=True）、receipts/d59research/arxiv_api_byid.json（fetched_at 2026-11-04T05:16:42Z）、receipts/d59research/arxiv_feed_paperscool.json（fetched_at 05:01:39Z）；审稿子代理 subagent_6e63279e865d 报 P1「台账观测时点错标」"
tags: [写作, 取数, arXiv, 台账, 诚实]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-04T13:40:38.447884+08:00"
updated_at: "2026-11-04T13:40:38.447884+08:00"
---

本班初稿的第十节与尾注写「本机直连 arXiv 被网络出口拦截，我走的是可达的 arXiv 分类 Atom feed 镜像」——这是从 d58 当天的环境结论沿用来的假设，**本班实测不成立**：export.arxiv.org 直连成功，6 个关键词查询全部 ok（agent memory 36 / self-evolving 60 / tool use safety 18 / context degradation 2 / evaluation 19 / multi-agent 60 条近两周记录），三篇主材料的摘要与元数据都可用 arXiv API `id_list` 直接取到（13:16 CST 实读）。

危害：取数途径写错会让读者以为证据等级比实际低，且**伴生台账里引用该回执的各行「观测时间」会与回执自身头部记录的抓取时间自相矛盾**——本班第三轮审稿子代理正是抓这一条报 P1。

修法：① 先实跑再落笔，取数途径以本班回执为准；② 伴生台账引用某个回执文件的行，观测时间必须等于该回执自身记录的抓取时点（本班：API 直连 13:16 CST，分类 feed 镜像 13:01 CST）；③ 若前一班的环境结论要沿用，必须当班实测复核，不许照抄。

当前性验证：跑 `python3 -I -c "import json;d=json.load(open('docs/promotion/receipts/d59research/arxiv_queries.json'));print({k:v.get('ok') for k,v in d.items()})"` 应输出 6 个 True；跑 `grep -n '直连 arXiv 被网络出口拦截' docs/promotion/20261104-lfl-daily-59.md` 应无输出。