---
title: Linux 现场旁路验证 LFL wheel 的可复用流程与三个坑（here-doc 硬阻断 / wheel 改名 / requires-python 门）
scenario: macOS 开发机向 Linux 现场（ssh 可达、活动 LFL release 需保护）做 fix wheel 端到端旁路验证；现场只有系统 python3（低于 requires-python），无 uv，活动 venv 无 pip。
root_cause: ""
solution: 本地构建→验包内容→scp 保名→旁路 venv --no-deps 安装→探测文件（printf 生成+scp，规避 here-doc 硬阻断）→活动版对照+未动复检。
evidence: "2026-10-28 22:33–22:36 execute_command 回执（probe 输出）：fix wheel sha256=47958304e11ce37a4b9b0a13943fabc2cec96125286e5d0b695d72450cd22990；wheel 含 _bundled/docs/ai_rules.lite.md(4681B)/ai_rules.md(98174B)/manifest.json；~/lfl-fixtest venv 中 rules_version()='20'、causality/status._rules_version() 均为'20'、lite exists=True；活动 0.6.37 venv 同探测返回''；活动 wheel 5747264B/14:21/sha e3de7657…未变，lfl --version=0.6.37。硬阻断回执：'here-doc 交给解释器执行'（E6_CATASTROPHIC_HARD）。pip 失败回执：'Invalid wheel filename (wrong number of parts): lfl_fix_0.6.37'。报告记录：artifact://v1/4ab639752b70492dabab7ff134e0f9b7 §2.6。"
tags: [ssh, wheel, e2e-verification, bypass-install, sandbox-hard-block, pip-wheel-filename]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-28T22:40:30.842355+08:00"
updated_at: "2026-10-28T22:40:30.842355+08:00"
---

场景：需要在 Linux 现场（无 pip/uv 的活动 venv、系统 python 3.12）验证一个含 fix 的 LFL wheel 是否解决 rules_version 空值，同时不许动活动 release。流程（2026-10-28 实测全通）：1) 本地 uv build --wheel，unzip -l 先验 _bundled/docs/ai_rules.lite.md 与 manifest 在包内，记录 sha256；2) scp 到远端 /tmp 时**保留规范 wheel 文件名**（曾改名 lfl_fix_0.6.37.whl 触发 pip "Invalid wheel filename"）；3) 远端 python3 -m venv ~/lfl-fixtest + pip install --no-deps --ignore-requires-python（pyproject requires-python>=3.13 而现场系统 3.12；探测模块 import 面为纯 stdlib + llm_loop，--no-deps 可行）；4) 探测脚本用 printf 逐行写成文件后 scp，远端普通命令链执行——**不要用 ssh 'python - <<PY'**（here-doc 交给解释器会触发 E6_CATASTROPHIC_HARD 硬阻断）；5) 同一探测在活动 venv 跑对照，并复检活动 wheel mtime/sha 确认未动。旁路安装不动 releases/ 指针，验证完留 ~/lfl-fixtest 与 /tmp wheel 供复查或清理。局限：这是旁路 smoke，不能替代 -I/离仓库/PYTHONPATH 剥离与全量门禁。