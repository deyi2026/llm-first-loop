---
title: "venv-first 依赖核验——先查项目解释器再断言\"环境缺依赖\""
scenario: "tool_loop_guard 线收口验证：子代理用系统 python3 跑测试发现缺 lark_oapi，尝试 pip install 被 PEP 668（externally-managed）拒绝，遂结论\"lark_oapi/pypdf/PIL 因 PEP 668 无法装入当前环境，完整环境回归待办、15 用例 skip\"。主会话独立核实时发现项目 .venv/bin/python 里 lark_oapi/pypdf/PIL 全部可导入——子代理自始至终用错了 python，PEP 668 是对系统 pip 的正确拒绝，被误读成环境缺陷。"
root_cause: "环境结论未对照项目实际解释器验证：把系统 python 的失败当成\"环境不可用\"，而 pyproject 声明依赖在 .venv 中本已齐备。"
solution: "诊断\"依赖缺失/环境不可用\"前，第零步先验证解释器身份：`.venv/bin/python -c \"import X\"` 探测项目 venv，与 `which python3` 对照；测试命令固定用项目 venv（本仓教训已写进 spec 约束 §4：PYTHONPATH=src .venv/bin/python，勿用系统 python）。用 venv 跑通全量后，\"待完整环境回归\"待办当场闭环，15 个 skip 中大部分实为可运行用例。"
evidence: ""
tags: [python, venv, 环境验证, false-negative, PEP668]
source: {}
status: active
qualification: 2026-09-18 batch2/3 per-file review: retained（methodology self-evident：步骤可机械复现或含实测细节；evidence 内嵌正文）
created_at: "2026-09-03T07:50:31.501494+08:00"
updated_at: "2026-09-03T07:50:31.501494+08:00"
---

经验来源：tool_loop_guard 线 C-G5/C-G6 收口与主会话独立终验的对比。子代理报告"57 passed"在残缺环境不可复现；主会话用 .venv 全量回归拿到真实口径（3591 passed / 56 failed 全归并行线、0 收集错误）。教训普适：环境断言必须先验证解释器身份，再下"依赖缺失"结论。