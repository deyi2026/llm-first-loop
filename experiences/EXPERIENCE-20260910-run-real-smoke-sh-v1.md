---
title: run_real_smoke.sh 取缓存门禁实测数字与 v1 基线的正确姿势
scenario: 本地真实回归：需要从 run_real_smoke.sh --quick 提取缓存门禁实测数字（R1/R2 prompt_cache_hit_tokens），或做 v1/v2 基线对比
root_cause: ""
solution: 门禁取数：复刻脚本 key 注入 + pytest -s 单跑 gate；v1 基线仅限 deepseek（v1 无法路由 glm/minimax）；旧 commit 基线期间不并行跑 pytest
evidence: ""
tags: [real_smoke, cache_gate, pytest, v1-v2-baseline, provider_routing]
source: {}
status: active
created_at: "2026-09-10T01:37:44.682931+08:00"
updated_at: "2026-09-10T01:37:44.682931+08:00"
---

问题：scripts/run_real_smoke.sh --quick 通过（EXIT=0）但看不到缓存门禁的 R1/R2 命中数字；直跑 pytest 又因缺 key 被 skip。方案：复刻脚本 load_env_val 注入（grep -m1 '^KEY=' .env | cut -d= -f2- | sed 去注释/空白，不打印值），再 .venv/bin/python -m pytest tests/integration/test_cache_hit_smoke.py::test_cache_hit_rate_gate -m real_llm -q -s 取 print 输出。v1(255562c) 版门禁仅支持 deepseek 直连，glm/minimax 模型会拿 deepseek key 打 deepseek 端点 → HTTP 400（v2 已修为 registry 路由）；v1 基线对比只对 deepseek 有意义。git checkout 旧 commit 跑基线时勿与其他 pytest 并行（工作树文件会被替换），跑完立即 git checkout - 回分支。