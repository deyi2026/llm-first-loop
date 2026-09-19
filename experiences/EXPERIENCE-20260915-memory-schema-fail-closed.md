---
title: 跨代码版本共享可写 memory 目录的 schema 静默清空事故与 fail-closed 根治
scenario: 旧代码 checkout 的进程（常驻服务/手动 CLI/评测子进程）加载新 schema 共享 data/memory/index.json：MemoryEntry(**e) 遇未知字段抛 TypeError，被 _load() 与 JSONDecodeError 并列捕获走 corruption 路径 → 备份+内存清空 → 后续任一次保存把空/部分索引写回，好数据被覆盖。2026-09-15 实际触发：主工作区 M1 旧代码 + main 线新 schema 数据。
root_cause: "schema 演进（main 3a95ed46 引入 observation_history 持久化字段）与旧 M1 checkout 共享同一可写 data/memory；_load 把\"reader 比数据旧\"误分类为\"数据损坏\"。"
solution: "两层修复（m1-g1-scorer-fix: 7833c42b + b34c098e，建议 cherry-pick main）: ①MemoryEntry 补 observation_history 持久化兼容字段（对齐 main，不带 promotion 语义），旧 reader 无损读写新格式；②_load 拆错误分类——JSON 语法破损维持 corruption 路径（备份+fail-open），TypeError→MemorySchemaMismatch fail-closed：原文件不动、不误备份、_save 双闸（构造时锁+merge 后锁）raise、_merge_remote_changes 置锁不静默 return。操作纪律：评测/手动 CLI 一律独立 checkout 或显式 DATA_DIR 隔离（data_dir 默认=代码所在 checkout 的 data/，绝对路径不随 cwd 漂移——主工作区手动 CLI 即事故源）。禁止 filter known keys（旧代码保存会静默删未来字段）。"
evidence: "tests/test_memory_schema_compat.py 7 项 + memory 回归 36 项全绿；真实 1479/1476 两份 value_loss=0、5 条 observation_history 原样保留；future_field 注入 1479 条实测: 文件零字节改动、无 .corrupt.json 误备份、save_entry 抛带未知字段诊断的 MemorySchemaMismatch。commits: 7833c42b（bridge）+ b34c098e（分类根治）@ m1-g1-scorer-fix。"
tags: [memory, schema-compat, fail-closed, data-isolation, incident-2026-09-15]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-15T20:50:45.368499+08:00"
updated_at: "2026-09-15T20:50:45.368499+08:00"
---

事故机制: data_dir 默认解析为"代码所在 checkout 的 data/"（绝对路径），不同版本 checkout 共享同一可写持久化目录时，旧代码 MemoryEntry(**e) 遇新字段 TypeError，被 _load() 与 JSONDecodeError 并列捕获 → 备份+清空+继续写 → 好索引被覆盖。修复两层: ①补持久化兼容字段（对齐 main 3a95ed46，不带运行时语义）; ②_load 拆错误分类——JSON 语法破损→corruption 路径（备份+fail-open），TypeError→MemorySchemaMismatch fail-closed（原文件不动、不误备份、_save 双闸 raise、_merge_remote_changes 置锁不静默）。操作纪律: 评测/手动 CLI 一律独立 checkout 或显式 DATA_DIR 隔离。