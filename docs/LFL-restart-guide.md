# LFL 重启操作指南与注意事项

更新：2026-09-17。适用：本机 macOS 上的 LFL mirror Web（8903）和 Feishu 服务。

依据：本次重启事故的实际回执，以及 `184f6cc6` 中的 `scripts/restart_mirror.sh`、Web 静态资源挂载和登录实现。文中的提交号是历史证据，不是永久部署目标。后续脚本改变时，应重新核对。

> **重启完成 = 正确版本 + 正确运行根 + 页面可用 + 所需服务可用 + 目标能力生效。**
>
> `rc=0`、端口监听、`/auth/status=200` 都只是部分证据。不要从 mirror 当前 HEAD、进程 cwd 或一份共享 manifest 单独推断全部运行状态。

## 1. 先确定本次重启范围

| 场景 | 使用动作 | 验收重点 |
| --- | --- | --- |
| 只补建前端，或只更新 Web | `web` | 前端挂载、登录、页面资源、Web 新 PID |
| 只修复飞书桥 | `feishu` | 新 PID、对应心跳、连接和消息处理 |
| 两个服务都需加载公共代码或启动配置 | `all` | 两个服务分别验收；不能只看其中一个成功 |
| 只想查看状态 | `status` | 观察，不重启 |

本指南不管理 8901 模型服务，也不管理主区 Web 8902。LFL 重启不能顺带重启模型、启动第二个模型实例或修改模型参数。

同一时间只保留一个重启操作者。开始前协调其他会话；如果验收中 PID、版本或重启回执被另一轮操作改变，停止继续写入，重新确认最新状态，避免相互覆盖。

## 2. 必须区分的三个根与版本

| 项目 | 含义 | 本机示例 |
| --- | --- | --- |
| runtime root | 配置、凭据兼容文件、数据、日志和运行状态的稳定归属 | `<mirror-runtime-root>` |
| code root | 实际加载代码及前端产物的精确部署目录 | runtime root 下的某个 `.worktrees/...` |
| process cwd | 进程工作目录；本部署通常是 runtime root | 可以是 mirror 根，与 code root 不同 |
| 目标 SHA | 本次已验证、准备运行的完整 40 位提交号 | 从本次候选和 CI 证据取得，不从旧聊天复制 |

正式脚本通过 `LFL_WORKSPACE_ROOT`、`LFL_RUNTIME_ROOT`、`PYTHONPATH=<code root>/src` 分离代码和运行状态。共同使用 mirror 的 `.venv` 也不代表加载 mirror 主检出的代码。

注意：

- mirror 主检出可能停在非 main 分支。本次曾是 `evo-20260914-exec-surface-followup@eb61ecc6`。
- 本地 `main`、本地远端跟踪分支 `lfl/main`、实际远端 main 和运行版本是四个不同事实。
- main 前进并不自动证明包含当前运行版本的全部能力。上线前应检查运行线独有修复是否保留。
- 不能直接在正在服务的 code root 里 checkout、rebase、reset 或覆盖构建产物；运行进程可能继续读取磁盘文件。

## 3. 准备参数与保全当前状态

以下命令在**本机新开的 Bash 会话**执行，按顺序保留变量。先替换两个占位符。不要整篇复制执行；构建、重启、回滚属于不同步骤。

```bash
set -euo pipefail

export LFL_OP_RUNTIME='<mirror-runtime-root>'
export LFL_OP_CODE="$LFL_OP_RUNTIME/.worktrees/REPLACE_WITH_QUALIFIED_WORKTREE"
export LFL_OP_SHA='REPLACE_WITH_40_CHARACTER_QUALIFIED_SHA'
export LFL_OP_ACTION='web'  # 按本次范围选择 web、feishu 或 all

cd "$LFL_OP_RUNTIME"
```

操作前保存当前回执；目录位于运行数据区，不进入 Git：

```bash
export LFL_OP_AUDIT="$LFL_OP_RUNTIME/data/restart-audit/$(date +%Y%m%d-%H%M%S)-$$"
mkdir -p "$LFL_OP_AUDIT"

for item in data/restart-receipt.json data/runtime/runtime_manifest.json data/feishu_heartbeat.json; do
  if test -f "$LFL_OP_RUNTIME/$item"; then
    cp "$LFL_OP_RUNTIME/$item" "$LFL_OP_AUDIT/$(basename "$item")"
  fi
done

git -C "$LFL_OP_RUNTIME" status --short --branch > "$LFL_OP_AUDIT/mirror-git-before.txt"
pgrep -fl 'llm_loop\.(web|feishu|runtime\.launch)' > "$LFL_OP_AUDIT/processes-before.txt" || true
lsof -nP -iTCP:8901 -sTCP:LISTEN > "$LFL_OP_AUDIT/model-before.txt" || true
```

记录当前 code root、完整 SHA 和两个服务 PID，保留其干净目录及可用前端作为回滚候选。不要在上线前清理旧 worktree。

若本次目标来自 main，用下列读操作核对；目标也可以是单独批准的已验候选，不能自动把“最新 main”当作目标：

```bash
git -C "$LFL_OP_RUNTIME" rev-parse HEAD main lfl/main
git -C "$LFL_OP_RUNTIME" ls-remote lfl refs/heads/main
git -C "$LFL_OP_CODE" log -1 --format='%H %s'
```

这台机器正式远端名为 `lfl`。查询 PR/CI 时要明确仓库，不能默认认为 `gh` 自动选中的仓库就是正式远端。

## 4. 停旧服务前，先完成部署前检查

### 4.1 精确代码与配置

必须满足：

- code root 的 HEAD 等于目标 SHA，工作树干净。
- 本次实际候选已通过所需专项测试、全量门禁、静态检查及 A.5；发布后核对实际合并提交的 CI。
- rebase 合并导致 SHA 改变时，检查合并前后 tree 是否一致，不能仅凭“同一个 PR”转移资格结论。
- runtime root 不变；`runtime.toml`、provider 配置、兼容 `.env` 和数据继续属于该运行根。
- 改动涉及数据格式时，另查回滚兼容性。不能用旧 reader 覆盖新 schema。

### 4.2 Web 前端是独立验收项

**新 worktree 默认不包含被 Git 忽略的 `webui/dist` 和 `node_modules`。代码干净不等于部署产物齐全。**

若要启动 Web，必须在目标 code root 验证 `webui/dist/index.html` 及其引用的 JS/CSS 文件。缺产物时，先在待部署目录构建，再停旧服务：

```bash
# 仅用于尚未服务的候选目录；npm ci 会重建该目录的 node_modules。
(
  cd "$LFL_OP_CODE/webui"
  npm ci
  npm run build
) > "$LFL_OP_AUDIT/webui-build.log" 2>&1
```

项目构建命令实际为 `tsc -b && vite build`。检查命令退出码和日志，不能只看到 `dist` 目录就认为成功。失败时保持旧服务运行，先处理构建错误。

离线复用依赖时，只能在确认 `package.json`、`package-lock.json` 与已验来源逐字节一致，并核对来源依赖状态后，复制依赖到待部署目录重新构建。不应直接复制不明版本的旧 `dist`，也不要修改共享 `.venv` 的 editable 安装来“修正路径”。

**允许的窄例外：已验静态产物的机械复用。** 如果待部署提交与已知稳定版本的 tracked `webui` tree 完全相同（例如 `git rev-parse <target>:webui` 与 `git rev-parse <stable>:webui` 相同，且 `git diff <stable>..<target> -- webui` 为空），并且来源 `dist` 已在真实 Web 稳定点验收过，则可以把该 `dist` 逐字节复制到目标 linked worktree。复制前后必须记录文件数和内容树 SHA256，并再次确认目标 Git worktree 仍干净。**只要 tracked WebUI tree 不同，就不能复用旧 `dist`，必须从目标源码重新 build。**

若使用 `UI_V2_DIR`，还要核对其实际指向。默认方案是使用目标 code root 自己的 `webui/dist`，避免旧环境变量把前端指到另一版本。

### 4.3 可复制的最小检查

下面脚本只检查文件与 Git，不启动服务，也不读取凭据内容：

```bash
python3 - <<'PY'
import os, pathlib, re, subprocess

runtime = pathlib.Path(os.environ['LFL_OP_RUNTIME']).resolve()
code = pathlib.Path(os.environ['LFL_OP_CODE']).resolve()
sha = os.environ['LFL_OP_SHA']
action = os.environ['LFL_OP_ACTION']
assert re.fullmatch(r'[0-9a-f]{40}', sha), '先填写完整目标 SHA'
assert action in {'web', 'feishu', 'learning', 'all'}, '动作必须是 web/feishu/learning/all'
assert code.is_dir(), 'code root 不存在'
head = subprocess.check_output(['git', '-C', str(code), 'rev-parse', 'HEAD'], text=True).strip()
assert head == sha, f'目标不一致：{head}'
dirty = subprocess.check_output(['git', '-C', str(code), 'status', '--porcelain'], text=True)
assert not dirty.strip(), '部署代码目录不干净'
for rel in ['runtime.toml', '.env', '.venv/bin/python']:
    assert (runtime / rel).is_file(), f'运行根缺少 {rel}'
assert (code / 'scripts/restart_mirror.sh').is_file()
assert (code / 'src/llm_loop').is_dir()
if action in {'web', 'all'}:
    dist = code / 'webui/dist'
    html = (dist / 'index.html').read_text()
    assets = re.findall(r'(?:src|href)="(/ui/v2/assets/[^"]+)"', html)
    assert assets, 'index.html 未发现构建资源引用'
    for asset in assets:
        assert (dist / asset.removeprefix('/ui/v2/')).is_file(), f'缺少资源：{asset}'
print('PASS：SHA、工作树、必要路径及所需前端产物检查通过')
PY
```

这些检查不替代功能测试、候选资格审查或真实登录验收。

### 4.4 发布共享服务 desired deployment（P0-A）

从 P0-A 起，Web/Feishu 的“当前 PID”只是观测事实，**不是生命周期控制权**。正式重启前必须先由 operator 发布一个 closed-schema desired deployment，把本次准许运行的 `code root + runtime root + exact Git SHA + WebUI artifact tree SHA256` 固化为 generation。`scripts/restart_mirror.sh` 会在停任何健康服务之前机械验证该 binding；缺失或不一致即 fail-closed。

先只读查看当前 generation：

```bash
LFL_WORKSPACE_ROOT="$LFL_OP_CODE" \
LFL_RUNTIME_ROOT="$LFL_OP_RUNTIME" \
PYTHONPATH="$LFL_OP_CODE/src" \
"$LFL_OP_RUNTIME/.venv/bin/python" -m llm_loop.runtime.service_control show \
  --data-dir "$LFL_OP_RUNTIME/data"
```

首次没有记录时返回空对象，`expected_generation=0`。后续发布必须使用刚观察到的 generation 做 CAS；过期 generation 会拒绝，不允许“最后写者覆盖”。发布新候选示例：

```bash
export LFL_OP_EXPECTED_GENERATION='REPLACE_WITH_CURRENT_GENERATION_OR_0'

LFL_WORKSPACE_ROOT="$LFL_OP_CODE" \
LFL_RUNTIME_ROOT="$LFL_OP_RUNTIME" \
PYTHONPATH="$LFL_OP_CODE/src" \
"$LFL_OP_RUNTIME/.venv/bin/python" -m llm_loop.runtime.service_control publish \
  --expected-generation "$LFL_OP_EXPECTED_GENERATION" \
  --code-root "$LFL_OP_CODE" \
  --runtime-root "$LFL_OP_RUNTIME" \
  --data-dir "$LFL_OP_RUNTIME/data"
```

`publish` 只接受 tracked-clean 的 exact Git worktree；WebUI `dist` 可以是 ignored artifact，但它的内容树 SHA256 会进入 desired deployment。发布本身**不停止、不启动服务**。如发布后候选 SHA、code root、runtime root 或 WebUI artifact 发生变化，必须再发布一个更高 generation；不要原地修改旧 generation。

发布后可做无副作用 binding 验证：

```bash
LFL_WORKSPACE_ROOT="$LFL_OP_CODE" \
LFL_RUNTIME_ROOT="$LFL_OP_RUNTIME" \
PYTHONPATH="$LFL_OP_CODE/src" \
"$LFL_OP_RUNTIME/.venv/bin/python" -m llm_loop.runtime.service_control verify \
  --data-dir "$LFL_OP_RUNTIME/data" \
  --code-root "$LFL_OP_CODE" \
  --runtime-root "$LFL_OP_RUNTIME"
```

Feishu-only restart 的正式脚本会跳过 WebUI artifact 比对，但仍严格核对 roots、exact Git SHA 和 tracked-clean。Web/all 必须同时核对 WebUI artifact。

**控制面边界：** LFL 模型会话不能再用普通 `execute_command` 直接 `kill` managed Web/Feishu PID、运行 mutating restart script、或直接 `runtime.launch web|feishu`。这些路径会被机械 fence；合法路径是先 `service_control(action=status)` 取得当前 generation，再由模型判断是否需要 `service_control(action=restart, target=..., expected_generation=...)`。程序不替模型决定“要不要重启”，只限定物理控制权和 exact deployment binding。`ps`、`kill -0`、`runtime.launch --dry-run`、restart `status` 等只读观测仍保留。

`service_control restart` 会先落 durable `accepted` action receipt，再启动脱离当前 Web 进程组的 worker。worker 两阶段执行：先在**不持有 lifecycle lease** 的前提下等待 requester 会话结束（仅 web/all，run.lock 释放即过）与目标空闲（feishu 心跳/活跃 run.lock，分 target 判定；均 900s fail-closed 超时），随后才获取跨进程 lifecycle lease、复核 generation/deployment_id，并执行 official restart 直到 terminal receipt 落盘。因此等待阶段的 desired deployment publish 不会被阻塞；物理执行阶段 publish 会等待，不会在 check→execute 窗口替换部署目标。发起 restart 的模型会话应在收到 accepted receipt 后立即结束本轮，而不是轮询等待终态。

### 4.5 确认任务空闲

- Feishu：心跳必须新鲜，核对对应活 PID，`processing_msg_id` 为空且 `queue_depth=0`。
- Web：另行确认没有正在生成、排队、执行工具或后台运行的任务。使用已登录 UI 或受保护的运行状态接口。
- 心跳缺失、过期或无法解析表示“未知”，不能当作“空闲”。
- 当前脚本的 `_restart_precheck` 主要检查飞书消息和队列，**不是 Web 全部任务的空闲证明**。

## 5. 通过目标版本的正式控制面执行

不要从 mirror 主检出裸跑旧脚本。P0-A 之后，**模型/Agent 会话优先使用 `service_control` 专用工具**；人工/operator 终端仍可直接调用目标版本的 official `restart_mirror.sh`，但脚本本身会先验证 §4.4 已发布的 desired deployment binding。两种路径最终都只允许目标版本的正式脚本执行物理 stop/start。

模型会话流程：`service_control(status) → 模型判断是否需要重启 → service_control(restart, expected_generation=刚观察值) → service_control(status, action_id=...)`。不要把普通 `execute_command` 的 shell 审批或可执行性当成 shared-service lifecycle authority。

### 推进 desired deployment：先 publish，再 restart（重启 ≠ 部署）

`service_control restart`（工具或脚本）只执行**已发布**的 desired deployment 记录（`data/runtime/managed_service_deployment.json`）：它不拉取代码、不创建 worktree、不比较仓库 HEAD。记录指向哪个 code root/SHA，就原样重启哪条线。

重启前必须先核对记录与本次目标一致（模块从目标 code root 导入，下同）：

```bash
LFL_WORKSPACE_ROOT="$LFL_OP_CODE" LFL_RUNTIME_ROOT="$LFL_OP_RUNTIME" PYTHONPATH="$LFL_OP_CODE/src" \
  "$LFL_OP_RUNTIME/.venv/bin/python" -m llm_loop.runtime.service_control show \
  --data-dir "$LFL_OP_RUNTIME/data"
```

`git_head` 不等于本次目标 SHA 时，直接 restart 只会把旧线原样重启一遍——回执同样 `rc=0`、PID 同样更新，没有任何报错提示版本未变（2026-09-17 实证：记录停在 gen3/`3eaae8f6`，仓库 HEAD 已前移两个提交，restart 成功但新提交未上线）。版本推进必须先发布新 generation：

```bash
LFL_WORKSPACE_ROOT="$LFL_OP_CODE" LFL_RUNTIME_ROOT="$LFL_OP_RUNTIME" PYTHONPATH="$LFL_OP_CODE/src" \
  "$LFL_OP_RUNTIME/.venv/bin/python" -m llm_loop.runtime.service_control publish \
  --expected-generation <show 读到的当前值> \
  --code-root "$LFL_OP_CODE" \
  --runtime-root "$LFL_OP_RUNTIME"
```

- publish 是 compare-and-swap：自动落 `generation+1`，从 code root 取 `git_head` 与 WebUI artifact SHA；`expected_generation` 与当前记录不符（他人已推进）会失败——重新 `show` 后重试，不要猜值、不要循环硬撞。
- 发布前提即 §4.1/§4.2 的 qualified worktree：`verify`（脚本 fence 同款检查）绑定 code/runtime 根、SHA、tracked-clean 与 WebUI artifact tree（web/all）；发布后可先 `verify` 自检再重启。
- **不要手改 `managed_service_deployment.json` 推进代次。** 手改可产出等值 JSON，但绕开 CAS 的单调 +1 校验与租约纪律（2026-09-17 gen4 曾以手改达成，属既有实践，不是规范路径）。
- 发布与重启是两步：publish 后仍按本节执行 restart、走 §6 验收；action 回执在 `data/runtime/service-control-actions/svc-*.json`（`status`/`deployment_generation`/`detail`）。

### 人工终端

下面配置等待飞书空闲，超时仍忙则交互确认；没有明确中断任务的意图时选否：

```bash
LFL_RESTART_CODE_ROOT="$LFL_OP_CODE" \
LFL_RESTART_RUNTIME_ROOT="$LFL_OP_RUNTIME" \
RESTART_WAIT_IDLE=1 \
FORCE=0 \
bash "$LFL_OP_CODE/scripts/restart_mirror.sh" "$LFL_OP_ACTION"
```

### 自动化执行

脚本提供的非交互用法为 `RESTART_WAIT_IDLE=1 FORCE=1`，但它有一个重要边界：

> 默认最多等 300 秒；等待超时后如果仍忙，`FORCE=1` 会继续重启。它不保证“绝不打断任务”。

因此自动化必须先完成独立的 Web/Feishu 空闲检查，并具有本次中断范围的明确授权；不能把双开关本身当作安全证明。可以调整等待时长，但加长超时不能消除这个语义。

满足上述条件后，使用可持续查询的命令通道，保存日志并保留退出码：

```bash
if LFL_RESTART_CODE_ROOT="$LFL_OP_CODE" \
   LFL_RESTART_RUNTIME_ROOT="$LFL_OP_RUNTIME" \
   RESTART_WAIT_IDLE=1 \
   FORCE=1 \
   bash "$LFL_OP_CODE/scripts/restart_mirror.sh" "$LFL_OP_ACTION" \
   > "$LFL_OP_AUDIT/restart.log" 2>&1; then
  LFL_OP_RC=0
else
  LFL_OP_RC=$?
fi
printf '%s\n' "$LFL_OP_RC" > "$LFL_OP_AUDIT/restart.exitcode"
cat "$LFL_OP_AUDIT/restart.log"
test "$LFL_OP_RC" -eq 0
```

执行通道应允许脚本正常完成，并能继续查询后台命令；不要使用会在 30 秒后杀进程组的短命调用方式。原生脚本内部用 `setsid + exec` 分离服务进程，不要另拼 `nohup ... &`、`launchctl submit` 或第二套拉起逻辑。

不要因为暂时没有回执就重复启动。先检查原命令是否还在运行，以及是否已经存在新服务 PID。

## 6. 重启后逐项验收

### 6.1 进程、身份和回执

```bash
cat "$LFL_OP_RUNTIME/data/restart-receipt.json"
pgrep -fl 'llm_loop\.(web|feishu|runtime\.launch)'
lsof -nP -iTCP:8903 -sTCP:LISTEN
lsof -nP -iTCP:8901 -sTCP:LISTEN
```

检查：

1. 回执时间属于本轮，`action` 正确，`rc=0`，`git_head_full` 等于目标 SHA。
2. 只更新被选中的服务 PID；未选中的服务及 8901 模型 PID应与操作前对照。
3. `data/audit/proc_versions.jsonl` 中每个新 PID 的启动 SHA 正确、`workspace_dirty=false`。
4. 实际 code root/模块来源与部署目标吻合；不要用 cwd 或 Python 可执行文件路径代替代码来源证明。
5. 目标 worktree 仍干净，没有第二个服务实例或仍持有旧 run lock 的残留进程。

`data/runtime/runtime_manifest.json` 是共享的最后写入者视图。`all` 重启后它常由 Feishu 写入，**不能据此单独证明 Web 身份**。Web 应结合自己的启动回执、PID 对应版本记录、启动路径记录，以及需要时真实请求的 `runtime_pid` 核验。

回执也可能被另一轮重启覆盖。只要发现 SHA/PID 不符合本次预期，就重新核对，不要覆盖、回退或宣称本轮验收通过。

### 6.2 Web 页面与登录

```bash
curl -sS --max-time 5 http://127.0.0.1:8903/auth/status
curl -sS --max-time 5 -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8903/ui/v2/
curl -sS --max-time 5 -o /dev/null -w '%{http_code}\n' 'http://127.0.0.1:8903/login?next=/ui/v2/'
```

在当前启用登录的配置下，未登录请求通常应为：

| 路径 | 预期 | 能证明什么 |
| --- | --- | --- |
| `/auth/status` | 200 | **仅证明后端就绪；不能证明 Web V2 已挂载。2026-09-16 已实证 `auth/status=200` 与 `/ui/v2/=404` 可同时发生** |
| `/ui/v2/` | 303，跳转登录 | 页面路由已挂载且鉴权生效；不证明登录后应用完整可用 |
| `/login?next=/ui/v2/` | 200 | 登录页面可访问 |
| 受保护 `/health` 或 API | 未认证时可为 401 | 鉴权拒绝，不能单凭此判定后端崩溃 |

断言 `303` 时客户端必须禁用自动重定向（curl 不加 `-L`；Python `urllib` 需自定义 no-redirect Handler），否则会跟随到链尾 `/login` 的 `200`，把首跳 `303` 掩盖成“通过”。断言对象是首跳状态码 + `Location` 头（2026-09-17 验收实证，`experience:EXPERIENCE-20260917-http-303-200`）。

随后在浏览器重新登录，确认实际应用页面、JS/CSS、会话列表和一个最小请求正常。**303 到登录页只是入口验收；不能冒充登录后全功能验收。** 不要为验证方便关闭鉴权或输出 API key、cookie、完整进程环境。

当前 `WebSessionStore` 保存在进程内存中，重启 Web 后旧登录 cookie 失效，需要重新登录。这不代表聊天记录丢失。

### 6.3 Feishu 与目标能力

Feishu 需要对应新 PID 的新鲜心跳，`state=connected`；检查启动后时间段的日志。仅“进程活着”或历史上出现过“已启动”不够。`connected` 也不能替代真实消息收发验收；发测试消息应沿用用户明确授权的对象和范围。

若本次上线包含 R05 exact-read 修复，额外验证：

- `read_file` 在已配置真实上限内完整返回请求范围，不再被通用 5K 投影预算二次裁剪。
- 超限时返回连续前缀和可用的稳定恢复 ref；续读偏移单调推进，不反复返回第一页。
- 其他工具及未 opt-in 的 frozen/manual harness 保持其原有 5K 语义。
- 100,000 是本次已验配置示例，不是所有部署的固定常量；以实际 `tool_max_output_chars` 为准。
- 证据来自新服务/新 PID；旧进程或隔离函数的探针不能单独证明生产能力已生效。

## 7. 故障速查

| 现象 | 优先检查 | 处置 |
| --- | --- | --- |
| Web 端口正常、`/auth/status=200`，但 `/ui/v2/` 返回 404 | 目标 code root 的 `webui/dist`；`UI_V2_DIR`；启动时是否挂载 | **不要判重启成功。** 先补齐/构建目标前端，再只重启 Web；若复用稳定 `dist`，必须先证明 tracked `webui` tree 完全相同并记录产物 hash |
| 补建 `dist` 后仍 404 | StaticFiles 挂载只在应用创建时判断 | 文件补齐后还需要重新创建 Web 进程 |
| API 401、旧页面不断报错 | 登录会话是否因重启失效 | 刷新并重新登录；不要关闭鉴权 |
| `FATAL_RUNTIME_IDENTITY_MISMATCH` | code/runtime 根、PYTHONPATH、模块来源、遗留环境变量 | 修正精确路径和启动配置，不降级身份校验 |
| 端口被占用/服务出现两个 PID | 旧进程是否真正退出、是否存在并行重启 | 停止重复拉起；由正式脚本精确处理目标服务 |
| `knowledge_preflight_failed` | 数据目录绑定、baseline、存储权限/格式 | 保留数据和日志，解决原因后再启动；不要删索引“修复” |
| Feishu 进程活着但心跳不更新 | PID 是否对应、启动日志、WS 连接/凭据来源 | 只处理飞书问题，避免反复重启健康 Web/模型 |
| `all` 后只有一个服务正常 | 两个服务各自日志与回执，不能只看共享 manifest | 修复失败的一项，健康项保持运行 |
| 日志出现 `CancelledError` | 是否在旧 Web 的关停时间窗口 | 对照新 PID 的启动和请求结果，不把旧关停栈当成新启动失败 |
| 测试在本机红、CI 绿 | 运行时环境变量是否泄漏；原始基线是否同样失败 | 用隔离测试环境定位，不扩大豁免，不改生产配置掩盖问题 |
| `service_control_binding_failed` | desired deployment 未发布，或 code/runtime root、SHA、tracked-clean、WebUI artifact 与已发布 generation 不一致 | **不要停旧服务。** 先查 `service_control show/verify`，确认候选后以当前 generation 做 CAS 发布新 generation |
| restart 回执 `rc=0`、PID 已更新，但版本没变（新提交未上线） | 是否把 restart 当成了 deploy：desired deployment 未推进 | `service_control show` 核对 `git_head` 与目标 SHA；按 §5 先 `publish` 再 restart，重跑 §6 验收（2026-09-17 实证） |
| 普通 `execute_command` 返回“共享服务控制权拦截” | 命令试图 signal managed PID、运行 mutating restart script 或 direct runtime.launch | 不绕过 fence；改用 `service_control status → restart(expected_generation=...)`，只读 status/dry-run/probe 继续使用 |
| 验收时版本/PID 又变化 | 是否有另一会话部署 | 协调操作者，重新核验最终状态 |

日志按本轮时间和 PID 阅读：`data/web.log`、`data/feishu.log` 长期追加，混有历史记录。不要只搜索到一个旧报错就认定本次故障。

## 8. 回滚和清理

回滚前先判断失败类型。前端缺产物通常可以补建解决；不应为此回退已恢复的业务能力。

确需回滚时：

1. 选定先前保全且验证过的完整 SHA、code root 和构建产物。
2. 确认旧代码兼容当前 runtime 配置和数据 schema；不兼容则停止回滚，改做前向修复。
3. 重新设定 `LFL_OP_CODE`、`LFL_OP_SHA` 和最小动作范围，按同样的前检查操作；**回滚不是 generation 倒退**，应把已验旧 code root 作为一个新的 desired deployment，以当前 generation 为 expected 值发布下一 generation，再执行受控 restart。
4. 保留 canonical runtime root；不要用旧代码目录的数据覆盖运行数据。
5. 如回滚会暂时失去 R05 或其他已上线能力，明确记录降级范围，不能把“恢复可访问”写成“能力全部保持”。

验收完成后才能考虑清理候选。正在服务的 code root、仍需使用的回滚目录、存在未提交工作的目录不能删除。“已合并”不等于“可以清理”；进程可能继续按路径读取静态资源或加载模块。

## 9. 本次事故记录与长期注意事项

2026-09-16 的实际故障链（早期一轮）：

1. R05 已进入 `12419cff`，新的部署 worktree 被正确绑定。
2. Web/Feishu 启动回执 `rc=0`，Web readiness 成功；但新的 worktree 没有 `webui/dist`。
3. Web 应用创建时未挂载 `/ui/v2`，用户访问得到 404，表现为“重启失败”。
4. 从精确源码构建前端后，只重启 Web，页面入口恢复。
5. 验收期间另一轮部署切换到 `184f6cc6`。已核对其包含 `12419cff`，目录干净、前端存在、登录入口正常、Feishu connected、8901 模型 PID未变。该记录不等同于已完成登录后全部功能或 R05 生产行为验收。

### 9.1 同日 `c5772baa` 部署再次复现：`rc=0` 不等于 Web 可用

这次复现把根因进一步钉死，并形成可复用的恢复流程：

1. `c5772baa` 已通过 PR、A.5、security、push/PR/full CI，并 exact fast-forward 到 `main`；使用 official dual-root `restart_mirror.sh all` 后，回执 `rc=0`，Web 8903 监听正常，`/auth/status=200`，Feishu heartbeat=`connected`，8901 未重启。
2. 但用户实际访问 Web 失败。post-canary 发现 `/ui/v2/` 为 **404**。因此本轮部署必须判 **FAIL**，不能因为端口监听、`rc=0` 或 `/auth/status=200` 宣称成功。
3. 只读核验发现 target linked worktree 没有 `webui/dist`；`.gitignore` 明确忽略该目录。`create_app()` 又只在启动时发现 `webui/dist` 存在时才挂载 `/ui/v2`，所以这是确定性的部署产物缺失，不是模型、鉴权或 c577 Python 代码故障。
4. 对比目标 `c5772baa` 与上一个已验稳定 `fe209380`：两者 tracked `webui` tree SHA 完全相同（`0fd1d4939b52b08e5c6f2d8a0bb4f87a56259e95`），`git diff fe209380..c5772baa -- webui` 为空。因此可以机械复用已验稳定 `dist`，不需要把旧前端跨版本硬塞给新代码。
5. 将 fe209 的已验 `dist` 复制到 c577 worktree 后，前后各 **63** 个文件，内容树 SHA256 都为 `516bb04f8c9390824710ff41edaab134f9bf3fdde67e0cb182584dfa4f44dec8`；目标 worktree 仍 Git clean，因为 `dist` 是 ignored runtime artifact。
6. 只执行 official dual-root **Web-only restart**，不重启 Feishu，不触碰 8901。新 Web 启动后：`/auth/status=200`、`/ui/v2/` 未登录时 `303 -> /login?next=/ui/v2/`、登录页 `200`；真实浏览器会话随后访问 `/ui/v2/?session=...` 与 JS/CSS 均得到 `200`。新 PID 启动段无新的 `ERROR/Traceback`。
7. 此次也暴露出 `restart_mirror.sh` readiness 的覆盖缺口：它能在 `/auth/status` 正常时返回成功，却没有证明 Web V2 静态产物已经挂载。**今后的“Web restart success”至少必须联合验证 `/auth/status` + `/ui/v2/` + `/login`，并在部署前验证 `webui/dist/index.html` 及其引用资源存在。**

### 9.2 同日第二类事故：普通 Web 会话越权控制共享服务生命周期

另一条真实事故链与 WebUI artifact 无关：一个普通 Web 会话通过 `execute_command` 多次执行 `kill -TERM <web-pid> <feishu-pid>`，其中一次直接杀掉承载自己的 Web 进程。durable journal 完整记录为 `tool.execution.started → finished(status=success) → receipt_committed`，说明 WAL/恢复机制没有丢事实；问题是 generic shell 当时确实拥有了它不应默认拥有的共享服务物理控制权。

审计确认：CatastrophicGuard 按设计只拦不可逆系统灾难；线上 `EXEC_MODE` 为空；Web/Feishu 没有 CLI 人工 approval callback；现有 `run.lock`、JobRegistry ownership、`maintenance.lock` 分别解决会话/子进程/watchdog 协调，都不是 shared-service lifecycle authority。P0-A 因此引入独立 `service_control` surface、operator-published desired deployment、generation CAS/lifecycle lease 和 generic-shell fence。它是 LFL 工具/控制面的 fail-closed ownership boundary，**不是对同一 OS 用户下任意恶意代码的安全沙箱承诺**。

必须长期保留的注意事项：

- 禁止 `pkill -f llm_loop.web` 这类跨实例匹配；使用正式脚本识别目标端口和进程。
- 禁止从 mirror 默认检出猜版本；显式指定已验 code root 和 runtime root。
- 禁止把 `rc=0` 或 readiness 当作整站验收；前端产物与真实页面必须单列。
- 禁止把运行时测试净化方式照搬到生产。不要一律清空 `LFL_*`、凭据或 provider 配置；由已验 canonical launcher 按契约解析配置。
- 不要机械照抄脚本顶部旧注释中的 `source .env` 或手工 `python -m llm_loop.web`。本版实际启动入口已是 `python -m llm_loop.runtime.launch web|feishu`。
- 不要 dump `.env`、完整 `ps eww` 或全量环境变量来排查；只读取需要的非敏感身份字段。
- 不要使用 `launchctl submit` 临时自重启循环；不要把 `nohup` 误认为已脱离原进程组。
- 不重启 8901，不双开模型，不在同一次运维中顺带清理 worktree、迁移数据或改配置治理。

## 10. 交付回执模板

```text
操作时间 / 操作者：
动作范围：web / feishu / all
目标完整 SHA / code root / runtime root：
发布 generation / publish 回执（show 核对的 git_head）：
前端构建来源 / 退出码 / 资源检查：
忙碌检查结果及中断授权（如适用）：
重启命令退出码 / 落盘回执位置：
Web 旧 PID → 新 PID / 启动 SHA / dirty：
Feishu 旧 PID → 新 PID / 启动 SHA / 心跳时间与状态：
8901 PID 前后：
未认证入口：auth/status / ui/v2 / login：
登录后页面与最小请求验收：
目标能力验收（如 R05）：
未验项 / 并行部署导致的变更：
回滚候选及兼容性：
结论：入口恢复 / 服务恢复 / 目标能力闭环（按实际证据填写）
```

## 11. 依据文件

本文是操作指南，不代替运行时事实。执行前以目标提交中的下列文件为准：

- `AGENTS.md`、`docs/DEVELOPMENT_REPAIR_SAFETY.md`
- `scripts/restart_mirror.sh`
- `src/llm_loop/runtime/launch.py`、`identity.py`、`manifest.py`、`service_control.py`
- `src/llm_loop/tools/builtin/service_control.py`、`src/llm_loop/tools/registry.py`
- `src/llm_loop/introspection/proc_version.py`
- `src/llm_loop/web/__init__.py`、`auth.py`、`auth_routes.py`
- `webui/package.json`、`webui/package-lock.json`、`webui/vite.config.ts`

运行证据位置：`data/restart-receipt.json`、`data/restart-receipt.log`、`data/audit/proc_versions.jsonl`、`data/runtime/runtime_manifest.json`、`data/runtime/runtime_manifest.web.json`、`data/runtime/runtime_manifest.feishu.json`、`data/runtime/managed_service_deployment.json`、`data/runtime/service-control-actions/`、`data/feishu_heartbeat.json`。这些属于运行数据，应保留在其原有权限边界内，不随公开代码或报告上传。
