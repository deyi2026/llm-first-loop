# 验证凭证：lane fix/review-pass-cross-run（EVO-20261106-141b29b9 审查闸 PASS 资格跨 run 失效）

- 日期：2026-11-07（宿主本地时区）
- worktree：`.worktrees/evo-141b29b9` @ branch `fix/review-pass-cross-run`（base main=9242dc74c）
- 演进：EVO-20261106-141b29b9（已批准 executing，2026-11-06 21:33 提交）

## 根因（生产实测）

full_test 审查锚点（远端推送基）在 start 与消费两次独立 ls-remote 解析；
`_full_test_review_base` 把暂时性失败（网络抖动/锚不在本地）**静默降级** legacy 锚
（`return "",""`）→ 任一次失败使材料 sha 错位 → 模糊通用 deny（重算逐位一致仍被拒）。
生产规避方式为「PASS 后同轮消费」（2026-11-06 M1.1 批 3 轮 full_test + 3 轮
git_push 审查；2026-11-07 部署复现 2 次）。

## 修复（提交 52f123650）

1. 暂时性锚点解析失败显式 raise `full_test_anchor_unresolved_fail_closed`——不再
   静默换锚；网络恢复或 git fetch 后重试同一目标即消费成功（资格不失效）。
   结构性 legacy（无 remote/detached HEAD，两次解析恒一致）行为不变。
2. 远端真实移动仍拒绝（重解析防漂移语义保持，新增测试锁定）。
3. 通用 deny 指名失配维度：no_pending_qualification / parent_mismatch /
   target_mismatch / sha_mismatch（行值 vs 查询值前缀对比）。

## 门禁记录

1. **红→绿**：新增 4 例（锚点静默降级 / 抖动窗口资格可恢复 / deny 维度指名 /
   drift 语义保持），红阶段失败模式与生产 deny 原文一致（模糊通用文本）。
2. **独立审查（RULE-AI-28 full_test patch）PASS**：candidate 75cb5cae。
3. **scripts/ci_gate.sh 全链路 exit 0**：ruff ratchet 新红 0（touched 2 文件干净）、
   env-pin PASS、pyright ratchet 新红 0、xdist 全量绿（红数对账 0 新红；汇总行见
   后台任务 job-7392927a87c84789ada0 档案）。
4. **回归面**：tests/unit/test_review_host_admission.py 266 passed；+
   tests/test_escalation_review_gate.py 合跑 279 passed，零回归。

## 安全护栏实测（RULE-AI-35）

- 应拦：远端锚点真实移动后消费旧 PASS → 实测拒绝且 deny 指名 sha 维度（锁定测试）。
- 应拒（fail-closed）：锚点网络抖动 → 明确 anchor 语义 deny（非静默换锚）；网络
  恢复后重试同一目标即消费成功（资格不失效，锁定测试）。
- 多会话隔离不放宽：parent_mismatch 维度保持（其他父会话的 PASS 不可消费）。
