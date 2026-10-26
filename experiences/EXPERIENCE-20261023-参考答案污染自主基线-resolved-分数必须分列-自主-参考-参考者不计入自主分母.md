---
title: "参考答案污染自主基线：resolved 分数必须分列\"自主 / 参考\"，参考者不计入自主分母"
scenario: "SWE-bench 类基准上产出修复结果时，修复过程可访问仓库 git 历史、数据集 gold patch 或官方 commit，最终只报一个总 resolved 率（如 19/19 = 100%），把\"自主修复\"与\"参考官方修复\"混进同一个分母。"
root_cause: "judge 只判\"最终是否 resolved\"，不判\"是否自主\"；修复路径的差异被总分掩盖，导致基线被系统性高估，并让后续 harness 对比（A/B、pass@1）建立在被污染的分母上。"
solution: "评测纪律三条：(1) 只读 problem_statement + test_patch，不读 gold patch / 官方 commit（若已读入，必须逐例标注为\"参考\"）；(2) 报告必须分列\"完全自主修复 / 参考官方修复（含直接应用 gold）\"两类，并给出各自计数；(3) 参考类不计入自主分母，跨会话/跨 agent 对比只用自主子集；(4) 历史记录中已混入参考的分数不可直接当基线，需重跑或降级标注。"
evidence: "2026-10-23 实测 docs/metrics/SWE-bench-official-pytest19_20260817.md：标题称 SWE-bench Verified pytest 19 实例 19/19 resolved (100%)，但同一文档\"修复方式统计（诚实标注，修正版）\"写明完全自主修复 7/19、参考官方修复 12/19（其中 2 例直接应用 gold patch、8 例应用官方 git fix commit、2 例读入参考后手动实现），且记录了\"10051 曾误标独立，已修正\"这一误标事实 —— 单看 100% 会严重高估自主能力。纪律来源另见 experiences/EXPERIENCE-20260820-swe-bench-django-full.md（只看 problem_statement+test_patch，杜绝 gold patch）。"
tags: [SWE-bench, 污染, 自主性, 评测纪律, baseline]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-23T08:53:40.750316+08:00"
updated_at: "2026-10-23T08:53:40.750316+08:00"
---