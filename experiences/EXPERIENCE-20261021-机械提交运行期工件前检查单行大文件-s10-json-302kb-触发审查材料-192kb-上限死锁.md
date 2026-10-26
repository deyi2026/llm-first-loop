---
title: 机械提交运行期工件前检查单行大文件（S10.json 302KB 触发审查材料 192KB 上限死锁）
scenario: 发布前置树收口：publish 要求 tracked 树干净，需把运行期工件（reports/*.json 时间戳刷新、experiences usage 计数）机械提交；随后 push 走 RULE-AI-28 审查。
root_cause: ""
solution: 机械提交前先筛单行大文件（JSON 报告单行 302KB 类）；变更仅为运行期刷新时，restore 到已推送版本使净变化归零并单独 commit revert，材料恢复可审体量；实质内容变化的大单行文件当前无合规推送通道，提演进建议。
evidence: 2026-10-21 回执链：review_admission start 拒绝 material=339158B cap=192000B（largest=S10.json 302187B）；恢复 S10.json 净变化归零（commit 5334efcad）后同口径材料约 37KB，review PASS（child_id=subagent_d692315b4370，candidate c4ac2fa…），push 成功 f68fcb0d2..5334efcad；publish 拒绝回执 tracked_worktree_dirty。
tags: [publish, review-admission, git-push, runtime-artifacts, material-cap]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-21T19:29:15.195044+08:00"
updated_at: "2026-10-21T19:29:15.195044+08:00"
---

现象：机械提交运行期工件（publish 前置树收口）后，review_admission(git_push) 拒绝：review_artifact_exceeds_192kb，largest 指向 committed:reports/phase3/m0/S10.json=302187B。

机制：审查材料含 committed_delta（base=push_remote_commit）。JSON 报告若是单行超长文件（S10.json 单行 302KB），diff 中任何 +/- 行都是完整单行，一个字段的刷新就贡献 ~300KB 材料，远超 192KB cap。_RUNTIME_OUTPUT_EXCLUDES 只排除 uncommitted 变更，committed 的 reports/ 全量计入。旧先例（f129bf871 等）过审依赖 merge-base(HEAD,main)==HEAD 的审查盲区，EVO-20261021-89256d43 修复后不可复用。

处置（已验证）：
1. 机械提交前检查变更清单里是否有单行大文件：git diff --stat + 对可疑文件 grep -c '^' 与 wc -c；
2. 若大单行文件的变更仅为运行期刷新（时间戳/计数），将其恢复到已推送版本使净变化归零：git restore --source=<origin HEAD> -- <file> 并单独 commit revert；base..HEAD 的 diff 不再包含该文件，材料恢复可审体量；
3. 其余运行期工件正常机械提交；
4. 若大单行文件确有实质内容变化且必须推送，当前无合规通道（结构死锁），已提演进建议（EVO-20261021-2f22aae5）待人工裁决。