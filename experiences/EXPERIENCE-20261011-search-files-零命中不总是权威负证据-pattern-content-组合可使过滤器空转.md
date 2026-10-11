---
title: "search_files 零命中不总是权威负证据：pattern+content 组合可使过滤器空转而伪造\"符号不存在\""
scenario: "核验一篇审稿对象点名 _GATE_CLASSIFICATION_ENTRIES，要求\"自行解析\"门禁分类表；用 pattern=文件名 + content=标识符 的组合检索返回零命中，差点判定\"该符号不存在\"。"
root_cause: ""
solution: "把\"零命中即不存在\"限定为单词一过滤器场景；同时施加 filename pattern/content 等多过滤器时，零命中须先按\"过滤器空转\"处理：去掉多余过滤器重搜一次或换 root 口径再搜，才能升级为权威负证据。"
evidence: "search_files(root=src, pattern=service_control.py, content=_GATE_CLASSIFICATION_ENTRIES) → 「无匹配」；search_files(root=src, content=_GATE_CLASSIFICATION_ENTRIES|gate_classification|GATE_CLASS) → 命中 llm_loop/runtime/service_control.py:203 定义、318/336 使用。"
tags: [search_files, 零命中, 假阴性, 过滤器, 核验纪律]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-11T21:40:22.802671+08:00"
updated_at: "2026-10-11T21:40:22.802671+08:00"
---

现象：对标识符 X 做 search_files 时同时给了 pattern=<文件名>(如 service_control.py) 与 content=X，回执为「无匹配」；改为仅 content=X（root=src）后，X 命中 16 处并确认存在（runtime/service_control.py:203）。

原因：pattern+content 组合语义是先按 pattern 限定文件集再在该集合内搜内容；若 pattern 的匹配基准与实际路径（root 相对路径 vs 全路径）不一致，文件集为空，content 搜索必然零命中——零命中来自"过滤器失效"，不是"标识符不存在"。

判别法：收到零命中时，先问该回执是"权威负证据"还是"过滤器可能空转"。同一标识符去掉 pattern 重搜一次即可判别；若两次口径不同，说明第一次零命中不可作为不存在证据。

与既有方法卡 verify-code-claims-via-receipt-vocabulary-and-cheapest-oracle 中"零命中回执即该名不存在的权威负证据，最多一次即停"相冲突之处：该规则只对"单词一、过滤器单"的检索成立；一旦同时施加了文件名等额外过滤器，零命中必须先排除过滤器空转才能升级为负证据。差点据此错误结论"该符号不存在、追注释邻域"，实为漏检。