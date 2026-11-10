---
title: edit_file 重写丢执行位（落 600→索引 100644），全量门禁全绿不报
scenario: 用 edit_file 改已有可执行文件（脚本/钩子），或批量重写文件后直接 git add；需要保证 clone/CI 拿到的文件仍有执行位。
root_cause: edit_file 用新建+rename 写入，未沿用原文件权限；git 只记录执行位而不记录 r/w 位，故 600 被规范成 644；ci_gate 不含任何权限位断言，无法发现。
solution: 改完立刻核对 `ls -l` 与 `git ls-files -s`（应对齐 100755）；用全仓不变量用例把「索引执行位 ⇔ 磁盘可执行」双向钉死，负例必须实测转红。
evidence: "commit 81e59a5f8（main）；文件 tests/unit/test_githooks_exec_bit.py（test_index_exec_bit_matches_disk_repo_wide）；负例实测记录见 docs/governance/receipts/merge-review-lane-557db454-20261110-0846.json 的 rule_ai_35_negative_probe 段；事故现场: `git show --summary 08e94614a` 含 `mode change 100755 => 100644 scripts/approve_skills.py`"
tags: [git, exec-bit, edit_file, gate, 反门禁失效]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-10T09:02:49.968680+08:00"
updated_at: "2026-11-10T09:02:49.968680+08:00"
---

现象: `edit_file` 重写一个磁盘上 755 的脚本后，文件落到 0o600；随后 `git add` 把 100755 写成 100644，`r9_commit.sh` 的 ci_gate 全链路 exit=0（ruff/pyright/pytest 全绿）——门禁完全不看权限位，故障静默入库。

复现（2026-11-10 实证）: 重写 scripts/approve_skills.py 后 `git show --summary` 出现 `mode change 100755 => 100644`，磁盘 `-rw-------`；同一提交通过全量门禁。

修复（两层）:
1. 立刻恢复: `chmod 755 <f> && git update-index --chmod=+x <f>`；不要 `rg`/全文件 format。
2. 加不变量用例（已落地 tests/unit/test_githooks_exec_bit.py::test_index_exec_bit_matches_disk_repo_wide）:
   `git ls-files -s` 一次取全量模式 → 索引 100755 集合 ⇔ 磁盘 os.access(X_OK) 集合必须相等，两个方向都断言：
   - 索引 755 / 磁盘丢位 → 本机 git 跳过钩子或脚本跑不起来（pre-push 落 600 那次）；
   - 磁盘 755 / 索引 644 → 本机照常跑，clone/CI 拿到不可执行文件（本次事故方向）。
   只在 .githooks 内断言会漏掉 scripts/ 等同事故面，必须全仓。

验证: 双向负例实测均转红（`git update-index --chmod=-x scripts/approve_skills.py` → 红；`chmod 644` → 红；恢复后 88/88 索引-磁盘一致）。

边界: 该断言不能阻止「索引被降权」本身（降权后索引与磁盘都 644，不变量成立），所以它只是最后一道网；真正的硬拦截要在 pre-commit 里比对 HEAD 与暂存区的模式位差（本仓尚未实现）。另: 未来引入子模块（目录 os.access 恒真）或指向可执行目标的符号链接会误报。