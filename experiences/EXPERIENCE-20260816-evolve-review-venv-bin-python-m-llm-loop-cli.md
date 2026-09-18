---
title: evolve-review 正确调用方式：.venv/bin/python -m llm_loop.cli
scenario: 人工审阅演进建议时想执行 evolve-review <id> accepted，直接敲命令报 command not found
root_cause: evolve-review 是 llm-first-loop 项目 CLI 子命令（llm_loop.cli），不是独立可执行文件；直接敲命令名不在 PATH 中。
solution: 在项目根目录 /Users/yyj/Project/llm-first-loop 下用：`.venv/bin/python -m llm_loop.cli evolve-review <id> accepted|rejected`（同理 evolve-list / evolve-complete / search / extract 等均走该入口；evolve-complete 用于涉边界演进的人工完成登记）。不确定时先 `.venv/bin/python -m llm_loop.cli evolve-review --help` 或查 README.md L85-95 / docs/api.md L123-127。
evidence: "2026-08-16 用户直接执行 `evolve-review <id> accepted` 报 zsh: command not found；查 README.md L92-93 / docs/api.md L126 找到正确入口 `.venv/bin/python -m llm_loop.cli evolve-review <id> accepted|rejected`，并在项目根目录验证通过。"
tags: [CLI, evolve-review, 演进审阅, llm_loop.cli, 命令入口]
source: {}
status: active
created_at: "2026-08-16T22:07:51.197175+08:00"
updated_at: "2026-08-16T22:07:51.197175+08:00"
---