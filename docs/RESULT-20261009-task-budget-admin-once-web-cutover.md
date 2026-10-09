# TaskBudget Web 单会话／单 Run 一次配置收口

## 本次批准与边界

2026-10-09 用户明确授权：首版仅 Web，一个既存或管理员创建的专用 Session、仅一个新 Run，管理员在受控终端一次性配置，不再对每条消息要求独立三账户双签。只能为 `glm/glm-5.3` 授予 **1 次物理 Provider POST 尝试**，工具调用、wake、SubAgent 均为 0。失败、掉线、取消后的 Provider 计费／物理静默不可臆断为 0；保留 UNKNOWN。

## 机械落实

- 入口：`[web].task_budget_canary_config` 指向绝对路径、0600、非符号链接、Web/ROOT 拥有、单硬链接、大小 <=16KB 的管理员配置。配置精确包含 `authorization_id`(随机 128-bit)、`session_id`、`workspace_root`、`glm/glm-5.3` 和 <=3600s 的批准有效窗。未配置时完全 OFF。
- 适用：仅 Web 登录态中显式选择 `glm/glm-5.3` 的流式请求。独立后台线程显式绑定 `AdminOnceEventPlan` 和独占进程 HTTP/1.1 verified TLS transport。同步端点 409；Web 人类事件在 EventStore 严格 fsync、重新水合校验后才可消耗批准。
- 消耗：预算 ID = `webadminonce-<authorization_id>`。`TaskBudgetStore.issue_root(reject_duplicate=True)` 使用 flock、文件及目录 fsync、防 symlink、revision CAS；同批准 ID 第二个 human event、第二个 Run、并发及进程重启后重复均硬拒绝，不会重新发行物理尝试额度。Run 代次、真实 EventStore event_id、Session/workspace、非 delegated 人类 Web ingress 必须一致。
- 物理边界：复用已冻结的 I5-G fixed GLM provider/model/url TLS 校验、一次 `physical_attempts` CAS、I5-B/C/D/H 独立进程 Stop。外部用量/账单未知时不得把发出请求等同结算。此版本**不是** Token 或资金绝对上限。
- 旁路：已选 Session 在 `LoopEngine` Run 入口设机械 fence，没有受控 plan 的 queue-recovery、direct/sync 或其他 Web Run 均拒绝。未选 Session 不受影响。

## 受管上线操作门槛

1. 完成相邻、架构及正式 R9 测试，在 tracked-clean exact Git 工作树上固定 commit SHA，并校验 WebUI artifact 与 runtime root。**仅用 LFL `service_control` 专用工具的 CAS publish + Web-only restart，或受控 operator 终端正式 CLI。不要通过普通模型 `execute_command`、手改 desired deployment、裸 `restart_mirror.sh` 绕过。**
2. 配置只允许管理员本机终端生成：在已发布相同代码与 runtime 配置的目标环境，执行 `PYTHONPATH=src .venv/bin/python scripts/task_budget_admin_once_setup.py --output /ABSOLUTE/OWNER-ONLY/admin-once.json`，新建专用 Session 与审批 ID；或者加 `--session-id` 指定已有专用 Session。文件 O_EXCL 0600+fsync，不覆盖、不打印授权 ID、无模型工具权限。
3. 管理员将 `runtime.toml` 的 `[web]` 项 `task_budget_canary_config = "/ABSOLUTE/OWNER-ONLY/admin-once.json"` 设置为该受控路径；用 Web-only 的受管服务重启加载（`main`、Feishu/Learning 不重启）。必须在有效时窗内操作，默认 900s；过期后该 Session 继续拒绝，绝不回退无限制执行。
4. 以 Web 已登录身份向匹配 Session 的 `/api/v1/chat/stream` 发送**仅一条**显式 `model="glm/glm-5.3"` 的简单文本（不带附件/队列），必须获得实际 Run generation、EventStore event_id 和预算文件，同一授权只出现 1 个预算 root；一次 `physical_attempts` 最多为 1，再提交必须被拒且没有第二次 Provider POST。检查 `TaskBudgetStore.report()` 与独立传输日志，Provider 调用成功或失败均如实记录；**没有可验证的真实外部调用回执不标记 Canary 完成**。
5. 出现 provider/network/授权/超时异常，停止且保留 CAS/UNKNOWN；若需第二次物理调用必须管理员创建*新的*一次批准，不自动重试或以原授权重新使用。若无有效 `service_control` 权限，不使用 shell 绕过共享服务生命周期。

## 已知残余风险

- 一次服务端配置不是独立三 UID 的密码学证明。若 Web 进程及可执行工具具有同一 OS UID 并能改写管理员配置/`runtime.toml`，则操作员文件的 0600 只提供 OS 文件访问边界，而非相互不信任进程的强隔离。不要向模型工具开放这些路径；如需要对同 UID 的恶意工具强抗性，必须用独立 UID 或 root 托管只读配置，不能靠签名模型提示词替代。
- 一次发送上限不等于 Provider 账单或硬 Token 上限；失败、网络断开和取消下不得声明远端已经静默。
- 候选代码通过测试只代表可部署资格。必须分别取得受管 publish、Web-only restart 和现场 GLM-5.3 单次 Canary 收据，才能声明生产 ON。
