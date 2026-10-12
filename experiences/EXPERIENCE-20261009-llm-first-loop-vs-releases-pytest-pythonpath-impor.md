---
title: llm-first-loop 工作树 vs .releases 快照：测试用 pytest pythonpath、验证改动勿用裸 import；.env canary 配置导致的环境性测试失败要用 business_config_snapshot 隔离
scenario: "本仓测试/导入校验：venv site-packages 指向 .releases/<git-sha> 服务快照而非工作树；pytest 经 pythonpath=[\"src\"] 测的是工作树；business_config_snapshot 读 dotenv 使携带真实 LFL_TASK_BUDGET_WEB_CANARY_CONFIG 的开发机 .env 泄入 build_app 类测试造成 22+3 个环境锚定失败（HEAD 同败）"
root_cause: ""
solution: "工作树验证一律走 .venv/bin/python -m pytest（勿用裸 import 校验）；需要隔离配置快照的测试用 monkeypatch.setattr(<模块>, \"business_config_snapshot\", lambda _s: {})（admin_once bootstrap 测试既有手法）；判断\"我是否引入失败\"用 git stash push→复跑→pop 对照，勿凭模块相关性推断"
evidence: 两次 stash 对照运行（web_cutover 3 例与 csrf/upload 样本在 HEAD 均败）；pytest 配置 grep；venv llm_loop.__file__ 输出 .releases 路径
tags: [task-budget, pytest, environment-isolation, dotenv-leak, llm-first-loop]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-09T17:59:43.488256+08:00"
updated_at: "2026-10-09T17:59:43.488256+08:00"
---

venv 的 llm_loop 解析到 .releases/14352cc6f 发布快照，直接 python -c "import llm_loop" 校验工作树代码会误判"改动丢失"；pyproject [tool.pytest.ini_options] pythonpath=["src"] 使 pytest 始终测工作树，且测试内应显式 monkeypatch business_config_snapshot（它读 .env dotenv，delenv 挡不住）——本机 .env 携带真实 LFL_TASK_BUDGET_WEB_CANARY_CONFIG 使 22+3 个无关 web 测试在 HEAD 即环境性失败，stash 对照两次证实。