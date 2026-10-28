---
title: R28 full_test 执行前 pop 运行期 dirt 的单文件体积风险（历史上限 192KB，现行 2.5M 字符）
scenario: 【历史现场，2026-10-21 当时上限 192KB；现行 2.5M 字符下 302KB 单文件不再超限】R28 full_test 审查门与运行期 dirt 的顺序冲突：先 PASS 后 pop 再跑全测时，材料按 dirty 全文计，可能被拒
root_cause: ""
solution: "把 dirt re-stash 回\"已获 PASS 的干净树状态\"执行已审查命令；原 dirt 留 stash 保全"
evidence: "2026-10-21 执行链实测：pop 后 execute_command 阻断回执 review_artifact_exceeds_192kb（含管道复合阻断 compound_protected_shell_requires_split_commands 各一次）；re-stash 后同一 PASS 准入（candidate_sha256=640e282a, subagent_4137f73b2c12）绑定成功，uv run --no-sync pytest -q 完整运行 744s 至终态 exit=1（2 failed=已知基线）。"
tags: [rule-ai-28, review_admission, full_test, git-stash, 192kb-cap]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-21T16:38:36.624037+08:00"
updated_at: "2026-10-21T16:38:36.624037+08:00"
---

> **当前适用性（2026-10-28 复核）**：审查材料上限已是 **2.5M 字符**（超限码 `review_artifact_exceeds_cap`），192KB 已废止。本卡触发条件“单文件 302KB 即超限”不再成立——302KB 远低于当前上限，pop 运行期 dirt 后通常可直接绑定执行，不必 re-stash。仍成立的纪律：材料按 dirty 文件完整内容计（单行大文件的一次刷新会放大材料）、被阻断后不得修剪/删除超限产物或绕过门。

场景：R28 Host 审查门下执行 full_test（如 uv run --no-sync pytest -q）。审查门 PASS 后 git stash pop 恢复运行期 dirt（测试再生成 reports/experiences），随后执行全测被阻断：review_artifact_exceeds_192kb——审查材料按 dirty 文件完整内容计，reports/phase3/m0/S10.json 单文件 302KB 即超 192KB 静态上限；重新 review_admission start 同样被拒（start 即拒，非可等待的轮询态）。
合规解法（实测有效）：git stash push 把 dirt 重新收起 → 工作树回到审查凭据（candidate_sha256）冻结的干净状态 → 该状态下既有 PASS 准入即可绑定执行（单条命令原样，不得加管道/复合，复合会被 compound_protected_shell_requires_split_commands 阻断）→ 原 dirt 全量保留在新 stash 条目中不丢失，事后按需取回。
边界：不要为过门修剪/删除"超限产物"（篡改证据）；不要绕过门；若业务上必须"带 dirt 运行"（测试读该 dirt 作输入），当前机制无解，应如实上报而非换壳执行。