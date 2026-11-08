# RUNBOOK：deepin 会话接管（P0，零代码）

> **状态：未在 deepin 实机实测。** 本文按 DESIGN-20261107 §7「P0 — 会话接管（零代码）」
> 编写，命令与验收项均取自仓库现有代码/文档事实（见 §2 出处）；**没有任何一条在本轮
> 于 deepin 实机上执行过**。首次落地时按 §6「必须实机验证的项」逐条打勾，未核项不得
> 对外宣称"已验证"。

## 1. 适用与前置

- 目的：让 mac 侧浏览器通过 SSH 隧道安全访问 deepin 上的 LFL Web 面，**不暴露公网、
  不开放远端 shell**。
- 前置：
  - deepin 主机已安装并可运行 LFL（`python -m llm_loop.web` 或既有服务方式）；
  - mac 侧有可登录 deepin 的 SSH 私钥；
  - 有 deepin 的 sudo/编辑 `.env` 权限（P0-3）。
- 非目标：peer 任务通道（P1）、桌面像素面（P2）。本 runbook 不改代码、不发版。

## 2. 事实基线（本轮核对过的仓库事实）

| 事实 | 出处 |
|---|---|
| Web 默认端口 `8903`（`WEB_PORT` 缺省值） | `src/llm_loop/web/__init__.py:597` |
| `WEB_HOST` 缺省 `127.0.0.1`（非回环会被判为需鉴权） | `src/llm_loop/web/auth.py:96` |
| `WEB_API_KEY` 读环境变量；`WEB_AUTH_REQUIRE=1` 强制鉴权 | `src/llm_loop/web/auth.py:72,92` |
| 鉴权已启用但两者都没配时 **fail-closed 拒绝服务** | `src/llm_loop/web/auth.py:661-684` |
| Deepin 25 Wayland/dde-lock 两条"非 LFL 故障"排障项 | `docs/installation.md:398-409` |
| 公网暴露时 Origin/Canonical 约束 | DESIGN-20261107 §7「P0 风险」段 |

## 3. 操作步骤

### P0-1 确认 deepin 只监听回环

deepin 侧：

```bash
ss -ltnp | grep -E ':(8903)\b'
# 期望：127.0.0.1:8903（或 [::1]:8903）
# 若出现 0.0.0.0:8903 / *:8903：先改回 WEB_HOST=127.0.0.1 再继续
```

验收：输出中**不出现** `0.0.0.0` / `[::]`。

### P0-2 建 SSH 隧道并收紧 authorized_keys（D12：SSH 只做隧道）

mac 侧建立隧道（保持前台，建议先手动验证再转常驻）：

```bash
ssh -N -L 8903:127.0.0.1:8903 <deepin-host>
```

deepin 侧把该公钥行的选项收紧（`~/.ssh/authorized_keys`，选项放在 key 之前）：

```
no-pty,no-agent-forwarding,no-X11-forwarding,permitopen="127.0.0.1:8903" ssh-ed25519 AAAA... 
```

mac 侧验收（两条都必须满足）：

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8903/   # 期望 200（登录页）
ssh <deepin-host> 'id'                                             # 期望被拒绝（no-pty/permitopen 生效）
```

失败处理：
- `ssh 'id'` 仍能执行 → `permitopen`/`no-pty` 写错位置或 sshd 未重载，**不要继续**；
- 隧道起不来 → 检查本机 8903 是否被占用（`lsof -iTCP:8903 -sTCP:LISTEN`）。

### P0-3 打开 Web 鉴权（fail-closed）

deepin 侧 `.env`（或服务环境）：

```bash
WEB_HOST=127.0.0.1
WEB_PORT=8903
WEB_AUTH_REQUIRE=1
WEB_API_KEY=<至少 32 字节随机值，例如 openssl rand -hex 32>
```

重启 Web 服务后验收：

```bash
# 不带凭证：期望 401
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8903/health
# 带正确凭证：期望 200
curl -sS -H "Authorization: Bearer $WEB_API_KEY" -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:8903/health
# 带错误凭证：期望 401
curl -sS -H "Authorization: Bearer wrong" -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:8903/health
```

说明：若该部署把 `/health` 列为探针豁免路径（部署差异），把上面三条换成任一受保护
业务端点（如 `/sessions`）再测；**401/401/200 的判定不变**。若服务直接起不来，先看
日志是否命中 `auth.py:661-684` 的 fail-closed 提示（说明 `WEB_AUTH_REQUIRE=1` 但两个
凭证都没配）。

### P0-4 排除 deepin 桌面问题误判

按 `docs/installation.md:398-409` 两条逐项确认：

1. 远控黑屏但 SSH 正常 → 登录会话选 **X11（deepin）**，不是 Wayland/treeland；
2. 登录后黑屏但桌面在渲染 → SSH 执行 `kill $(pgrep -f dde-lock)`，并在系统设置关闭
   自动锁屏/唤醒锁屏。

这两条属发行版/远控环境问题，**不计入 LFL 故障**。

## 4. 日常操作

- 接管：`ssh -N -L 8903:127.0.0.1:8903 <deepin-host>`，浏览器开 `http://127.0.0.1:8903/`；
- 断开：Ctrl-C 终止隧道进程（无状态变更）；
- 轮换 `WEB_API_KEY`：改 `.env` → 重启 Web → 重新执行 P0-3 三条验收；
- 核查隧道只做转发：`ssh <deepin-host> 'id'` 必须始终被拒。

## 5. 并发操作与凭证残留（U8/U9 处置）

> 编号说明：本节沿用任务验收里的 U8/U9 命名（会话接管域）。DESIGN §9.4 的 U8/U9 是 P1
> 的 grant 撤销与证书伪造验收项，两者不要混用。

### U8：双操作者并发输入

风险：两人经同一隧道/同一浏览器会话操作，输入互相覆盖或互相打断，事后无法区分"谁下的指令"。

处置：
1. **单一写者**：同一时刻只允许一人持有浏览器标签操作，另一人只读（日志/只读页）。
2. 必须并行时：各自用**独立浏览器 profile**（不共享 cookie），并各跑独立隧道端口
   （第二个操作者 `ssh -N -L 8904:127.0.0.1:8903 <deepin-host>`），避免共享登录态与会话游标。
3. 冲突已发生：先停手 → 由当前主操作者确认最近一次有效动作 → 另一人刷新页面重同步；
   **不要用"再点一次"试探**（可能重复提交）。
4. P0 范围无操作者身份审计：需要追责时先记录时间点，等 P1 的 `data/peer/` 请求级审计上线后再定位。

### U9：旧管理员仍持 token（凭证残留）

触发：管理员轮换/离职后，旧 `WEB_API_KEY` 或旧浏览器会话仍在有效期内。

处置：
1. 轮换 `WEB_API_KEY`（`openssl rand -hex 32`）→ 改 `.env` → **重启 Web**（只改文件不重启不生效）；
2. 让旧登录会话失效：清空服务端会话并重启进程（P0 依赖进程内会话），通知所有操作者重新登录；
3. 删除或收紧旧 `authorized_keys` 行（`permitopen` 只留需要的人），验证
   `ssh -i <old-key> <deepin-host> 'id'` 必须被拒；
4. 复核 `ss -ltnp` 仍只见回环，防止"轮换期间临时开过监听忘了收回"；
5. 验收：旧 key/旧 token 请求全部 401，新 token 200（按 P0-3 三条重跑）。

## 6. 回滚

- 关隧道（Ctrl-C）即恢复到"无远程访问"；
- 若要回退鉴权：去掉 `WEB_AUTH_REQUIRE=1` 并重启——**仅在 deepin 全程只监听回环时**可接受；
- 本 runbook 不写任何磁盘状态（除 `.env` 与 `authorized_keys`，改动前先备份）。

## 7. 必须实机验证的项（首次落地逐条打勾）

- [ ] `ss -ltnp` 实际只看到回环 8903；
- [ ] mac 侧 `curl http://127.0.0.1:8903/` 得到登录页；
- [ ] `ssh <deepin-host> 'id'` 被拒绝（证明 shell 不可用）；
- [ ] 不带/错误凭证 → 401，正确凭证 → 200（三条都跑）；
- [ ] deepin 桌面在所选会话下可正常远控（或已按 P0-4 排除）；
- [ ] 重启后隧道与鉴权仍按预期（防"配了但没生效"）；
- [ ] U8 双操作者并发：按 §5 演练一次，确认无重复提交；
- [ ] U9 凭证轮换：旧 token/旧 key 全部失效，新 token 200。

## 8. 已知未覆盖

- 公网暴露（Cloudflare tunnel 等）**不在本 runbook 范围**；若采用，必须先按 DESIGN §7
  「P0 风险」配置 `WEB_ORIGIN_ALLOWLIST` / `WEB_CANONICAL_HOST`，否则 canonical 升级判定会误伤。
- 尚未验证 SYSTEMD 常驻方式的具体 unit 名与重启命令——按 deepin 侧现有服务管理方式执行。
- 本文所有命令均未在 deepin 实机执行过（见文首状态声明）。
