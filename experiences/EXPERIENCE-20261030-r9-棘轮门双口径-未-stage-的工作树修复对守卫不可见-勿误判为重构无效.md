---
title: R9 棘轮门双口径：未 stage 的工作树修复对守卫不可见，勿误判为重构无效
scenario: "在 llm-first-loop 仓库做函数行数减重（R9 棘轮门只降不升）时，修复只写在工作树、未 git add：test_arch_guards.py 的棘轮对账仍报 HEAD/暂存口径的旧行数（如 196/75），看起来\"改了没用\"。"
root_cause: ""
solution: "识别守卫双口径而非反复改代码：porcelain 为 ' M'（X 不在 {'M','A'} 且 Y=='M'）时 _read_source 读 `git show HEAD:<rel>`，只有 'M '/'MM'（含 staged 现实）才读工作树。先用 git status --short 确认 XY 码，再用 git show HEAD:<f> / :<f> 与工作树文本分别 AST 计量定位守卫实际读的版本；守卫 stderr 自带指引\"修复仅在工作树请 git add 后复验\"。在禁止 git add 的委派下：如实报告 + monkeypatch _git_porcelain=lambda:[] 复跑 _ratchet_problems 做 stage 后等价仿真（working 口径=stage 后现实），由掌握 git 的父代理执行 stage/commit。"
evidence: "实测三口径：HEAD run=75/execute=196、INDEX 同 HEAD、WORKING run=68/execute=164；真实 pytest -q 为 1 failed(棘轮)/39 passed 且 stderr 给出 git add 指引；porcelain=[] 仿真 _ratchet_problems=[] 全绿。仓库为 llm-first-loop 主仓（本机工作副本绝对路径已脱敏，不入库），本轮 write_scope 减重任务。"
tags: [ratchet-guard, dual-caliber, git-porcelain, test_arch_guards, rule-ai-28]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-30T14:24:13.647369+08:00"
updated_at: "2026-10-30T14:24:13.647369+08:00"
---

tests/unit/test_arch_guards.py 的 _read_source 有双口径：porcelain ' M'（纯工作树漂移、X 不在 {M,A}）→ 读 `git show HEAD:`；'M '/'MM' → 读工作树。因此：HEAD/暂存区里是"未重构的功能版"而重构只落在工作树时，test_function_lines_ratchet_within_baseline 仍按 HEAD 报旧值失败，且 stderr 会提示"若你的修复仅在工作树，请 git add 后复验"。验证方法（2026-10-31 实测）：对同一文件分别用 `git show HEAD:f`、`git show :f`、工作树读文本跑 AST 计量对比；或 monkeypatch test_arch_guards._git_porcelain=lambda:[] 后调 _measure_functions()+_ratchet_problems 做 stage 后等价仿真。结论：未 stage 的减重修复不可能让该门在真实命令下变绿；如实报告 + 仿真证明 + 由控制 git 的父代理执行 stage。