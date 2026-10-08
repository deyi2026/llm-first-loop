# DESIGN: Durable Run Contract（P0-2，决策文档，无代码变更）

- 状态：设计决策（Option A 为主候选）；本轮零产品代码改动。
- 输入：AUDIT-20261007 §3.3（G2：7 个子系统中至少 8 个 durability surface 分散；10-07 单日 4 个 schedule durability 补丁）。
- 证据基线：main @ `4bd0b9356`（本文所有 file:line 均对此版本核验）。

## 1. 问题陈述 [事实]

"每个事故新增一套持久化"是复发模式。当前至少 7 个子系统、8 个持久化 surface 各自实现锁/原子性/恢复/幂等，语义不一致。Schedule 子系统必须拆成主状态与授权账本两个 surface 看待：

| # | 基座 | 位置 | 写入语义（核验） | 原子性 | 锁 | fsync | 崩溃恢复 | 幂等 |
|---|---|---|---|---|---|---|---|---|
| 1 | EventStore | `event_log/store.py` | 会话级稳定锁 `<sid>.lock`（flock）+ O_APPEND 单行；seq 续号；分段轮转 | 行级 append | ✅ | 未见 | 尾部截断行丢弃（读侧容错） | seq 单调 |
| 2 | Fleet 结算账本 | `fleet/store.py` | fcntl 跨进程锁；`_save`=tmp+`os.replace`（L142-145） | ✅ tmp+replace | ✅ | ❌ | 最后完整 JSON | lease 租约 CAS |
| 3a | **ScheduleStore 主状态** | `core/scheduler.py:178+` | flock + 锁内重读磁盘合并 + **`write_text` 覆写**；OSError → **fail-open 仅告警** | ❌ 非原子 | ✅ | ❌ | 磁盘损坏 → 以内存/空基底继续（fail-open） | ❌ |
| 3b | **WakeAuthorizationStore 私有授权账本** | `core/trace_leak/wake_authority.py:52+` | 0600 私有文件 + flock；`_write` 使用 unique tmp + file fsync + `os.replace` + directory fsync；HMAC scope/signature + consumed/revoked tombstone | ✅ | ✅ | ✅✅ | 完整 JSON + 签名校验；无效授权 fail-closed | scope/signature + one-shot state |
| 4 | ServiceControl CAS | `runtime/service_control.py` | generation 乐观并发（publish 时 CAS+git head+webui 产物 hash 绑定）；desired 部署态 to_dict/from_dict | 语义强（CAS） | CAS | 未核验 | 代际回退屏障 | expected_generation |
| 5 | Evidence blob | `memory/evidence.py` | `put_text`：tmp+fsync+`os.replace`+目录 fsync（L1367-1389） | ✅ 最强 | 写一次 | ✅✅（文件+目录） | 内容寻址天然完整 | sha256 键 |
| 6 | usage.jsonl | `methods/store.py:627` | 裸 `open("a")` 追加单行 | 行级 append | ❌ | ❌ | 读侧跳过坏行 | 无键 |
| 7 | ExperienceStore | `experiences/store.py`（save/update_status，2026-10-08 T2 迁移后） | 单记录 markdown：store flock 内 tmp(O_EXCL)→file fsync→link(create-if-absent)/replace→目录 fsync，typed 结果分型 | ✅ T2（2026-10-08） | save=创建一次；update=单写者 RMW | ✅✅（文件+目录） | 锁失败 fail-closed；损坏旧记录 fail-open 跳过 | 文件名=experience:<id>；同日同 slug 冲突不覆盖 |

## 2. 目标 / 非目标

- 目标：给"运行态落盘"定义一套**统一语义契约**（接口 + 三档 tier），使新基座不再各自发明；存量按矩阵迁移或显式豁免。
- 非目标（本轮）：不写产品代码；不实施任何迁移；不改存储格式/schema；不做事件溯源改造；不统一为单数据库。

## 3. 候选方案

- **Option A（主候选）统一持久化语义接口**：定义 `DurableContract`（分层 tier + 显式恢复钩子 + 幂等键），存量实现逐个适配，不强制共享后端。
  - 优点：不动数据格式，迁移可按 surface 独立推进；evidence blob（#5）与 WakeAuthorizationStore（#3b）已经提供两类事实参考实现；与 P1-4 kernel 契约方向一致。
  - 缺点：契约若无人强制会退化为纸面（→ 需 P0-3 式机械 guard 配套：新持久化基座必须声明 tier）。
- Option B（否决）事件溯源统一后端：所有基座改写为 EventStore 事件流。
  - 否决理由：改写面=全部 7 套 + schema，风险与当前"冻结扩张"方针冲突；schedule 账本的 HMAC 签名投影语义在纯 append 流上需重建。
- Option C（否决）只写规范不改接口：纯文档约定。
  - 否决理由：10-07 的 4 连补丁证明"约定"不足以阻止第 8 套基座出现。

## 4. Option A 接口草案（设计，不实施）

```
Tier（三档，语义而非实现）:
  T1 append_log   —— O_APPEND 单行 + 读侧截断容错；适用于事件/用量（#1、#6、archive）
  T2 state_file   —— 锁/CAS + tmp+fsync+os.replace（+目录 fsync）；适用于状态覆写（#2、#3、#4、#7）
  T3 blob         —— 内容寻址、写一次、不可变（#5）

DurableContract(Protocol):
  tier: Tier
  def acquire(self, key) -> WriteLease        # 单写者准入（flock/CAS/写一次）
  def commit(self, lease, payload) -> Receipt # 按 tier 原子落盘；Receipt 含新版本指针
  def recover(self) -> RecoveryReport         # 启动时自检：完整/截断/孤儿/fail-open 计数
  def idempotency(self, payload) -> Key|None  # 重复 commit 的判定键（如 sha256、sid、generation）
```

契约红线（机械可查，供 P0-3/P1-4 guard 落地）：
1. T2 覆写禁止裸 `write_text`（必须 tmp+replace）；**禁止 fail-open 吞写失败**（#3 现状即违例）。
2. 每个基座必须能回答 `recover()`；无法回答的必须豁免登记+理由。
3. 跨进程写必须持锁或 CAS（#6、#7 现状违例，按风险排序豁免或修复）。

## 5. 符合性 / 迁移 / 豁免矩阵（结论）

| # | 基座 | 结论 | 理由 | 动作 |
|---|---|---|---|---|
| 5 | evidence blob | **符合（T3 参考）** | tmp+fsync+replace+目录 fsync+内容寻址，全仓最强 | 作为接口参考实现，零改动 |
| 1 | EventStore | **符合（T1）** | 锁+O_APPEND+读侧容错+seq | 零改动；可选：fsync 策略显式化 |
| 2 | Fleet 结算 | **符合（T2）** | 锁+tmp+replace | 补目录 fsync 即全绿；低优先 |
| 4 | ServiceControl | **符合（T2，2026-10-08 迁移）** | CAS+state lease；`_atomic_json` 已迁 tmp+file fsync+replace+目录 fsync+outcome 分型 | 已实施；见 §6 rev6 |
| 6 | usage.jsonl | **豁免（低风险 T1）** | 单行小 append，进程模型下交错窗口小；读侧跳坏行 | 显式豁免登记；不加锁 |
| 7 | ExperienceStore | **符合（T2，2026-10-08 迁移）** | ~~裸 write_text 覆写，崩溃可致整卡损坏~~ → save=store flock+tmp+fsync+link 原子 create-if-absent；update_status=单写者 RMW+replace；两者均区分 definitely_not_committed / commit_outcome_uncertain + exact readback（`test_experience_store_durability.py` 12 例故障注入） | 已完成（含调用面 receipt 分型：`tools_experience.py` 禁止 uncertain 盲重放） |
| 3a | **ScheduleStore 主状态** | **符合（T2，首个 client）** | 原子可见性+目录 durability fence+跨进程锁+显式 commit outcome/reconcile | 见 §6 |
| 3b | WakeAuthorizationStore | **符合（T2 参考）** | 锁+tmp+file fsync+replace+目录 fsync；HMAC scope 与 one-shot tombstone | 零改动；作为 schedule 迁移的同子系统参考 |

## 6. 首个迁移 client：ScheduleStore 主状态（已实施）

- 理由：a) 风险最高（fail-open + 非原子）；b) 事故密度最高（10-07 四补丁：`06e6a587c`/`ee75b861d`/`a829e254a`/`54fc378c4`）；c) 改动面最小（仅 `ScheduleStore._persist`/`_mutate` 的主状态落盘语义需要迁移）；d) 同子系统的 `WakeAuthorizationStore._write` 已有 tmp+fsync+replace+directory-fsync，可作为实现参考，**不得重复改造授权账本**。
- 迁移验收（未来实施时）：i) 覆写经 tmp+`os.replace`+目录 fsync；ii) OSError 不再 fail-open（重试+显式降级事件）；iii) `recover()` 能报告截断/损坏条目数；iv) 现有 schedule 回归全绿。
- 迁移顺序建议：#3a → #7 → #2（补 fsync）→ #4（核验归档）；#3b 不迁移。

### 实施记录（2026-10-08 rev5：#3a + commit outcome 已闭合）

- 写路径分相：`_persist`/`_mutate` 统一走 `_commit_state`。**replace 前** = tmp(O_CREAT|O_EXCL)→write→flush→file fsync→`os.replace`，可有界重做完整 payload；**replace 后**只重试 directory fsync，绝不再次 rewrite/rename 同一 semantic mutation。
- 单写者：POSIX `flock` 锁文件打开/加锁 OSError 不再 fail-open 成无锁写，改为 `SchedulePersistError` fail-closed；无 `fcntl` 的非 POSIX 兼容路径仍保留进程内 RLock fallback，并明确不声称跨进程 T2 保证。
- 读侧边界：`recover()` 能识别非法条目后，`_load/refresh/_persist/_mutate` 同步把非 dict 导致的 `AttributeError` 纳入既有 fail-open 分类；顺序敏感回归证明“非法元素在第一条”不再崩初始化。
- **两类机械 outcome**：
  - replace 前耗尽/锁失败/目录不可用 → `SchedulePersistError`, `outcome=definitely_not_committed`；`_mutate` 回滚到 mutation 前内存快照，调用点再声明该操作自己的 `retry_safe`。
  - replace 已成功、directory fsync 耗尽 → `ScheduleCommitUncertainError`, `outcome=commit_outcome_uncertain`；在仍持 store flock 时逐字 readback intended payload，附 `expected_sha256 + visible_state(matches|mismatch|unreadable)`。禁止把异常解释成“肯定没写”后盲重放。
- **reconcile policy（按 mutation，而不是按异常文本猜）**：

| mutation | definitely-not-committed | uncertain + exact `matches` | 对外语义 |
|---|---|---|---|
| `add` | 内存回滚；wake 先行 authority/grant 补偿撤销；新注册可重试 | 不撤 authority；向调用方返回 sid + uncertain | user/model 必须先按 sid 核当前排程，禁止直接重复 add |
| `cancel` | 同 sid 重试安全 | 仍向调用方报告 uncertain | cancel 是同 sid 幂等，可 reconcile/retry |
| `claim_due` | 下 tick 可重试 | 接受可见 lease，不再 claim 第二次 | 纯内部生命周期 |
| `retry_later` / `defer_wake_retry` / `note_wake_waiting` | 同 sid 重试安全 | 接受可见状态 | 纯内部生命周期 |
| `mark_triggered` | ack 可重试；普通 notify effect 本身按 occurrence 幂等 | 接受可见 ack | 不因 durability uncertain 再做第二个 semantic mutation |
| `note_wake_started` | **不可**当普通可重试：authority consume 可能已落 tombstone | 接受可见 started；authority `started` 保持 at-most-once | provider work 仍受 durable authority tombstone 约束 |
| `recover_wake_grant` / re-arm | 同 sid 可重试 | 接受可见 adopt | 不新造 human authority |

- **普通提醒 effect identity**：interop notify 使用 `schedule:<sid>:<count>` 与稳定文件名 `notify-<sid>-occ-<count>.json`。同 occurrence 的 ack 失败重试复用同一 effect；Interop done 已有同名且同 id 时只消费 pending，不再制造第二份用户可见通知。repeat 合法下一次因 `count` 增长获得新 identity。
- **调用 surface**：`schedule` / `schedule_cancel` ToolResult 与 Web cancel API 都结构化暴露 `outcome/sid/visible_state/durability_confirmed/retry_safe`；程序只给机械事实，不替模型判断任务层是否要重新安排。
- 边界钉子（实施中发现）：旧 `_mutate` 的宽 `except OSError` 顺带吞掉 `preserve_fields` 内的授权账本写失败——这是 wake 投递 `WAKE_DEFERRED` 降级语义的既有依赖（授权持久化失败必须阻止模型工作）。迁移后语义拆分：主状态写失败=显式抛出；授权投影失败=跳过本次提交（不写半套状态）+ warning，不抛。由 `test_schedule_durability.py::test_authority_projection_failure_skips_commit_without_raising` 与既有 `test_failed_authority_persistence_prevents_model_work` 双向钉住。
- `recover()`（§7.1 决策：仅启动时调用，`_load` 记录报告）：exists/readable/corrupt/entries/invalid_entries/orphan_tmp；损坏基底处理策略不变（读侧 fail-open），但不再静默。
- 验收：`tests/unit/test_schedule_durability.py` 保留六点写入故障注入，并新增 outcome 分型、pre-replace 内存回滚、post-replace no-rewrite、add/cancel surface、wake authority compensation/retention、claim/ack/started reconcile；scheduler/interop 测试覆盖 notification occurrence identity 与 durable done dedupe。最终 candidate full `not real_llm` = **7662 passed / 107 skipped / 16 deselected / 3 failed / 5 errors**；3 fail 均为 MCP sandbox `HOME=/var/.../home` 导致的既有 safety 环境红项，5 errors 均为缺 Playwright Chromium executable。为避免历史口径豁免，另在 detached pre-change `4704e3a20` 上只复跑这 8 项，精确复现 **3 failed / 5 errors**，故无本轮新增 full-suite regression。
- registry：`schedule_store` 保持 `T2/conform`，但 rationale 升级为 outcome/reconcile 级保证。WakeAuthorizationStore（#3b）本轮仍零改动；为闭合普通 notify 重投幂等，仅调整 scheduler notify effect identity 与 Interop done 同-id 归档去重。

### 实施记录（2026-10-08 rev6：#4 service_control_state partial → conform）

- 顺序调整授权：§6 原建议顺序为 #3a → #7 → #2 → #4；2026-10-08 发布链 dual-root sidecar 事故（gen196/gen197 双次实证根因）闭环验证（gen198 restart 三服务 succeeded、收敛 `51f7f4755`、preflight 无人工补文件 PASS）后，GPT 接力 08:18 顺序将 #4 提前实施，#7/#2 顺延。
- 写路径迁移：`runtime/service_control.py::_atomic_json`（desired-state `managed_service_deployment.json` 与 `service-control-actions/*.json` 共用落盘点）改为与 `_commit_state` 相同的两阶段语义——replace 前 tmp(O_CREAT|O_EXCL)→write→flush→file fsync→`os.replace`，可有界重试（3 次）整 payload 并清理 tmp；replace 后只重试 directory fsync，绝不重写/重命名同一 semantic mutation。
- outcome 分型：replace 前/目录不可用 → `ServiceControlPersistError`（`definitely_not_committed`）；replace 后目录 fsync 耗尽 → `ServiceControlCommitUncertainError`（`commit_outcome_uncertain`，含 `expected_sha256` + 持 state lease 逐字 readback 的 `visible_state`）。单写者沿用既有 state lease flock fail-closed；readback 因两个调用点均持 lease 而成立。
- CAS 协同：uncertain 后磁盘已推进到新代，按旧 `expected_generation` 盲重放被 `DeploymentGenerationConflictError` 机械拒绝（reconcile 由 CAS 承担，无需新增调用面）。
- 验收：新增 `tests/unit/test_service_control_durability.py` 7 项故障注入（正常无 tmp 残留/replace 前分型+旧态保留+重试计数/目录 fsync 耗尽 uncertain+no-rewrite+sha 校验/预算内瞬时恢复/readback unreadable/CAS 集成两态）全绿；service_control 相关既有回归 250 passed / 0 failed。
- registry：`service_control_state` `T2/partial` → `T2/conform`，rationale 记录写路径、outcome 分型、单写者与验收口径。

### 实施记录（2026-10-08 rev7：action/barrier uncertain reconcile）

- rev6 后续核验发现：desired deployment 的 uncertain 已可由 generation CAS 机械 reconcile，但 action transition 仍有后置副作用顺序。原顺序为
  `_write_action_unlocked(updated)` → barrier release/establish → terminal event；若 action 文件已 replace 成新状态、仅 directory fsync 耗尽，
  `ServiceControlCommitUncertainError(visible_state=matches)` 会在后置副作用前抛出，造成“action 已 succeeded、barrier 仍残留”等控制面裂缝。
- 修正：`_write_action_unlocked` 在持 state lease 下捕获 **post-replace uncertain + visible_state=matches**，随后重新读取同一 action；
  仅当反序列化后的完整 `ServiceControlAction` 与 intended action 完全相等时，才把本次写视为“可见态已机械 reconcile”，继续既定后置 transition effects；
  不重写 action、不重放 semantic mutation。若 `visible_state` 为 mismatch/unreadable，或 exact action readback 不相等，则保持 fail-closed 并继续抛出 uncertain。
- transition 语义不变：`accepted` uncertain+matches 后继续建立 admission barrier；`accepted/waiting → failed` 与 `→ succeeded` 按既有策略释放 barrier；
  `running → failed` 仍因可能已有物理副作用而保留 barrier。terminal event 仍只在 transition 后置阶段发一次。
- 故障注入：`tests/unit/test_service_control_durability.py` 从 7 项扩为 **12 项**，新增 accepted/succeeded/failed 三类 action 生命周期验证、
  running→failed fail-closed barrier 保留、terminal event 单次、accepted uncertain no-rewrite 与 non-matches 不建立 barrier。
  最终相邻回归：service_control 关联测试 **305 passed**、arch guards **21 passed**；Ruff 相对 pre-change HEAD 零新增（候选与 HEAD 均只剩同 4 个既有 SIM105）。
- full `not real_llm` 候选：**7686 passed / 107 skipped / 16 deselected / 3 failed / 5 errors**。3 fail 为 MCP sandbox
  `HOME=/var/.../home` 下既有 safety 环境红项，5 errors 为缺 Playwright Chromium executable。为避免口头豁免，另在 detached pre-change
  `97d1eff43` 上只复跑这 8 项，精确复现 **3 failed / 5 errors**；故本 rev7 无新增 full-suite regression。
- 测试隔离修正：rev7 full 首跑额外暴露两条 durability 计数失败，根因为测试全局 monkeypatch `os.replace` 截获后台 Scheduler 写入；
  fault injection 已改为仅匹配本测试目标 path。与 ScheduleStore 既有测试隔离纪律一致，混跑
  `test_service_control_durability.py + test_schedule_durability.py` = **34 passed**。

### 实施记录（2026-10-08 rev8：#7 ExperienceStore migrate → conform）

- 写路径迁移（`experiences/store.py`）：`save()` 由裸 `write_text` 改为 store flock 内
  tmp(O_EXCL)→write→file fsync→`os.link` 原子 create-if-absent→目录 fsync；`update_status()`
  由裸 read-modify-write 覆写改为 store flock 内单写者 RMW + tmp→fsync→`os.replace`→目录 fsync。
  最终文件只可能整体旧或整体新，崩溃位不再产生截断半卡。
- 新增跨进程单写者锁 `_file_lock`（flock LOCK_EX，锁失败 fail-closed；无 fcntl 运行时退化进程内
  RLock 并显式不声称跨进程）。覆盖此前两处 TOCTOU/丢更新窗口：save 的 exists 检查（并发同日同
  slug 现在必然一方 FileExistsError，不再静默覆盖）与 update_status 的丢失更新。
- outcome 分型：replace/link 前失败 → `ExperiencePersistError`（确定未提交，同一 payload 重试安全）；
  link/replace 已生效但目录 fsync 有界重试（3 次）耗尽 → `ExperienceCommitUncertainError`
  （含 `expected_sha256` + 持锁逐字 readback 的 `visible_state`，禁止盲重放）。post_save_hooks
  仅在确定提交后运行；uncertain 不触发 hooks。
- 调用面（`introspection/tools_experience.py`）：save/refine receipt 对两类 typed 异常分别给出
  reconcile 指令——save uncertain 后"同日同 slug 已占用，重存必然冲突，先按 expected_sha256 核对"；
  refine uncertain 后"先 get() 按实际 status 决定，同目标幂等，禁止叠加第二份语义动作"。
- 故障注入验收：新增 `tests/unit/test_experience_store_durability.py` **12 例**全绿（happy path 无
  tmp 残留 / replace 前分型+原样保留 / 冲突契约不覆盖 / save uncertain=matches+sha 校验+重存必然
  冲突 / update uncertain=整体新完整卡+重试计数 / replace 失败原样 / 双实例 8 线程并发 save 单赢家
  / 并发 update_status 串行不撕裂 / 损坏旧记录 fail-open 原样 / 孤儿 tmp 与 lock 文件不入扫描 /
  uncertain 后 get() 可逐字取回+故障恢复后续写）。相邻面 experience+introspection **200 passed**；
  arch guards **21 passed**。
- registry：`experience_store` `T2/migrate` → `T2/conform`（rationale 记录写路径、分型与验收口径）。

## 7. 开放决策点

1. `recover()` 的调用时机：仅启动时 vs 每次 acquire 前（成本/收益待定）。
2. fail-open 全局禁令是否有例外（如"宁可丢一条提醒也不能阻塞主循环"的 schedule 场景——若是，降级事件必须落 EventStore）。
3. 契约归档位置：并入 P1-4 kernel 边界契约，或独立 ARCHITECTURE 章节。

## 8. 与其他任务的关系

- P0-3 的 guard 扩展已落为 filesystem-write candidate registry：生产源码中新增明确写入原语的文件必须声明 tier（T1/T2/T3）+ status（conform/migrate/partial/observe），或给出 non-durable exemption；登记不等于合规证明。
- P1-4 kernel 契约：`event_log` 在 kernel 集合内，T1 语义即 kernel 级契约的一部分。

## 9. rev 3 currentness 修正（2026-10-07）

- 初版把 ScheduleStore 主状态与 WakeAuthorizationStore 私有授权账本合写成一行，造成“私有账本非原子”的错误印象。
- HEAD 核验：`scheduler.py` 主状态仍为裸 `write_text`；`wake_authority.py::_write` 已明确执行 tmp → file fsync → `os.replace` → directory fsync。
- 因此迁移对象严格限定为 **ScheduleStore 主状态文件**；WakeAuthorizationStore 归档为 T2 参考 surface。
- 新数量口径：**7 个子系统，至少 8 个持久化 surface**。后续新增 surface 必须声明 T1/T2/T3 或显式豁免，不能只按“子系统数”统计。

## 10. registry guard 补充（2026-10-07）

- “至少 8 个”是 rev3 已逐项核验的高价值 durability 子集，不再冒充全仓完整数量。
- 机械 guard 对 `src/llm_loop` 做 AST 扫描，捕获 `Path.write_text/write_bytes`、literal write-mode `open`、以及带写 flags 的 `os.open`；当前所有命中文件必须进入 `durability_registry.surfaces` 或 `write_exemptions`。
- registry 的 `observe` 只表示“已发现并分类”，不表示已满足对应 tier；只有有专项证据的条目才标 `conform/migrate/partial`。
- 新写入面不是永久禁止，但必须通过 `guard(r9):` 可见提交显式登记，避免在既有包内部悄悄新增第 N+1 套持久化。
