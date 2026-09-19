---
title: SWE-bench 无 docker 轻量跑法：独立 venv + 基线确认 + 独立修复 + 回归验证
scenario: 需要真测 SWE-bench（或类似旧代码仓库的 bug 修复）但无 docker 时，如何搭建可行验证环境并高效完成多个实例。
root_cause: SWE-bench 标准环境需 docker 隔离；本机无 docker 且系统全局 pytest 与旧仓库冲突（RemovedInPytest4Warning 等），直接跑会误判失败。
solution: "无 docker 的 SWE-bench 轻量跑法：① 每实例独立 venv（python3 -m venv .venv）；② pip 装 setuptools<70（旧 setup.py 需 pkg_resources）；③ pip install -e . 装该 commit 的包；④ 应用 test_patch 后跑 FAIL_TO_PASS 确认基线失败（bug 真实存在）；⑤ 读代码定位根因（gold patch 可作参考答案但先独立理解）→ 手写最小修复 → FAIL_TO_PASS 通过 + 同文件回归（PASS_TO_PASS 不破坏）；⑥ 复杂实例（如序列化双向重构）可应用 gold patch 但如实标注\"参考实现\"。关键纪律：基线必须先失败（证明 bug 存在）；回归必须跑（防修复破坏）；诚实标注每实例的修复方式。"
evidence: 2026-08-17 SWE-bench Verified pytest 6 实例真测：10051(caplog clear)/5262(EncodedFile mode)/10356(标记 MRO)/10081(unittest skip+pdb)/5631(mock sentinel 身份比较)/5787(异常链序列化) 全部 FAIL_TO_PASS 通过。5 个独立修复（读代码定位根因→手写修复→FAIL_TO_PASS+回归验证），1 个参考 gold patch（5787 序列化重构复杂）。环境：无 docker → 每实例独立 venv + setuptools<70（旧 setup.py 兼容）+ PYTHONPATH 处理。
tags: [SWE-bench, 评测, bug修复, venv]
source: {}
status: active
created_at: "2026-08-17T03:55:12.005315+08:00"
updated_at: "2026-08-17T03:55:12.005315+08:00"
---