---
title: llm-first-loop evals/pilot 测试必须以脚本方式从 evals/pilot 目录运行，不能用 pytest
scenario: 在 evals/pilot 运行 M1 评测仓库的确定性测试时，用 pytest 从 worktree 根目录执行导致 collection 期 JSONDecodeError（Extra data）
root_cause: ""
solution: 以脚本方式从 evals/pilot 目录运行：`cd evals/pilot && python3 test_g1_fixes.py`；pytest 仅适用于正常测试文件。worktree 根下另有同名 data/results.jsonl 会误导路径解析
evidence: "evidence://v1/e37bf8e4be99c9da9fa221740d88280cbb8140a4a8a3e3f24a9b91fea7134709"
tags: []
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-15T22:53:43.135395+08:00"
updated_at: "2026-09-15T22:53:43.135395+08:00"
---

在 llm-first-loop-mirror 仓 evals/pilot 下，test_g1_fixes.py / test_t02_effect_receipt.py 这类"import 期就做断言"的脚本式测试不能用 pytest 跑：analyze.py 顶层 `RESULTS = Path(sys.argv[1] if len(sys.argv) > 1 else "data/results.jsonl")` 会把 pytest 传入的测试文件名当数据文件解析，报 JSONDecodeError（Extra data）。必须 `cd evals/pilot && python3 test_xxx.py`（cwd 决定 data/results.jsonl 相对路径解析）。另外干净 linked worktree 缺 gitignored 的 data/providers.json（主仓有一份，sha256 见 evidence），按记录的门禁程序临时拷贝→跑→删。