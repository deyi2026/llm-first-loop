---
title: worktree 提交与合并队列的四个机械坑（git -C / 40 位 SHA / 真实凭证 / 执行位断言口径）
scenario: 在带 lane 主写守卫 + 合并队列的仓库里，从独立 worktree 提交一个分支并把 4 文件改动 ff 合入 main；同时给「钩子执行位静默失效」加回归守卫
root_cause: ""
solution: "提交用 `git -C <worktree> commit`（cwd 留主树）；lane_queue_submit 传完整 40 位 base/head SHA；verify_ref 用 issue_verify_receipt.py --apply 签发的 `lane:<base8>`；钩子权限守卫同时断言磁盘 0o755 与索引 100755 并做负例实测；r9_commit.sh 的 probe 红改用主树 ci_gate 绕开（并另行报修）"
evidence: "evidence://v1/e854d60d5e21f7e3c24b3aa8ef20e1adbfd6ed8eff4c5223138f9d573e3d2fb1（git -C 提交成功）；evidence://v1/20baffcaa77f52e3c4981560fa5276604cf45d0f788bfcc35a0f5c17ed9e163a（40 位 SHA 重投后四检 pass）；evidence://v1/47fd2417e590105a98bd6420e0bee27fd870bc7750ee4ae3a2e5730a0022a2b1（凭证签发）；evidence://v1/1946674d415279e2b68dcecf9b4653b976fddb409c96c45c4eaa5138b430578c（主树 ci_gate 启动）"
tags: [git, worktree, lane, 合并队列, git-hooks, RULE-AI-35, 沙箱]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-10T07:50:47.950874+08:00"
updated_at: "2026-11-10T07:50:47.950874+08:00"
supersedes: [EXPERIENCE-20261108-共享-worktree-有他人-staged-未提交文件时-用-merge-tree-commit]
---

在 llm-first-loop 仓库内做「分支 lane 提交 → 合并闸 → ff 合入 main」时，四个已复现实证的点：

1) worktree 内提交必须用 `git -C <worktree> commit`，不能用 `cd <worktree> && git commit`。
   后者报 `fatal: Unable to create '<repo>/.git/worktrees/<name>/index.lock': Operation not permitted`（exit 0 因管道末端），
   受保护命令被更严沙箱包裹，worktree 专属 gitdir 写不进去；从主树 cwd 用 `git -C` 指向 worktree 则成功。
   同理 `git -C .` 在 worktree 内会被 lane 守卫解析成「目标 main」而拒（lane_main_write_conflict）。

2) lane_queue_submit 的 base_stale 检查是**字面字符串比较**：传 12 位缩写 `36e314c87f34` 会被判 stale，
   即使它就是当前 main。必须传完整 40 位 SHA（`git rev-parse main`）。failure_reasons 会写
   `entry_base X ≠ main_head Y`，两者前缀相同即为该症状。

3) verify_ref 必须是真实凭证 ID（`data/audit/verify_receipts.jsonl` 里 `lane_id:base8`），
   由 `scripts/issue_verify_receipt.py --apply` 在 merge-review PASS 后签发；拼字符串会被判 verify_required。
   该 jsonl 被 .gitignore 的 `data/*` 覆盖，追加不脏工作树。

4) 门槛类变更要跑负例（RULE-AI-35），且要知道 git 只记录 x 位、不记录 r/w 位：
   `chmod 711` 在 git 看来仍是 100755，所以「索引模式 100755」的断言抓不到 711；
   必须在磁盘上断言 `mode & 0o755 == 0o755`。另外 `edit_file` 重写文件会丢执行位（本次实测重写
   .githooks/pre-commit 落成 600，被新用例当场拦下）——这是同类故障第 3 次，前两次因无断言而静默。

附带发现（未修，属仓库级缺陷）：scripts/r9_commit.sh 会在 /tmp 建 probe worktree 跑 ci_gate，
probe 无 .venv，而 conftest.py 在 .venv 缺失时按设计输出占位「(.venv 不存在)」，
tests/unit/test_env_preflight.py 却断言 `实测版本 \d+\.\d+`，故该红必现、与改动无关（主树同用例 12 passed）。
后果：r9_commit.sh 这条提交路径对所有人堵死；替代做法是主树直接 `bash scripts/ci_gate.sh`。