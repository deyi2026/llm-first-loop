---
title: 否定性存在性结论（“机制不存在”）不得建立在字面量 grep+head 截断+单一路径追踪上
scenario: "Phase3 M0 验收基线：判断「停止 run 是否回收后台 job」时，我用 grep \"JobRegistry.instance()\" | head -15 + 只追 registry.cancel_session→terminate_session 单一路径，得出「停止路径无任何 JobRegistry 调用」的否定性结论并写入基线报告 F1 与设计书 §9.2-5，据此错误修改了 M3 的范围（新增按会话回收）。独立审查子agent发现 factory.py:731 通过 registry.add_session_cancel_hook(JobRegistry.instance().cancel_session) 已注册回收，registry.cancel_session 末段遍历 _session_cancel_hooks；S04 原始实测「job 存活」系 tests/conftest.py 装配缺该 hook（只注册了 subagent hook），非生产缺口。生产装配重跑 0.1ms killed 证实。"
root_cause: ① grep 字面量（JobRegistry.instance()）+ head -15 截断漏看 factory.py 的变量名式调用（_job_registry.cancel_session）；② 只追 terminate_session 单一路径，未检索其他 hook 机制；③ 在装配残缺的测试环境里做了生产行为结论。
solution: 撤回 F1 并在基线报告 §0/§2 留痕修订对照（不静默改历史）；设计书 §9.2-5 同步改写；S04 场景测试显式注册生产 hook 并在记录里标注 assembly 口径；M3 任务验收追加「装配一致性验证」。后续纪律：否定性结论=穷尽式检索+全文件读取；测试装配差异显式标注。
evidence: "factory.py:731（add_session_cancel_hook 注册 JobRegistry.cancel_session）；registry.py:651-670（_session_cancel_hooks 遍历）；tests/conftest.py:355（仅 subagent hook）；M0 报告 §2 修订对照（docs/phase3-m0-baseline.md）；01:53 生产装配重跑 S04 job 0.1ms killed"
tags: [负存在性主张, grep截断, 装配差异, 独立审查, Phase3, 基线]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-13T01:51:59.569579+08:00"
updated_at: "2026-10-13T01:51:59.569579+08:00"
---

1) 否定性存在性主张的检索纪律：结论「机制不存在」需要穷尽式支撑——机制入口常见多种命名（hook/callback/observer），单一路径追踪+字面量 grep+head 截断不构成穷尽。本例真实机制是 registry.add_session_cancel_hook + factory 装配注册，与我在 runner/engine 里追到的 terminate_session 是平行两层。修正动作：先 grep 机制关键词全集（hook|cancel|terminate|register），按命中文件全列再读；head 截断时必须换更窄 pattern 分批查全。2) 测试装配≠生产装配：tests/conftest.py 组装 registry 时只注册了 subagent hook，缺 factory.py:731 的 JobRegistry hook；在测试环境观测到的「停止行为」只是装配行为。涉及装配敏感行为（停止/取消/回收）的验证，必须显式对齐生产装配（在测试内注册同一 hook 并标注 assembly 口径），否则结论无效。3) 审查子agent独立复核抓到了 3 处失真+1 起记录覆盖事故，价值极高；关键结论（尤其影响后续范围决策的）应在写入设计文档前过独立审查。