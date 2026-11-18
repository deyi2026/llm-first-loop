# LFL Task Capability & Host Execution v1.0 — 需求与实现设计方案书

> 日期：2026-11-19
> 状态：**v1.0 实施基线冻结（2026-11-19）**；代码仍需独立 Reviewer 与完整验收，不是“已开发/已部署”证明
> 代码基线：`origin/main = 98d0bb2a6e14655afe341f0c29189a4abb83908f`（创建隔离 worktree 时的事实）
> 生产观察：`desired_generation=433`、`deployed_sha=98d0bb2...`、`in_sync=true`（只读 board 快照，必须在部署前重新核验）
> 主要责任：ChatGPT 主开发/集成/验收；LFL Goal、Lane、受管执行与任务续接；独立 Reviewer 审核精确候选
> 模型：LFL 执行默认 `glm/glm-5.3-flash`；独立 Reviewer 不写死模型，可用 `deepseek/deepseek-v4-flash` 等经准入的模型
> 适用：Mac、Deepin/Linux；Web/Feishu/Learning/WeCom 的既有受管服务流程
> 关联：`docs/DEVELOPMENT_REPAIR_SAFETY.md`、`docs/EXECUTION-ISOLATION.md`、`docs/design/DESIGN-20261114-deepin-host-grant-closure.md`、`docs/DESIGN-20261107-linux-managed-upgrade-restart-sandbox-authorization.md`

## 0. 执行摘要与冻结裁决

LFL 当前的主要问题不是 Git 本身，而是 **任务授权、实际 OS 权限、工具执行通道、跨项目资源边界与人机交互没有统一闭环**。已有工具分别解决了局部问题，但组合后常出现：用户已批准而执行仍失败；正常跨项目编辑被沙箱拦截；IDE/桌面操作受限；同一任务不断重复申请权限；多 Agent 的文件归属与恢复回执难以贯通。

**目标**：在不关闭沙箱、不引入万能 root shell、不让网页/模型自我提权的前提下，让用户授权的正常任务在真实 Mac/Deepin 上连续完成，包括跨项目文件、构建、Git、浏览器、桌面和 LFL 自身维护。权限不足时返回具体可执行的授权或环境修复路径，不能假称成功。

**唯一架构方向：任务级 Capability Lease + 轻量 Resolver + 复用现有受管执行适配器。** 先完成一个跨项目真实开发闭环，再扩展桌面/系统能力。程序负责授权、隔离、版本、锁、效果与审计；模型负责规划、语义判断、工具选择与验收建议。

明确不做：
- 不设 `EXEC_SANDBOX=none` 全局默认，不开放整个 `HOME`、`/tmp`、`.git` 或系统根目录的泛写权限。
- 不实现任意命令的“审批后直接在宿主 root 执行”。
- 不以模型文本、网页内容、仓库 README 或子 Agent 自报身份铸造授权。
- 不重复开发完整文件管理、GitHub CI、浏览器 CDP、桌面 AX、systemd 或服务发布系统。
- 不为了测试通过放宽既有安全门禁或伪造 Reviewer/CI/部署回执。
- 不触碰其他活跃 Lane 的代码、数据、审计、服务，未经归属协调不得抢占文件。

## 1. 现状与证据

### 1.1 当前已存在的能力

| 组件 | 源码/事实入口 | 当前边界 |
|---|---|---|
| 沙箱后端 | `src/llm_loop/tools/sandbox.py` | macOS `sandbox-exec` 主要控制写；Linux `bwrap`；Docker 有单文件 grant 适配缺口 |
| 命令工具 | `tools/builtin/execute_command.py` | 工作目录可写、命令扫描、write-scope、Host Grant、受管 Review Admission |
| 文件工具 | `tools/builtin/{read_file,edit_file,...}.py`、`tools/file_service.py` | 相对路径跟随 workspace；与命令沙箱物理边界并非完全一致 |
| Host Grant | `tools/builtin/host_access.py`、`tools/escalation.py` | 既存单文件 read/write、精确命令/路径/会话、最多 600 秒、一次性消费 |
| 审批 UI | `webui/src/components/sidebar/EscalationCenter.tsx` | 已有登录提示；批准状态尚不能代表执行能力实际就绪 |
| 子 Agent 权限 | `core/write_scope.py`、`workspace/worktree_isolation.py` | 父子 write-scope 求交；隔离 worktree，脏树保留；未形成任务级多根资源授权 |
| 桌面 | `tools/builtin/desktop_operate.py`、`desktop/*` | macOS only；真实写默认 OFF；终端/IDE 只读；HID idle 60 秒用户在场拒绝 |
| 浏览器 | `browser_operate` / `browser_perceive` | DOM/CDP 受管操作；网页发布、支付等独立审批，不得用 GUI 绕过 |
| 服务 | `service_control` | desired generation/CAS、restart/publish/health；不可被任意 shell 代替 |
| 副作用恢复 | `core/tool_execution_journal.py`、`core/loop/side_effects.py` | 有 WAL、效果围栏与 outcome unknown；需要复用，不能另造独立状态真值 |

### 1.2 已完成的真实诊断

- 临时 `sandbox-exec` 双项目探针：只放行项目 A 写时，读取项目 B 成功、写入项目 B 返回非零、原内容未变。说明**现行 macOS 写隔离不等于读/网络隔离**。
- Git linked worktree 的 `.git` 可为指向仓库外 gitdir 的文件，单纯放开工作树不足以让 `git add` 创建 index.lock；应授权受管 Git 元数据操作，而不是给所有模型命令整个仓库元数据写权限。
- Host Grant 签名密钥当前为进程内随机 HMAC，重启后旧 grant 不再有效；这是已有安全设计事实，不应将其称为可跨重启的任务授权。
- 已连接 MCP Console 的原生 Computer Use 能力与 LFL `desktop_operate` 不同；前者有后台窗口操作能力不等于 LFL 运行时已集成。
- 当前只读协调看板有多条在途 Lane；本方案新建独立文件/分支，不抢已有 Lane 的写入权。部署前重新取看板、main、live SHA。

### 1.3 需要解决的根因

1. **审批与执行分离**：用户批准应用层请求后，内核沙箱/TCC/Polkit/服务锁仍可能拒绝。
2. **能力粒度错误**：把“任务访问两个项目”压缩成“单命令访问一个文件”。
3. **后端语义不等价**：macOS Seatbelt、Linux bwrap、Docker、GUI、CDP、服务控制不能只靠一个布尔 `allowed`。
4. **人机并行冲突**：全局 HID 活跃即拒绝，不支持优先后台窗口级协作。
5. **授权续接缺口**：任务运行长于 600 秒或重启时，批准、实际权限和副作用结果容易失联。
6. **工具边界不一致**：独立文件工具与 Shell 沙箱、浏览器上传路径、子 Agent 继承规则不完全共用权威能力事实。

## 2. 用户故事、目标与非目标

### 2.1 用户故事

- US-01：我授权 LFL 维护项目 A、B；Agent 可以连续查看、编辑、测试和普通提交，不必每个文件再问。
- US-02：我使用电脑时，Agent 在独立窗口后台完成已授权的文稿、IDE 和浏览器任务，不抢焦点。
- US-03：我批准 LFL 重启自身服务，Agent 能通过受管服务入口完成、恢复并核验 PID/版本/健康。
- US-04：一个 Goal 下多 Agent 并行修改不同文件，锁/CAS 防丢更新；授权不能越过父任务。
- US-05：遇到 EPERM，Agent 能告诉我到底是 write-scope、Seatbelt、bwrap、TCC、Polkit、OS ACL、登录还是审批问题，并提出有效下一步。
- US-06：我随时撤销授权，新的副作用停止；已开始且结果不明的动作可查询、核验、处置，不自动重放。
- US-07：LFL 能处理创建目录、重命名、构建缓存、项目间引用与 Git linked worktree，不因正常操作模式不同而卡死。

### 2.2 范围边界

**纳入 v1**：任务授权、能力预检、已授权多根项目文件/构建、Git 受管适配、桌面后台操作的授权衔接、浏览器和服务既有能力复用、跨进程恢复/撤销、真实 Mac/Deepin E2E。

**不纳入 v1**：任意系统管理员 shell、无人审批的系统安装/生产发布、全平台 GUI 完全等价、对所有第三方软件的任意 UI 自动化、跨多个仓库的真实原子提交、无人值守支付、跨信任边界自授权。

## 3. 需求：功能 EARS 合同

### 3.1 授权与能力发现

- FR-01 WHEN Agent 计划执行工具 THEN Runtime SHALL 解析 `task_id/goal_id/owner_session/agent_id/lane_id` 和有效 Capability Lease，缺失事实不得由模型猜测。
- FR-02 WHEN 用户授权多个精确目录 THEN Runtime SHALL 允许所列根目录的指定动词；未列根目录不得继承权限。
- FR-03 WHEN 任务授权已覆盖普通操作 THEN Runtime SHALL 在有效期内免重复逐命令审批；精确高风险动作仍走原门禁。
- FR-04 WHEN 子 Agent 启动 THEN 其能力 SHALL 为父任务授权与子声明的交集；子声明扩大父授权 SHALL 被拒并给出原因。
- FR-05 WHEN 用户通过可信 Owner UI 扩大任务范围 THEN Host SHALL 生成新版本授权，旧授权失效或受控收敛；不能通过子 Agent 自报绕过父范围。
- FR-06 WHEN 授权撤销/过期/Owner 变化/Lease 代次失配 THEN 新的外部副作用 SHALL 拒绝；运行中副作用按可停止性和 WAL 进行处置。
- FR-07 WHEN 权限预检 THEN 结果 SHALL 区分 policy_allowed、backend_supported、os_permission、runtime_ready、required_human_action，不能把“批准”直接显示为“可执行”。
- FR-08 WHEN 后端无法实现等价隔离 THEN 高敏感操作 SHALL fail-closed，并提供支持的执行器或授权路径；普通只读诊断可继续。

### 3.2 跨项目与文件系统

- FR-09 WHEN 用户批准项目 A/B 的 `read/write/create/rename/delete` 子集 THEN 文件工具与命令工具 SHALL 使用同一能力判定；文件级敏感 deny 永远优先。
- FR-10 WHEN 创建不存在的文件/目录 THEN SHALL 先安全固定已存在父目录，校验授权根、禁止 symlink 逃逸，原子写入/rename 后复核目标。
- FR-11 WHEN 文件发生并发变化 THEN SHALL 使用 snapshot/CAS 或 Lane 锁，不能静默覆盖。
- FR-12 WHEN 跨项目执行构建 THEN SHALL 使用显式工作目录、受控可写根和必要的精确缓存根；不得通过任意全 HOME 写实现。
- FR-13 WHEN 请求读取密钥、凭据或隐私核心目录 THEN SHALL 适用独立隐私/读取策略；macOS 当前写沙箱不视为读取隔离证明。
- FR-14 WHEN 多项目操作部分成功 THEN SHALL 返回每项目效果、补偿或人工处置计划；不得声称跨仓库原子事务。

### 3.3 Git、服务与系统

- FR-15 WHEN Agent 请求普通 Git status/diff/add/commit THEN SHALL 走受管 Git Adapter，绑定 canonical repo/worktree/gitdir、Lane 和预期 HEAD；只允许明确列出的子命令/参数。
- FR-16 WHEN Git linked worktree 的 gitdir 在工作树外 THEN SHALL 由可信适配器对精确元数据执行，不能向通用 Shell 追加整个 gitdir 的永久写权限。
- FR-17 WHEN push/merge/release THEN SHALL 保留独立 Reviewer、原版完整 R9、远端 CI、受保护 main 与 Host 签发/人工批准的既有门禁；任务级授权不能替代这些证据。
- FR-18 WHEN 维护 LFL 自身 THEN SHALL 使用 `service_control` 的 desired/CAS/受管重启与回滚，服务重启前持久化任务/效果状态，重启后核验实际 SHA/PID/健康。
- FR-19 WHEN 系统级操作需要 OS 授权 THEN SHALL 经明确受信任 Host Helper/TCC/Polkit 处理；模型不能通过 GUI 终端、脚本或 sudo 提示绕过。
- FR-20 WHEN GitHub/网络暂不可用 THEN SHALL 不阻断本地已核验服务的 status/restart/rollback；需要远端的 push/下载则明确等待。

### 3.4 桌面、浏览器与人机协作

- FR-21 WHEN 用户在其他窗口活跃 THEN Agent SHALL 优先使用窗口绑定的后台 AX 操作，避免全局 HID 抢焦点；需要前台时必须获取短时前台租约并复核窗口。
- FR-22 WHEN 操作目标为浏览器网页内容 THEN SHALL 使用 `browser_operate` 的 CDP/DOM 绑定；浏览器 chrome 与原生对话框可用桌面适配器。
- FR-23 WHEN 用户授权 IDE 普通编辑 THEN SHALL 允许限定应用/窗口/编辑动作；终端/IDE 的“通过 GUI 执行任意 Shell”仍不允许，命令经 `execute_command` 或受管 Git Adapter。
- FR-24 WHEN 操作触发关闭、删除、发布、发送、支付或高风险提交 THEN SHALL 走独立精确确认/受管发布闸，且事后核验。
- FR-25 WHEN TCC/AX/Screen Recording/图形会话不可用 THEN SHALL 报告具体系统授权步骤，不能用空闲计时或假 token 冒充系统许可。
- FR-26 WHEN 桌面操作无法验证投递效果 THEN SHALL 返回 `outcome_unknown`，不盲目重试可能产生重复副作用。

### 3.5 恢复、可观察性与 UX

- FR-27 WHEN 任务跨进程/重启恢复 THEN SHALL 读取可信授权版本与副作用 WAL，复核 Owner/TTL/撤销/后端权限，不默认恢复未验证的危险动作。
- FR-28 WHEN 操作被拒 THEN SHALL 返回稳定 `reason_code`、`layer`、`remediation`、`retryable`、`approval_required`；禁止笼统“权限不足，换命令重试”。
- FR-29 WHEN 用户点击批准 THEN UI SHALL 区分 `approved`、`capability_ready`、`running`、`effect_verified`，并提供撤销入口。
- FR-30 WHEN 同一失败连续重试 THEN Runtime SHALL 按稳定错误码去重，优先一次性诊断或请求必要授权，不无限尝试。
- FR-31 WHEN 审计写入失败/权威账本不可信 THEN 外部写入 SHALL fail-closed；只读诊断继续并报告降级。
- FR-32 WHEN 用户询问 Goal 完成 THEN SHALL 以真实测试/审查/CI/部署回执回答，不因设计文档存在就标记 complete。

## 4. 非功能、安全与性能要求

- NFR-01 默认普通开发体验：授权一次后，在已授权范围内不逐文件弹窗；一个真实开发任务应可连续完成。
- NFR-02 未授权写入零成功；授权凭证不可由 workspace、模型输出、网页、子进程伪造或扩权。
- NFR-03 只暴露最小权限；应用和 OS 权限按平台分别证明，不能拿 macOS 测试冒充 Deepin 通过。
- NFR-04 任务中断/取消/撤销后，无未经核验的重复发布、支付、提交或文件覆盖。
- NFR-05 对现有未使用 Capability Lease 的会话保持旧行为；灰度按会话/Goal opt-in，不突然放宽全局策略。
- NFR-06 新 Resolver 纯本地、无模型调用；目标单次预检开销低于 50ms p95（性能目标，须真实测量）。
- NFR-07 以“完成率、审批次数、权限错误率、错误归因率、恢复成功率、端到端时间”作为验收 KPI，不以工具调用次数单独评价。
- NFR-08 不在审计、Provider 可见文本或浏览器响应中泄漏授权密钥、Cookie、密码、私钥、完整敏感路径内容。

## 5. 威胁模型与信任边界

### 5.1 信任等级

1. **Owner 人工审批通道**：登录的可信浏览器/桌面用户确认，Host 侧权威；loopback/Bearer 不能自批 Host 授权。
2. **Host Capability Authority**：持久受保护账本、签发/撤销/版本；不运行模型文本提供的任意命令。
3. **Agent/子 Agent**：不可信决策主体，可申请能力但不能签发；执行权限由 Runtime 注入。
4. **网页/文件/工具输出**：不可信数据；不得包含可执行授权或改变任务权限。
5. **执行后端**：沙箱 Shell、文件服务、Git Adapter、CDP、AX、service_control、系统 Helper；各自保留原安全边界。

### 5.2 必须防住的攻击

| 攻击 | 强制不变量 | 验收负测 |
|---|---|---|
| prompt injection 自称“已批准” | 模型文本不能生成 Lease | 伪造审批文字无效 |
| 伪造/篡改 grant 文件 | Host 验签 + owner-only 存储 | HMAC/签名篡改拒绝 |
| 通过 `../`、symlink、rename 越界 | canonical root + 安全目录 FD/路径固定 + 后端隔离 | symlink/TOCTOU 拒绝 |
| 父子授权越权 | 子能力为父与子交集 | 子申请第三项目拒绝 |
| 命令/GUI 互相绕过 | 同一资源策略 + 各通道守卫 | IDE Terminal 粘贴 Shell 不放行 |
| 用户操作与 Agent HID 竞争 | 后台优先、前台租约/窗口复核 | 用户活跃时不抢焦点 |
| 撤销后仍执行 | 操作前实时授权版本/撤销检查 | revoke→下一副作用拒绝 |
| 重启后重放不可逆动作 | WAL outcome unknown 不自动重试 | 模拟崩溃无重复效果 |
| 直接改审计/授权账本 | 账本位于沙箱写根外，OS ACL/签名 | 子进程不可改写 |
| Reviewer/CI 证据伪造 | 受信 Host 独立签发、远端验证 | 假 PASS/旧 SHA 拒绝 |

### 5.3 特殊说明：macOS 读侧

现行 `sandbox-exec` profile 主要是 `deny file-write*` + 精确写根，普通读取并非受限。v1 不得将它宣传为完整读取隔离。对敏感资料采用工具层读策略；对高风险不可信 Shell 要求能证明读侧隔离的执行器（如经实测配置的容器）或明确拒绝。不得默许任意 Shell 读取凭据后再靠审计补救。

## 6. 目标架构

```text
User / Owner UI ──[review exact task scope]──> Host Capability Authority
                                                   │
                                         signed/versioned Task Lease
                                                   │
LFL Goal/Task/Lane ──> Capability Resolver <───────┘
      │                  │
      │           Policy + OS/backend preflight
      │                  │
      ├── sandboxed execute_command (multi-root only when proven)
      ├── FileService (read/edit/create/rename/delete with CAS)
      ├── Managed Git Adapter (repo/worktree/gitdir, locks, HEAD)
      ├── Browser CDP / Desktop AX (window binding + foreground lease)
      └── service_control / trusted OS Helper (only explicit verbs)
                              │
                     Effect Journal / Audit / Recovery
```

**最小新增核心**：`core/capabilities/task_lease.py`（不可变契约与判定）、`core/capabilities/resolver.py`（纯预检）、Host Authority adapter（签发/撤销/查验）、执行器薄适配；尽量复用已有 `HostCapabilityGrantStore`、`WriteScope`、`ToolExecutionJournal`。不把新持久状态放在 Web 组件里。

### 6.1 TaskCapabilityLease v1 建议字段

```json
{
  "schema": "lfl.task-capability-lease/v1",
  "lease_id": "opaque-host-issued",
  "goal_id": "GOAL-...",
  "task_id": "TASK-...",
  "owner_session_id": "trusted-session-id",
  "agent_id": "agent-or-lane-id",
  "parent_lease_id": null,
  "revision": 1,
  "expires_at": "ISO8601",
  "resources": [
    {"kind": "project", "canonical_root": "/absolute/project-a",
     "verbs": ["read", "write", "create", "rename", "build", "git_commit"]},
    {"kind": "project", "canonical_root": "/absolute/project-b",
     "verbs": ["read", "write", "build"]},
    {"kind": "app", "bundle_id": "exact.app.bundle", "verbs": ["observe", "edit"]},
    {"kind": "service", "service_id": "lfl-web", "verbs": ["status", "restart"]}
  ],
  "denies": ["secrets", "host-authority-store", "protected-audit"],
  "constraints": {"lane_fence": "opaque", "require_cas": true},
  "issuer_key_id": "trusted-host-key-id",
  "signature": "host-signature-over-canonical-payload"
}
```

这是**设计合同，不是当前已经实现的 API**。路径为示例，真实授权必须来自 Host 对具体设备、目录、应用的规范化观测。Lease 仅在可信 Runtime/Host 内保存完整凭证；模型只能拿到不含签名/秘密的能力摘要与拒绝原因。

### 6.2 Lease 状态机

`requested → pending_human → approved → ready → active → expired/revoked/closed`。

- `approved`：可信用户确实批准；不等于 OS 后端就绪。
- `ready`：后端、OS 权限、资源身份、父级范围全部预检通过。
- `active`：一次或多次被授权的普通动作在受控范围内执行。
- `revoked`：新的副作用必须拒绝；在途动作经 WAL/取消屏障处置。
- 服务重启后重新验证签名/Owner/TTL/撤销/OS 权限；不能凭旧进程 HMAC 自动恢复。
- **不强求跨重启保留每条高风险一次性批准**：高风险动作仍须绑定精确内容与新鲜版本。

### 6.3 授权边界的两层关系

- **Owner 任务权威范围**：人类可批准新增项目/应用/服务；修改此范围需可信审批、版本递增和旧权限收敛。
- **Agent 委派范围**：子 Agent 只能从已批准 Owner 范围取子集；`write_scope` 父子求交仍有效。
- 现有 Host Grant 是精确单文件/命令的低层授权机制，保留兼容；Task Lease 不得直接覆盖它的灾难命令、隐私、服务、Reviewer 门禁。
- 如 Owner 新增项目 B，必须由 Host 修改 Owner 范围，再创建受限子租约；不能用“Host Grant 豁免父 scope”捷径。

## 7. 执行器实现设计

### 7.1 Capability Resolver（P0）

输入：可信执行上下文、目标资源、动词、预期版本/效果、后端状态。

输出稳定结构：
```json
{
  "decision": "allow|need_approval|need_os_permission|unsupported|deny|stale",
  "layer": "owner|parent_scope|lane|sandbox|os|service|review",
  "reason_code": "capability_scope_missing",
  "backend": "bwrap|sandbox-exec|file-service|git|ax|cdp|service",
  "approval_required": true,
  "retryable": false,
  "remediation": "向 Owner 申请项目 B 的 write 权限",
  "authority_revision": 7
}
```

要求：纯机械判定、无模型调用、不创建授权、不隐式修改文件；不得将 Resolver 的“允许”当作 OS 实际执行成功。执行器在真正副作用前必须复检（TOCTOU），并产出效果回执。

### 7.2 跨项目文件与命令（P0）

- 资源绑定：精确 canonical 项目根 + 允许动词 + 版本 + Lane；多根授权不等于以父目录为工作根。
- 文件工具：统一调用 Resolver，复用 `FileService` snapshot/CAS；创建新路径时固定现存父目录、检查符号链接与最终落点，禁止 `..` 越界。
- 命令工具：新增结构化 `authorized_roots` 的可信注入（不允许模型任意传根）；明确 `workdir`，保留现有命令危险扫描、Review Admission、父 write-scope 和审计。
- macOS：在 `sandbox-exec` profile 中追加获准的写根，并在末尾覆盖受保护目录 deny；对可写根祖先 rename、symlink、硬链接等做负测。
- Linux：`bwrap` 精确 `--ro-bind/--bind`，先建立 mount point，再挂受保护账本的只读 overlay；需要目录级授权时应实测 bind/rename/符号链接攻击，不直接复用单文件 FD 逻辑假称等价。
- Docker：未完成隔离等价验证时不得静默忽略新增根；显式 `unsupported_backend` 并提供受支持路径。
- 构建缓存：按工具链固定最小根（项目 `.venv`、`node_modules`、受管缓存等），不能把 `HOME` 作为默认可写根。
- Git 元数据：不作为普通命令通用可写根；交给 Git Adapter。

### 7.3 Managed Git Adapter（P0）

只复用/补齐必要动作：`status`、`diff`、`add`、`commit`、`fetch`、受管 `push`。拒绝任意 `-c`、hook 路径、`--exec-path`、`core.sshCommand` 等可将 Git 变成任意执行器的注入参数。

- `repo_root`、`worktree_root`、`gitdir`、`common_dir` 由可信 Git 探针解析；不能由模型随意传入“可信路径”。
- 对 `add/commit` 使用 Lane 文件归属、工作树/HEAD 前置版本、受管锁；不对别的 Lane 文件执行 `git add -A`。
- 对 `push`、`merge`、发布保持既有 `review_admission`、原版 R9、远端 CI、保护分支与人工批准，不因任务级 Lease 自动跳过。
- 单仓库内 index/refs 操作可以事务化；跨仓库提交是有序 Saga，记录每仓库 commit SHA 与失败后的恢复/补偿，不声称跨仓库 ACID。
- 测试：linked worktree `.git` 指针、外置 gitdir、锁冲突、并发更新、恶意 Git 参数、protected main、无网络、重试/恢复。

### 7.4 桌面/浏览器（P1）

- 桌面按 `bundle_id + pid + window_id + revision` 绑定，优先 AX 背景操作，失败后才申请受控前台短租约；不得默认使用全局 HID 60 秒门禁阻断所有后台动作。
- 当前 `desktop_operate` 默认 OFF 不直接全局开启；通过任务授权及 Host 已具备 TCC/AX 的前提，灰度开放精确应用/动作。
- IDE 文本编辑允许在可信窗口/编辑控件范围内使用 AX；终端命令一律通过受管命令工具，不开放终端粘贴任意 Shell。
- 浏览器网页使用 `browser_operate`；浏览器 chrome/原生文件对话框使用桌面工具；发布、提交、支付仍独立审查。
- 多窗口同时操作要有窗口租约；当前用户活动不等于全部后台操作必须拒绝，但前台抢焦点必须检测并获得许可。
- macOS TCC/辅助功能/屏幕录制不可由 LFL 自己静默批准；Deepin 需分别验证 Wayland/X11、DDE/DBus/portal/Polkit 支持，不能声称 macOS AX 可直接移植。
- 结果以 AX/DOM 状态回读为准；不可观测的 HID 投递标为 `outcome_unknown`。

### 7.5 LFL 自身维护/系统操作（P1）

- 复用 `service_control`，任务级 Lease 只作为准入之一；不得直接 `kill` 进程绕过发布屏障。
- Linux 用户级 systemd、Mac 受管 LaunchAgent 走各自既有可信入口；真正 OS 管理员动作需要最小 Polkit/受信 Helper，绝不通用 sudo。
- 自重启前将 Goal、Lease revision、pending effect、期望 generation 持久化；服务恢复后核对真实 SHA/PID/健康与目标一致，失败则受管回滚。
- GitHub 不可用不阻断本机 status/restart/rollback；新候选下载与 push 必须真实网络回执。

## 8. 并发、生命周期与持久性

### 8.1 多 Agent

- 一个问题族只允许一个写入 Owner Lane；最多三个只读分析子 Agent 可并行；独立 Reviewer 只审冻结候选。
- 每个写动作绑定 `goal_id/task_id/lane_id/lease_revision/base_sha/snapshot_ref`；锁、CAS 与 effect fence 同时成立才执行。
- 新增项目权限不意味着获得其他项目已有 Lane 的文件所有权；需要通过受管 Lane 交接/队列释放。
- 子 Agent 结束时仅提交可验证产物与回执；主代理负责交叉验收、合并与部署。
- 无法获得 Lane 的写权限时可以只读审查或排队，不能自行删除/重置别人的 worktree。

### 8.2 恢复与撤销

- Host Authority 采用跨进程可信签名/验证或等价受保护凭据，不把签名密钥放入 Agent 可写目录/环境/Provider 上下文。
- 账本追加审计或受保护事务存储；持久化 `lease_id/revision/status`、精确目标、动作结果和 revoke epoch。
- 撤销后新副作用拒绝；已开始动作应尝试取消/等待终态并核验，不可将“取消请求已发出”冒充“动作已撤销”。
- 对不可逆 `outcome_unknown` 保持 HOLD，等待可证明的远端/本地效果检查或人工裁决，禁止自动重放。
- 使用已有 `ToolExecutionJournal` 和 `side_effects`，只补必要的授权引用，不造第二套执行真值。

## 9. 错误分类、用户体验与指标

### 9.1 错误码

| 层 | 示例代码 | 用户看到的处理 |
|---|---|---|
| Owner/Lease | `capability_scope_missing` | 申请增加项目/动词 |
| 父子 | `parent_scope_denied` | 由 Owner 扩大任务范围或换 Lane |
| Lane/CAS | `lane_conflict` / `stale_revision` | 等待归属/刷新快照 |
| 沙箱 | `sandbox_bind_missing` / `sandbox_backend_unsupported` | 选择受支持后端/补精确挂载 |
| OS | `os_tcc_required` / `os_polkit_required` / `os_acl_denied` | 真实系统授权步骤 |
| 审批 | `human_auth_required` / `approval_pending` | 登录后审批/等待 |
| 服务 | `service_busy` / `deployment_generation_stale` | 等待/刷新 generation |
| 效果 | `effect_outcome_unknown` | 核验效果，不自动重试 |

### 9.2 UI 最小改动

一个“任务授权”卡片展示：批准的项目、应用、服务、允许动作、有效期、当前状态、最近效果、撤销入口。需要新权限时展示**实际新增范围的差异**，而不是整段命令重复确认。UI 明确区分“已批准”“后端已就绪”“执行成功并核验”。

### 9.3 量化指标（真实验收，不预设假绿）

- 完成率：指定 Mac/Deepin 场景中真实副作用达成比例。
- 审批摩擦：单个已授权普通开发任务的重复审批次数，目标为 0。
- 沙箱误拒率：已授权普通操作因非必要 EPERM 失败的比例，目标为 0。
- 安全：未授权写入/跨 Lane 写入/越权 GUI 命令执行成功数，必须为 0。
- 恢复：中断后状态、版本、效果可核验；不可逆动作自动重复数，必须为 0。
- 延迟：Resolver p95、工具端到端耗时、首个有效动作时间；记录相同任务 A/B，不通过降低安全性换速度。

## 10. 分阶段实施与最小真实闭环

### M0：冻结基线与协调（必须先做）

交付：本设计书、真实代码路径/风险清单、现有 Goal/Lane/主分支/部署快照、独立工作树和精确文件所有权。

- 确认其他在途 Lane，不抢占 `src/llm_loop/tools/builtin/execute_command.py`、`sandbox.py`、`desktop_operate.py` 等文件；冲突由协调 Owner 释放后再写。
- 建立 LFL durable Goal，创建 Task M0/M1/M2/M3，记录验收标准和依赖。
- 不在设计审查循环中无限迭代；Reviewer 只审冻结候选的 P0/P1，修复后进入真实代码。

### M1：P0 跨项目正常开发闭环（第一优先）

**最小可验收场景**：两份临时项目 A/B、一个 linked worktree、一个 Python 测试/构建任务。

实施：
1. 定义 Task Lease 最小可信结构、Resolver 纯判定和稳定错误码；复用 Host 既有审批入口。
2. 让文件工具与命令工具在获批两个根目录内一致执行，未获批第三根不可写。
3. 在 Mac Seatbelt、Linux bwrap 中分别编译真实多根写域；禁止“参数被忽略仍成功”。
4. 让 Git add/commit 在 linked worktree 真实成功，通用 Shell 不获整仓 `.git` 泛写。
5. 覆盖 create/rename/symlink/并发 CAS/撤销/审计/重启边界。
6. 用真实模型 `glm/glm-5.3-flash` 运行一次完整开发任务；不得仅以 mock 单测代替。

M1 完成条件：两项目可编辑/测试/普通提交；第三项目越权拒绝；未授权敏感路径拒绝；用户对已授权普通操作不重复审批；Mac 和 Deepin 各有实测回执。无法完成 Deepin 真机时标记该平台 HOLD，不能宣称双平台完成。

### M2：P1 电脑控制与 LFL 自身操作

实施：
1. Capability Lease 绑定桌面应用/窗口动作，后台 AX 优先，前台焦点租约仅用于确需前台的动作。
2. IDE 正常编辑、浏览器 CDP、原生文件对话框联动；不开放 GUI Terminal 绕过命令门禁。
3. LFL `service_control` 接受任务级授权准入但保留 CAS/发布门禁；受管重启一次，核对实际 SHA/PID/健康。
4. Deepin X11/Wayland/Polkit 真实环境探测和受限能力回退；缺支持必须报告而非静默。
5. 人机同时使用电脑的 A/B 实测：用户窗口 A、Agent 窗口 B；前台无意外抢占。

M2 完成条件：至少一个 Mac 原生 IDE/文稿场景 + 一个浏览器场景真实成功；LFL 自重启安全恢复；Deepin 真实支持范围被如实记录。

### M3：P2 持久授权、撤销与并发恢复

实施：
1. 跨进程 Host 签发/验证、撤销 epoch、最小授权状态 UI。
2. 两 Agent 并行不同项目/文件的 Lane/CAS/Lease 交叉测试。
3. 故障注入：审批后未就绪、系统权限撤销、重启中断、效果未知、远端 CI 失败、窗口焦点变化。
4. A/B：旧单文件逐命令授权 vs 任务级授权，量化完成率、审批次数、误拒、耗时。

M3 完成条件：安全负例全部拒绝、合法任务连续成功、恢复无重复副作用，性能没有明显退化。

### M4：正式集成与受管部署（仅 M1–M3 全部达标后）

1. 每阶段完成独立开发提交；只对精确冻结候选发起独立 Reviewer，要求真实 PASS、P0/P1=0。
2. 运行**原版完整 R9**，保存精确 SHA、原始日志和 exit 0；不以定向测试/重试掩盖失败。
3. 受管 `git_push`、PR、远端 CI、受保护 main 合并；主 CI 通过后才可部署。
4. 合并前重查最新 `origin/main`、15+ 在途 Lane、文件归属与代码漂移；冲突则最小协调/重审新 SHA。
5. 统一受管部署/重启一次（仅实际需更新服务），核对 Mac 四服务与 Deepin 目标版本、PID、实际 SHA、健康、恢复、回滚条件。
6. 完整验收后正式关闭 LFL Goal；任一平台/门禁缺失则保留 active/HOLD，明确剩余事项，不宣称完成。

## 11. 任务拆分、归属与依赖

| Task | 依赖 | 唯一写 Owner | 验收材料 |
|---|---|---|---|
| T0 设计冻结/证据/冲突盘点 | 无 | 主代理 | MD、main/Lane/运行态快照 |
| T1 Lease + Resolver + 审批衔接 | T0 | 单开发 Lane A | schema、纯判定/负测、批准→ready |
| T2 多根沙箱 + FileService | T1 | 单开发 Lane B（文件无冲突时） | Mac/bwrap 实测、创建/rename/CAS |
| T3 Git Adapter + linked worktree | T1 | 单开发 Lane C（文件无冲突时） | add/commit 成功、元数据隔离、锁 |
| T4 桌面/浏览器/服务衔接 | T2/T3 | 单开发 Lane D | AX/CDP/service 真实效果 |
| T5 持久授权/撤销/并发/恢复 | T2/T3/T4 | 单开发 Lane E | 故障注入、WAL、撤销、A/B |
| T6 独审/R9/PR/CI/main/部署 | T1–T5 | 主代理/受管 Host | 全链证据、live SHA、Goal complete |

**并行约束**：每个问题族只允许一个写 Agent；最多三个只读子 Agent 并行审查；T2/T3 只有在文件集合无重叠且 Owner/Lane 已受管登记后才能并行。主代理负责最终交叉验证和收口。绝不为提高吞吐强制清理其他会话脏树。

## 12. 测试与验收矩阵

| ID | 场景 | 正向断言 | 负向断言 |
|---|---|---|---|
| A01 | 双项目目录授权 | A/B 创建、修改、测试成功 | C 未授权写失败 |
| A02 | Git linked worktree | add/commit 成功、HEAD 可核验 | 通用 Shell 不可随意写 gitdir |
| A03 | 构建工具链 | Python/Node 构建缓存精确可用 | HOME/密钥目录不可被泛写 |
| A04 | 文件创建/重命名 | 目标原子更新、版本正确 | symlink/../rename 越界拒绝 |
| A05 | 父子 Agent | 子集内写成功 | 子自报扩权拒绝 |
| A06 | 审批真实生效 | approved→ready→effect_verified | 只有 approved 时不得称执行成功 |
| A07 | 撤销/过期 | 下一写入被拒 | 重放旧 grant 无效 |
| A08 | Mac GUI | 后台窗口动作回读成功 | 人在用电脑时不抢前台 |
| A09 | Browser | CDP 目标绑定成功 | 发布/支付不能绕过审批 |
| A10 | LFL service | 受管 restart+SHA/PID/health | 无 CAS/屏障不得直接重启 |
| A11 | Deepin | bwrap/systemd/授权真实成功 | unsupported backend 不假绿 |
| A12 | 故障恢复 | WAL 正确恢复、outcome unknown HOLD | 不可逆动作不自动重试 |
| A13 | 多 Agent | 不同 Lane 并行无丢更新 | 重叠写入/CAS 冲突拒绝 |
| A14 | 审查/发布 | 精确 SHA 的 Reviewer/R9/CI/部署齐全 | 假 PASS/旧 SHA/未保护合并拒绝 |

测试分层：纯单元（快速）→ 实际沙箱子进程/临时目录（必须有）→ Mac/Deepin 真机 → 真实 LFL 模型任务 → 独立 Reviewer → 原版 R9 → 远端 CI → 生产验收。每个回执须标明 platform、backend、SHA、执行时间、结果、未覆盖边界。

## 13. 交互流程示例

### 13.1 正常双项目开发

1. 用户：维护 A/B，运行测试并普通提交。
2. Resolver：A/B 读写/构建/commit 需要授权；Owner UI 一次展示差异。
3. 用户批准：Host 签发任务 Lease，预检 `ready`。
4. Agent：读取/编辑 A/B → 构建测试 → Git Adapter 普通提交 → 回读 SHA。
5. 用户：如需 push/main/部署，继续走既有独审/R9/CI/受保护合并/发布。
6. Agent：报告实际结果、证据与下一步；不因普通命令切换重复申请授权。

### 13.2 用户正在用电脑

1. 用户在窗口 A 打字，Agent 计划在窗口 B 编辑文稿。
2. Resolver 核验窗口 B 的应用/动作授权、AX/TCC、revision、后台能力。
3. Agent 以后台 AX 修改窗口 B，回读验证；不移动系统前台焦点。
4. 若后台不可行，返回 `foreground_required`，申请短时前台租约；不得直接抢焦点。
5. 如果用户拒绝前台控制，保留草稿/任务状态，等待继续。

### 13.3 权限不足

1. 工具返回 `sandbox_bind_missing` 而非笼统 EPERM。
2. Resolver 提供确切项目根、动词、可用后端及审批动作。
3. 用户批准后 Host 编译可用写根并做真实预检。
4. Agent 只重试原失败动作一次（同一效果 ID），成功后核验；若 OS 仍拒绝则显示真实层级，不循环重试。

## 14. 迁移、灰度与回滚

- **默认旧行为**：未授权新 Lease 的会话完全沿用现有执行边界；不自动扩大用户环境权限。
- **灰度开关**：按 Goal/Owner/平台启用，不使用全局“关闭沙箱”开关。
- **兼容**：旧 `host_access_request` 继续存在；新 Lease 是更高层的任务范围，不直接覆盖旧 grant 的签名与一次性高风险语义。
- **回滚**：撤销 Lease/禁用新 Resolver 路由，恢复旧工具行为；既有已核验副作用不回滚为“未执行”。
- **平台**：Mac 与 Deepin 分开验收；未实测的平台标注 unsupported/HOLD。
- **上线**：部署前保留原版本与恢复点；按受管 generation CAS 切换，失败使用现有回滚，不重启整机。
- **防漂移**：代码、配置、Host helper、TCC/Polkit 权限、实际服务身份分开核验；不能以源码存在代替生效。

## 15. 独立 Reviewer 必问的十个拷问

1. 新 Lease 是否被不可信模型/网页/子 Agent 伪造或扩大？
2. 多根目录授权是否存在 symlink、rename、mount、硬链接、路径大小写或父目录逃逸？
3. macOS 写沙箱未限制读/网络，是否被误宣称为完整隔离？
4. bwrap/Docker/sandbox-exec 是否对授权根与 deny 规则做了等价证明？未支持是否 fail-closed？
5. Git Adapter 是否可被参数、hook、配置或仓库内容转成任意宿主命令？
6. Owner 任务范围扩大是否经可信人工审批，而非子 Agent 自报？
7. 撤销/重启/取消与 WAL 效果记录是否存在重复不可逆动作窗口？
8. 桌面 AX/HID 是否会误投递到用户前台或敏感应用？浏览器网页是否绕过 CDP 门禁？
9. 服务/发布是否仍受保护 main、Reviewer、原版 R9、CI、CAS、人工授权约束？
10. 是否实际减少审批和误拒，还是仅增加复杂度与新状态机？

Reviewer 只针对精确冻结候选审查；发现 P0/P1 修复代码和测试后重审，P2 排入可验证待办。不要因文字设计“看起来完整”宣称功能完成。

## 16. 最终 DoD（Definition of Done）

必须同时满足：

- [ ] 完整需求设计 MD 已冻结并与实际代码/测试对应。
- [ ] LFL durable Goal/Task/Lane 归属可查；无覆盖其他会话未完成工作。
- [ ] Task Lease/Resolver/审批→后端 ready→真实效果闭环完成。
- [ ] 两项目、linked worktree、构建缓存、普通文件/提交真实成功。
- [ ] 未授权项目、敏感路径、父子扩权、撤销、并发冲突全部负测通过。
- [ ] Mac 桌面后台、浏览器和 LFL 受管服务真实场景通过。
- [ ] Deepin 真机 bwrap/系统授权/服务场景通过，平台限制如实披露。
- [ ] 长任务中断恢复与副作用未知态安全验收通过。
- [ ] 独立 Reviewer PASS，P0=0、P1=0，证据绑定精确 SHA。
- [ ] 原版完整 R9 `exit 0`，无以重试掩盖失败。
- [ ] GitHub PR、远端 CI、受保护 main 合并及 main push CI 成功。
- [ ] 统一受管部署/必要重启，实际 SHA、PID、健康、回滚与 Goal 续接通过。
- [ ] LFL Goal 由真实回执正式关闭；任何缺项保持 active/HOLD。

## 17. 当前执行状态（2026-11-19）

- 设计：**v1.0 实施基线已冻结**；若后续事实证明必须修改关键合同，记录 spec_change 并对新候选重新审查，不进入无限文档拷问。
- 代码：M1 已提交**纯判定基础** `src/llm_loop/core/task_capabilities.py` 和 22 条定向单测（`2e7d10d19`、`0a16d7742`）；Ruff/Pyright/pytest 定向通过。尚未接入 Host 签发、文件/命令执行器、多根物理沙箱、Git Adapter、桌面/服务工具，**不能称正常任务闭环已完成**。
- LFL Goal：必须通过 LFL 原生 `create_goal` 在独立会话创建；本文件不是 Goal 创建凭证。
- 审查/R9/PR/CI/合并/部署：尚未针对本方案执行；不得借用 Issue #73 或其他 Lane 的回执。
- 并行风险：创建本方案时协调看板显示 15 条在途 Lane；后续以实时看板为准。
- 下一步：冻结文档、建立独立 Goal 与 Task、分配无冲突 Lane、从 M1 的双项目真实闭环直接落代码。
