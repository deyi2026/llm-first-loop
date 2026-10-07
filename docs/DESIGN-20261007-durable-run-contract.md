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
| 7 | ExperienceStore | `experiences/store.py:155,603` | 单记录 markdown 文件 `write_text` 覆写 | ❌ | ❌ | ❌ | 无 | 文件名=experience:<id> |

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
| 4 | ServiceControl | **部分符合** | CAS 语义强；desired 落盘原子性未核验 | 核验后归档；不改语义 |
| 6 | usage.jsonl | **豁免（低风险 T1）** | 单行小 append，进程模型下交错窗口小；读侧跳坏行 | 显式豁免登记；不加锁 |
| 7 | ExperienceStore | **迁移（T2，第 2 顺位）** | 裸 write_text 覆写，崩溃可致整卡损坏 | 换 tmp+replace；改动极小 |
| 3a | **ScheduleStore 主状态** | **迁移（T2，首个 client）** | 非原子覆写+fail-open 丢写+当日 4 补丁集中爆发 | 见 §6 |
| 3b | WakeAuthorizationStore | **符合（T2 参考）** | 锁+tmp+file fsync+replace+目录 fsync；HMAC scope 与 one-shot tombstone | 零改动；作为 schedule 迁移的同子系统参考 |

## 6. 首个迁移 client：ScheduleStore 主状态（本轮不实施）

- 理由：a) 风险最高（fail-open + 非原子）；b) 事故密度最高（10-07 四补丁：`06e6a587c`/`ee75b861d`/`a829e254a`/`54fc378c4`）；c) 改动面最小（仅 `ScheduleStore._persist`/`_mutate` 的主状态落盘语义需要迁移）；d) 同子系统的 `WakeAuthorizationStore._write` 已有 tmp+fsync+replace+directory-fsync，可作为实现参考，**不得重复改造授权账本**。
- 迁移验收（未来实施时）：i) 覆写经 tmp+`os.replace`+目录 fsync；ii) OSError 不再 fail-open（重试+显式降级事件）；iii) `recover()` 能报告截断/损坏条目数；iv) 现有 schedule 回归全绿。
- 迁移顺序建议：#3a → #7 → #2（补 fsync）→ #4（核验归档）；#3b 不迁移。

## 7. 开放决策点

1. `recover()` 的调用时机：仅启动时 vs 每次 acquire 前（成本/收益待定）。
2. fail-open 全局禁令是否有例外（如"宁可丢一条提醒也不能阻塞主循环"的 schedule 场景——若是，降级事件必须落 EventStore）。
3. 契约归档位置：并入 P1-4 kernel 边界契约，或独立 ARCHITECTURE 章节。

## 8. 与其他任务的关系

- P0-3 的 guard 扩展应把"新持久化基座必须声明 tier"纳入登记项（本文 §4 红线 3）。
- P1-4 kernel 契约：`event_log` 在 kernel 集合内，T1 语义即 kernel 级契约的一部分。

## 9. rev 3 currentness 修正（2026-10-07）

- 初版把 ScheduleStore 主状态与 WakeAuthorizationStore 私有授权账本合写成一行，造成“私有账本非原子”的错误印象。
- HEAD 核验：`scheduler.py` 主状态仍为裸 `write_text`；`wake_authority.py::_write` 已明确执行 tmp → file fsync → `os.replace` → directory fsync。
- 因此迁移对象严格限定为 **ScheduleStore 主状态文件**；WakeAuthorizationStore 归档为 T2 参考 surface。
- 新数量口径：**7 个子系统，至少 8 个持久化 surface**。后续新增 surface 必须声明 T1/T2/T3 或显式豁免，不能只按“子系统数”统计。
