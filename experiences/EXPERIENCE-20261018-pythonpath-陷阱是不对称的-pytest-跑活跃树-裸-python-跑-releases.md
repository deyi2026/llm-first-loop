---
title: PYTHONPATH 陷阱是不对称的：pytest 跑活跃树，裸 python 跑 .releases 快照——两者结论会互相矛盾
scenario: 在 llm-first-loop 工作区验证 src/ 改动。pytest 下 conftest 保证 llm_loop 解析到活跃 src（测试全绿、修复看似生效）；但用 .venv/bin/python 直接跑 ad-hoc 脚本/性能探针时，llm_loop 解析到 .releases/<sha>/src 快照（改动完全不生效）。两条路径结论互相矛盾。
root_cause: ""
solution: "任何 ad-hoc 脚本（性能基准、探针、诊断）都必须显式 PYTHONPATH=<repo>/src，并在脚本首行打印 llm_loop.<mod>.__file__ 自证绑定；不能沿用 pytest 的结论反推 ad-hoc 结果，反之亦然。做性能 A/B 时更要用 git show HEAD:<file> 落到临时副本做干净基线，不能拿 .releases 快照当基线——它与当前 HEAD 未必同源。pytest 侧的活跃树绑定另由 tests/conftest.py sys.path 注入保证。"
evidence: "evidence://v1/861f686cae6a2c3a7e2b7f4e1c6e0e5b (PYTHONPATH 实测 .releases 快照优先); evidence://v1/0b98a764713377315272fa1f8162f4a68b1a3df8f2935bdde479bb4324abec1b (pytest 182 passed 跑活跃树); /tmp/lfl_perf_probe.py BASELINE vs LAZY 对照"
tags: [pythonpath, 验证纪律, 假阴性, ad-hoc脚本, 性能基线]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-18T13:08:24.245015+08:00"
updated_at: "2026-10-18T13:08:24.245015+08:00"
supersedes: [EXPERIENCE-20261013-工作区-pythonpath-指向-releases-发布快照会导致-修复无效-的假阴性]
---