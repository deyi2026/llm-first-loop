# GOAL-20261016-cf563b27 批次一编码自报告：settlement 口径与幂等 7 项（P-SET-1..7）+ r1N1

- 基线：HEAD=f7c081282，工作树干净开工；规格=docs/tasks/P2-pool-knowledge-feedback.md 批次一节；
  语义权威=docs/LFL 任务知识使用反馈与检索闭环设计草案.md v3。
- 行号均按符号重新定位（回执时点行号已漂移，如 r1N1 的 674→现 722）。

## 开工纪律（方法论有界检索）记录
- data/methods（content=settlement / 幂等 / 去重，各 limit≤5）：命中若干；适用卡
  `verify-inherited-premise-then-fix-producer-dc7ec29f3a65`（先权威读取核验继承前提再修）——
  已应用于本任务：7 项全部以符号在当前源码重新定位并逐一核对原始回执 JSON 后才动手；
  其余命中（settlement 回执判读类）仅作背景，无直接适用修法。
- data/experiences：目录不存在 → 如实记录「无适用命中」。

## 每项【位置 / 修法一句话 / 测试名 / 验证结果】

### P-SET-1 聚合去重忽略 slot
- 位置：`settlement.py::RuleFeedbackProjection._aggregate`（deduped 键构造处）
- 修法：去重键由 `submission_hash` 单键改为 `(slot_id, submission_hash)` 元组——同内容跨
  slot（不同工作单元对同一规则）不折叠；同 slot 同 hash（传输层重试）仍收敛；无 hash
  的 legacy 行退化为 ts 键防误并。
- 测试：`test_settlement_receipts.py::test_rule_projection_counts_same_content_across_slots_separately`
- 验证：PASS（跨 slot 同内容 count=2；同 slot 重复事件不重复计数）

### P-SET-2 空 session 回执抵扣任意会话
- 位置：`settlement.py::_offsets` 降级分支 + `_ledger_receipts`/`_receipts_for_session`（新增窗口过滤）
- 修法：降级 session 窗口只接受「回执自身携带非空且等于本会话的 session_id」的回执；空
  session 的 legacy 行不参与抵扣，且被排除行数在清单 `window.legacy_receipts_without_session_excluded`
  显式披露（显式标注，不静默吞行）。确定任务窗口按工作单元匹配，不看 session（不变）。
- 测试：`test_settlement_receipts.py::test_degraded_window_ignores_empty_session_receipts_with_disclosure`
- 验证：PASS（空 session 行不抵扣且披露=1；同会话回执仍正常抵扣）

### P-SET-3 experience 回执收集 limit=200 截断
- 位置：`settlement.py::_ledger_receipts` + `experiences/store.py::usage_entries`
- 修法：store 的 `usage_entries` 增 `limit: int | None = 200`（None=无界读取，默认口径不变）；
  结算收集侧显式请求 `limit=None` 无界读取后按（工作单元｜会话）窗口过滤，与 method 侧
  无界口径对齐；假 store 兼容旧签名（TypeError 逐级回退 {"limit":None}→{}→("")）。
- 测试：`test_settlement_receipts.py::test_experience_receipt_window_survives_default_200_cap`
- 验证：PASS（251 行账本、默认读取面仍 200；最旧目标回执仍在匹配集内完成抵扣，读取不重现待结算）

### P-SET-4 统计视图与去重扫描 integrity 口径分叉（选「统计侧同样校验」）
- 位置：`methods/store.py::usage_entries`
- 修法：读取面加 `line_integrity_matches` 校验——integrity 失配行不进入统计/回执视图，
  与 `record_use` 去重扫描（`read_ledger_entries`）同一行集；legacy 无凭据行仍可读（口径不变）。
- 测试：`test_use_ledger_contract.py::test_usage_entries_share_integrity_view_with_dedup_scan`、
  `test_use_ledger_contract.py::test_usage_entries_legacy_rows_without_credential_stay_readable`
- 验证：PASS（中段篡改行两视图一致剔除；同内容重报不被篡改行吞掉；legacy 行可读）
- 备注（未扩权处理）：experience 侧 `_iter_usage_entries` 存在同类「读取面不校验 integrity」
  的结构性缺口，规格未列——如实上报给追踪池 owner，本批未动。

### P-SET-5 规则 ref 大小写不对称 + supersedes 静默忽略
- 位置：`settlement.py::_normalize_rule_ref`（新）/`_submit_one` rule 分支/`_submit_rule_item`/
  `RuleFeedbackProjection._aggregate` 摄取处
- 修法（归一处）：规格给「入投影前归一或提交时归一，选一处」；本实现取同一归一器
  `_normalize_rule_ref`（RULE-AI-N 模式统一大写）同时落在**提交侧**（slot/载荷/回执，保证跨
  大小写重提同 slot 幂等）与**投影摄取侧**（收敛已在盘上的 legacy 小写行）——理由：只选提交
  侧则存量小写事件仍漏读，只选投影侧则跨大小写 slot 不稳定；两处同源归一器保证两侧恒一致
  （归一幂等，非两套口径）。method/experience ref 不在归一范围（大小写敏感）。
  supersedes 对 kind=rule 由静默忽略改为**显式支持**：请求父必须是同 slot 链上既有
  submission_hash（与 ledger 侧 `resolve_submission` 父校验同口径），不满足回 failed 并给
  原因，不落事件；未显式请求时沿用程序推导链头。
- 测试：`test_rule_ref_case_normalized_at_submission_and_cross_case_idempotent`、
  `test_rule_projection_normalizes_legacy_lowercase_refs`、
  `test_rule_supersedes_explicit_parent_supported_and_rejected_with_reason`
- 验证：全 PASS（载荷/slot/回执归一；小写提交→大写重提幂等且仅 1 事件；legacy 小写行投影
  可读且抵扣大写读取 pending=0；显式 supersedes 采纳 revision=2、坏父 failed 带原因不落账）

### P-SET-6 降级模式成本计入全局账本
- 位置：`settlement.py::submit_settlement_batch`（成本回执收集处）
- 修法：无 wu 时成本回执按 `session_id` 过滤（与 `_offsets` 降级窗口口径对齐）；有 wu 时
  维持按工作单元过滤（叠加 P-SET-3 的窗口过滤后为显式二次过滤）。
- 测试：`test_settlement_receipts.py::test_degraded_settlement_costs_count_only_current_session_receipts`
  （B1 回执探针 A6 场景回归：全局账本 5 行噪音回执 + 本会话首笔提交）
- 验证：PASS（首笔 calls=1、rounds=0；同会话第二笔 calls=2——本会话回执仍计数）

### P-SET-7 规则条目幂等查重只扫当前会话（**选优先方案**：跨会话投影查重，未降级到改工具描述）
- 位置：`settlement.py::_scan_rule_feedback_rows`/`_rule_receipts`/`_submit_rule_item` +
  `SettlementChannel.event_logs_dir`（新装配件）+ `factory.py` 装配 + `registry_experience.py`
  两个工具入口传递
- 修法：确定任务 slot（wu 非空）的规则回执查重/抵扣经 `event_logs_dir` 投影扫描跨会话进行
  （复用 RuleFeedbackProjection 的文件布局遍历，按 work_unit_id 过滤；当前会话行去重不重复
  计入）；同 (slot, submission_hash) 跨会话重提返回幂等回执、不追加重复事件；确定任务窗口
  的待结算清单同样被跨会话规则回执抵扣（读取不再重现）。降级 slot 以会话为身份，维持会话内
  查重（跨会话本就是不同 slot）。扫描失败 fail-open 退回会话内口径；通道未携带目录（None）
  时同样退回——装配面经 factory 传 `settings.event_logs_dir`，工具面测试断言已覆盖。
- 测试：`test_rule_determined_slot_dedup_spans_sessions`、
  `test_pending_rule_receipt_offsets_across_sessions_for_determined_task`、
  `test_settlement_tools.py::test_submit_tool_rule_dedup_spans_sessions_via_channel_logs_dir`（工具面端到端）、
  断言强化 `test_settlement_tools.py::test_factory_assembles_settlement_channel_and_tools`
- 验证：全 PASS（跨会话重提 idempotent=True 且两会话合计仅 1 条 rule.feedback；跨会话抵扣
  生效且不抵扣其他工作单元窗口；工厂装配携带 event_logs_dir）

### 顺手 r1N1
- `test_settlement_receipts.py:722`（回执时点 674）：`experience_store.usage_entries(...)[-1]`
  → `[0]`（默认倒序最新在前，[-1] 实取最旧），附行内注释。
  所在测试 `test_experience_settlement_uses_episode_attribution_when_provided` PASS。

## 改动文件清单（sha256）
```
33dccfca8e2df45f128e56c41bf66c448a836f621c3d4c693e479198963ac94f  src/llm_loop/introspection/settlement.py
4e04776e89ac22ec6d4a9ad82bf226daf638e01dc3f267833a77f4962ae11cc9  src/llm_loop/methods/store.py
670f77f85d79cd42b1a993b3e7991fbc48a51468d215c0e9b115c478b0a3e474  src/llm_loop/experiences/store.py
be809fcb0d098dade33e519e3f4ecafda387beb59ce1603f2e37d500fc228d96  src/llm_loop/factory.py
bbb7d15ccf24f6f4b0c432b00b3b4cdc0d7ac3c93fd1ce462dd658dd2da4b5f6  src/llm_loop/introspection/registry_experience.py
e8e4366acd8689533c8a42b2199c9a4e60e540dd17baf829680a4dc9804d2264  tests/unit/test_settlement_receipts.py
8b488f50d037755ae465108ecd2c7bb7cc9189d1c90dbb093381aa1184b58f02  tests/unit/test_settlement_tools.py
159f2f4c7a2abf64cf3944b1a851f744f5b893a8e5a0b5c27ea8fc450856a9e7  tests/unit/test_use_ledger_contract.py
```

## 定向验证（真实执行，退出码）
1. 指定 5 文件 + 两侧 store 邻接回归（17 个测试文件，一条命令）：
   `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/{test_settlement_receipts,test_settlement_tools,test_use_ledger_contract,test_search_feedback_reflow,test_method_usage_watermark,test_usage_net,test_experience_library,test_experience_store_durability,test_experience_supersede_link,test_experience_lifecycle_contract,test_experience_learning_record_contract,test_experience_retrieval_contract,test_evo_618f7fd1_method_gate,test_injection_ledger,test_method_learning,test_factory,test_ai_rules_sync}.py -q`
   → **258 passed in 10.97s，退出码 0**。
2. 静态诊断（与 ci_gate 同口径，均真实执行）：
   - `PYTHONPATH=src .venv/bin/python scripts/check_static_diagnostics.py --tool ruff`
     → `R9 ruff: PASS (historical debt visible; no new errors; touched files clean)`，
     `new=0, changed_file_diagnostics=0`，**退出码 0**。
   - `PYTHONPATH=src .venv/bin/python scripts/check_static_diagnostics.py --tool pyright`
     → `R9 pyright: PASS (historical debt visible; no new errors; touched files clean)`，
     `new=0, changed_file_diagnostics=0`，**退出码 0（PYRIGHT_EXIT=0）**。

## 合规声明
- 全任务**无 git 写操作**（无 commit/stage/push；`git status --porcelain` 仅显示上述 8 个
  已修改文件 + 父代理未跟踪的规格文件，无本代理新增暂存）。
- **未跑** `scripts/ci_gate.sh`，**未跑**整仓 pytest（RULE-AI-28 全量门归父代理专属）。
- 全程**未用 uv run**（一律 `.venv/bin/python` 直调，未触碰 uv.lock）。
- 测试断言落在行为上（回执字段/事件计数/清单条目/两视图行集），非实现细节。
- 本报告为编码自报告；独立审查闸与全量门按规格验收行由父代理流程接续。
