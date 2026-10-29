---
title: 死参判定必须核到每条转发路径的消费终点，不能停在直接调用者签名层
scenario: "清理 cli.py application_main 320→323 引入的 plan_first_use() rule_lookup 死参（P2-4），上一轮结论是\"start 线是死接线，删 cli 调用点那行，323→322\""
root_cause: "消费面分析停在\"直接调用者签名层\"，没有展开调用者体内每条转发实参的下游终点"
solution: "删参前用 grep 列出直接调用者（run_start）体内全部转发（onboarding.py:29/:51/:57），逐条追下游（:51→run_first_use→_interactive_setup:262→inspect_first_use→doctor.py:89-92 真消费；:57→inspect_first_use 真消费；:29→plan_first_use 零消费）。只删死终点：plan_first_use 签名参数 + 两处死转发；cli.py 三处注入与 run_start/run_first_use 签名保留。回归用 .venv/bin/python -m pytest，181 passed 后 commit+review_admission(git_push) PASS+push lfl/main。"
evidence: "push lfl/main 0b6138833（P2-1 拍板豁免注记 + P2-4 死参清理）含本修正；.venv python3.13.13 pytest test_arch_guards.py + test_terminal_cli.py = 181 passed；review_admission(git_push) PASS candidate_sha256=46a940ec…；消费面 grep 留痕：onboarding.py:29/:51/:57 三条转发实读。"
tags: [dead-param, wiring-audit, refactor-safety, pytest-env]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-29T09:21:18.396675+08:00"
updated_at: "2026-10-29T09:21:18.396675+08:00"
---

核对"疑似死参"时，仅确认两件事不够：(a) 目标函数体内零消费、(b) 直接调用者签名带该参转发。必须列出直接调用者体内每一条转发实参的下游，逐条核到消费终点。本次 run_start 体内 rule_lookup 有三条转发（→plan_first_use 死、→run_first_use 真、→inspect_first_use 真），若按"删 cli 调用点那行"的方案执行会砍掉 start 线两条真消费，破坏 doctor.py:89-92 探测链。修正后 application_main 保持 323 而非预期 322，豁免注记文案需同步按实测改写。另：pytest 输出接 tail 会把 ImportError 假绿成 exit 0（Xcode python3.9 无 StrEnum，conftest 加载即炸）；跑测必须用 repo 自带 .venv（>=3.13）且看输出首行而非退出码。