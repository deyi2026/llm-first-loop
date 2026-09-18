---
title: search_files 参数语义：pattern/content/root/path 必须分层使用
scenario: 按文件名、内容或已知单文件定位代码时，模型容易把 pattern 当内容关键词，或把单个文件路径塞进 root/path 并同时给 content，导致空命中、目录错误或仅 stat 而没有真正搜索内容。
root_cause: search_files 的四个入口语义不同：pattern=文件名/相对路径 glob，content=内容正则，root=搜索根目录，path=精确存在/stat 的 O(1) 查询。compact 契约若只说“可搜索”而不给正确组合，本地模型会把参数名按自然语言直觉混用。
solution: 文件名查找用 pattern；内容查找用 content；限定目录用 root（必须是目录）。已知单个文件里查内容时，用 root=<父目录> + pattern=<文件名> + content=<关键词>，或直接 read_file 后按范围取证。path 只用于确认路径存在/类型/mtime，不与 content 组合做内容搜索。参数/状态不变时不要盲重跑。
evidence: "本轮: search_files(pattern='build_history_messages', root='src/llm_loop/core') → 无匹配; 改用 search_files(content='history_messages', root='src/llm_loop/core') → 命中 4 条（含 history.py:419 定义点）。评估 ID: eval:SE-20260820-001-e2eb（tool_efficiency=0.88，对应该冗余调用）。；2026-09-11 Ornith failure replay：历史会话把 content=batch_chars/grace_queue/preserve_group_digests 与 root=<episode_history.py 文件> 组合，3 次均返回目录不存在，随后改 path 又只得到 stat。贴近历史单变量 A/B：旧 compact 3/3 生成 content+path=<文件>（执行会忽略 content）；仅补正向组合语义后 3/3 改为 root=<父目录>+pattern=<文件名>+content=<关键词>。"
tags: [search_files, tool-contract, pattern, content, root, path, local-model, failure-replay]
source:
  tool: self_evaluate
  eval_id: SE-20260820-001-e2eb
  failure_replay: 2026-09-11
  model: Ornith-1.5-35B-A3B-MLX
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-08-20T13:32:36.582542+08:00"
updated_at: "2026-09-11T19:44:33.330953+08:00"
last_verified_at: "2026-09-11T19:44:33.330953+08:00"
---

## 现象
search_files 无匹配（pattern=build_history_messages, root=src/llm_loop/core）。
直觉以为 pattern 是关键词搜索，实际只匹配文件名。

## 修正
- 查文件内容关键字 → 用 `content` 参数
- 查文件名 glob   → 用 `pattern` 参数
- 可同时使用：pattern='*.py' + content='def build' 缩小范围

## 教训
工具 Schema 中并列参数未必语义同维度；首次使用前应读 Schema 或先用 search_files(content=...) 探一下。
