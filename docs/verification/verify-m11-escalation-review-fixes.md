# 验证凭证：lane escalation-m11-review-fixes（M1.1 复审修复批 R1-R5）

- 日期：2026-11-06（宿主本地时区）
- worktree：`.worktrees/esc-m11` @ branch `escalation-m11-review-fixes`（base main=5e295e1e0）
- 复审报告：`docs/promotion/LFL_Sandbox_Escalation_Implementation_Review_2026-11-06.md`（R1 P1 + R2-R5 P2，§6 最小后续顺序 1-3 项）

## 修复范围（R → 提交 b646c5a7b）

| 问题 | 修复 | 主要验证 |
|---|---|---|
| R1 (P1) 跨进程写回污染原签名记录 | `_ForeignRecord` 只读视图：内存标记 `_sig_unverified`、写回按磁盘原样恢复（零派生字段、不代签）；历史污染记录剥离标记+MAC 受控验证迁移；不可验证记录保持 fail-closed 只读 | `test_r1_foreign_writeback_must_not_pollute_local_records` / `test_r1_reverse_alternation` / `test_r1_migration_recovers_historically_polluted_local_records` / `test_r1_migration_does_not_trust_foreign_records` / `test_r1_foreign_records_stay_fail_closed` / `test_r1_real_cross_process_smoke`（真实子进程） |
| R2 503 不可见+清空快照 | useEscalations 失败保留最后成功快照（未知≠空）；横幅标注"可能已过期"；空态仅确认态显示；Watcher 不可见态全局错误 chip（esc-watch-error） | 前端 R2 三用例（先成功后 503 保留快照 / 首屏 503 不显示无待审 / Watcher 错误 chip） |
| R3 失效历史死分支 | history 过滤改为 `status !== "pending" || _sig_unverified`，"已失效" badge 可达 | 前端 R3 用例（失效 pending 在历史区呈现"已失效"） |
| R4 无分页+计数=窗口长度 | store.list 增 `before_id` 稳定游标（routes 透传）；面板用权威 `pending_count`；"加载更多"单调读完；总数缩水弃续读页防已决残留 | `test_r4_list_before_id_stable_cursor` + 前端 R4 用例（60 条显示真实总数+游标续读+读完按钮消失） |
| R5 查看资格未绑指纹 | PendingCard 资格绑定 (request_id, command_sha256)：详情指纹非空且一致才解锁；缺指纹不解锁不展示原文（fail-closed 防钓鱼）；待审指纹变化重新锁定 | 前端 R5 两用例（缺指纹不解锁 / 指纹变化重新锁定） |

## 门禁记录

1. **红→绿冻结**：后端 5 红（R1×4+R4×1，均因缺陷本身失败）+前端 7 红（R2×3/R3×1/R4×1/R5×2）；2 个 fail-closed 锁定用例修复前即绿（他进程记录不可审批语义保持）。修复后全部转绿。
2. **独立审查（RULE-AI-28 full_test）**：PASS ×3（candidate a8f9d273 patch / e2ae48d7 patch / b9729bd6 tree scope=最终消费凭证）。
3. **scripts/ci_gate.sh 全链路 exit 0**：ruff ratchet new=0 touched clean；env-pin PASS；pyright ratchet new=0；xdist 全量 **13862 passed, 158 skipped, 3 xfailed, 0 failed**（231.29s，红数对账 0 新红；较 M1 基线 13847 +15 = 本批新增 7 后端 + 7 前端 + 环境对齐 1，对账吻合）。
4. **前端**：vitest 全套 57 文件 598 passed；`tsc --noEmit` 无错误。

## 环境对齐（非代码问题，如实登记）

- 首次 ci_gate 红：`test_env_preflight::test_preflight_exit_on_missing_dep_single_diagnostic` 断言预检消息含 `.venv` 实测版本号，worktree 无 `.venv` 时报"(.venv 不存在)"——与 M1 批同类环境问题（见 verify-m1 凭证"新红归因"），按同模式建相对软链（`.gitignore` 覆盖，不入版本库）后绿。

## 安全护栏实测（RULE-AI-35）

- 应拦（保持 fail-closed 不回退）：他进程 pending 幂等复用/计数/审批/消费 4 路实测拒绝；历史污染的他进程记录迁移后仍失效只读。
- 应拦（R5 新防线）：detail 缺指纹 → 批准保持禁用且原文不展示；指纹变化 → 已解锁按钮重新禁用（红→绿实测）。

## 已知残余（不在本批范围）

- 复审报告 §5 M2/M3 范围未实施（文件授权接入沙盒、执行绑定、消费与执行结果、审批权威与恢复、来源交互）——按报告 §6 第 4-5 项独立批次推进。
- RULE-AI-28 Host 闸观察到"PASS 后跨轮消费被拒"现象（重算 sha/target 与记录一致仍 deny）；规避方式为 PASS 后同轮消费或 scope=tree 新审查。已按规避模式完成门禁；根因建议另行排查（不在本 lane 范围）。
