# LFL 受管服务重启方法与经验纠偏（2026-10-25）

**性质：隔离候选，待独立审查后回写正式 MethodStore，不是已经生效的部署声明。**

## 已证实的当前事实

- 2026-10-25 22:29 Web 受控重启终态 `succeeded/confirmed_ok`，PID43317，HTTP `/auth/status` 200，Live SHA `7ad21715d...`，对应 desired319；同一时刻 Feishu/Learning live SHA 同样匹配，但 stable 回执为315，`restart_required=false`。
- 登录哈希升级持久化曾把 `WEB_SESSION_TTL_SECONDS` 追加至哈希尾部，导致 Web 22:07/22:09 启动立即报哈希格式无效。独立读回、原值保留并拆行、0600 限权后 Web 单服务恢复。
- 旧经验 `EXPERIENCE-20260919-service-control-cli-restart.md` 断言 CLI 不存在 `restart`，当前 `python -m llm_loop.runtime.service_control restart --help` 已验证存在。此事实随目标版本变动而变化，不应长期硬编码。
- 在本次隔离工作期间有另一控制面发布 desired320/`26530f9f2` 且 Web 等待 `requester_exit`；因此不能把前一快照 319 当作一直有效的操作授权或实时状态。

## 精确需要修订的 Method 卡（保留既有 ID，不新建冗余卡）

| 旧 Method ID | 需要保留的正确部分 | 已证明需要撤销/修改的说法 | 建议的最小修订 |
|---|---|---|---|
| `current-state-snapshot-first-per-service-restart-effect-verdict-8418f9c7749d` | 优先使用按服务身份快照，避免猜进程 | 将 `live.git_head` 与**当前 checkout HEAD** 相等、或 stable 未到当前代视为生效/未生效的充分判据 | 改为比较 `live.git_head == desired.git_head` 且 live PID alive，另报 `stable.generation` 与 `desired.generation` 的代差；稳定回执滞后不单独触发重启；功能是否生效另用端到端探针 |
| `verify-deployment-state-via-runtime-receipt-not-unrelated-local-mirror-921affe7d537` | 服务身份优先于无关 checkout，fetch 错误不可静默忽略 | 以 stable 回执“当前代”作为已生效的唯一依据 | 分开 `desired` / `live` / `stable`；stable 是上次成功动作历史，只有当前 desired 代回执才可声明其 git 身份，旧回执 SHA 必标未知；本机 checkout 仅用于调查源码来源 |
| `registry-first-service-restart-2d87ee392004` | 对 launchd/systemd 真正管理的普通桌面或系统服务，注册表优于进程名猜测 | “所有服务都应以 OS unit registry 为唯一重启句柄”的泛化 | 在 Trigger/Counterexamples 明确：LFL Web/Feishu/Learning 受 managed `service_control` 支配，不得用 `launchctl kickstart` 或按 PID 杀进程替代正式 action、锁、回执；仍适用于真正的 launchd/systemd 外部应用 |
| `managed-restart-target-config-preflight-and-rollback-binding-356473240ac6` | 目标版本配置加载、相容回滚、两阶段等待、只修已证实故障等均适用 | 尚未包含 Web 登录哈希升级对下一项行终止符损坏的失败模式 | 在短路径配置预检加入独立重载 `.env`、校验 `WEB_LOGIN_PASSWORD_HASH` 规范值、TTL 独立行、修改前后非目标字节、0600 权限；只在目标服务相关时执行，不把 Canary 专属校验强加给每次纯重启 |

**实施原则：** 这些条目目前仍是运行时 `data/methods` 中的候选资产；只做上述精确语义修订，沿用原 ID、来源证据及历史，不扩大状态门禁，也不因为一例事故把全部相关方法标为 invalidated/retired。MethodStore 的销毁性状态需要独立证据，直接改文本不应冒充已完成审查。审查通过后以原子写回并回读 `MethodStore.get` 的方式更新；保留受限原件以便恢复。

## 下一次受管重启：LFL 快捷决策链

1. 只读读取 `service_control status/show`，在当前回执中核对 desired（release SHA、generation）、live（pid_alive、code git_head）、stable（成功代次/时间），以及已在途 action/barrier。状态刚被他人更新，必须以新代次重算，不复用旧 status。
2. 若 live 匹配 desired 且 `restart_required=false`，只把 stable 旧回执作为历史代差显示；不为数字相同而重启其他服务，不伪造成功回执。
3. 若确需重启，先检查目标版本自身的配置与最小启动依赖（Web 包括认证哈希及其下一项、TL/TTL 范围、配置改动行边界；其他服务不做无关 Web 检查），核验目标版本与回滚版本均可读取准备使用的配置。检查失败时继续保留现役服务，不启动重启。
4. 若需新版本先按冻结候选和既定 Review/R9 资格与权限正式 publish，`restart` 只重启已发布 desired，不会自动包含正在编辑的代码；不要为了表面一致对 desired 代次空转 +1。
5. 用当前目标版本 `--help`/工具 schema 选 `service_control` 正式接口；绑定目标服务范围，action 被受理后由外部观察者跟踪至真实终态，Web requester run 自身退出释放锁，不能在同一进程内无限等待。
6. 只有 `succeeded`、live/desired SHA 一致、PID 和健康接口真实可用、实际用户入口通过且未授权相邻服务 PID 未变，才可宣告恢复。失败时取单动作精确错误与日志，保留配置备份，禁止循环盲重启或强制跳过活跃用户任务。

## 经验生命周期处理

- 2026-09-19 的“没有 CLI restart”以及以该前提写成的“三服务标准流程”已在隔离候选中改为 `superseded`，保留原事故证据与历史时间，撤出当前 active 检索。
- 新经验 `EXPERIENCE-20261025-受管重启认证写回与代次判读` 记录当日真实故障、修复、版本/代次独立口径以及复用条件。在正式回写之前，已将压缩的当前事实与可执行原则存入 LFL 自身的持久记忆空间供后续检索。
- 同一个事实在不同版本上可能失效：重启前先检查目标版本源码/接口事实，不准让过时的 Method/Experience 覆盖新状态。
