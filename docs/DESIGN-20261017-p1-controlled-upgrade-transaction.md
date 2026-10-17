# P1 受控升级执行事务：需求、失败注入及 RED 契约 v0.1

**阶段：设计 + 真实 RED，尚未实现升级执行，不构成生产上线许可。**

**Stage A 实施记录（独立候选，未合并）：** `upgrade --plan --candidate WHEEL
--expected-sha256 SHA --json` 已补充离线只读 wheel 内容和包身份校验，以及
`--require-trust`、`--require-data-compatibility` 明确拒绝；无可信来源、schema
兼容、运行态停机证据时 `stage_eligible=false`。这只把原 8 项 RED 的前三项
相关只读目标转为 GREEN，**不是升级准备/执行闭环已完成**。
原实验分支保留了 8 项完整原始 RED（待继续做真正服务身份、冷备份覆盖、
事务 journal、升级 commit/abort）；当前 `--prepare/--commit/--abort` 仍不支持且
参数错误退出码 2，不会安装/替换软件或变更数据。

前置基线：本地 main `7e281014c` 已包含 `lfl upgrade --plan`（只读）、
`backup --plan/create/verify`（操作者冷停声明、`selected_roots`）、
`rollback --into NEW_DIR`（**只恢复新隔离目录**）。这些能力已完成独立审查与完整 R9，
但不具备包环境原子替换、真实服务停机确认或业务数据 schema 逆迁移能力。

## 1. 目标、刻意不做的事

- 目标：把“安装一个经过核实的候选 wheel”拆成**可验证、可中止、可回读、可恢复**
  的两阶段事务；所有证据绑定当前安装身份、受影响数据根、冻结包 SHA 和服务实例身份。
- 不做：模型推理策略、工具能力、默认权限削弱、服务重启快捷键、用户数据目录覆盖、
  未知版本 schema 自动迁移、自动在线下载安装、运行中数据热拷贝。
- 已有 `service_control` 只负责所管理服务的发布/启停/known-good；这不是 Python
  wheel 安装环境的版本控制，也不能代表所有非受管写入进程已停。
- 软件包 SHA-256 是**内容完整性**，不是可信发布者身份、签名、审查资格或合法来源证明。

## 2. 明确授权与事实源

1. 受控命令要求在 `lfl check-install` 确认现有安装身份可用；源码工作区运行模式只
   能预览，不进入执行。
2. 候选来源限定本地已下载的**规则路径下普通文件**；操作员必须提供预期 SHA-256、
   已受信渠道/签名或由人确认的来源证据 ID。无证据或来源不可验证一律停止。
3. 运行态通过已存在的服务控制工具只读获取 Web、Feishu、Learning 的实例身份、
   generation/进程和是否停止的**权威回执**；操作者单独设置
   `--confirm-services-stopped` 不足以证明所有写入者已退出。必须单独识别或明确
   排除外部 JSONL/SQLite 写入者。控制面 unavailable/unknown 时拒绝。
4. 新增机器可读受控 `preflight` 回执，应包含 candidate SHA、当前安装版本、目标
   版本与数据 schema 兼容状态、服务身份检查结果、快照完整性；**不输出凭证、
   配置绝对路径或用户文件字节**。读取前后权威状态再次验证，绑定不可被替换。
5. 已存在的 `selected_roots` 快照只证明所选根的 SHA 一致，不能自称 full 或实现
   数据 schema 降级兼容。未知 schema 必须阻断切换，不得把 backup verify PASS 当作
   schema compatibility PASS。

## 3. 建议接口（此刻均为 *未实现的 RED 契约*）

| 命令 | 性质/保障 |
|---|---|
| `lfl upgrade --plan --candidate WHEEL --expected-sha256 SHA --json` | Stage A 独立候选已实现只读 v2 内容及包身份检查，输出 `lfl.upgrade.preflight/v1`；不接触包管理、网络、Engine 或服务控制写入；**hash 校验成功仍不构成来源信任或可升级资格** |
| `lfl upgrade --prepare --candidate WHEEL --expected-sha256 SHA --snapshot DIR --trust-receipt FILE --json` | 仅验证来源、版本/数据兼容、服务真实停机、已完成冷快照；全部通过后才允许复制 wheel 至私有 staging 并创建**独立**新 venv，永不改 active pointer |
| `lfl upgrade --verify-stage --receipt FILE --json` | 只读检查暂存环境、已安装包内容 SHA、`check-install`、`doctor` 和相同 generation，拒绝丢失或人为修改的阶段回执 |
| `lfl upgrade --commit --receipt FILE --expected-generation GEN --confirm-cutover --json` | 需再取服务状态、清点外部写入者，另有明确 operator cutover 批准；独立持久 journal 的 CAS 切换，不得使用 `uv tool install --reinstall` 原地覆盖现有 venv |
| `lfl upgrade --abort --receipt FILE --json` | 仅允许丢弃尚未切换的**自己新建** staging；保留已完成备份与审计，不删除 live 数据；失败/崩溃后需可恢复检查 |

所有新命令应区分 `0=动作完成并有回执`、`1=已验证的安全阻断`、
`2=参数格式错误`。`--plan` 不能静默安装软件，`--prepare` 不能隐式切换服务。
逐项错误需 machine-readable `reason`，而非模糊 stdout 成功语句。

## 4. 事务与失败原子性

`S0 observed -> S1 candidate_verified -> S2 cold_snapshot_verified ->
S3 offline_venv_prepared -> S4 stage_verified -> S5 owner_authorized ->
S6 pointer_switch_pending -> S7 active_verified -> S8 settled`

- 各状态写入 `O_EXCL` / 私有权限 / `fsync(file+dir)` 的本地 journal，回执含唯一
  transaction_id、前后 SHA、source version、服务 generation 和核验工具版本；不持久
  生产凭证。所有未来调用按 tx 身份单调前进；重复 prepare 只能返回同一已验证阶段或
  明确冲突，不允许创造第二个活动事务。
- 如果候选 wheel digest/可信来源、已存冷快照、schema 兼容、运行态身份任何一项
  未知或变化，则仍停留在预切换阶段，不创建/改变 active wheel 指针。
- 在 pointer 切换前失败：旧安装、旧数据原样可用，stage 保持隔离且可以核查。
- 切换后健康检查失败：**只允许在确认旧代码仍兼容现存 schema 且服务真正停止的
  条件下撤回代码指针**；涉及数据更改时必须从已核验备份到新路径恢复并单独审批
  数据源切换，绝不直接回写覆盖生产 data。不能证明时转人工修复，不能说已自动回滚。
- 原子切换操作必须绑定同一设备、expected-current pointer 和服务 generation，
  拒绝 symlink 逃逸/路径穿越/目标覆盖、跨设备 rename、不明确状态与并发竞争。
- 禁止包管理器联网更新其他依赖，全部依赖由已验证的锁定哈希清单构成；受控升级
  实行与分发一致的纯 Git commit 派生产物与已审查 wheel 身份校验。

## 5. 先行 RED 测试与准入路径

Stage A 用 `tests/unit/test_application_upgrade_transaction_red.py` 冻结需求行为：

1. `--plan --candidate` 在虚构已验 wheel 时返回 v2 回执且零网络/安装副作用。
2. 候选 SHA 不匹配时返回 `candidate_hash_mismatch`，不建立 staging。
3. 缺失可信来源回执时返回 `candidate_trust_unknown`，不能仅凭 SHA 放行。
4. 未核验服务身份/未确认真实停机时返回 `service_identity_unverified`，
   即使有操作者同意也不得自动安装。
5. 冷备份 manifest 被篡改时返回 `snapshot_unverified`，不生成 stage。
6. 备份范围 `selected_roots` 或 schema 不相容/未知时拒绝自动数据回滚。
7. `--commit` 未持有事务回执和预期 generation 时不能切换 active 代码。
8. `--abort` 只能终止本事务的 staging，绝不删备份/live data。

RED 需记录每个 case 的真实错误/exit，测试文件暂保留在独立实验分支，
**不作为 main 或原版 R9 的已验收测试**。后续 Stage B 按最小实现顺序逐步 GREEN：
先机械只读 candidate 校验和受控错误 → 权威状态整合 → staged wheel 安装 →
事务 journal → 明确批准的 cutover；每一步独立 GLM-5.3 Rule28 PASS 才进入原版完整
R9，再做最新 main Stage C Rule34 资格审查，真实本地合并/推送/启停各需单独批准。

## 6. 未消除风险

- 当前服务控制权威是否能覆盖所有外部持久化写入者：**尚未证明**。
- 数据 schema 兼容/降级契约：**尚无完整版本化索引**。
- `uv tool install` 的本机装载机制不满足“版本指针原子 CAS”；因此只可 staged
  新虚拟环境，真实切换需另设计独立安全 adapter。
- 停电/fsync、跨文件数据一致性、签名供应链与真实生产 cutover 未验证；
  这些是独立资格问题，不会通过提高超时/放宽门禁自动解决。
