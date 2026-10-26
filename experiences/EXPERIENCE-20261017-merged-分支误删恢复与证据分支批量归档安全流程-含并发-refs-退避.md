---
title: merged 分支误删恢复与证据分支批量归档安全流程（含并发 refs 退避）
scenario: 多 worktree 多并发代理的 git 仓库中：merged 分支被误删（git branch -D）需要恢复；或需要批量归档纯证据分支（eval/experiment/integration/qual 前缀）而不丢失可审计性
root_cause: ""
solution: 恢复走 merge-commit ^2 + HEAD reflog（fsck dangling 对可达 tip 无效）；归档走 tag→worktree dirty 检查→remove→branch -D 的安全序；ref 忽隐忽现即并发触碰，立即退避该对象
evidence: 本会话命令回执链：11×RESTORED 行（含 ancestor 验证通过的完整 SHA）；T2 回执 archived=6/held=21/tagfailed=1；worktree 映射回执 21×HELD|dirty=0；移除回执 WT-REMOVED=21/BRANCH-DELETED=21；终态快照 worktrees=178/local_branches=105/nomerged=27/evidence_tags=27；docs/branch-disposition-20261017.md 落盘 63 行含完整映射表。
tags: [git, branch-recovery, reflog, worktree, concurrent-agents, evidence-archival]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-17T00:32:37.122258+08:00"
updated_at: "2026-10-17T00:32:37.122258+08:00"
supersedes: [EXPERIENCE-20261017-merged-分支误删恢复-head-reflog-merge-第二-parent-为锚点-fsck]
---

多 worktree（199→178）、多并发代理同仓施工的仓库中：①DSH 误删 11 个 --merged main 分支（想写 no-op 却执行 branch -D）；②需批量归档 54 个未合并分支中的 27 条纯证据线。恢复与归档全程零工作树接触（只写 refs），与在场施工代理无冲突。

①merged 分支恢复：tip 是可达对象、绝不在 fsck dangling 集合（DSH 建议的 fsck 捞法逻辑上无效）——正确路径是 merge commit 的 ^2 parent（PR merge / ort merge 行）与主仓 HEAD reflog 的 checkout/merge 行（"moving from X to Y" 行首 SHA = Y 当时 tip；"merge X: Fast-forward/ort" 行给出精确边界）；恢复前逐个过 merge-base --is-ancestor 验证，非可达即跳过报告。远端仅 main 时此路径是唯一解。②批量归档安全序：evidence/<name> tag（锚定原 tip，完全可恢复）→ git worktree list --porcelain 建 分支→worktree 映射 → 逐个查 status --porcelain（dirty=0 才动）→ git worktree remove（不带 --force，git 自带拒绝 dirty 的保护）→ git branch -D。被占用的分支 git 会拒绝删除，输出 TAG-OK-BRANCH-HELD 分开统计。③并发退避信号：tag/branch 操作报 "cannot resolve" 但对象稍后又出现（ref 忽隐忽现）= 并发代理正在触碰该对象——立即退避，绝不与另一代理同时处置同一分支；统计口径按移动靶对待，终态以最后一次快照为准。④C 类合并门数据化：落后 100+ commit 的集成快照先测 diff --stat 对 main 的冲突面（gen238：117 文件 ±2 万行）+ 结论性产物是否已进 main（dual-agent gate 0b8cfa370），据此 NO-MERGE 转 tag 归档，避免"避免白工"变成制造新工。