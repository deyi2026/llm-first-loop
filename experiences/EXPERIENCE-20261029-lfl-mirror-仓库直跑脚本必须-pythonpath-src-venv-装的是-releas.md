---
title: lfl-mirror 仓库直跑脚本必须 PYTHONPATH=src：venv 装的是 .releases 冻结副本
scenario: 对本仓库源码（如 EVO 修复）做单元测试之外的直跑验证：写临时脚本 import llm_loop.xxx 并调用刚改的函数。
root_cause: ""
solution: 写临时 .py（勿用 -c，会被灾难守卫阻断），用 `PYTHONPATH=src .venv/bin/python script.py` 执行；先在脚本里 print(module.__file__) 确认指向工作区 src，再信结论。涉及运行时行为时另注意 .releases 冻结副本与服务 publish 机制。
evidence: PYTHONPATH=src 冒烟输出（briefing 新行+full_test 锚点解析成功）对照无 PYTHONPATH 时的 ImportError（回指 .releases/41cac7b7…/src），以及 pytest 159 passed（conftest 路径注入下跑的是工作区代码）。
tags: [llm-first-loop, pythonpath, venv, releases-mirror, smoke-test, verification]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-29T12:46:46.380065+08:00"
updated_at: "2026-10-29T12:46:46.380065+08:00"
supersedes: [EXPERIENCE-20261020-在-lfl-会话内跑-llm-first-loop-测试-剥部署环境变量并用-venv-解释器]
---

在 llm-first-loop-mirror 工作区：`.venv/bin/python` 直接 import `llm_loop` 解析到 `.releases/<sha>/src/llm_loop/...` 冻结副本，不是工作区 `src/`；pytest 能跑工作区代码是因为 conftest 注入了路径。因此：(1) 对工作区源码做直跑冒烟/验证脚本时必须 `PYTHONPATH=src .venv/bin/python script.py`，否则冒烟的是旧代码并得出假结论（本次 `_full_test_review_base` ImportError 暴露了这一点）；(2) 判断"运行中服务是否已带修复"也要看 .releases 指针——改工作区源码不影响运行时，需 publish 才生效；(3) 脚本仍写临时 .py 文件执行（内联 -c 被 E6 守卫硬阻断），放 .tmp-ci/ 用后删除。