---
title: 判据 A/B 重判必须走生产调用路径，直接调谓词会造出假翻转
scenario: "改判据（verdicts.py）后想量化\"修了多少、误放了多少\"。我先写脚本直接调 VERDICTS['no_violation'](trace, answer, forbidden=..., context=...) 做对比，得到 3 处翻转，其中 RL12 s2 看起来是\"禁止类从违规翻成通过\"——若属实就是误放，是严重问题。但换成生产真实路径 run_verdict 重判后，RL12 s2 一直判 True（无翻转），真实翻转只有 2 处，且都是误杀修复。差点把一个不存在的问题报成 P0。"
root_cause: ""
solution: "判据重判对比必须走**生产调用路径**（run_verdict + params），不能直接调谓词函数：no_violation 有 neg_scope 等关键字参数有默认值，直接调用漏传会得到与生产不同的结论（我漏传 neg_scope='sentence'，把一句里的 \"RULE-AI-\" 误判成违规）。正确做法：(1) 先用 git show HEAD:<file> 取出旧版模块到 /tmp，用 importlib 加载成第二个命名空间，两版并存；(2) 两侧都调各自的 run_verdict，params 从 spec 的 case 里取（排除 cid/prompt/input 等元信息）；(3) 翻转样本逐条读原文核实方向，禁止类若出现 False→True 必须逐条确认不是误放；(4) 同时报告\"禁止类判据 0 翻转\"这类负向证据。"
evidence: "旧批 rule_redline_v2_m31flash_20261023/checkpoint.jsonl 全 108 条；生产路径 run_verdict 重判 v4=83 v5=85，仅 2 处翻转（RL04 s1/s6 英文拒绝，False→True）；禁止类 forbidden 判据 0 翻转。src/llm_loop/eval/verdicts.py v5 改动（_NEG_WORDS 补英文、窗口 4→12、refuses_destructive/refuses_injection/evidence_ref_required/budget_cap_respected 补英文形态、answer_has_receipt 补 harness 工具名与\"路径+具体内容值\"形态）。tests/unit/test_eval_verdicts_*.py 107 passed。当前性验证：跑 `grep -n \"v5 英文形态\|v5 英文否定形态\" src/llm_loop/eval/verdicts.py` 应有多处命中；跑 `.venv/bin/python -m pytest tests/unit/test_eval_verdicts_heldout.py tests/unit/test_eval_verdicts_redline.py tests/unit/test_eval_verdicts_v2.py -q` 应全过。"
tags: []
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-23T19:24:23.291495+08:00"
updated_at: "2026-10-23T19:24:23.291495+08:00"
---