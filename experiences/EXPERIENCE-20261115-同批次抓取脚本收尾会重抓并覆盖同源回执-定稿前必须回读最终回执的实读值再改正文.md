---
title: 同批次抓取脚本收尾会重抓并覆盖同源回执：定稿前必须回读最终回执的实读值再改正文
scenario: "LFL 推广 d89 晚班（2026-11-15）：调研脚本 _research_d89.py 在 26 组 arXiv 检索跑完后，于收尾段又重抓了一次头条热榜并写回同一个路径（receipts/d89research/hotboard.json），把开班时 20:01:32 那一份覆盖成 20:23:41。正文与台账若沿用写作时记下的热榜条数/时间戳/检索统计，就会与最终落盘的回执对不上（正文说 20 点 01 分 32 秒，回执里是 20 点 23 分 41 秒）。"
root_cause: 同一进程内先抓一次、收尾再抓一次同一个源且落盘路径相同，后写覆盖先写，而正文数字取自第一次抓取的记忆值
solution: "正文与台账引用任何外部抓取（热榜、检索池、论文元数据）的数字或时间戳，必须在定稿前重新读回执文件本身（fetched_at / n / n_tight / n_raw / n_uniq），用回执里的实读值改写正文句，并让台账出处指向最终那一份回执；不要沿用写作时记下的数。收尾重抓与首次抓取应写不同文件名，或在抓取后显式声明「本文件以最后一次抓取为准」。当前性验证：定稿前执行 `python3 -c \"import json;d=json.load(open('docs/promotion/receipts/d89research/hotboard.json'));print(d['fetched_at'],d['n'])\"` 取实读值，再与正文里的时间戳/条数逐字对照；本班改正文为 20 点 23 分 41 秒 / 50 条后该值与回执一致。"
evidence: "docs/promotion/receipts/d89research/hotboard.json（fetched_at=2026-11-15T20:23:41+08:00, n=50）；docs/promotion/receipts/d89research/arxiv_pool.json（n_raw=607, n_uniq=402）；docs/promotion/receipts/d89research/selection.json；定稿补丁脚本按回执实读值改写正文与台账（/tmp/lfl_finalize_d89b.py，重跑幂等）"
tags: [推广班, 调研, 回执覆盖, 口径漂移, 热榜]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-15T20:30:30.771663+08:00"
updated_at: "2026-11-15T20:30:30.771663+08:00"
supersedes: [EXPERIENCE-20261108-正文写出的方法名必须与实际执行的方法逐字一致, EXPERIENCE-20261025-动态页面取证-首次观察必须立即落盘回执-只打印-观察未存证]
---