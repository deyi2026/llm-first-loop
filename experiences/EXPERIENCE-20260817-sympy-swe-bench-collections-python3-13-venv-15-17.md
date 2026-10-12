---
title: sympy SWE-bench 环境：collections 垫片 + python3.13 venv（15 实例 17/17 通过）
scenario: SWE-bench 测试 sympy（或类似老代码仓库）时：环境需 collections 垫片 + 3.13 而非 3.14。
root_cause: sympy 老代码（2017-2022）依赖 collections.Mapping（3.10 移除），Python 3.14/3.13 venv 直接 import 失败；批量 F2P 验证脚本 grep 定位同名测试函数可能选错路径。
solution: sympy SWE-bench 环境：① 用 python3.13 建 venv（3.14 不兼容老代码）；② 写 sitecustomize.py 到 venv site-packages（把 collections.Mapping/Sequence/Set 等映射到 collections.abc，python 启动即加载，早于 sympy import）；③ 装 setuptools<70 + mpmath + pytest；④ 全为极简 1-2 行修复（映射表加项/索引修正/符号修正/空参判断），15 实例 avg patch <500 字符。批量 F2P 验证：同名测试函数（如 test_Min 多个）须指定文件路径而非 grep 首命中。
evidence: 2026-08-17 SWE-bench sympy 15 实例（patch 277-505 最小子集）：17/17 FAIL_TO_PASS 全部通过。环境：sympy 老代码需 collections.Mapping 垫片（sitecustomize.py 注入 venv site-packages，3.13 下有效）+ mpmath + pytest；python3.14 venv 不兼容须用 3.13 重建。15 个修复全为 1-2 行极简改动（映射表/索引/符号/空参判断）。批量脚本对 test_Min 误判（grep 多同名），单独跑 PASSED。
tags: [SWE-bench, sympy, collections垫片, 环境搭建]
source: {}
status: active
created_at: "2026-08-17T23:49:16.194640+08:00"
updated_at: "2026-08-17T23:49:16.194640+08:00"
---