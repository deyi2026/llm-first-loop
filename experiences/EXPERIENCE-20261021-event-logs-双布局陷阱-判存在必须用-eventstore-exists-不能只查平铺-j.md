---
title: event_logs 双布局陷阱：判存在必须用 EventStore.exists()，不能只查平铺 .jsonl 路径
scenario: 扫描或核验 llm-first-loop 会话事件日志（data/event_logs/）是否存在/是否回填时，用自拼的平铺路径 <sid>.jsonl 检查文件。
root_cause: 扫描/核验脚本自拼存储路径，未使用 EventStore 自身的 exists()/read()，漏掉多段目录形态；替身探针的 exists 语义与真实实现不一致放大了误诊。
solution: 判存在与读事件一律用 EventStore.exists(sid)/EventStore.read(sid)；写扫描器时先读 EventStore 的 _path/_segment_dir/_is_multi_segment 源码确认全部落盘形态；做替身诊断时让替身的方法语义（尤其 exists）与真实实现严格一致。
evidence: 本会话命令回执：ls data/event_logs/ 见 <sid>/ 目录；EventStore.exists() 对平铺路径不存在的 sid 返回 True；sed 确认 _path()/_segment_dir()/_is_multi_segment() 定义；终局核验 598/598 经 EventStore.read() 均含 archive meta_changed 事件。
tags: [event-log, storage-layout, session-archive, verification, false-alarm]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-21T00:59:52.467746+08:00"
updated_at: "2026-10-21T00:59:52.467746+08:00"
---

现象：llm-first-loop 的 data/event_logs/ 同时存在两种形态：平铺单文件 <sid>.jsonl 与滚动后的多段目录 <sid>/<segment_seq>.jsonl。任何"会话是否有事件日志"的判定若只查平铺路径（os.path.exists(f'{dir}/{sid}.jsonl')），会把已滚动的会话误判为无日志。本例中该误判导致上游交接预估"89 个会话需回填 178MB 事件、耗时 10–30 分钟"，实际这些会话一直有完整事件日志，批量归档 39 秒完成且零回填；执行者随后用同样的平铺路径复核，再次得出"89 个缺失"的错误结论。根因：EventStore._path() 只给出单文件形态路径，多段形态路径由 _segment_dir()/_is_multi_segment() 表达，扫描脚本自拼路径时天然只见其一。正确做法：判存在/读事件一律走产品 API——EventStore.exists(sid) 与 EventStore.read(sid)（两者都覆盖两种形态）。附带教训：用替身对象（ProbeStore）做诊断时，其 exists() 等语义必须与真实实现一致，否则会把诊断引向"产品 bug"的错误方向。