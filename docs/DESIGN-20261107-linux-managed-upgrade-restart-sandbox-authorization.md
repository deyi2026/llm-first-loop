# Deepin Linux：LFL 自动升级、无人值守重启与沙盒授权统一需求实现设计

- 日期：2026-11-07
- 类型：需求与实现设计（SDD）
- 状态：设计草案；未实现、未独立 Reviewer PASS、未授权生产变更
- 本地源码核查基线：main @ 9242dc74cbd4（v0.6.40 发行面，2026-11-07 09:46 时的 main）
- 修订时实际基线：main = origin/main = ee475a3526ae（2026-11-07 13:44 只读复核）；基线漂移 3 个提交（52f123650 fix(review)、1b738c432 docs(verification)、ee475a352 docs(governance)），均未触及本设计所列阶段 0 事实源的代码路径，但须在 Stage 0 逐条重冻结后才可作为施工基线
- 实机核查基线：Deepin 25 / Linux 6.6.155-amd64 / x86_64 / LFL wheel 0.6.40
- 原则：优先修复现有机制，不重造运维框架；不扩大功能范围；不因 GitHub 临时不可达而阻断本机服务恢复。

---

## 0. 执行摘要

本轮拷问确认：LFL Linux 已有版本目录、wheel SHA-256 校验、活动/前一版本指针、安装器锁、用户级 systemd Web 服务和部分升级预检能力，但尚未形成端到端的自动升级与服务恢复闭环。更关键的是，Deepin 当前 Web 使用 wheel release，Feishu / Learning 使用源码工作区虚拟环境，service_control 的源码仓库身份校验又无法直接适配 wheel 布局；因此简单增加 restart 按钮或把 systemd 的 Restart 改成 always 都不足以解决问题。

建议把工作拆为三个相互协作、权限边界独立的控制面：

1. **发行控制面**：候选版本来源、完整性与信任校验、预装、快照、事务 journal、原子切换和回滚。
2. **服务控制面**：wheel / source 双身份识别、Web / Feishu / Learning 的 systemd 生命周期、忙闲准入、开机恢复和健康验收。
3. **宿主能力控制面**：workspace / write-scope、OS 沙盒挂载、网络能力、一次性路径授权和系统管理员动作的分层执行。

核心决策：

- 保留现有 Linux 安装器和 release 目录，不另造包管理器。
- 为 wheel 安装增加真实的 wheel-release service backend；保留 source checkout backend。严禁伪造 Git SHA、假仓库或 .venv 来绕过身份校验。
- 三服务统一交由 systemd --user 管理，稳定启动器从唯一活动版本指针解析实际 release。
- 新版本下载、安装依赖、check-install、doctor 和候选 smoke 全部在旧服务仍运行时完成；只有 staging 成功才进入停机切换。
- GitHub 网络与服务运维解耦：服务重启、健康检查、回滚旧 release、开机恢复不得依赖 GitHub。候选包可来自官方 Release、受信镜像、预先缓存或用户提供的本地 wheel，但所有来源必须经过同一信任和摘要验证；不能因 GitHub API 不通而停止本机恢复，也不能因此接受未知包。
- 默认自动下载、暂存和预检，不自动切换生产。无人值守升级必须显式启用，且来源、审查、兼容、备份、服务 idle 和回滚条件全部满足。
- 沙盒授权必须真正传递到文件工具和 bwrap mount plan；UI 显示批准不等于 OS 已授予能力。
- 不关闭沙盒、不授予通用 root shell、不强杀正在执行的 Run、不自动重启整台主机。

### 0.1 优先级

| 优先级 | 项目 | 目标 |
|---|---|---|
| P0 | wheel 部署身份与 service_control 兼容 | Deepin wheel 安装版可被权威识别、检查、重启 |
| P0 | 三服务统一 systemd 生命周期 | 开机自启、崩溃自愈、受控重启可验收 |
| P0 | upgrade prepare / commit / abort / recovery 事务 | 新版本安全切换，失败可恢复 |
| P0 | HostCapabilityGrant 接入 bwrap 与文件工具 | 批准后精确路径能力真实生效 |
| P1 | GitHub / 镜像 / 本地候选来源解耦 | GitHub 暂时故障不阻断重启、回滚和离线恢复 |
| P1 | 网络 / 沙盒后端诊断 | 明确区分代理、DNS、索引、bwrap、Docker 和 OS 权限问题 |
| P1 | 无人值守维护策略 | 仅在可证明安全的维护窗口自动切换 |
| P2 | 管理面板和审计体验 | 可查看状态、授权、升级进度、失败原因和回滚回执 |

---

## 1. Deepin 实机事实

以下是本轮 SSH 只读核验与本地源码检查所得，不把设计目标写成已实现事实。

### 1.1 主机状态

| 项目 | 本轮已核实 |
|---|---|
| 操作系统 | Deepin 25 |
| 内核 / 架构 | 6.6.155-amd64 / x86_64 |
| 活动 LFL | 0.6.40 |
| LFL_HOME | ~/.local/share/lfl |
| Web unit | systemd --user 的 lfl.service |
| Web ExecStart | 固定指向 releases/LFL-0.6.40/venv/bin/lfl start |
| Web Restart | always，RestartSec=5s，TimeoutStopSec=20s |
| Web 开机启用 | 已修复为 enabled，当前 active |
| 用户 linger | Linger=yes |
| Feishu / Learning | 由源码工作区 .venv/bin/python -m llm_loop.runtime.launch 启动；未统一为 LFL user units |
| 沙盒后端 | /usr/bin/bwrap、Docker CLI 存在，Docker daemon 可访问 |
| 网络 | Clash Party 代理端口可用；系统代理开关关闭 |

已完成的主机配置修复：lfl.service 已 enable，且当前 active。它不代表已完成真实整机 reboot E2E，也不代表 Feishu / Learning 已启用开机自启。

### 1.2 GitHub 连接不再是本机运维的前置条件

当前 GitHub Git 访问已通过 Clash Party 代理验证，git ls-remote 成功。但需要明确：

- Git 的 http.proxy 不会自动成为 curl、uv 或 pip 的代理配置。
- GitHub Release API、wheel 下载、Python package index 和模型 API 是不同网络路径。
- 当前服务 restart、systemd status、健康检查、旧 release rollback、事务恢复都应在本机完成，不依赖 GitHub 在线。
- 新版本候选获取失败只应阻断“下载/升级”，不能阻断“重启现有版本、恢复旧版本或诊断服务”。
- 候选可来自官方 GitHub Release、配置的可信镜像、已缓存的发布工件或用户指定本地 wheel。无论来源如何，必须校验可信发布身份、版本元数据、SHA-256 和发行回执；仅有 SHA-256 不能证明来源可信。
- 本机有已核验旧 release 时，网络断开不影响继续启动该 release。

Nexitally 订阅按服务商要求本地直连拉取，不得强制走第三方转换器或 updater 代理。

### 1.3 三服务版本混用

当前实测：

- Web：wheel release 的 0.6.40 venv。
- Feishu / Learning：源码工作区 llm-first-loop/.venv。
- systemd --user：仅发现 LFL Web 的 lfl.service。

这意味着仅切换 .LFL-active-version 并不能证明三服务同时更新；只重启 Web 也不能证明 Feishu / Learning 使用同一代码身份、配置锚点和 DATA_DIR。

目标状态必须是三服务使用同一已核验 wheel release 身份；过渡期间若仍混合运行，面板必须显示 source / wheel identity mismatch，不能显示为同一版本或绿色健康。

---

## 2. 现有实现拷问

### 2.1 Linux 安装器已有基础，但未管理服务

主要入口：scripts/install_linux.sh。

已实现且应保留：

- 每个版本独立的 releases/LFL-VERSION/venv。
- wheel SHA-256、metadata、lfl --version 和 lfl check-install。
- .LFL-active-version / .LFL-previous-version 指针。
- 指针更新采用临时文件、fsync、原子替换和目录 fsync。
- .installer-incomplete 标记、安装器锁和部分失败恢复。
- 已安装 release 的完整性复核。

缺口：

1. 安装器不创建、不维护、不重载 systemd user units。
2. 安装器不停止、启动、核验 Web / Feishu / Learning。
3. assert_no_managed_lfl_processes 主要匹配 release venv 和 uv tool 路径，未覆盖源码工作区 .venv 中的 Feishu / Learning。
4. 当前安装流程没有端到端证明三服务已切换。
5. --rollback 只切换版本指针并验证 release，不负责服务恢复和业务健康。
6. 指针切换成功不等于服务已运行新版本。
7. 若在停机后才下载 wheel 或创建 venv，uv / pip / 网络卡住会扩大服务中断。

修订：候选下载、venv 创建、依赖安装、pip check、check-install、doctor 和 smoke 全部在旧服务仍运行时完成。只有 staging 完成后才停机。停机资格由权威 service_control 和真实进程身份提供，不依赖不完整的 ps 字符串匹配。

### 2.2 lfl upgrade 当前不是完整自动升级

主要入口：src/llm_loop/cli.py、runtime/install_recovery.py、runtime/upgrade_stage.py、runtime/upgrade_preflight.py。

当前真实语义：

| 命令 | 现状 |
|---|---|
| lfl upgrade --plan | 离线只读计划 |
| --plan --candidate + --expected-sha256 | 本地 wheel 字节、metadata、SHA 完整性检查 |
| --stage | 隔离暂存候选，不安装、不切换 |
| --verify-stage | 复核暂存候选 |
| --abort | 撤销已核验隔离候选 |
| --prepare | 缺少真实服务身份 / 停机资格时安全拒绝 |
| --commit | 缺少事务资格时安全拒绝 |
| lfl backup | 操作者声明冷停后的选定根备份 |
| lfl rollback --into | 恢复到新隔离目录，不覆盖生产数据 |

缺口：

- SHA-256 只证明内容完整性，不证明可信来源。
- 当前 stage 不是生产切换资格。
- backup coverage 为 selected_roots，不等于全量系统快照。
- --confirm-services-stopped 是操作者声明，不是程序证明所有 SQLite / JSONL writer 已退出。
- 数据 schema 兼容、迁移和回滚尚未形成完整资格链。

修订：保留现有只读与 staging 命令语义，增加独立持久化事务。不得把当前 prepare / commit 的拒绝回执包装成已具备自动升级。

### 2.3 service_control 的 wheel 身份不兼容

主要代码：runtime/service_control.py、tools/builtin/service_control.py、scripts/restart_mirror.sh。

source checkout 当前要求精确 Git SHA、code_root、runtime_root、WebUI artifact SHA；_control_code_root() 还要求从当前模块路径找到 src/llm_loop。重启脚本进一步检查 code_root / runtime_root 的双根 Git worktree 身份。

wheel site-packages 不具备源码仓库根，Deepin 实机已出现 wheel 布局下 managed restart 在身份检查处 fail-closed 的结构性问题。

禁止伪修复：

- 不创建假的 .venv 或 Git 元数据。
- 不伪造 git_head。
- 不以 PYTHONPATH 指向另一源码树冒充运行身份。
- 不绕过 _control_code_root() 或 restart_mirror.sh 的身份检查。
- 不把手工 SSH、pkill、setsid nohup 当正式长期运维入口。

修订：service_control 增加两个明确 backend：

- SourceCheckoutBackend：继续使用现有源码身份和 restart_mirror 路径。
- WheelReleaseBackend：以 version、wheel_sha256、release_dir、package manifest、deployment_id、generation 为真实身份，控制 systemd user units。

两个 backend 共享上层 action/status/receipt 语义，但不能混用或伪造身份字段。

### 2.4 manifest / DATA_DIR 分歧

服务启动时会自行写 manifest；DATA_DIR 锚点不同会导致面板只读目录与实际 manifest 目录不一致。Deepin 曾出现 Web wheel manifest 写入 ~/.local/share/lfl/data/runtime，而 Feishu / Learning 写入源码仓库 data/runtime 的情况。

修订：

- 明确区分 LFL_HOME、release_dir、DATA_DIR、LFL_WORKSPACE_ROOT、config_file。
- 三服务统一 DATA_DIR 和 runtime manifest 根。
- DATA_DIR 与 LFL_DATA_DIR 同时设置但不相等时，doctor / service preflight 报冲突并阻断切换。
- manifest 记录 artifact_kind、deployment_id、generation、version 或 git_head、artifact_sha256、service、pid、started_at、data_dir identity 和 config_hash。
- 软链接只可作为迁移期只读兼容，不作为长期身份修复。
- 面板必须读取权威 manifest 根，不以“PID 存活”单独显示绿色。

#### 2.4.1 数据根处置矩阵（P0）

现状：同一台 Deepin 上存在两个 data 根——源码工作区 `<repo>/data/`（Feishu / Learning 与早期 CLI 写入）与 `LFL_HOME/data/`（wheel 版 Web 写入）。二者都含 experiences、methods、audit 等长期资产；只改 `DATA_DIR` 而不处置存量，会同时造成“读到空历史”和“旧写入成为孤儿”。下表逐项给出策略；未列出的资产一律 `hold`（不迁移、只读观察），不得凭推断扩大迁移面。

本机已核实的存量规模（2026-11-07，源码工作区）：`data/audit/` 下有 48 个 `*.jsonl` 追加流（含 `lanes.jsonl`、`lane_events.jsonl`）；内容根同时存在 `experiences/`、`methods/` 与 `data/methods/` 三处。

| 资产 | 现所在 | 目标 | 策略 | 校验 | 回滚 |
|---|---|---|---|---|---|
| experiences/（知识卡） | 双端均可能有 | `LFL_HOME/data/experiences` | copy+verify → 只读 alias → move | 文件数 + 逐文件 sha256 清单 + 文件名集合相等 | 源端保留一周期，alias 指回源端 |
| data/methods/、methods/（方法与索引） | 双端 | `LFL_HOME/data/methods` | copy+verify → 只读 alias → move | 目录树 sha256 + 方法 id 集合 + 索引可解析 | 同上 |
| data/audit/*.jsonl（48 个 append-only 流） | 双端 | `LFL_HOME/data/audit` | append-only 合并，禁止覆盖（见 2.4.2） | 行数 + 逐行可解析 + sha256 + fork point | 截断到 fork point |
| runtime manifest | 双端 `data/runtime` | 重写，不迁移 | 由 deployment identity 重建 | manifest schema + generation | 重新生成 |
| backups/、artifacts/、attachments/、archives/、cache/ | 双端 | 不随本次迁移 | hold（cache 可丢弃） | 仅登记大小与文件数 | 无需 |
| bench_*/canary*/.tmp/ 测试夹具 | 源码仓库 | 不迁移 | hold | — | — |

顺序硬约束：冻结写入（服务 idle + writer 退出）→ 复制并校验 → 切换 `DATA_DIR` → 只读 alias → 观察一周期 → move 并删除 alias。任何一步失败都停在“双端可读”，不进入下一步。

禁止事项：不得用 `cp -r` 覆盖目标同名文件；目标端已存在同名但内容不同时不得静默取其一（去重必须人工裁决并留回执）；不得把 alias 当长期身份修复（§2.4 已定）；不得让两个根同时可写。

#### 2.4.2 append-only 流的连续性、校验与回滚（P0）

`lanes.jsonl` / `lane_events.jsonl` 等文件是 lane 账本与运行审计的真值，迁移只能是“追加”，不能“重写”。

- 连续性：合并后 `lane_id` 首次出现顺序单调、`version` 逐条 +1 无跳号、`ts` 非递减；`lane_events.jsonl` 的 `event` 与 `lanes.jsonl` 的状态可对账（每条 lane 的最终 `version` 等于其事件条数）。
- 完整性：逐行 JSON 解析成功；末行必须带换行（半行=截断，fail-closed）；行数与 sha256 写入迁移回执；写入前后各取一次 `stat` 的 size/mtime，出现并发变化立即中止。
- 合并方式：目标端已有内容时只做追加；追加前记录 fork point（源端最后一行的 sha256 + 行号），追加段整体带 `migration_id`；不删除目标端任何历史行。
- 未知 schema：单行出现未知附加字段可前向兼容；出现未知 `schema_version`、缺 `lane_id`/`ts` 等必需字段、或结构无法归一时整批 fail-closed——保持双端原状并转人工裁决，不猜测、不补齐、不覆盖。
- 回滚：回滚=截断 fork point 之后的新增段（保留历史前缀）并重建索引；禁止用备份整文件覆盖目标端（会丢掉 fork 后目标端产生的行）。
- 双写窗口：迁移完成前若必须双端写入，只允许一端权威，另一端以只读 alias 暴露；出现双写即判定迁移失败。

### 2.5 沙盒授权并非一条权限链

已核实源码：

- core/write_scope.py 提供 Agent 写侧声明与路径判定；当前生效范围本身是 core/run_context.py 的 ContextVar `current_write_scope`（`edit_file`、`verify_path_scope` 均从此处读取；源码位置已核：`src/llm_loop/core/run_context.py`，不在 `core/write_scope.py`）。
- execute_command 的 _write_scope_command_gate() 对受限会话做命令写侧静态检查。
- edit_file 使用 workspace scope 和当前 write-scope。
- verify_path_scope 是只读审计视图，不能自动获得子进程的全部执行态。
- Linux bwrap 当前只挂载系统只读目录、/dev、/proc、/tmp 和当前 workdir；workdir 是可写根。
- 当前 bwrap 未使用 --unshare-net，网络与宿主共享。
- Docker 后端为 --network=none、rootfs 只读、工作区 RW bind，与 bwrap 能力并不等价。
- sandbox_argv 的 writable_roots 追加根只被 macOS sandbox-exec 消费；bwrap / Docker 当前明确忽略该参数。
- Linux auto 探测主要检查 bwrap 是否在 PATH，不足以证明当前用户可以建立所需 namespace / mount。
- EscalationStore 解除的是 LFL 内部 CatastrophicGuard 特定命令阻断；它不会自动增加 bwrap bind mount、改变 workspace scope、改变 UID 或授予 root。

结论：右侧提权栏显示“已批准”，不能等同于宿主路径已挂载或文件工具已获得权限。必须增加 Host Capability Grant 并贯通工具执行和 OS sandbox。

---

## 3. 目标架构与身份

### 3.1 统一架构

~~~text
LFL Web / CLI
  |
  +-- Deployment Control
  |     +-- SourceCheckoutBackend -> existing restart_mirror
  |     +-- WheelReleaseBackend -> supervisor -> systemd --user
  |
  +-- Upgrade Transaction
  |     +-- source / digest / trust
  |     +-- staging release + candidate smoke
  |     +-- snapshot + idle barrier
  |     +-- atomic version pointer
  |     +-- service health + rollback
  |
  +-- Host Capability Authorization
        +-- workspace / write-scope
        +-- HostCapabilityGrant
        +-- bwrap RO/RW mount plan
        +-- file-tool enforcement
        +-- separate polkit admin helper
~~~

### 3.2 双部署身份

建议 deployment schema v2，并显式声明 artifact_kind。

Source checkout 身份：

~~~json
{
  "schema": "lfl.managed-service-deployment/v2",
  "artifact_kind": "source_checkout",
  "deployment_id": "stable-id",
  "generation": 7,
  "git_head": "exact-40-char-sha",
  "code_root": "/absolute/source/root",
  "runtime_root": "/absolute/runtime/root",
  "data_dir": "/absolute/data/root",
  "webui_artifact_sha256": "sha256"
}
~~~

Wheel release 身份：

~~~json
{
  "schema": "lfl.managed-service-deployment/v2",
  "artifact_kind": "wheel_release",
  "deployment_id": "stable-id",
  "generation": 8,
  "version": "0.6.40",
  "wheel_sha256": "sha256",
  "release_dir": "/absolute/LFL_HOME/releases/LFL-0.6.40",
  "runtime_root": "/absolute/LFL_HOME",
  "data_dir": "/absolute/data/root",
  "webui_artifact_sha256": "sha256"
}
~~~

规则：

- source 必须提供真实 git_head / code_root。
- wheel 必须提供真实 version / wheel_sha256 / release_dir / package manifest identity。
- wheel 不伪造 git_head。
- 两种身份都包含 deployment_id、generation、data_dir 和 WebUI artifact SHA。
- status 同时核对 desired、真实进程、unit、manifest 和 artifact identity。
- manifest 缺失、进程身份不一致或数据根冲突时显示“需核验”，不报绿色。

### 3.3 Wheel supervisor

新增随 wheel 打包的轻量 supervisor，例如 llm_loop.runtime.linux_supervisor。

固定职责：

- 验证 LFL_HOME、活动指针、release 目录、wheel SHA 和安装 manifest。
- 仅查询和控制 LFL 自己的 systemd user units。
- 读取三服务 manifest、健康端点和 upgrade journal。
- 执行事务状态推进、崩溃恢复和脱敏审计。
- 提供 status / restart / upgrade / rollback 的固定参数入口。

不得提供任意 shell、任意 systemctl 参数、任意 PID kill、任意路径删除或 root command。

Supervisor 由旧活动 release 启动并在 cutover 期间保持运行；旧 release 在事务 settled 前不可清理，避免升级替换了正在执行的控制面代码。

#### 3.3.1 post-commit 交接（P1）

commit 之后控制面自己也要换代码。不显式设计会出现两种故障：新版本已 active、控制面仍是旧进程；或两个 supervisor 同时写同一份 journal。

1. 旧 supervisor 保持运行，直到新 release 的 supervisor 通过 `--self-check` 并回报 `ready(generation=N+1)`。
2. 单实例由 `LFL_HOME/upgrade-transactions/supervisor.lock`（0600 + flock）保证；拿不到锁的新实例直接退出并回报 `supervisor_conflict`，不改任何状态。
3. 交接顺序：新实例 ready → 旧实例停止接受新请求（drain）→ 旧实例把 `active_generation` 交给新实例（CAS `expected_generation=N`）→ 旧实例退出。CAS 失败即中止交接，旧实例继续服务。
4. 交接期间 status / restart 返回 `handover_in_progress`，不排队、不猜测哪个实例是权威。
5. 新实例在 `settle_window`（候选 60s，待实机实测）内崩溃或未回报健康：active pointer 回切旧 release，旧 supervisor 继续服务，事务置 `rollback_pending`，不标 committed。
6. 旧 release 的清理晚于“新 supervisor 稳定运行 + 一次完整 status 对账”，由独立清理动作完成，不挂在交接路径上。
7. 交接回执记录：old_generation、new_generation、CAS 结果、settle 窗口内健康样本、最终权威实例 PID 与 start_time。

---

## 4. 三服务 systemd 管理

### 4.1 单元布局

保留 lfl.service 作为 Web 兼容单元名，新增：

- lfl-feishu.service
- lfl-learning.service

三个单元均由安装器生成和校验，均使用用户级 systemd，不需要 sudo。ExecStart 指向稳定启动器，而不是写死某个版本目录。

建议 Web 单元核心配置：

~~~ini
[Unit]
Description=LFL Web service
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory=%h/.local/share/lfl
Environment=LFL_HOME=%h/.local/share/lfl
Environment=DATA_DIR=%h/.local/share/lfl/data
Environment=LFL_DATA_DIR=%h/.local/share/lfl/data
Environment=LFL_ENV_FILE=%h/.local/share/lfl/.env
Environment=PYTHONUNBUFFERED=1
ExecStart=%h/.local/share/lfl/bin/lfl-service web
Restart=always
RestartSec=5s
KillMode=control-group
KillSignal=SIGTERM
TimeoutStopSec=45s

[Install]
WantedBy=default.target
~~~

Feishu / Learning 使用相同的 LFL_HOME、DATA_DIR、LFL_ENV_FILE 和 release identity，仅 service 参数不同。45s 是待实测的设计候选值，不是未经验证的最终常数。

unit 模板与自定义安装根（P2）：上面的 `%h/.local/share/lfl` 是默认安装根的展开值，不是可写死的常量。安装器按解析后的 `LFL_HOME` 生成 unit：

- `LFL_HOME` 等于默认值时才可用 `%h/...`；自定义根必须写绝对路径，并与 `WorkingDirectory`、`Environment=LFL_HOME=` 三处保持一致。
- 生成前校验：绝对路径、不含 `..`、不含空格与控制字符、不是 symlink、不落在 `/`、`/usr`、`/etc`、`/var`、`/home` 这类系统目录的裸路径上；不满足即拒绝安装，不“自动修正”。
- unit 内不出现 `~`、不出现拼接版本号的目录；版本只由 `.LFL-active-version` 决定（§4.2）。
- 生成后用 `systemd-analyze --user verify` 校验，并把 unit 文本 sha256 写入安装回执；重装时若 unit 内容变化，先 `daemon-reload` 再 `try-restart`，不整机重启。

重要规则：

- 保留 Restart=always。已实测 Restart=on-failure 不覆盖某些 SIGTERM 后以 exit 0 退出的优雅关闭超时场景；always 可以覆盖。显式 systemctl stop 仍是有意停止，不会被立即拉起。
- StartLimit 防止坏配置快速无限重启；达到限制后必须留下可诊断原因，不自动 reset-failed 掩盖根因。限流后 unit 进入 `failed`，诊断路径固定为两级：`systemctl --user status <unit>` 给 systemd 原始状态与最近日志；`lfl doctor --json` 输出 `unit_state / result / n_restarts / start_limit_hit / last_exit_code / journal_tail(脱敏) / next_action`。面板显示“已限流（需人工介入）”，不显示“已停止”或绿色。`reset-failed` 只作为显式人工动作，且在存在未完成 upgrade journal 时拒绝执行。
- Web 离线也应能启动；网络依赖由 Feishu / Provider 自行重连，不作为 Web 启动硬前置。
- 三单元均 WantedBy=default.target；Linger=yes 时用户注销后仍可由 user manager 拉起。
- 只操作 LFL 自己的 unit；不重启整个 user manager，不影响 DDE、Lark、Docker 等无关服务。

### 4.2 稳定启动器

安装器维护 LFL_HOME/bin/lfl-service。

启动器：

1. 验证 LFL_HOME 和活动指针，拒绝 symlink escape。
2. 验证目标 release 存在、无 .installer-incomplete、wheel SHA / manifest 一致。
3. 按 service 参数启动当前 release：
   - web：venv/bin/lfl start
   - feishu：venv/bin/python -m llm_loop.runtime.launch feishu
   - learning：venv/bin/python -m llm_loop.runtime.launch learning
4. 使用 exec 保留 systemd MainPID / cgroup 语义。
5. 输出不含密钥的 release identity。

systemd 不再固定引用 LFL-0.6.40 目录；版本只由 .LFL-active-version 一个权威指针决定。禁止同时引入第二个 current symlink 作为版本真值。

### 4.3 忙闲准入

每服务至少暴露 unit 状态、MainPID、NRestarts、cgroup 内进程、manifest、deployment identity 和业务健康状态。

| 状态 | 处理 |
|---|---|
| confirmed_idle | 可进入受控重启 |
| confirmed_busy | 等待、排队或延期，不强杀 |
| unconfirmable | fail-closed，不当作 idle |
| stale_manifest / pid mismatch | 先核验真实进程身份 |
| port conflict | 定位精确占用者，不杀无关进程 |

保留 Run lease、detached worker、generation CAS 和 admission barrier。重启不能在请求它的 Run 尚未结束时强行杀 Web；Learning inflight、Feishu 未完成消息和队列任务按业务 idle 规则等待。all 的目标范围沿用现有定义，不擅自把 WeCom 加入全量重启。

### 4.4 开机恢复和自愈验收

区分六项独立能力：

1. 开机自启：units enabled + Linger=yes。
2. 崩溃恢复：SIGKILL 后 MainPID 更换、NRestarts 增加、health 恢复。
3. 干净退出恢复：SIGTERM 后进程退出 0，systemd 仍拉起新实例。
4. 维护性停止：systemctl stop 不被 Restart=always 立即拉起。
5. 启动失败限流：坏配置 / 端口冲突触发有限重试和明确错误。
6. 整机 reboot：真实重启后三个 unit 均 active，版本、manifest 和业务健康一致。

建议增加一次性 lfl-recovery.service，在业务单元启动前检查未完成 upgrade journal：

- 无未完成事务：正常放行。
- pointer 未切换：继续旧版本。
- pointer 已切换但未 settled：先验证候选；失败则按 journal 原子恢复旧 pointer。
- 无法判断数据兼容或恢复安全：保持维护状态，不猜测。
- 三服务恢复由单一 recovery coordinator 串行处理，不让三个 ExecStartPre 竞争同一 journal。

`lfl-recovery.service` 的单元语义（P2）：不能写成“每个业务单元各自 ExecStartPre 里跑一段脚本”，否则三个单元会竞争同一份 journal，也无法保证 fail-closed。

- `Type=oneshot` + `RemainAfterExit=yes` + `Restart=no`；`Before=lfl.service lfl-feishu.service lfl-learning.service`，三个业务单元以 `Wants=` + `After=lfl-recovery.service` 引用，形成单点串行。
- fail-closed：recovery 未成功（failed / 超时 / 被 stop / 标记缺失）时业务单元不得启动。业务单元前置检查 `$LFL_HOME/state/recovery-ok`（默认根展开为 `%h/.local/share/lfl/state/recovery-ok`，自定义安装根时按 §4.1 写绝对路径；或等价 launcher 前置判定），标记缺失即退出非零并停在 failed，原因写 `recovery_incomplete`；不自动重试、不自动 reset-failed。
- 只有 recovery 判定“可放行”才写 `recovery-ok`（含 `journal_id`、`decision`、`ts`、判定摘要）；每次新事务推进前先删除该标记，避免旧标记放行新事务。
- 超时用 `TimeoutStartSec`（候选 120s，待实测）；超时按 fail-closed 处理，不当作“没有未完成事务”。
- recovery 自身日志同时进 journal 与 `data/audit/` 审计流，两边以 `journal_id` 对账。

---

## 5. 受控自动升级

### 5.1 先 staging，后停机

升级顺序必须是：

候选解析 -> 来源/摘要校验 -> staging venv -> 候选 smoke -> 数据快照 -> 服务 idle -> 停服务 -> 原子切换 -> 启动三服务 -> 身份/健康验收 -> commit。

候选下载、uv / pip 安装、check-install、doctor 和 smoke 不能发生在服务停止之后。

### 5.2 候选来源与 GitHub 解耦

升级来源按优先级可配置：

1. 官方 GitHub Release API / assets。
2. 已配置的可信镜像或内部 artifact cache。
3. 已缓存的、此前已验证来源身份的 wheel。
4. 用户明确提供的本地候选 wheel。

共同约束：

- 候选来源必须映射到可信发布身份和精确版本。
- SHA-256 必须匹配官方发布清单或受信签名回执。
- 本地 wheel 不能仅凭用户路径或模型建议就获得生产资格。
- 网络探测按 API、下载、uv index、pip index 分别进行，不能假设 Git 代理配置会被其他工具继承。
- 下载超时或索引不可达时，在 staging 前失败；旧服务保持运行。
- 服务 restart、旧 release rollback、开机 recovery 和 status 完全本地化，不访问 GitHub。
- 断网时允许从已验证旧 release 恢复，不允许从未知来源自动安装。

### 5.3 可信性与候选预检

至少校验：

- 发布来源身份、Release tag 和版本。
- wheel SHA-256 和 wheel metadata Name / Version。
- wheel 内资源 manifest、规则、方法、技能和 WebUI 资产。
- 发布 provenance / 签名或受信发布回执。
- 独立 GLM-5.3 Reviewer PASS、P0/P1=0 和原版完整 R9 PASS（按项目当前发行治理规则）。
- WebUI artifact SHA 与 release identity 一致。
- 数据 schema 兼容性和回滚路径。

SHA 只证明字节完整性；来源未知时状态必须为 trust_unknown。

#### 5.3.1 信任锚：指纹、轮换与离线校验（P1）

- 存储：`LFL_HOME/trust/anchors.json`，目录 0700、文件 0600，`O_NOFOLLOW` 打开，`fstat` 校验 `st_uid == getuid()` 且非 group/world 可写。内容为公钥集合：`key_id / algorithm(ed25519) / public_key_b64 / fingerprint_sha256 / not_before / not_after / status(active|retired|revoked)`。起始锚由安装器写入，运行期只读。
- 指纹核对：既比 `key_id` 也比 `fingerprint_sha256`，任一不匹配即 `trust_unknown`；禁止“新清单自带新公钥”的自举更新。
- 轮换：新公钥必须由当前 active 键签名的 `rotation` 记录引入，`not_before` 晚于签发时间；旧键转 `retired` 并保留验签能力至少一个发布周期；`revoked` 立即失效，使用它的清单一律 fail-closed。轮换需独立人工确认（本机 TTY 或已认证 Web 会话），不做无人值守自动轮换。
- 离线清单校验算法（纯本地，无网络）：
  1. 读 `manifest.json`，`schema` 必须已知；未知 schema → `trust_unknown`，不尝试兼容解析。
  2. 按 `key_id` 在 anchors 中取 `active` 且时间窗有效的公钥；找不到 → `trust_unknown`。
  3. 对清单规范化字节（`canonical_json`：键排序、UTF-8、无浮点、末尾无换行）验签 `sig`；失败 → `signature_invalid`。
  4. `key_id` 与 `fingerprint_sha256` 双匹配；`generation` 严格递增且 `version` 不低于本地已知最大版本（防重放与降级）。
  5. `wheel_sha256` 等于候选 wheel 实际摘要；`version` 与 wheel metadata 的 Name / Version 一致。
  6. `expires_at` 未过期；过期清单只允许拒绝，不允许“忽略过期继续”。
  7. 全通过才置 `trust_verified`，校验输入与输出摘要写入 transaction journal；任一步失败按对应 reason 落账并停在 staging 之前。
- 镜像回执字段：受信镜像必须签名返回 `mirror_id / artifact_sha256 / manifest_digest / version / signed_at / expires_at / key_id / sig`。镜像与官方清单冲突时取更严格的失败（两者都通过才放行）；镜像只是传输通道，不能成为信任根。

### 5.4 Staging 和 smoke

- 新 release 独立目录和独立 venv。
- 旧服务保持运行。
- 设置明确 connect / read / total timeout 和有限重试。
- pip check、check-install、doctor --json、资源可检索性、Python import、WebUI SHA 均通过。
- 使用隔离 DATA_DIR 和虚构凭证做最小启动 smoke；不连接真实 Provider、不写生产数据。
- staging 失败保留 .installer-incomplete，绝不设为 active。
- 已存在 release 不允许不同字节覆盖。

### 5.5 数据快照

复用现有 lfl backup / backup verify，补足真实写入者和 schema 资格：

- 数据根本身怎么处置（迁移/合并/回滚）不在快照里决定，见 §2.4.1 与 §2.4.2；快照只负责 selected_roots 的一致副本。
- 从统一 RuntimePaths、dotenv 和 service config 解析 config / data / experiences / methods 根。
- SQLite 使用 SQLite backup API 或受控 checkpoint，不在 WAL 写入中直接复制主文件。
- JSONL 必须确认 writer 退出并检查文件稳定。
- manifest 记录 coverage、source consistency、版本、schema 和文件 SHA。
- selected_roots 只能表示选定根已完整备份，不能标为 full system backup。
- 备份目录 0700、文件 0600；不输出 .env 明文。
- schema compatibility unknown 时禁止无人值守切换。

### 5.6 事务状态机

~~~text
S0 observed
 -> S1 candidate_resolved
 -> S2 source_and_digest_verified
 -> S3 staged_release_built
 -> S4 candidate_smoke_passed
 -> S5 snapshot_verified
 -> S6 services_confirmed_idle
 -> S7 services_stopped
 -> S8 active_pointer_switched
 -> S9 services_started
 -> S10 health_and_identity_verified
 -> S11 committed
~~~

任一失败进入 aborted_before_cutover 或 rollback_pending，不能将中间状态报告为成功。

### 5.7 journal 与恢复

每个事务持久化到 LFL_HOME/upgrade-transactions/TRANSACTION_ID/journal.json。

字段至少包括：

- schema、transaction_id、idempotency_key。
- old_version、candidate_version、wheel_sha256。
- expected_generation、target_generation。
- source_trust_receipt_id、reviewer_receipt_id、r9_receipt_id。
- snapshot_id、snapshot_coverage、schema_before / schema_after。
- affected_services、stop_receipts、start_receipts。
- state、failure_reason、各步骤时间和操作者 / 自动策略 ID。

要求：

- 目录 0700、journal 0600；原子写入并 fsync。
- 每次状态推进采用事务锁和 expected-state CAS。
- 同一事务重复调用幂等；不允许并行第二个活动升级。
- prepare 只创建隔离候选和事务回执，不改 active pointer。
- commit 必须携带真实事务回执、expected generation 和切换授权。
- abort 只清理本事务可证明属于自己的 staging，不删除备份或生产数据。
- supervisor 崩溃后由 recovery unit 根据 journal 验证候选或恢复旧 pointer。
- 无法证明恢复安全时保持维护状态，不静默重启到未知版本。

### 5.8 原子切换、启动和回滚

- 重新校验 active version / generation，防止过期事务覆盖新 desired。
- 先记录 previous version，再原子写 active pointer；沿用现有临时文件、fsync、replace、目录 fsync。
- 旧 release 在新版本全部验收前不得清理。
- 三服务分别启动、分别验收：unit active、PID、cgroup、manifest、release SHA、DATA_DIR、config identity、业务健康。
- Web health / API / WebUI 静态资源通过。
- Feishu heartbeat connected，或给出可解释的网络降级状态。
- Learning manifest healthy，队列可读。
- 任一服务失败不得报告全量升级成功。

失败策略：

| 故障 | 处理 |
|---|---|
| 来源 / SHA / metadata 失败 | 拒绝候选，旧服务不动 |
| venv / pip / check-install 失败 | staging 失败，旧服务不动 |
| snapshot 不完整 / schema 未知 | 不停机、不切换 |
| 服务 busy / unconfirmable | 延期或阻断 |
| stop 失败 | 保持旧 pointer，恢复已停止服务 |
| pointer 写入失败 | 原子恢复旧 pointer |
| 新 Web health 失败 | 旧 pointer 回切并恢复 Web |
| Feishu / Learning 启动失败 | 回滚全事务或进入明确 partial-maintenance，不报成功 |
| 数据迁移不可逆 / schema 未知 | 不覆盖生产数据，进入人工恢复 |

代码 pointer rollback 与数据 schema rollback 是两件事。恢复数据必须先 verify，再恢复到隔离目录；生产 DATA_DIR 切换需单独批准。

### 5.9 无人值守策略

| 模式 | 默认 | 行为 |
|---|---|---|
| notify_only | 否 | 只提示新版本 |
| stage_auto | **是** | 自动下载、校验、staging、候选 smoke，不切换 |
| maintenance_window_auto | 否 | 显式启用后，在维护窗口满足所有资格才切换 |

maintenance_window_auto 必须同时满足：

- 官方稳定发布，来源可验证。
- 独立 Reviewer PASS，P0/P1=0，原版 R9 PASS。
- wheel / WebUI SHA 与发布身份一致。
- 数据 schema 兼容，snapshot verify 通过。
- 三服务均 confirmed_idle。
- 网络和候选 smoke 已完成。
- 无活动 upgrade transaction、无手工 desired 变更、无 service-control barrier。
- 在用户明确设置的维护窗口。
- 上一 known-good release 仍在且可运行。
- 自动切换后逐服务健康验收通过。

任何资格未知都视为不满足。默认不自动执行跨 schema 迁移、不自动升级系统包、不自动重启整台 Linux 主机。

---

## 6. 沙盒授权与宿主能力

### 6.1 四层权限分离

| 层 | 负责 | 不代表 |
|---|---|---|
| Tool Capability | 当前 Agent 能否调用 read_file / edit_file / execute_command / browser | 不代表能访问任意宿主路径 |
| Workspace / WriteScope | 当前 Run / 子代理允许写哪些工作区路径 | 不代表 bwrap 已挂载外部目录 |
| OS Sandbox | bwrap / Docker 的实际挂载、网络、socket 能力 | 不代表 root |
| OS Admin | polkit / pkexec 对固定系统管理动作授权 | 不代表任意 root shell |

四层必须在同一工具执行回执中分别呈现。UI 的“已批准”、write-scope allowed、bwrap mounted 和 OS operation succeeded 不能合并成一个状态。

### 6.2 新增 HostCapabilityGrant

新增独立的 HostCapabilityGrant，不复用 EscalationStore 的 catastrophic-command token。

建议 schema：

~~~json
{
  "schema": "lfl.host-capability-grant/v1",
  "grant_id": "opaque-id",
  "requester_session_id": "session-id",
  "agent_id": "agent-id",
  "tool_name": "read_file",
  "resource_type": "filesystem",
  "canonical_path": "/absolute/approved/path",
  "operation": "read",
  "recursive": false,
  "max_uses": 1,
  "expires_at": "timestamp",
  "policy_hash": "sha256",
  "approver_identity": "authenticated-local-user",
  "status": "approved"
}
~~~

能力类型：

- filesystem.read：精确文件 / 指定目录只读。
- filesystem.write：指定文件或目录读写。
- filesystem.create：指定父目录下创建文件。
- filesystem.delete：单独高风险能力，默认不包含在 write grant。
- network.connect：指定网络能力或代理模式。
- user_service.manage：仅管理 LFL 自己的 systemd user units。
- browser / desktop：继续使用 Browser / Computer Use 独立权限。
- system_admin：仅由受信本机 helper + polkit 管理。

#### 6.2.1 grant store：持久化、审计与并发（P1）

grant 必须能被重启后的进程继续执行或撤销，且不能被同机其他用户伪造或替换。

- 布局：`LFL_HOME/grants/<grant_id>.json`（单条一文件，便于原子写与按需撤销）；索引 `LFL_HOME/grants/index.jsonl` 为 append-only 摘要流。目录 0700、文件 0600。
- 打开与归属校验：读写一律 `O_NOFOLLOW`；`fstat` 核对 `st_uid == os.getuid()`、非 group/world 可读写、非链接、非设备文件。任一不满足 → `grant_store_insecure`，直接拒绝该 grant，不“顺手修权限后继续”。
- 写入：临时文件（同目录、0600）→ fsync → `rename` → 目录 fsync。`max_uses` 的消费用 `flock` + 写前重读比对 `version`（CAS），避免两个进程各消费一次。
- 审计：`LFL_HOME/grants/audit.jsonl` append-only，字段 `grant_id / event(issue|consume|deny|expire|revoke|error) / tool / canonical_path / operation / session_id / agent_id / ts / reason / prev_hash`；`prev_hash` 串成哈希链，链断即判定审计不可信，停止签发新 grant 并报 `audit_chain_broken`。
- 多进程与重启：授权以磁盘为准，内存只做缓存；进程重启后按 `grant_id` 重新加载并复核 canonical path（路径可能已被替换）。同一 grant 被两个进程并发消费时，后到者失败并写 `deny(consumed)`。
- 过期与清理：`expires_at` 由读取方判定，不依赖清理定时器；清理只删除已终态记录，不删审计行。时钟回拨时不延长有效期（取 `max(wall_clock, last_seen)`）。
- 撤销：写 `revoked` 并删除对应 grant 文件；每次工具判定都重读磁盘，撤销应在两次工具调用内生效。

### 6.3 授权规则

1. 默认 one-shot；session grant 必须显式选择 TTL。
2. 绑定 canonical path、操作类型、递归范围、工具和会话。
3. 拒绝空路径、..、任意 glob、通配 Home 和 symlink escape。
4. 目录授权不自动覆盖目录外 symlink target。
5. read / write / create / delete 分开授权。
6. 子代理只继承父 grant 的明确子集，不自动获得全量 host grant。
7. 拒绝、过期、撤销、消费都写审计。
8. 授权记录不保存管理员密码、API key、订阅链接或文件内容。
9. Host grant 不能突破父会话 write-scope；外部路径授权是独立 OS capability，不是悄悄扩大 workspace。
10. CatastrophicGuard、write-scope、HostCapabilityGrant 和 OS sandbox 均继续执行；一个层批准不能跳过另一层。

### 6.4 审批 UI

沿用 Web 右侧提权栏，但显示真实能力对象：

- requester session / Run / Agent / Tool。
- 目标路径或网络目标。
- 申请操作：读、写、创建、删除、联网、服务管理。
- 是否递归和影响范围。
- 当前为何被沙盒阻断。
- TTL、最大使用次数和是否一次性。
- 授权后改变哪一层能力、哪些层仍阻断。

默认选项是“仅本次操作”。支持“当前会话限定路径授权”“拒绝并说明原因”“撤销未消费 grant”。不提供永久开放整个 Home、关闭全部沙盒或任意 sudo 按钮。

### 6.5 bwrap mount plan

Linux bwrap 从默认仅 workdir 可写演进为显式 mount plan：

- system directories：RO。
- 当前 workdir：按现有工作区规则 RW。
- 已批准外部目录：按 grant 显式 RO 或 RW bind。
- 已批准单文件：只绑定该文件，不开放父目录全部内容。
- /run/user/UID/bus、SSH agent、Docker socket、浏览器 profile、Keyring 不默认挂载。
- .ssh、.gnupg、浏览器 Cookies / Profile、系统凭据目录必须单次严格授权或专用受控工具。
- bind 前后核验真实路径，拒绝 symlink escape、设备文件和不支持文件类型。

关键实现要求：

- 不把 write-scope glob 直接转换成 bwrap subpath；glob 和 mount prefix 语义不同，转换可能扩大权限。
- 只将获批 canonical root 编译为明确 bind mount；write-scope 继续作为独立逻辑约束。
- 当前 writable_roots 对 bwrap / Docker 不生效，必须补齐后端参数和回执，不能静默忽略。
- bwrap auto 探测从 PATH 检查升级为有时限的真实 canary：验证 namespace、RO/RW bind、执行和清理。记录时间和 backend capability fingerprint。
- EXEC_SANDBOX=none 不作为权限修复；它没有 OS sandbox，不能宣称已隔离。
- Docker 作为显式选择的隔离后端；其 --network=none 和只挂工作区能力不能冒充 bwrap，Docker daemon 也是额外信任边界。

### 6.6 网络能力

当前 bwrap 未隔离网络；Docker 后端断网。不能从“沙盒开启”推断网络可用或不可用。

| 模式 | 语义 |
|---|---|
| shared | 复用宿主网络；当前 bwrap 行为 |
| none | 网络 namespace / Docker 断网 |
| proxy | 只允许指定代理出口 |

升级器网络 profile 独立于业务服务：

- GitHub / Release API / wheel 下载代理单独配置。
- uv / pip index 分别探测，不假设 uv 读取 pip.conf。
- NO_PROXY 包含 localhost / loopback 和 LFL 本地服务。
- 订阅拉取使用服务商要求的直连策略。
- Clash Party 未启动或代理端口不可达时，updater 在停服务前失败。
- 代理 URL、认证信息和订阅参数不进入 stdout、receipt 或模型上下文。

### 6.7 系统管理员权限

普通 LFL 运维使用 systemd --user，不需要 sudo。安装系统包、修改 /etc、配置 TUN / 路由 / 防火墙、系统用户和系统级服务等属于 OS Admin，不属于普通 HostCapabilityGrant。

确需系统级操作时，使用固定、可核验的本机 helper + polkit / pkexec。helper 只允许固定动作和参数 schema，不接受 arbitrary command、任意路径或通用 root shell。管理员密码不得经过 LFL Web、HTTP、模型或工具参数。

### 6.8 统一错误回执

| reason | 含义 | 建议 |
|---|---|---|
| workspace_scope_denied | 不在当前工作区 | 切换工作区或申请外部路径 |
| write_scope_denied | 当前 Run 写域不允许 | 缩小范围或请求父会话授权 |
| host_capability_required | OS sandbox 未获路径 / 网络能力 | 显示精确授权卡 |
| grant_expired | 授权过期 | 重新申请 |
| grant_scope_mismatch | 工具 / 路径与 grant 不匹配 | 不重放旧 token |
| sandbox_backend_unavailable | bwrap / Docker 不可用 | 显示实际探测原因 |
| sandbox_mount_denied | namespace / mount 被拒绝 | 显示路径与 mount 类型 |
| catastrophic_command_denied | 高危命令 guard 阻断 | 走原有危险命令审批 |
| os_permission_denied | Linux UID / ACL 拒绝 | 说明不是 LFL grant 能解决 |
| system_privilege_required | 需要管理员动作 | 使用本机 polkit helper |

---

## 7. 实施阶段

### Stage 0：只读基线冻结

- 固定源码 commit、wheel SHA、活动版本。
- 基线重冻结（P1）：以当前 main 重跑冻结，不用“main 最新”这类相对描述。本版修订时 main = origin/main = `ee475a3526ae`（2026-11-07 13:44 复核）；相对本设计初稿基线 `9242dc74cbd4`（v0.6.40 发行面）漂移 3 个提交：`52f123650` fix(review)、`1b738c432` docs(verification)、`ee475a352` docs(governance)。
- 漂移对账：baseline receipt 必须逐条列出 §1、§2、§3.2、§11 引用的文件路径与行号，并标注“未变 / 已变 / 已消失”；任何影响设计结论的漂移先改设计再施工，不允许“施工时按现状顺手改”。
- receipt 中每个关键文件带 `sha256`，并记录冻结时的 `git status` 是否干净；不干净则先说明未跟踪/已修改文件是否影响结论。
- 记录三服务 PID / cwd / executable / cgroup / manifest。
- 读取 systemd units、Linger、Restart、NRestarts。
- 脱敏核验 .env、runtime.toml、DATA_DIR 和 manifest 来源。
- 执行 bwrap / Docker canary，不改沙盒配置。
- 输出 service identity mismatch 和 data/config split 清单。
- 输出数据根盘点（§2.4.1 的输入）：两个 data 根各自的内容根、文件数、总大小、append-only 流清单与末行 sha256。

交付：host baseline receipt（含 re-freeze 的 commit、关键文件 sha256 清单、漂移对账表、数据根盘点）。不停服务、不改生产数据。

### Stage 1：三服务 systemd 统一

- 安装器增加 stable lfl-service launcher。
- 增加 lfl-feishu.service、lfl-learning.service。
- 统一三服务 DATA_DIR、LFL_HOME、LFL_ENV_FILE 和 release identity。
- 保留 lfl.service 名称。
- 逐服务迁移：验证 unit -> 精确停止旧进程 -> 启动新 unit -> 核验后再动下一个。
- 不 pkill，不重启无关服务。
- 按 §2.4.1 处置数据根：先冻结写入，再 copy+verify，再切 `DATA_DIR`，再只读 alias，观察一周期后才 move；append-only 流按 §2.4.2 只追加合并。

验收：三服务均由 user systemd 管理，PID / cgroup / manifest / version 一致；且完成 §2.4.1/§2.4.2 的迁移一致性核验——迁移回执逐项列明策略、文件数与行数、sha256 清单、每个 append-only 流的 fork point 与连续性对账（version 无跳号、事件条数可对账）、未知 schema 零覆盖、双端无同时可写、alias 未长期化。

### Stage 2：wheel service_control backend

- deployment schema v2 增加 artifact_kind。
- source backend 保留原逻辑。
- wheel backend 使用 detached supervisor + systemd user units。
- desired / live / manifest 使用一致 deployment identity。
- DATA_DIR 统一，取消长期依赖 manifest 软链接（数据根处置与迁移回执按 §2.4.1 / §2.4.2 执行）。

验收：Deepin wheel 下 status 可识别三服务；单服务 restart 有真实 action receipt；不伪造 git_head。

### Stage 3：事务升级和回滚

- 增加 prepare / verify-stage / commit / abort / recover。
- staging 完全在旧服务运行时完成。
- cutover 前由权威控制面证明服务 idle 和 writer 已停。
- 接入 backup verify、schema compatibility、journal、active pointer CAS。
- 逐服务启动和健康验收；失败按事务状态回滚。
- 实现 §3.3.1 的 supervisor post-commit 交接：单实例锁、ready→drain→CAS 交接、settle 窗口内失败回切旧 supervisor。

验收：候选 wheel 旁路安装、完整升级、故障注入、断电恢复和旧版本回滚；交接路径覆盖“新 supervisor ready 后崩溃”“CAS 失败”“交接期间 status 请求”三个用例，且任一时刻只有一个 supervisor 写 journal。

### Stage 4：HostCapabilityGrant

- 先统一错误分类和只读观测。
- 再实现 one-shot grant store 与审批 UI。
- 先接外部路径 RO，再接限定 RW bind。
- 最后扩展网络 / user-service / host integration capability。
- read_file / edit_file / search_files / execute_command 统一接入判定。
- Browser / Computer Use 保持独立 connector 权限。
- 完成 symlink / traversal / TOCTOU / child-agent / revoke 测试。
- 按 §6.2.1 实现磁盘持久化：单条一文件 + append-only 索引 + 哈希链审计 + `O_NOFOLLOW`/属主/权限校验 + 多进程 CAS 消费。

验收：授权前拒绝，批准后仅精确能力生效，授权外路径仍拒绝，过期和撤销立即生效；重启后 grant 仍可执行且可撤销；两个进程并发消费同一 grant 只有一个成功；伪造文件（他人所有 / 0777 / symlink）被判 `grant_store_insecure` 而不是被修复后放行。

### Stage 5：可选无人值守升级

- 默认 stage_auto。
- 显式启用 maintenance_window_auto 后才可切换。
- 每次自动升级保存完整 transaction receipt。
- 失败自动恢复旧代码指针；数据可逆性未知时进入维护状态并通知用户。

---

## 8. 验收矩阵

### 8.1 升级

| 场景 | 期望 |
|---|---|
| GitHub / 镜像 / uv index 不可达 | staging 失败，旧服务继续运行 |
| 本机服务 restart / rollback 期间断网 | 本机动作照常完成 |
| wheel SHA / metadata 错误 | 拒绝候选，不激活 |
| venv / pip 安装中断 | incomplete 标记保留，旧服务可用 |
| candidate smoke 失败 | 不切 active pointer |
| 服务 busy / unconfirmable | 不停服务、不切换 |
| DATA_DIR 与 LFL_DATA_DIR 冲突 | preflight 阻断 |
| selected_roots 备份 | 不显示 full backup |
| schema compatibility unknown | 禁止无人值守切换 |
| pointer 写入中断 | journal 恢复旧状态 |
| 新 Web health 失败 | 回切旧 pointer 并恢复 Web |
| Feishu / Learning 启动失败 | 不报告全量成功 |
| 两个并发 upgrade | 第二个由事务锁 / generation CAS 拒绝 |
| 清单签名无效 / 未知 key_id | trust_unknown，停在 staging 前；不降级、不忽略过期 |
| 清单 generation 回退（重放旧清单） | 拒绝，标记 downgrade_rejected |
| supervisor 交接中新实例崩溃 | 回切旧 supervisor，事务置 rollback_pending |
| 交接期间收到 status / restart | 返回 handover_in_progress，不猜测权威实例 |
| 数据根迁移中出现双写 | 判定迁移失败，双端保持只读，转人工 |
| append-only 流出现未知 schema / 半行 | fail-closed，双端原状，不覆盖不补齐 |

### 8.2 systemd

| 场景 | 期望 |
|---|---|
| kill -9 Web MainPID | 新 PID、NRestarts 增加、health 恢复 |
| SIGTERM 后 exit 0 | Restart=always 拉起新实例 |
| systemctl stop | 不被立即拉起 |
| 真实注销 / 主机重启 | Linger + enabled units 自动启动 |
| 端口冲突 | 限次重试，报告占用者，不杀无关进程 |
| 坏配置 | 限流失败并给出修复建议 |
| Learning busy | restart 延期 |
| Feishu 未完成消息 | 按业务 idle 规则延期 |
| 升级中断电 | recovery 根据 journal 验证或回滚 |
| 三服务版本混用 | status 显示 mismatch，不报绿色 |
| recovery 未成功 / 超时 | 业务单元 fail-closed 停在 failed，原因 recovery_incomplete |
| StartLimit 触发 | status 显示“已限流”，doctor 给出 unit_state / last_exit_code / next_action |
| 自定义安装根 | unit 写绝对路径，`systemd-analyze --user verify` 通过且与 LFL_HOME 三处一致 |

### 8.3 沙盒授权

| 场景 | 期望 |
|---|---|
| 未批准访问工作区外文件 | read / write 拒绝 |
| 单文件 read grant | 仅可读该文件 |
| 目录 RO grant | 可读，不可写 |
| 目录 RW grant | 仅该 canonical subtree 可写 |
| symlink 指向授权外路径 | 拒绝 |
| ../ 路径穿越 | 拒绝 |
| grant 过期 / 撤销 / 已消费 | 立即拒绝 |
| 子代理未获 delegated grant | 拒绝外部路径 |
| bwrap namespace 不可用 | 真实探测失败，strict 模式 fail-closed |
| Docker 后端 | 明示断网和挂载差异 |
| EXEC_SANDBOX=none | 明示无 OS sandbox |
| CatastrophicGuard 已批准但无 Host grant | OS sandbox 仍拒绝 |
| grant 文件属主不符 / 0777 / symlink | grant_store_insecure 拒绝，不修权限后放行 |
| 两进程并发消费同一 grant | 仅一个成功，另一个 deny(consumed) |
| 审计哈希链断 | 停止签发新 grant，报 audit_chain_broken |
| 进程重启后使用未过期 grant | 重新加载并复核 canonical path，通过才生效 |

### 8.4 回归

- macOS sandbox-exec writable_roots 既有语义不回归。
- source checkout service_control / restart_mirror 路径不回归。
- write-scope allow / deny、子代理继承和 audit 不回归。
- EXEC_SANDBOX=none 的静态危险命令 guard 保持有效。
- 后端能力降级必须明确回执，不静默扩大权限。

---

## 9. 非目标与红线

1. 不关闭沙盒解决工具不可用。
2. 不把 EXEC_SANDBOX=none 设为 Linux 默认。
3. 不把整个 Home、.ssh、浏览器 profile 或 Docker socket 默认挂给 Agent。
4. 不把 CatastrophicGuard 批准转成永久文件系统授权。
5. 不伪造 Git SHA、仓库、软链接或 PYTHONPATH 身份。
6. 不让 LFL Web 接收管理员密码。
7. 不给 LFL 通用 sudo / root shell。
8. 不在 active Run、Learning inflight 或 Feishu 未完成消息时强制重启。
9. 不在候选下载、依赖安装、smoke 和备份完成前停止旧服务。
10. 不在 schema compatibility unknown 时自动覆盖生产数据。
11. 不自动重启 Deepin 整台主机或升级系统内核。
12. 不把 GitHub Git proxy 当作 curl / uv / pip 的全局代理。
13. 不把 PID 存活、HTTP 200 或 selected_roots 单项指标误报为升级成功。

---

## 10. 实施准入

本文件是需求与设计，不授权修改主线、生产主机、服务单元、数据目录或沙盒默认值。

后续实施纪律：

1. 从固定 main commit 建立隔离 worktree；每阶段限定文件范围。
2. 代码和设计独立 GLM-5.3 Reviewer Host PASS，P0/P1=0 后再跑原版完整 R9。
3. R9 必须真实 exit 0；候选变化后重新冻结、审查和 R9。
4. Rule34 独立合并审查 PASS 后才允许本地合并。
5. 未单独授权不 push、不发布、不切换生产 release、不重启生产。
6. Deepin 先旁路验证 wheel、systemd units、崩溃 / 干净退出 / reboot 和 grant 失败注入。
7. 所有切换需真实 action receipt、PID / cgroup / version / SHA / health 对账。
8. 资格未知时阻断；不通过修改门禁或伪造 manifest 使其变绿。

---

## 11. 代码与既有设计锚点

既有设计：

- docs/DESIGN-20261017-install-upgrade-backup-rollback-p1.md
- docs/DESIGN-20261017-p1-controlled-upgrade-transaction.md
- docs/QUALIFICATION-20260916-service-control-p0a.md
- docs/SPEC-20260922-service-control-restart-fixpack-v1.md
- docs/DESIGN-20261012-escalation-native-admin-boundary.md
- docs/DESIGN-20261030-write-scope-and-concurrent-writer-ownership.md
- docs/SPEC-20261031-write-scope-os-enforcement-and-cache-correctness.md
- docs/LFL_Linux_0.6.37_sandbox_wheel_review_2026-10-28.md
- docs/minimax-linux-setup.md
- docs/EXECUTION-ISOLATION.md

主要源码：

- scripts/install_linux.sh
- scripts/uninstall_linux.sh
- scripts/restart_mirror.sh
- src/llm_loop/cli.py
- src/llm_loop/runtime/install_recovery.py
- src/llm_loop/runtime/upgrade_preflight.py
- src/llm_loop/runtime/upgrade_stage.py
- src/llm_loop/runtime/service_control.py
- src/llm_loop/runtime/manifest.py
- src/llm_loop/runtime/identity.py
- src/llm_loop/runtime/paths.py
- src/llm_loop/tools/sandbox.py
- src/llm_loop/tools/escalation.py
- src/llm_loop/core/write_scope.py
- src/llm_loop/core/run_context.py
- src/llm_loop/tools/builtin/execute_command.py
- src/llm_loop/tools/builtin/edit_file.py
- src/llm_loop/tools/builtin/verify_path_scope.py

本轮实机经验：

- experiences/EXPERIENCE-20261107-deepin-wheel-布局-lfl-三服务重启-权威入口结构性-fail-closed-rest.md
- experiences/EXPERIENCE-20261107-deepin-服务面板身份判定链-manifest-目录分歧可软链修复-但-desired-提交与.md
- experiences/EXPERIENCE-20261106-systemd-restart-on-failure-不覆盖干净退出-守护常驻服务要用-always.md
- experiences/EXPERIENCE-20261029-deepin-端-lfl-三服务对齐-mac-端的操作路径-runtime-launch-runti.md
- experiences/EXPERIENCE-20261028-linux-远程安装-lfl-引导-uv-的-120-秒总时长上限是慢链路主因.md

### 修订记录

- v0.1（2026-11-07）：基于 Deepin 25 / LFL 0.6.40 实机只读探测和本地 main 源码检查形成；明确 wheel/source 双身份、三服务 systemd、升级事务、宿主能力授权和 GitHub 解耦五条主线。未实现、未审查 PASS。
- v0.2（2026-11-07）：按首轮独立审查 GO-WITH-CONDITIONS（P0=1 / P1=4 / P2=4）修订，仅改本文档、未改代码：
  - P0：新增 §2.4.1 数据根处置矩阵、§2.4.2 append-only 流连续性与回滚；Stage 1 验收补迁移一致性核验。
  - P1：§0/Stage 0 基线重冻结与 9242dc74→ee475a352 漂移记录；§5.3.1 信任锚、轮换与离线校验、镜像回执字段；§3.3.1 supervisor post-commit 交接；§6.2.1 grant store 持久化与并发。
  - P2：§4.1 unit 模板与自定义安装根、StartLimit 后 doctor/status 诊断路径；§4.4 recovery oneshot/Before/fail-closed 单元语义；§2.5 `current_write_scope` 归属更正为 `core/run_context.py`。
  - 未纳入：`lane_open` 未校验 Goal 存在性的工具缺陷（首轮审查判为 out of scope，单独登记为后续治理事项）。

