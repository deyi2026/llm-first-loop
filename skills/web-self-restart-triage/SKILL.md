---
name: web-self-restart-triage
description: 镜像 web 服务自愈重启失败排障技能——guard 守护反复 pull_up_fail、restart_system 报"端口 8903 已被占用"、web 挂死后拉不起来、或面板/status 误报 web 死亡（live_pid_not_running 但服务实际在响应）时使用。核心：识别探针口径矛盾（pgrep argv 失明 vs 端口 lsof vs HTTP /health vs manifest 观察面失真），按单一权威探针修复守护的停止/启动幂等链。含两条重启通道（service_control vs restart_system）的边界纪律、三服务（web/feishu/learning）受理差异与就绪探针、受理≠完成的终态核对、已知上游诱因（流式滴流挂死、启动超时误报、短命进程覆盖 manifest）。常用工具: execute_command/read_file/search_files。
---

# 镜像 web 自愈重启排障（web-self-restart-triage）

守护（guard_system.sh loop，launchd `com.user.llm-loop-guard`）反复拉不起 web、或 web 挂死后自愈失败时，按本流程定位。**核心：先钉死探针矛盾，再修幂等链，最后回归验证——不猜测、不重复按重启。**

## 为什么需要这个 skill（2026-09-24 实证血泪）

`data/guard.log` 11:16 连续两轮死锁（旧守护）：

```
detect_fail  svc=web detail=服务不健康
pull_up_start … restart_system.sh restart
[restart_system] [web] 未运行，跳过停止          ← 停止探针说没进程
[restart_system] ERROR: [web] 端口 8903 已被占用  ← 启动探针说端口有人
pull_up_fail  svc=web detail=restart 失败（进入退避）
```

**根因是双探针口径矛盾**：

| 探针 | 实现 | 对 runtime.launch 进程的行为 |
|---|---|---|
| 停止路径 | `pgrep -f "$PROJECT_DIR/.venv/bin/python -m llm_loop\.web"` | **失明**——正式服务经 `python -m llm_loop.runtime.launch web` 启动，argv 不匹配 |
| 启动路径 | `lsof -iTCP:8903 -sTCP:LISTEN` | 准确——端口被占即拒启 |
| 健康路径 | HTTP `/health`（或端口+进程组合，见 542d98ccf 修复） | 准确但受进程挂起影响 |

web 进入 **unhealthy-but-alive**（事件循环挂起/长阻塞——典型如已修复的流式滴流 1a146b176）时：健康探测失败 → 守护决定重启 → 停止探针 pgrep 失明说"未运行，跳过停止" → 活着的进程仍占端口 → 启动 `_die 端口已被占用` → 退避循环，**永远拉不起**。只有进程真死透才恢复（11:32 那次成功恰是进程已崩）。

## 排障流程

### Step 1 — 识别失败形态（30 秒定分类）

```bash
tail -50 data/guard.log
tail -5  data/restart-receipt.log        # service_control 通道的成败（rc=1 带 detail）
lsof -tiTCP:8903 -sTCP:LISTEN            # 端口现状（谁在占）
curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8903/auth/status
```

三类形态与对应根因：

1. **`未运行，跳过停止` + `端口已被占用` 同现** → 双探针矛盾（本 skill 主体）
2. **receipt rc=1 `webui_artifact_preflight_failed`** → webui/dist 与 index 引用不一致，先 `cd webui && npm run build`
3. **receipt rc=1 `service_control_binding_failed` / CLI `dirty_worktree` / `git_head mismatch`** → 权威通道门禁（见下文通道边界），publish 前须 clean tree + rebuild dist
4. **面板/status 报 `restart_required: live_pid_not_running` 但 lsof 端口有监听者、/health 有响应（401 也是响应）** → **观察面失真，不是真死**：`runtime_manifest.web.json` 的 pid 被短命进程覆盖（2026-09-24 11:32 实证：真实 web 90846 监听中，manifest 却记 5 秒后退出的探测进程 90928）。处置：对照 manifest pid 与 `lsof -tiTCP:8903`，以端口为准；勿按面板误报盲目 restart。根因已修（v0.6.21 活进程守卫，813e0b470），旧代码进程需换代生效。

### Step 2 — 进程真伪鉴定（unhealthy-but-alive vs 真死）

```bash
pgrep -fl "runtime.launch web"           # 正确的 argv 模式（不是 llm_loop\.web）
lsof -tiTCP:8903 -sTCP:LISTEN            # 有 PID = 进程活着占端口
kill -USR1 <web_pid>                     # SIGUSR1 → faulthandler 全线程栈进 web.log
grep -A16 "Current thread" data/web.log | tail -20
```

栈顶判读：`ssl.py read / httpcore` = 挂在等 provider 字节（流式滴流，1a146b176 已修，需进程换代生效）；`queue.get / Event.wait` = 空闲但健康探测误判；`mkdir / 文件 IO` = 持久化路径。

**判死前先对三个口径**（2026-09-24 11:34 教训）：面板/status 的 pid 来自 `runtime_manifest.web.json`（last-writer，可能被短命进程污染）→ 与 `lsof -tiTCP:8903`（端口权威）+ HTTP 响应三方对照。任一口径显示服务在响应 → 按"观察面失真"处置（见 Step 1 形态 4），不当真死处理。

### Step 3 — 修复原则（写代码时遵守）

1. **单一权威探针 = 端口**（`lsof -tiTCP:$PORT`）。进程类信息只作展示，不作停止判定——argv 会随启动通道漂移（llm_loop.web → runtime.launch web），端口不会。
2. **restart 必须幂等于"端口占用"**：启动前撞端口 ≠ `_die`，而是"端口有人 → 按端口 PID 优雅停（SIGTERM→等→SIGKILL）→ 重启"。参考 restart_mirror.sh `_stop_web` 的成熟实现（端口 lsof ∪ argv，双源停止、等 PID 退出）。
3. **健康超时**：web 冷启动（大会话/大注册表）实测可 >20s——`STARTUP_WAIT_S` 至少 60s，或先探进程活着再续等。
4. **禁止把 service_control 的绑定门（clean tree / publish / dist hash）搬进守护**：守护必须在 agent 有 WIP 的 dirty tree 下可靠工作，绑定校验属于权威通道的职责分层（见下）。

### Step 4 — 两条重启通道的边界（不要混用语义）

| | service_control restart（权威） | restart_system.sh（守护自愈） |
|---|---|---|
| 入口 | `python -m llm_loop.runtime.service_control restart --target web` | guard_system.sh → restart_system.sh |
| 门禁 | 部署绑定（clean tree、git_head=published、dist hash） | 无绑定门（按设计） |
| 适用 | 代码变更后的计划重启、版本推进 | 进程死亡/挂起的自愈拉起 |
| 产物 | restart-receipt.json（authoritative=true） | guard.log 记录 |
| target 范围 | web / feishu / learning / all（同名） | 同左（restart_mirror.sh 亦接受 learning） |

计划性重启走权威通道（先 commit → 需要时 build dist → `publish` → restart）；**自愈只求"把服务拉起来"**，不做部署裁决。守护若也去查 clean tree，agent 每次写代码都可能让自愈瘫痪——这是职责倒置。

**三服务差异（受理时按此排序与验证）**：

| target | 就绪探针 | 受理/门禁差异 |
|---|---|---|
| web | 端口 `lsof -tiTCP:8903` + `/health`（401 也是响应） | 断宿主会话（两阶段：会话结束后才执行） |
| feishu | 心跳 `data/feishu_heartbeat.json`（state=connected + pid；WS 波动 15~55s 正常） | 等目标空闲；不影响会话 |
| learning | manifest `runtime_manifest.learning.json`（service=learning + pid；无端口/心跳） | **空闲门**（在飞任务排空才执行，busy=持锁且有 in-flight）；fail-open 退避不影响 web |

多服务换代受理顺序（2026-09-24 实践）：**feishu → learning → web**（web 最后，减小宿主会话被先断导致的观察盲区）；或逐单受理 web 置末。守护（v0.6.20）对 feishu/learning 以**进程存活为底线**，半僵/部署一致性归权威通道面，guard 不越权。

**权威通道受理纪律（EVO-20260924-8266b693，2026-09-24 实证）**：
- 受理回执 ≠ 完成——restart 是异步两阶段（先等 requester 会话结束、再等目标空闲），终态发生在发起会话之外；
- 终态核对三入口：`service_control(action=status, action_id=...)`（回执摘要）、`event_stream(query=service_action_terminal)`（统一事件流）、`data/restart-receipt.log`（rc=1 带 detail）；
- failed 终态保留待确认：`service_control(action=verify_acknowledge, verdict=accept)` 显式销账；不确认则每次新会话开场自动提醒（不静默消失）；
- 发布前 CAS 缺口：desired 与实际 git_head 不一致时 restart 直接 `deployment binding failed`——先 `publish` 推进 desired 再 restart，不硬重试；
- **版本三件套**：CHANGELOG + pyproject bump + git tag 同次提交——缺任一项，重启后横幅显示 `-dev` 后缀（2026-09-24 实证：只写 CHANGELOG 不 bump/tag，横幅停在 v0.6.15-dev.253）。

### Step 5 — 回归验证（修完必须做）

```bash
# 模拟 unhealthy-but-alive：挂起 web 进程（SIGSTOP 保留端口占用）
kill -STOP $(lsof -tiTCP:8903 -sTCP:LISTEN)
# 等守护 1-2 个检测周期（默认 20s/轮），观察 guard.log：
#   应看到 按端口停止（SIGTERM）→ 拉起 → pull_up_ok
kill -CONT <pid> 2>/dev/null || true   # 清理残留（若守护已按新逻辑停旧进程则无残留）
```

再加一条单测（参考 tests/scripts/test_restart_mirror_hardening.py 模式）：_stop_service 对"端口占用但 pgrep argv 失明"的桩进程必须仍能停止。

## 已知上游诱因（先排除再深挖）

1. **流式滴流挂死**（2026-09-24 上午，已修 `1a146b176`）：read-timeout 只限字节间隔，provider 滴流可无限拖 → 事件循环阻塞 → unhealthy-but-alive 的主要来源。**修复需进程换代**——旧进程不重启就还会复发。
2. **健康探测把"认证 401/重定向"当不健康**：`/health` 在 `WEB_AUTH_REQUIRE=1` 下按设计需认证——守护探测必须用免认证端点（`/auth/status`）或带本地凭据，否则永远"不健康"。
3. **web.log 40MB 触发轮转**（restart_system 内置 ≥20MB 轮转）——轮转瞬间日志断流不是故障。
4. **短命进程覆盖 manifest → 面板误报死**（2026-09-24 11:32，已修 `813e0b470`/v0.6.21 活进程守卫）：restart 探测路径的短命进程在真实 web 之后写 `runtime_manifest.web.json`，面板按已死 pid 误报 `live_pid_not_running`。守卫：specific 身份只允许被"旧持有者已死/就是自己"的写入刷新；**需进程换代生效**。

## 红线（不要做）

- ❌ `pkill -f llm_loop.web`——会误杀旧主区（:8902），历史事故，必须带 PROJECT_DIR 限定或按端口
- ❌ 守护里加 `git status` 检查/`publish`——自愈与部署裁决混层
- ❌ 撞端口就换 `WEB_PORT=xxxx` 启动——制造双进程/端口漂移，掩盖根因
- ❌ 不看 guard.log 直接手甩 restart——先分类（Step 1），三类根因处置完全不同
