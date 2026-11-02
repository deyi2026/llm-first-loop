---
title: 引用自己仓库的行号必须 grep -n 实测：凭印象写会整段偏移
scenario: LFL 推广稿件第七节写自己仓库的代码事实时引用文件行号。
root_cause: 行号是凭阅读印象填的，且把「字段起始行」「常量定义行」「函数定义行」混为一谈；审稿包里的源码摘录一旦与正文行号不一致，独立审稿立刻判 P1。
solution: 写行号前一律 grep -n 实测（连字段定义、装饰器、函数体范围一起取），台账与正文用同一组实测行号；被审稿指出 off-by-one 时，正文、台账、配图里的行号三处一起改，并重跑 R5 审计与配图复验。
evidence: "src/llm_loop/memory/store.py：source_session_id 第 41 行、source_message_id 第 42 行、citations 第 70 行、_HALF_LIFE_DAYS 第 86 行、_compute_decay 第 557-565 行；误写位置为 store.py:43、88、556 与 client.py 缺失语义「保持 0」。"
tags: [promotion, 行号, off-by-one, grep, 源码引用]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-02T20:30:38.351606+08:00"
updated_at: "2026-11-02T20:30:38.351606+08:00"
---