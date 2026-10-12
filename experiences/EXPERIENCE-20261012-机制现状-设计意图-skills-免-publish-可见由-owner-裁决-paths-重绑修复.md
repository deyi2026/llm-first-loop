---
title: 机制现状≠设计意图：skills 免 publish 可见由 owner 裁决，paths 重绑修复已落地
scenario: "skill_list 发现不了工作区新 skill 时，我曾把\"注册表只读发布快照\"当设计行为记录进经验卡；owner 纠正：免 publish 即可见才是意图，现状是缺陷。"
root_cause: ""
solution: "机制类事实与设计意图分开记：事实卡只记\"观察到的机制\"，\"是否应该如此\"必须由 owner 裁决。发现行为与直觉预期冲突时，先提请 owner 确认意图再定缺陷/特性，不要在经验卡里自封\"设计行为\"。修复模式：运行态资产类目录（skills 与 data/experiences 同类）在 linked sidecar 场景统一重绑主工作树。"
evidence: commit ad5bb66c9 + 回执 docs/governance/receipts/20261012-skills-live-rebind-review.json + A/B 日志（/tmp/unit_full.log 287F/6860P vs /tmp/unit_baseline.log 287F/6859P）+ 审查子代理 subagent_3fdd5946aad3 verdict PASS
tags: [skill-registry, runtime-paths, linked-worktree, owner-directive, fact-vs-intent, RULE-AI-28]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-12T23:28:13.096245+08:00"
updated_at: "2026-10-12T23:28:13.096245+08:00"
---

事实链：owner 澄清设计意图=工作区新 skill 免 publish 即入注册表；此前 skills_dir 跟随 code_root（发布快照）是把"机制现状"误当"设计意图"的教训。
修复（verified，commit ad5bb66c9）：resolve_runtime_paths 中 skills 在 linked_worktree（发布快照运行态）场景解析到 git common_root/skills（主工作树），显式 SKILLS_DIR 仍最优先，非 linked 场景行为不变——与 data/experiences 的重绑模式一致。
验证：定向 7/7；A/B 全量基线（stash 前后各跑一次全量 unit）失败集合 287=287 完全一致（全预存依赖缺失），passed 6859→6860 净增即新测试；独立子代理审查 PASS（0P0/0P1/4P2，2 采纳 1 拒绝 1 无需动作）。
边界：运行中进程的 skills_dir 启动时已解析，修复自下一次运行时重启起生效；重启前子代理仍可 read_file 工作区路径即时用 skill。
可复用判据：把"现状行为"升格为"设计意图"前必须问 owner——事实层正确不等于意图层正确。