---
title: macOS 上跑 LFL CLI/doctor 的正确姿势：.venv/bin/lfl + 写临时 .py 文件（系统 python 与内联 heredoc 均不可用）
scenario: "2026-10-29 12:10 自我检查中试图用系统解释器跑 `lfl doctor` 取运行时健康证据，连续踩三种失败：系统 /usr/bin/python3 是 Xcode 3.9（缺 tomllib）、/opt/homebrew/bin/python3 是 3.14（缺 Crypto，且 import 到 .releases 树而非工作区 src）、macOS 无 `timeout` 命令；另外把 python 脚本用 heredoc 直接管道给解释器执行，被 E6 灾难守卫硬阻断。"
root_cause: ""
solution: "在 llm-first-loop-mirror 工作区做只读诊断：(1) 一律用 `.venv/bin/lfl <cmd>`（或 `.venv/bin/python`）——它带齐 tomllib/Crypto 且指向正确依赖；(2) 需要 Python 逻辑时用 `cat > /tmp/x.py <<'EOF' ... EOF` 再 `python3 /tmp/x.py`，绝不写 `python3 -c \"...\"` 或把脚本管道给解释器；(3) macOS 无 GNU timeout，不要用 timeout 包命令，改用工具自身参数或 `gtimeout`/后台 job；(4) 读非 UTF-8 文件（如含中文的 jsonl）用 errors='replace' 兜底，避免 UnicodeDecodeError。"
evidence: "失败回执：/usr/bin/python3 -m llm_loop.cli doctor → ModuleNotFoundError: tomllib（Python 3.9 Xcode）；/opt/homebrew/bin/python3 -m llm_loop.cli doctor → ModuleNotFoundError: No module named 'Crypto'（3.14.6，且 traceback 指向 .releases/41cac7b7 树）；`timeout 90 python3 ...` → bash: timeout: command not found（退出码 127）；`python3 - <<EOF` 管道直连解释器 → [安全硬阻断][E6_CATASTROPHIC_HARD] 任意管道直连解释器执行（FR-SAFE-01）；`head -c 600` 读含非 UTF-8 字节的 jsonl → UnicodeDecodeError: 'utf-8' codec can't decode byte 0xe5 in position 1688。成功回执：`.venv/bin/lfl doctor` → 状态：ready，9 项检查全通过（上下文资产：规则索引 8 条、方法 13 条、经验 693 条、技能 37 个；rules_version=20）"
tags: [macOS, venv-first, doctor, heredoc, E6硬阻断, 诊断取证]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-29T12:21:20.013239+08:00"
updated_at: "2026-10-29T12:21:20.013239+08:00"
---