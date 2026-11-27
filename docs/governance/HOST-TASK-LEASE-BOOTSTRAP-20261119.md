# Host Task Lease 独立签发与撤销：Mac 受管安装清单

状态：**候选代码 / 未安装 / 未签发生产 Task Lease**。此清单不是管理员授权，也不是 T1 验收通过的证明。不得把可变 worktree 代码直接作为特权脚本执行。

## 1. 信任边界与复用范围

- 复用既有独立签发 OS 身份 `_lfl_dual_witness`（UID 462）和经管理员核验的 Python 3.13 解释器，但**不复用** premerge 的安装目录、私钥、签名域、审核证据或授权语义；不得修改 `/Library/Application Support/LFL-HostIssuer` 及其 `bin/issuer.py`。macOS 的 `/Library` 可能为 root:admin 0775；只允许这一**精确路径**的系统特例（root UID0、admin GID80、无 other-write），因为 admin 属 OS 特权组。不得放宽新专用根或其他祖先的权限，也不得 chmod 共享系统目录；Linux 不适用此例外。
- 新脚本：`scripts/host_task_lease_issuer.py` → 安装为 `/Library/LFL-TaskHostIssuer/bin/task_lease_issuer.py`（root-owned 0555）；必须从**独立 Reviewer PASS、完整原版 R9 exit0、远端 CI 通过且受保护 main 的精确 SHA**取得源码，安装前后核对 SHA256。
- 新独立根：`/Library/LFL-TaskHostIssuer/task-authority`（root:wheel 0755）。受信 Crypto 依赖安装到同一专用根下的 `/Library/LFL-TaskHostIssuer/runtime/site`（root-owned、非组/其他可写；仅复制经管理员校验的冻结依赖，不从可变工作树直接加载）。其 `public_key.pem` 与 `trust.json` 必须 root-owned 0644；`trust.json` 仅包含固定 `schema=lfl.task-authority-trust/v1`、`issuer_uid=462` 和 `public_key_sha256`（公钥 PEM 字节 SHA256）。
- `private/`、`private/approvals/`、`private/consumed/`：UID462 0700；`private/task-ed25519.pem`：UID462 0600；`private/task-public.pending.pem`：UID462 0600；`leases/`、`states/`、`bindings/`：UID462 0755；签名收据及 `bindings/<sha256(session)>/<lease_id>.json`：UID462 0644。普通 LFL UID501 只可读取公钥/签名收据/绑定，不可读取私钥或修改收据/绑定/信任锚。
- Host 签发只在隔离解释器 `python3.13 -I -S`、精确 UID462、root-owned 安装代码和受信 Crypto site 下执行。**没有** LFL 模型工具、Web 任意签名 API、daemon 或同 UID 私钥回退。

## 2. Operator 一次性安装（需真实 macOS 管理员操作）

1. 确认当前 GitHub 受保护 `main` 的精确 SHA、required checks、独立 Reviewer/R9 证据、候选与安装脚本 SHA256；不接受本地未合并候选。
2. 先只读核验 `/`、`/Library` 到新专用根的每一级目录均 root-owned、非符号链接；除 macOS 精确 `/Library` 的 root:admin(GID80) 0775（无 other-write）特例外，全部须 `mode & 0022 == 0`。其他组写/其他写、符号链接或身份异常均 **HOLD**，不得修改 `/Library` 或 `/Library/Application Support` 的全局权限。再由系统管理员创建专用根、`bin`、`runtime/site` 及 `task-authority`，逐级设为 root-owned、非组/其他可写，复制**已核验受保护 main** 中的脚本为 root-owned 0555，校验安装 SHA256 一致；受信 Crypto site 的内容与来源也须核验并冻结。不得运行未经核验的 shell 安装脚本。
   - 在安装新版受保护脚本后、首次 `issue-lane` 前，以本地管理员运行一次固定路径初始化（不读取或生成密钥）：

     ```bash
     sudo "/Library/Application Support/LFL-DualAgent/python/bin/python3.13" \
       -I -S /Library/LFL-TaskHostIssuer/bin/task_lease_issuer.py \
       --mode init-lane-gitconfig
     ```

     仅允许创建 `task-authority/gitconfig-safe-directories`（UID462 的主组、0644）；`INITIALIZED` 或 `ALREADY_INITIALIZED` 表示成功。已有文件必须是单链接、非符号链接、精确 owner/group/mode，内容及 inode 不改；不可信文件返回 HOLD，不自动修复或覆盖。再用 `sudo -u _lfl_dual_witness /bin/test -w /Library/LFL-TaskHostIssuer/task-authority/gitconfig-safe-directories` 验证实际签发 UID 的写权限。保留原签发器、密钥、信任根及所有收据；不放宽父目录权限。仅从已通过门禁的受保护 main 安装并运行，不在开发工作树执行 root 初始化。

3. 以 UID462 在隔离 Python 下运行 `--mode keygen`（create-only）。生成的独立私钥不离开 `private/`；管理员从 `task-public.pending.pem` 复制公钥到 root-owned `public_key.pem`，写入并校验 root-owned `trust.json`。若已有密钥，拒绝覆盖。
4. 以普通 LFL UID 验证私钥/审批目录不可读写、`trust.json`/公钥/状态不可写、收据可读；无特权直接运行签发器必须 `HOLD`。完成真实伪造签名、篡改、旧 epoch、已撤销、跨 Owner/Goal/Task/Lane、过期、路径越界和 Mac Seatbelt 拒写负测。
5. 只在 Owner 明确批准的 Task/roots/verbs/TTL 内签发一次任务 Lease。先验证 LFL Goal/Task/Lane 的真实状态、owner session、HEAD/CAS、父 scope、项目路径与其他 Lane 排他，再由管理员将审核过的请求放入 **UID462 0600** `private/approvals/<approval_id>.json`。此文件不能由 Agent 或 LFL Web 写入；每个 approval_id 只能使用一次。
6. 以 OS 管理员授权切换 UID462，执行已安装脚本 `--mode issue --approval-id <approval_id>`。签发器还会生成 issuer-owned session binding；**binding JSON 本身未签名**，其可信性依赖 UID462 文件所有权、权限和无符号链接检查，真正的 Lease/State 收据才带 Ed25519 签名。LFL 仅在 Run lease 获得后读取当前 session 的**唯一有效**受信绑定，并核对 workspace=Lane worktree、实际 Git HEAD/CAS 后激活 Task Context，Run 退出即清除。多个活跃绑定或不可信绑定一律 HOLD。只有签名租约、状态和审计均持久可见，且 LFL Runtime 在每次物理副作用前复验 Host 状态、Lane、父 scope 和 OS 权限，才允许任务执行。不得通过 Web 按钮自行铸造签名或由模型模拟 Owner 确认。

### 日常开发文件操作

在已签发、当前 Run 已激活的窄 Task lease 中，先用 `read_file(snapshot=true)` 读取已有文件；不存在返回 `TaskFileNotFound`，真正的 OS 权限拒绝仍是 `os_permission_required`。创建新文件复用现有受管 `execute_command` 和 Task sandbox（使用 no-clobber，例如 `set -C`，不覆盖已有文件）；不新增任意写文件或提权入口。创建后重新读取取得精确 `sha256:` 基线，再用 `edit_file(expected_snapshot_ref=...)` 修改，保留原有原子替换、WAL、版本冲突与撤销复检。测试命令和 `task_git_commit` 仍走既有受管入口。命令创建的效果以命令回执及随后文件观察核验，不冒充 FileService 编辑 WAL。Mac Seatbelt 是写隔离，不是读或网络隔离；Deepin bwrap 真机能力需另验收。

## 3. 签发与撤销合同

审批请求的字段严格固定为 `schema,approval_id,approved_at,approved_by,purpose,goal_id,task_id,owner_session_id,agent_id,lane_id,revision,authority_epoch,ttl_seconds,parent_lease_id,resources`。资源只能是精确 `project/app/service` 身份及受限 verbs；不支持全 HOME、任意 shell 提权、`git_push`、`merge`、`release`。批准后 10 分钟内消费，TTL 不超过 24 小时；超过需重新审批。

签发器输出分离的 Ed25519 Lease 和 State 收据；状态文件可由独立 UID462 使用 `--mode revoke --lease-id <lease_id>` 原子改为 `revoked`。创建/替换时须文件 fsync 加父目录 fsync 完成后才回报 `SIGNED`/`REVOKED`；任一持久化失败即 HOLD，不能声称撤销已成功。LFL 每次副作用前重新验签和读取当前状态，撤销后拒绝**新**副作用；已经运行的后台进程取消/效果对账仍属 T3，未完成前不得宣称任意时点撤销全覆盖。

## 4. 发布、回滚与边界

- 首次安装不得从未审查的工作树执行。若需要受保护 main 的一次性 feature-disabled bootstrap，必须单独通过现有独审/R9/PR/CI/分支保护并取得相应批准；不要为了安装绕过门禁。
- 出现任何安装 SHA/UID/ACL/签名/审计不一致，保持 **HOLD**，不回退到 `EXEC_SANDBOX=none`、同 UID HMAC、自签发或可变脚本。
- 回滚：停止签发、撤销现有 Lease、保持 `current_task_execution=None` 默认旧沙箱行为；保留审计与证据，通过受保护 PR 回退代码。不得删除/覆盖原 premerge 签发器及密钥。
- Deepin 的独立 Host UID、Polkit/TCC 等价授权和 bwrap 真机验收在 T2 单独收口；Mac 的通过不代表 Deepin 通过。
- Task 模式 IDE AX `type` **仍为 HOLD**：VS Code 等 IDE 的内嵌终端与编辑器都可能呈现 `AXTextArea`，签名 app bundle、窗口 PID、TCC 和控件 role 不能证明目标是编辑文档。当前即使签名 Lease 有效也拒绝真实投递；后续必须先补受信编辑文档身份/祖先链核验与内嵌终端负例，不能通过允许 AX role 绕过终端命令工具。Browser Task mutation 和 Service Task 异步发布同样继续 HOLD。
