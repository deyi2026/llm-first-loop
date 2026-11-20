---
title: 出图脚本别用 python3 -I：隔离模式屏蔽 user-site，Pillow 直接不可见
scenario: "LFL 推广班次出配图（docs/promotion/figures/_dNNN_figs.py，基于 _draw.py 用 PIL 画图）。本班按 RULE-AI-36「脚本先落盘再执行」的习惯写 `python3 -I /tmp/xxx.py` 或 `python3 -I figures/_d101_figs.py`，结果 `ModuleNotFoundError: No module named 'PIL'`；同一脚本用 `python3`（Xcode 3.9.6 + Pillow 11.3.0）与 `/opt/homebrew/bin/python3`（3.14.6 + Pillow 12.3.0）均正常出图。"
root_cause: ""
solution: 用 `python3 script.py`（不带 -I）跑依赖 user-site 的出图脚本；若必须隔离解释器环境，先逐个候选解释器实测 `import PIL` 再决定（`for py in python3 /opt/homebrew/bin/python3; do $py -c 'import PIL' ; done`）。-I 会同时忽略 PYTHONPATH 与用户 site-packages，RULE-AI-36 的示例姿势 `python3 -I /tmp/x.py` 与「需要 Pillow/requests 等用户级依赖的脚本」不兼容，须按依赖来源分别取姿势。
evidence: "2026-11-20 d101 出图实测：`python3 -I docs/promotion/figures/_d101_figs.py` → ModuleNotFoundError: No module named 'PIL'（退出码 1）；同一文件 `python3 docs/promotion/figures/_d101_figs.py` → 4 张图全部生成且 PIL 边界断言通过；解释器探测输出：/usr/bin/python3 3.9.6 PIL 11.3.0、/opt/homebrew/bin/python3 3.14.6 PIL 12.3.0。"
tags: [python, PIL, 出图, 解释器选择, rule-ai-36]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-20T09:07:43.498763+08:00"
updated_at: "2026-11-20T09:07:43.498763+08:00"
supersedes: [EXPERIENCE-20261117-一次性脚本依赖第三方包时不要加-python-i-隔离模式会丢-site-packages]
---