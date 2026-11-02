---
title: 审查闸自引用时存在引导悖论：先部署再补全量，并保留离线对账通道
scenario: "需要交付的变更本身就是 RULE-AI-28 审查准入的实现（命令分类器、切片外绑定、材料构造），而准入判定运行在\"已部署\"代码上：修复前 scope=patch 因旧绑定 git_state_too_large 报不可校验、scope=tree 因材料 762K 字符过不了时长预检，两条路同时不可用，于是\"修闸\"这项变更拿不到任何全量测试资格（引导悖论）。"
root_cause: ""
solution: "1) 先做定向证据（受影响套件全绿 + 逐项回归锁）；2) 显式披露\"全量未跑\"及原因，不把定向当全量；3) 先 publish 后由 worker 重启，使部署版带修复，下一轮再走 review_admission 拿 PASS 跑全量；4) 长期修法：准入判定应读取 worktree 代码而非部署代码，或提供只读离线对账通道（full_test_report.py --report 读现成 junit）。当前性验证：grep 确认 review_host_admission.py 中 _out_of_scope_binding 已用 rev-parse HEAD + diff --name-only，且 review_admission(scope=patch) 不再报 review_scope_drift_unverifiable。"
evidence: "本轮 review_admission(full_test, scope=patch) 返回 review_scope_drift_unverifiable；scope=tree 返回 reviewer_duration_precheck est=7625s>3600s(task=762509chars)；publish 后 .releases/924dbbea3 内含修复文件，restart 受理 svc-b5e8924cf52f4b80bdb2cab8223754e9（deferred_effect=requester_run_end）。另：scripts/full_test_report.py --report 模式已实现只读对账，可作离线通道雏形。"
tags: [review-gate, bootstrap, process, rule-ai-28]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-02T10:29:03.031351+08:00"
updated_at: "2026-11-02T10:29:03.031351+08:00"
supersedes: [EXPERIENCE-20261025-review-admission-两坑-路径须绝对-按工具-cwd-解析非-workdir-revi]
---

适用边界：仅当待交付变更触及准入自身实现（classify_host_shell / _out_of_scope_binding / _source_snapshot 材料构造）时成立；普通业务变更不受影响，仍走"先 PASS 后全量"。

反例/不适用：如果部署本身有风险（会破坏在线服务），不要用"先部署"破局，应改为缩小材料（scope=patch 明确 paths）或临时降低仓库 tracked 规模；本次接受先部署的理由：变更是纯读判定逻辑、受 223 条定向测试覆盖、重启 deferred 到 run 结束可中断。

当前性验证：先 `grep -n "_out_of_scope_binding\|_REVIEW_REPORT_WRAPPER" src/llm_loop/tools/review_host_admission.py` 确认两个符号存在；再 `git ls-files | wc -l` 确认 tracked 规模仍 >5000（这是本陷阱的触发条件）；随后 `review_admission(action=start, kind=full_test, scope=patch, ...)` 若返回 review_scope_drift_unverifiable 即复现了本陷阱。