---
title: "pytest 双 -q（addopts 叠加）静默吞掉最终统计行——exit 0 但日志无 \"N passed\""
scenario: "LLM 长任务终验：全量 pytest 跑完 exit=0，但日志 grep 不到 \"passed\" 汇总行，无法直接读出通过数。lfl_merge_full2.log（2026-09-11，mirror 仓 main 合并验收）实际为 117 行完整文件、无任何截断。"
root_cause: ""
solution: "三步定位：1) tail | cat -et 确认末行换行完整（本例末行是 wrapper 追加的 full_exit=0，非撕裂）；2) grep session starts/collected 确认连横幅也没有 → 系统性缺失而非丢字节；3) 复原原始命令并查 pyproject addopts——命令行 -q 叠加仓库 addopts 自带 -q，verbosity=-2。pytest 9.1.1 对照实验（3 测试）：-q 仍输出 \"3 passed, 1 warning in 0.00s\" 无边框统计行；-q -q 连统计行都省略，但点号进度、warnings summary、-- Docs 行保留。该行为与日志结构逐项吻合。替代可靠信号：退出码 + 进度区统计（tr -cd '.' | wc -c 数点=passed 数，数 s=skipped，零 F/E/x）。修复预防：终验跑法写 pytest -q（单层）或显式 -o addopts= 抵消叠加。"
evidence: "对照实验：/tmp/pq_probe 3 测试，-q 输出 \"3 passed, 1 warning in 0.00s\"，-q -q 无统计行。事件流复原原始命令：cd /private/tmp/lfl-merge-cache-20260911 && .venv/bin/python -m pytest tests -q > /tmp/lfl_merge_full2.log 2>&1; echo full_exit=$?。仓库 pyproject.toml:59 addopts 含 -q。"
tags: [pytest, verbosity, addopts, evidence-verification, exit-code, ci-logs]
source: {}
status: active
created_at: "2026-09-11T01:29:05.343527+08:00"
updated_at: "2026-09-11T01:29:05.343527+08:00"
---

症状：全量 pytest 日志中 grep 不到 "N passed" 汇总行，但 exit=0，进度区点数正常。
诊断路径：tail 看行尾是否撕裂（排除截断）→ head 找 session starts 横幅 → 查 pyproject addopts 与 CLI 参数叠加。
根因：仓内 addopts="-q ..." + CLI "-q" → verbosity -2。pytest 9.1.1 实测：-q（单）仍输出无边框统计行；-q -q（双）完全省略最终统计行，但保留点号进度、warnings summary、-- Docs 行。
可靠信号：① 退出码；② 进度区统计：grep -E '^\.*[.s]+ +\[ *[0-9]+%\]' log | tr -cd '.' | wc -c（点数=passed），s 计数=skipped，F/E/x 标记=失败/错误。
预防：终验命令显式对冲，如 pytest tests -q -o addopts='' 或用 --no-header 单独控制，保留统计行。