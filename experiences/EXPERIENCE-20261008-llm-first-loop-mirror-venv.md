---
title: llm-first-loop-mirror 全量门禁解释器必须用仓库 .venv
scenario: ASSESS-20261008 收口轮：对 llm-first-loop-mirror 跑全量回归门禁
root_cause: ""
solution: 全量门禁必须用仓库自带 .venv/bin/python -m pytest tests/ -q；系统 python3 结果只能作局部跑。收口数字（7828/107/16）以 venv 口径为准。
evidence: job-4e5ff55b（系统 python3：52 collection error，全为 ModuleNotFoundError）与 job-9899cef（.venv：7828 passed / 107 skipped / 16 deselected）同一工作树对照
tags: []
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-08T19:53:47.133495+08:00"
updated_at: "2026-10-08T19:53:47.133495+08:00"
---

在 llm-first-loop-mirror 仓库跑全量门禁时，系统 python3 缺 pypdf/lark_oapi 依赖，tests/web/* 会出现 52 个 collection error，形似"改动破坏全量"；用 .venv/bin/python 跑同一命令得 7828 passed / 107 skipped / 16 deselected。判断依据：错误全部是 ModuleNotFoundError 而非断言失败，且 HEAD 未改动时系统 python3 同样失败。任何"全量失败"先核对解释器与依赖环境再定位代码。