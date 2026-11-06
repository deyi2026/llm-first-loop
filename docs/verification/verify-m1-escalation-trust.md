# 验证凭证：lane m1-escalation-trust（M1 提权审批可信可恢复）

- 日期：2026-11-06（宿主本地时区）
- worktree：`.worktrees/m1-escalation-trust` @ branch `m1-escalation-trust`
- 设计书：`docs/promotion/LFL_Sandbox_Escalation_Audit_Requirements_Design_2026-11-06.md` §13 M1 批次

## 修复范围（ESC → 提交）

| 问题 | 修复 | 主要验证 |
|---|---|---|
| ESC-04 到期时间缺失/非法消费放行 | consume/consume_for_execution fail-closed 拒绝+作废令牌 | `tests/unit/test_escalation_m1_trust.py::test_consume_rejects_*` |
| ESC-09 过期投影不一致 | `_effective_status` 统一投影（list/get/wait/consume） | `test_list_projects_expired_uniformly` / `test_wait_for_decision_projects_expired` |
| ESC-03 失效 pending 复用 | create 幂等排除 `_sig_unverified`；wait 快速失败 | `test_create_does_not_reuse_cross_process_stale_pending` / `test_wait_tool_fails_fast_on_unverified_record` |
| ESC-07 待审被最新 50 条挤出 | 前端 pending 专用查询 `status=pending`；store 过滤排除失效记录 | `test_pending_not_squeezed_out_by_newer_terminal_records` + EscalationCenter.test.tsx（挤出场景） |
| ESC-08 存储错误伪装空列表 | list/detail 存储 OSError/ValueError → 503+error（细节只入日志） | `test_corrupt_store_returns_503_not_empty_200` / `test_unreadable_store_returns_503`（root skipif） |
| ESC-05 长命令不可完整审阅 | detail 端点返回未截断原文；前端"查看完整命令"入口+批准门控+指纹比对 | `test_detail_returns_untruncated_command` + EscalationCenter.test.tsx 门控用例 |

## 门禁记录

1. **独立审查（RULE-AI-28 full_test）4 轮**：
   - R1 REVISE（P1×1 detail 判别冲突 + P2×5）→ 全部修复
   - R2 PASS（candidate a4c534d7）
   - lint 提交后产物变化 → R3 PASS（candidate ad1fa92f）
   - 两新红归因处置（baseline 登记 + worktree .venv 锚）→ R4 PASS（candidate 24fec997，覆盖 8 路径含 baseline json）
2. **scripts/ci_gate.sh 全链路（exit 0）**：
   - ruff ratchet：new=0，touched files 0 红
   - env-pin 声明门禁：PASS
   - pyright ratchet：new=0，touched files 0 红
   - [5/5] xdist 全量：**13847 passed, 158 skipped, 3 xfailed, 0 failed**（229.74s，junitxml 红数对账 0 新红）
   - 观察项（非阻断，如实登记）：[4/5] tier0 预检本次收集异常（"1 passed, 51 deselected"，与并发会话测试运行的收集竞争相关，audit 插件警告重复输出两遍为佐证）；tier0 为预检非提交门禁，全量（超集）真实全绿。手动复跑 tier0 = 341 passed/13682 deselected 正常。
3. **前端**：vitest 全套 57 文件 590 tests passed；`tsc --noEmit` 无错误。

## 新红归因（第二次 ci_gate 对账拦截，均已处置）

- `test_runtime_env_access_gate`：新端点 `escalation_detail` 直读 LFL_DATA_DIR → 官方工具 `--update-baseline` 登记（与同文件 7 端点同模式，registration_log 留审计线索）
- `test_env_preflight`：worktree 缺 `.venv` → 建相对软链（`.gitignore` 覆盖，不入版本库）

## 安全护栏实测（RULE-AI-35：宣称"生效"前实测应拦输入）

- 应拦：到期时间空串/垃圾串令牌消费 → 实测被拒+令牌作废（红测试先证缺陷、修复后转绿）
- 应拦：跨进程失效 pending 复用 → 实测新记录新 ID、wait 立即失败提示重申请
- 应拦：存储损坏/权限 → 实测 503（不再 200 空列表）
- 应拦：未查看完整命令的截断审批批准 → 前端按钮实测 disabled；指纹不一致不解锁

