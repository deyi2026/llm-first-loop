---
title: statebraid fork server 单测的运行目录与解释器契约
scenario: 在 llama.cpp-statebraid fork（/Users/yyj/Project/research/llama.cpp-statebraid-managed-m1 worktree，主仓 llama.cpp-statebraid-l1）跑 tools/server/tests/unit/ 下的 server 单测（真实起 llama-server），用于核验提交或回归。
root_cause: ""
solution: CWD 固定为 <repo>/tools/server/tests，用 /private/tmp/llama-test-venv/bin/python -m pytest unit/test_statebraid_managed_cache.py -v；后台运行 + job_output 轮询（约 6 分钟）。不要从 unit/ 子目录跑（相对路径解析二进制失败），不要用 /private/tmp/statebraid-m1-server-tests-venv（PEP 668 锁定且缺 wget）。
evidence: "evidence://v1/0c06d8cc885a00d9dea323480f7545731e984875d016fd55d2dde02beebc147a (HEAD=1b9d0fc7a 定位与 stat)；evidence://v1/7e2bf59698cd62da0f4d8319da46345f8c35aee685b22e91c513b827a37b3c50 (worktree list)；evidence://v1/26cdb753b59ccc40587d3f558d690b6d4fec47f736ca5ca996afd00ea8809c8c (clean tree + stat)；grep '^E ' 输出 FileNotFoundError ../../../build/bin/llama-server；job-6dbe869639524d5c9456 输出 9 passed in 346.72s（CWD=tools/server/tests, /private/tmp/llama-test-venv/bin/python）"
tags: [llama.cpp, server-tests, pytest, workdir, statebraid]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-14T19:55:38.219888+08:00"
updated_at: "2026-09-14T19:55:38.219888+08:00"
---

llama.cpp-statebraid fork 的 server 单测运行契约（2026-09-14 实测）：(1) 必须以 tools/server/tests 为 CWD 运行 pytest —— tests/utils.py 用相对路径 ../../../build/bin/llama-server 解析二进制，从 unit/ 子目录跑会 FileNotFoundError；(2) 可用解释器是 /private/tmp/llama-test-venv/bin/python（含 wget+pytest）；/private/tmp/statebraid-m1-server-tests-venv 是 PEP 668 外部管理环境且缺 wget，pip install 被拒绝；(3) 全文件 9 用例约 350s（每用例真实起 llama-server），建议后台运行；(4) 采信测试结果前核对 build/bin/llama-server mtime 晚于源码 mtime 且工作树干净。