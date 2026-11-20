# LFL 受限开发提交：独立 Host 签发与启用手册（候选）

> **状态：隔离代码候选，未安装、未激活、未部署。** 必须先通过精确 SHA 独立 Reviewer、原版完整 R9、安全负测和 Owner 的单独 Host 安装授权。

## 1. 可信边界

正式 `bash scripts/r9_commit.sh "<message>"` 始终走原版完整 R9。显式 `--dev` 只允许 `feat/*` / `fix/*` 开发 Lane **本地提交**，不能签发 Reviewer、R9、PR、push、main、Release 或部署资格。

`--dev` 必须同时满足：独立 Host UID462（Mac `_lfl_dual_witness`）；安装在仓库外的 root-owned 冻结签发器；**专用** Ed25519 私钥（不得复用 premerge、Task Lease、Oracle）；root-owned 精确树审批；root-owned 激活配置；Host-owned 一次性消费账本。环境变量、模型声明、仓库内自签 JSON 都没有授权效力。缺任一条件一律拒绝。

## 2. 安装规范（须另行 Owner 批准，当前未执行）

| 固定路径前缀：`/Library/Application Support/LFL-HostIssuer/` | 所有者 / 权限 | 说明 |
| --- | --- | --- |
| `bin/dev_commit_host_authority.py` | root / 0644 | 冻结代码，Python `-I -S`，仅 root-owned Crypto site |
| `private/` | UID462 / 0700 | 与 premerge 隔离 |
| `private/dev-commit-ed25519.pem` | UID462 / 0600 | 独立签发私钥，禁止进入仓库 |
| `private/dev-commit-ed25519.pub.pem` | UID462 / 0600 | 独立验签公钥 |
| `private/dev-commit-ledger.jsonl` | UID462 / 0600 | `issued/consumed`，flock+fsync，不得清空 |
| `receipts/dev-commit/` | UID462 / 不可组写 | 签名 Grant，文件 0600 |
| `approvals/dev-commit/` | root / 0755 | root-owned Owner 精确审批 JSON（文件 0644，供 Host UID462 只读） |
| `config/dev-commit-enabled.json` | root / 0644 | **默认不存在**，人工审查后才能创建 |

仅由受信任的 Host UID462 运行一次 `keygen`，不得覆盖已有私钥/账本。启用配置的精确内容：

```json
{"schema":"lfl.dev_commit.activation.v1","enabled":true,"host_uid":462,"repo":"deyi2026/llm-first-loop"}
```

安装、激活、sudo 权限委派均须单独审批；不得配置通用 NOPASSWD shell/Python，也不得开放任意模型签名 API。现有 `/usr/bin/sudo -n -u _lfl_dual_witness` 若未配置**精确受限**的调用委派，会安全拒绝；不要绕过。

## 3. 单次开发提交操作

1. 在隔离 Lane 暂存精确文件，无未暂存修改或未跟踪文件，`origin/main` 与 Lane base 一致。`scripts/`、CI、钩子、`docs/governance/`、Goal 完成门禁等敏感文件不得使用 `--dev`。
2. Owner 确定精确提交消息及其 UTF-8 SHA256，使用**已安装** Host CLI 的只读 `inspect` 模式独立重算 repo/worktree/branch/HEAD/staged Tree/base/Goal/REQ/Lane/version/paths/message hash。`inspect` 不签发、不激活。
3. 经独立 OS 管理员认证，Owner 在 root-owned `approvals/dev-commit/<随机ID>.json` 中写入审批：`schema=lfl.dev_commit.approval.v1`、`approval_id`（16～64 字符随机且不重复）、`context`（与 Host inspect 输出**完全相同**）、`expires_at`（签发时刻之后且不超过 600 秒）。仓库或模型进程不得写入该文件。
4. 已安装 Host CLI `issue --approval-id ... --worktree ... --goal ... --req ... --base ... --message-sha256 ...` 独立验证审批与实时 Git/Lane，使用专用 Ed25519 签名并持久登记 `issued`，生成最长 300 秒有效的 Grant。根审批不能重复使用。
5. 在精确 staged 白名单下运行：

   ```bash
   R9_STAGED_ALLOW="$(git diff --cached --name-only)" \
     bash scripts/r9_commit.sh --dev \
       --goal "GOAL-..." --req "REQ-..." --base "<精确40位main SHA>" \
       --design "docs/design/<已批准设计>.md" \
       --grant-id "<Host签发的随机ID>" \
       "feat(r9): <明确开发切片消息>"
   ```

   脚本复用全局锁、staged 白名单、PROBE/fixture、R9 机检和安全扫描；然后真实运行增量 Ruff/Pyright/Pytest 并复核 Tree；通过固定安装路径的 Host `consume` 复验签名、过期、精确 Tree/Goal/Lane/消息、开发回执与消费账本，原子登记 `consumed` 后才 Git commit，并复核提交 tree/parent。失败后 Grant 可能已被消费，**不得重放**。
6. 开发回执**不是** Reviewer/R9/CI/发布凭证。正式合并和部署仍按原有独立 Reviewer → 完整 R9 → PR/CI → 受保护 main → main CI → 统一受管部署执行。

## 4. 负例、回滚与状态

必须验证：无安装/激活、伪造环境变量/审批/签名、私钥或账本权限错误、重复消费、过期、树/HEAD/base/Goal/REQ/Lane/消息漂移、跨 Lane 冲突、脏树、保护路径、增量失败/未知、`DRY_RUN` 假 PASS、`release_qualified=true`。单元测试使用临时 Ed25519 密钥与一次性 Git 仓，**不等于真实 Host UID/权限委派 E2E**。

回滚只由 root 管理员禁用或撤销 `config/dev-commit-enabled.json`，新 `--dev` 自动拒绝；保留审批、私钥与消费账本用于审计，不删除重建账本，不碰其他会话工作树。默认完整 R9 路径不变。

**当前未完成**：真实 Host 安装/激活/单次签发 E2E、独立 Reviewer、完整 R9、PR/CI/main、四服务部署、原生 Goal 全 REQ 验收；全部通过前不得宣称收口。
