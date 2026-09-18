# 镜像重启指南（Mirror Restart Guide）

> 适用范围：镜像工作区（主区同级 `*-mirror` 目录，web :8903 + 飞书桥）常驻服务的重启操作。
> 唯一重启入口：`scripts/restart_mirror.sh`（2026-09-09 加固版）。
> 相关协议：`docs/MIRROR-workspace-protocol.md`；事故证据见 `experiences/EXPERIENCE-20260828-*`、`experiences/EXPERIENCE-20260829-*`。

## 1. 镜像里跑的是什么

| 服务 | 命令 | 锚点 | 就绪判据 |
|---|---|---|---|
| web | `python -m llm_loop.web` | 端口 **8903**（主区 8902 互不监听） | `GET /auth/status` 返回 `{"status":"ok",...}` |
| feishu | `python -m llm_loop.feishu` | 无端口；WS 长连 msg-frontier.feishu.cn | `data/feishu_heartbeat.json` 的 `state=connected` |

## 2. 什么时候需要重启

| 场景 | 动作 |
|---|---|
| 改了镜像 `.env` / 配置（web/feishu 常驻进程读 env，改文件不热生效） | `restart_mirror.sh all` |
| 经审批 promotion 后代码同步到镜像，需加载新代码 | `restart_mirror.sh all` |
| web 或飞书桥单服务挂死/异常 | 只重启对应服务（`web` / `feishu`） |
| 想确认现状，不确定要不要重启 | `restart_mirror.sh status`（无副作用） |

## 3. 标准命令

```bash
cd <镜像根目录>   # 即本仓库根

bash scripts/restart_mirror.sh status   # 查看现状：web 8903 / feishu 心跳 / 主区 8902
bash scripts/restart_mirror.sh web      # 只重启 web（默认）
bash scripts/restart_mirror.sh feishu   # 只重启飞书桥
bash scripts/restart_mirror.sh all      # 全量重启（web + feishu）
```

**AI/自动化代执行**（后台 job、非 tty 环境 `read` 撞 EOF 必取消，双开关缺一不可）：

```bash
RESTART_WAIT_IDLE=1 FORCE=1 bash scripts/restart_mirror.sh all
```

- `RESTART_WAIT_IDLE=1`：重启前 poll 飞书心跳（`processing_msg_id`/`queue_depth`）至空闲（默认 300s 超时，`RESTART_WAIT_IDLE_TIMEOUT_S` 可调），防止打断进行中的长任务；
- `FORCE=1`：等待超时后免交互确认（责任在调用方）。
- 飞书 WS 握手实测 15~55s 波动（脚本轮询至多 90s），整个 `all` 重启预期 **1~2 分钟**，请用后台 job 或足够长的超时执行。

## 4. 重启前二查

1. **查飞书心跳**：`data/feishu_heartbeat.json` 的 `processing_msg_id` 非空或 `queue_depth>0` = 有任务在跑——等完成，或人工确认可中断再重启（`FORCE=1` 会跳过确认）。
2. **查 launchd 残留**：`launchctl list | grep lfl`——确认无遗留 launchd 重启作业（2026-08-28 无限复活事故源头）。

## 5. 重启后四验

```bash
bash scripts/restart_mirror.sh status
```

1. **status 全绿**：`web ✅ pid <新pid>` + `feishu ✅ ... (hb: connected)`；
2. **心跳文件** `data/feishu_heartbeat.json` 的 `state=connected` 且 `pid` = 新进程（脚本 lsof 告警「未见 feishu.cn 连接」多为时序误报，以心跳文件为准）；
3. **web.log 的 `Shutting down` 计数冻结**：`grep -c "Shutting down" data/web.log` 间隔 20s 两次取样不变（持续增长 = 有外部循环在杀 web，追查 PPID=1 的派生者 + launchd）；
4. **主区 8902 零外溢**：重启前后主区健康状态一致（镜像操作不得影响主区）。

**回执落盘（唯一可独立核查载体）**——stdout 回执会随宿主 shell 死亡消失，落盘不会：

```bash
cat data/restart-receipt.json   # 最新一次（覆盖）
tail data/restart-receipt.log   # 历史追加
# 字段: ts / action / rc / git_head / web_pid / feishu_pid / detail
```

`rc=0` = 成功；`rc=1` 时看 `detail`（如 `web_stopped=0` = 停止失败已跳过启动防双进程）。

## 6. 红线（历史实证事故，绝对禁止）

| 禁止 | 后果（实证） |
|---|---|
| `pkill -f "llm_loop.web"` | 主区/镜像进程命令行相同，会**误杀主区 web（:8902）**（2026-08-22）。正确做法：按端口 `lsof -tiTCP:8903`（脚本已内置） |
| `launchctl submit` 执行重启 | submit = KeepAlive 常驻作业，退出即重拉 → web 陷入每 ~30s 循环重启（2026-08-28，web.log 累计 100 次 Shutting down） |
| 手写 `nohup python -m llm_loop.web &` 启动 | 绕过脚本的 DSH 环境隔离/凭证清理/PYTHONPATH 注入/WEB_PORT 设置（见 §7），且不换进程组，会被调用方超时 killpg 波及 |
| 服务启动省略 `PYTHONPATH=<镜像>/src` | 共享 venv 的 editable .pth 指向**主区** src → 镜像加载主区代码，验证失真（协议 §3/§7） |
| 翻转共享 venv 的 `__editable__*.pth` 指向镜像 src | 反向毒化主区一切无显式 PYTHONPATH 的 import（2026-08-29，两个方向都是事故） |
| 停止失败后强行启动 | 制造双进程（旧进程持 `<session>.run.lock`，新请求全被判「另一进程执行」）。脚本已内置保护：停失败即跳过启动 |

## 7. 脚本内置的隔离机制（为什么必须走脚本）

- **按端口杀 + argv 精确识别**：web = 端口 lsof ∪ 镜像 venv 绝对 argv（能找到已释放端口但持 run lease 的 stale owner）；feishu = 心跳 pid（≤180s 新鲜度门，防 PID 复用误杀）∪ argv 兜底（uv 启动会改写 argv）。等待 **PID 本身退出**而非仅端口释放。
- **等 PID 退出**：SIGTERM 后最多等 10s，仍存活则 SIGKILL；旧 PID 未退出 / 端口仍占用 → 拒绝启动新进程。
- **`_prep_dsh_env` 环境自卫**：
  - 服务身份恢复真实账户 `HOME`/macOS `TMPDIR`（不继承调用方沙箱，2026-09-11 MCP Console 事故）；
  - `DSH_HOME=<镜像>/data/dsh-home`（dsh_task 会话目录按镜像 workspace_key 解析）；
  - `unset` 清理跨区污染键：`LFL_DATA_DIR`/`DATA_DIR`（否则镜像直读主区 data）、`PYTHONPATH`（残留主区 src）、`FEISHU_APP_ID`/`FEISHU_APP_SECRET`（单边残留 = 凭证错配对 → 飞书预检 10014）、`DSH_SESSION_*`。
- **配置归 python resolver**：`WEB_PORT`/`WEB_HOST` 经 `PYTHONPATH=<镜像>/src` 查询 runtime resolver（.env 权威 + 外部 shell 残留 8902 不压过镜像 8903），空值用 `${VAR:-default}` 兜底（`$(cmd || echo x)` 兜不住空串成功）。
- **`_spawn_detached` 进程脱离**：python `setsid()+execvp()`（macOS 无 setsid(1)；nohup 不换进程组）→ 新会话/新进程组，调用方 shell 超时 killpg 不牵连。
- **失败补偿**：`all` 分支各服务独立成败（web 停/启失败不再短路吞掉 feishu 恢复），聚合退出码。

## 8. 常见故障排查

| 症状 | 原因 | 处理 |
|---|---|---|
| 新进程报 `Errno 48` 地址被占 | 旧进程未真正退出（曾因 resolver 空输出假停机） | `lsof -nP -iTCP:8903` 找占端口者；确认是镜像 web 后按 pid kill，再重跑脚本 |
| feishu 预检 `10014 app secret invalid` | shell 残留单边 `FEISHU_APP_ID` 与文件 SECRET 错配对 | 走脚本启动（内置 unset）；手工诊断：`env \| grep FEISHU` 找残留 + 比对 app_id 前 10 位归属 |
| 心跳显示 connected 但服务无响应 | 进程被杀时心跳不写终态（残留假象） | 存活判定以 pgrep/lsof 为准，心跳只作辅助 |
| web 30s 未就绪 | 启动崩溃 | `tail -20 data/web.log` 看异常栈 |
| feishu 启动即退出 | 凭证占位符/网络 | `tail -8 data/feishu.log`（真凭证在 `.feishu.env`，不能是 `cli_xxx` 占位符） |
| status 显示 web ❌ 但 8903 可访问 | 加载了主区代码或绑错端口 | `ps eww <pid>` 查进程 `PYTHONPATH` 是否 = 镜像 src、端口是否 8903 |
| web.log `Shutting down` 计数持续增长 | 外部循环在杀 web（launchd 作业等） | `launchctl list \| grep lfl` 找作业并 `launchctl remove <label>`；追 PPID=1 派生者 |

## 9. 实例（2026-09-14 本镜像真实重启）

```text
$ RESTART_WAIT_IDLE=1 FORCE=1 bash scripts/restart_mirror.sh all   # 后台 job 执行
[mirror] 13:50:48 停止镜像 Web pid(s): 91734  (port 8903)...
[mirror] 13:50:49 已停止（旧 PID 全部退出）
[mirror] 13:50:50 飞书桥已停止 (pid 30190)
[mirror] 13:50:58 ✅ web 就绪: http://127.0.0.1:8903/ (pid 94809)
[mirror] 13:51:37 ✅ 飞书桥心跳 connected (pid 94936)
[mirror] 13:51:37 回执已落盘: data/restart-receipt.json (rc=0)

$ cat data/restart-receipt.json
{"ts": "2026-09-14T13:51:37+08:00", "action": "all", "rc": 0, "git_head": "2d247ba7",
 "web_pid": 94809, "feishu_pid": 94936, "detail": "web_stopped=1 feishu_stopped=1"}
```

四验全过：status 全绿、心跳 connected 且空闲、Shutting down 计数冻结、主区 8902 前后一致（零外溢）。全程约 50s（web 就绪 9s + feishu WS 握手 39s）。

## 10. 相关文档

- `docs/MIRROR-workspace-protocol.md` — 镜像工作区协议（变更门禁/隔离边界/共享 venv 协议）
- `scripts/restart_mirror.sh` — 脚本本体（头部注释含全部设计依据）
- `tests/scripts/test_restart_mirror_hardening.py`、`tests/unit/test_restart_mirror_script.py` — 脚本行为回归
- `experiences/EXPERIENCE-20260828-mirror-restart-launchd-trap.md` — launchctl 无限复活事故
- `experiences/EXPERIENCE-20260829-restart-mirror-r2-triple-failure.md` — 共享 venv/PYTHONPATH/凭证错配三连环事故

## 12. T0 增补（2026-09-16）: CODE_ROOT 来源判定 / 嵌套禁令 / worktree registry

同日两起事故的制度化修复（实现见 `scripts/restart_mirror.sh` T0-A3 块、
`src/llm_loop/runtime/worktree_registry.py`、`scripts/bootstrap_worktree_registry.py`）：

1. **CODE_ROOT 来源三态**（`_code_root_source_check`，位于根校验之前）：
   - 脚本目录默认（未设 `LFL_RESTART_CODE_ROOT`）→ 通过；
   - 调用点显式（环境值==脚本目录，或 `LFL_RESTART_CODE_ROOT_CONFIRMED=1`）→ 通过；
   - 疑似会话残留（环境值≠脚本目录且未确认）→ 告警+审计
     `data/audit/restart_preflight.log`；**自动化通道（非 tty 或 FORCE=1）直接 abort**。
   事故案例：17:22 会话环境残留指向旧 worktree，`service_control` 缺失才暴露。
2. **嵌套 worktree 禁令**（dual-root 校验内 + `--check-add` guard）：
   CODE_ROOT 内含嵌套 worktree 一律拒绝；创建前用
   `scripts/bootstrap_worktree_registry.py --check-add <path>` 预检（拒绝 rc=2，
   审计 `data/audit/worktree_guard.log`）。主 worktree 下挂 `.worktrees/` 是既定布局，不算嵌套。
3. **worktree registry**（`data/audit/worktree_registry.json`，fail-open 非承重）：
   bootstrap 全量落表，默认唯一 protected=现役 code root（`runtime_manifest.json`
   的 workspace_root）+显式回滚候选，其余标 legacy；人工 retired 标记不被覆盖；
   缺失/损坏时消费方降级既有校验。GC（A4，9/19 再议）：只标记永不自动删除。
4. `restart_mirror.sh preflight`：只读 dry-run（根校验+来源判定+webui 产物预检），
   不触服务、不验 service_control 绑定；测试与运维共用。
5. bash 陷阱记录：`$VAR` 后紧跟多字节字符（如全角括号）会被吞首字节成
   `VAR\xef: unbound variable`——一律 `${VAR}`。
