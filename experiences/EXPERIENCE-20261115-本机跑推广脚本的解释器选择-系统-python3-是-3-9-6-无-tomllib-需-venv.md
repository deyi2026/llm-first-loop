---
title: 本机跑推广脚本的解释器选择：系统 python3 是 3.9.6（无 tomllib），需 .venv/bin/python，且 -I 会剥离 site-packages
scenario: 在推广班次里跑需要 websockets（CDP）或宿主模块（tomllib）的脚本时，反复遇到解释器选错导致的假故障。
root_cause: ""
solution: 需三方包或宿主模块 → 用 .venv/bin/python 执行且不加 -I；一次性脚本落盘到工作区再执行（避免 heredoc 交给解释器被安全闸硬阻断）。
evidence: "本班实测：python3 --version → Python 3.9.6；.venv/bin/python --version → Python 3.13.13；`.venv/bin/python -c \"import tomllib, websockets\"` → deps ok；`python3 -I /tmp/x.py` → ModuleNotFoundError: websockets。STATUS-20261115-daily87.md 第十节第 10、11 条"
tags: [推广班次, python版本, venv, tomllib, websockets]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-15T08:34:35.309524+08:00"
updated_at: "2026-11-15T08:34:35.309524+08:00"
---

场景：推广班次脚本需要 import 宿主仓库模块（src/llm_loop/...，内部用 `tomllib`）或第三方包（websockets）时：

- 系统 `python3` 在本机是 **3.9.6**（无 `tomllib`，Python 3.11+ 才有）→ `ModuleNotFoundError: No module named 'tomllib'`；
- 仓库自带 `.venv` 是 **Python 3.13.13**，依赖齐全 → 用 `.venv/bin/python <script>` 执行；
- `python3 -I`（isolated mode）会剥离 site-packages → `import websockets` 失败，且该失败与脚本内容无关，容易误判成脚本写错。

对策：
1. 需导入宿主模块或三方包 → 一律 `.venv/bin/python`；
2. 不加 `-I`；
3. 一次性脚本先落盘到工作区再执行（RULE-AI-36）：heredoc 交给解释器会被安全闸硬阻断（E6_CATASTROPHIC_HARD），需 `cat > file.py <<'EOF' … EOF` + `python3 file.py`；
4. 若脚本要落盘到 /tmp 且需要三方包，不要用 `python3 -I /tmp/x.py`，改为落盘到工作区并用 `.venv/bin/python` 执行。