# Host Task Lease 独立签发与撤销：Mac 受管安装清单

状态：**候选代码 / 未安装 / 未签发生产 Task Lease**。此清单不是管理员授权，也不是 T1 验收通过的证明。不得把可变 worktree 代码直接作为特权脚本执行。

## 1. 信任边界与复用范围

- 复用已存在的 `/Library/Application Support/LFL-HostIssuer` root-owned 安装基础、独立签发 OS 身份 `_lfl_dual_witness`（UID 462）及 root-owned 冻结 Python 3.13 运行时。**不复用** premerge 的私钥、签名域、审核证据或授权语义；不得修改既有 `bin/issuer.py`。
- 新脚本：`scripts/host_task_lease_issuer.py` → 安装为 `/Library/Application Support/LFL-HostIssuer/bin/task_lease_issuer.py`（root-owned 0555）；必须从**独立 Reviewer PASS、完整原版 R9 exit0、远端 CI 通过且受保护 main 的精确 SHA**取得源码，安装前后核对 SHA256。
- 新独立根：`/Library/Application Support/LFL-HostIssuer/task-authority`（root:wheel 0755）。其 `public_key.pem` 与 `trust.json` 必须 root-owned 0644；`trust.json` 仅包含固定 `schema=lfl.task-authority-trust/v1`、`issuer_uid=462` 和 `public_key_sha256`（公钥 PEM 字节 SHA256）。
- `private/`、`private/approvals/`、`private/consumed/`：UID462 0700；`private/task-ed25519.pem`：UID462 0600；`private/task-public.pending.pem`：UID462 0600；`leases/`、`states/`：UID462 0755；签名收据：UID462 0644。普通 LFL UID501 只可读取公钥/签名收据，不可读取私钥或修改收据/信任锚。
- Host 签发只在隔离解释器 `python3.13 -I -S`、精确 UID462、root-owned 安装代码和受信 Crypto site 下执行。**没有** LFL 模型工具、Web 任意签名 API、daemon 或同 UID 私钥回退。

## 2. Operator 一次性安装（需真实 macOS 管理员操作）

1. 确认当前 GitHub 受保护 `main` 的精确 SHA、required checks、独立 Reviewer/R9 证据、候选与安装脚本 SHA256；不接受本地未合并候选。
2. 使用系统管理员权限创建上述目录和属主/权限，复制**已核验受保护 main** 中的脚本为 root-owned 0555，校验安装 SHA256 一致；不得运行未经核验的 shell 安装脚本。
3. 以 UID462 在隔离 Python 下运行 `--mode keygen`（create-only）。生成的独立私钥不离开 `private/`；管理员从 `task-public.pending.pem` 复制公钥到 root-owned `public_key.pem`，写入并校验 root-owned `trust.json`。若已有密钥，拒绝覆盖。
4. 以普通 LFL UID 验证私钥/审批目录不可读写、`trust.json`/公钥/状态不可写、收据可读；无特权直接运行签发器必须 `HOLD`。完成真实伪造签名、篡改、旧 epoch、已撤销、跨 Owner/Goal/Task/Lane、过期、路径越界和 Mac Seatbelt 拒写负测。
5. 只在 Owner 明确批准的 Task/roots/verbs/TTL 内签发一次任务 Lease。先验证 LFL Goal/Task/Lane 的真实状态、owner session、HEAD/CAS、父 scope、项目路径与其他 Lane 排他，再由管理员将审核过的请求放入 **UID462 0600** `private/approvals/<approval_id>.json`。此文件不能由 Agent 或 LFL Web 写入；每个 approval_id 只能使用一次。
6. 以 OS 管理员授权切换 UID462，执行已安装脚本 `--mode issue --approval-id <approval_id>`。只有签名租约、状态和审计均持久可见，且 LFL Runtime 在每次物理副作用前复验 Host 状态、Lane、父 scope 和 OS 权限，才允许任务执行。不得通过 Web 按钮自行铸造签名或由模型模拟 Owner 确认。

## 3. 签发与撤销合同

审批请求的字段严格固定为 `schema,approval_id,approved_at,approved_by,purpose,goal_id,task_id,owner_session_id,agent_id,lane_id,revision,authority_epoch,ttl_seconds,parent_lease_id,resources`。资源只能是精确 `project/app/service` 身份及受限 verbs；不支持全 HOME、任意 shell 提权、`git_push`、`merge`、`release`。批准后 10 分钟内消费，TTL 不超过 24 小时；超过需重新审批。

签发器输出分离的 Ed25519 Lease 和 State 收据；状态文件可由独立 UID462 使用 `--mode revoke --lease-id <lease_id>` 原子改为 `revoked`。LFL 每次副作用前重新验签和读取当前状态，撤销后拒绝**新**副作用；已经运行的后台进程取消/效果对账仍属 T3，未完成前不得宣称任意时点撤销全覆盖。

## 4. 发布、回滚与边界

- 首次安装不得从未审查的工作树执行。若需要受保护 main 的一次性 feature-disabled bootstrap，必须单独通过现有独审/R9/PR/CI/分支保护并取得相应批准；不要为了安装绕过门禁。
- 出现任何安装 SHA/UID/ACL/签名/审计不一致，保持 **HOLD**，不回退到 `EXEC_SANDBOX=none`、同 UID HMAC、自签发或可变脚本。
- 回滚：停止签发、撤销现有 Lease、保持 `current_task_execution=None` 默认旧沙箱行为；保留审计与证据，通过受保护 PR 回退代码。不得删除/覆盖原 premerge 签发器及密钥。
- Deepin 的独立 Host UID、Polkit/TCC 等价授权和 bwrap 真机验收在 T2 单独收口；Mac 的通过不代表 Deepin 通过。
