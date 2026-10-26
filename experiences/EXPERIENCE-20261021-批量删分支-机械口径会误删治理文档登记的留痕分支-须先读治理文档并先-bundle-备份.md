---
title: 批量删分支：机械口径会误删治理文档登记的留痕分支，须先读治理文档并先 bundle 备份
scenario: 按「已合并分支可删」批量清理本地分支时，仓库内可能存在 docs/governance/branch-triage-*.md 之类的治理文档，把部分分支登记为 B 组（留痕不合并）/ D 组（长期实验现场），并明写「本次不删」「批量删除待用户明示」。
root_cause: 只用了机械口径（merged/cherry）判定可删集，未先读仓库内治理文档的分组登记，导致删除本应保留的留痕/实验分支；且删除前未预先对整个待删集做 git bundle 备份。
solution: "删除前必须同时用两类口径判定「可删」，不能只用 git branch --merged / git cherry：① 拓扑口径（已合入 main）；② 内容口径（git cherry main <branch> 全为 '-'，即 squash 合入导致拓扑未合入但内容已合入）。更关键的是先读仓库治理文档（docs/governance/branch-triage-*.md、docs/branch-disposition-*.md）——它可能把某些分支登记为「留痕/实验现场/本次不删」，这类登记应优先于机械判定，需保留。被机械口径误删的分支可用删除日志里的 \"Deleted branch X (was <sha>)\" 精确 SHA 恢复，或用 git bundle create 预先备份整个待删集（git bundle create f.bundle <branches...>）后 git fetch <bundle> 'refs/heads/X:refs/heads/X' 恢复。删除前必须先 bundle 备份整个待删集。"
evidence: 本次实测：181→20 分支清理中，机械口径（git branch --merged + git cherry 全 '-'）把 docs/governance/branch-triage-20261017.md 登记的 B 组 rule31×4 与 D 组 feat/harmonyos-native-agent-poc-20261011 一并删掉；D 组为「长期实验现场」性质，已从预先创建的 bundle 恢复；B 组 4 个当时 ahead=0（已被 main 吸收），经 bundle 备份后按用户「已合并即可删」的明示删除。另注意文档里的分支名可能与实际分支名有日期笔误（文档写 20260909，实际为 20261009），需用 git branch/tag --points-at 交叉核对，治理文档里 rule31×4 的 HEAD=2ad0bc06d 也已被后续提交取代（实际 tip 79cef184b）。
tags: []
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-21T21:40:20.561999+08:00"
updated_at: "2026-10-21T21:40:20.561999+08:00"
supersedes: [EXPERIENCE-20261017-merged-分支误删恢复与证据分支批量归档安全流程-含并发-refs-退避]
---