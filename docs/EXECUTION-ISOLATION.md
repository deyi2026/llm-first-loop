# 执行隔离边界声明（Execution Isolation Boundary）

> 状态：v0.6.14 起生效。本文如实声明 `execute_command` 在不同配置下的**实际**隔离能力与边界，
> 不宣称未实现的安全性。代码实现见 `src/llm_loop/tools/sandbox.py`。

## 运行条件（由 `EXEC_SANDBOX` 决定）

| 条件 | 配置 | 平台 | 隔离强度 | 网络隔离 |
|---|---|---|---|---|
| A. 个人受信宿主 | `EXEC_SANDBOX=none` 或 `auto` 解析到 none | 任意 | 无内核隔离 | 无 |
| B. bwrap 沙箱 | `EXEC_SANDBOX=bwrap` / `auto`（Linux 命中） | 仅 Linux | 命名空间 + 只读系统目录 | **无**（未 unshare network） |
| C. docker 容器 | `EXEC_SANDBOX=docker` / `auto`（daemon 在跑且未命中平台首选——darwin 首选 sandbox-exec） | macOS/Linux | 容器边界 + 断网 + 只读 rootfs | 有（`--network=none`） |
| D. sandbox-exec | `EXEC_SANDBOX=sandbox-exec` / `auto`（darwin 首选） | 仅 macOS | 仅写域约束（工作区 + 缓存目录） | **无** |

**fail-closed 契约**：显式配置 B/C/D 而对应后端（`bwrap` / `docker` CLI / `/usr/bin/sandbox-exec`）
缺失 → 命令**拒绝执行**，不静默降级到无沙箱路径；`auto` 解析到 none 时默认放行为无沙箱执行，
但**必写一次 warning**（列出全部原因，不静默），`EXEC_SANDBOX_STRICT=1` 时同样 fail-closed。

> 2026-10-25（P2-1）：`EXEC_SANDBOX` 默认值从空/none 改为 **`auto`**——首次执行时按平台
> 顺序解析（darwin：sandbox-exec → docker；其余：bwrap → docker → sandbox-exec → none），
> 详见文末「auto 解析与平台矩阵」。

## 条件 A：个人受信宿主（EXEC_SANDBOX=none，或 auto 解析到 none）

**适用**：开发者本机、单用户、自己对自己负责的运行环境。

**实际边界**：
- 唯一防线是 `CatastrophicGuard` 硬阻断清单（灾难性命令模式，如 `rm -rf /` 类、fork 炸弹类）。
- **没有**任何内核级隔离：进程以当前用户全部权限运行，可读用户全部可达文件、可联网。
- 工作目录白名单之外仍可被命令触达（阻断的是"灾难模式"，不是"越界访问"）。

**不适用**：多租户、不受信任务来源、无人值守自动化。这些场景必须用条件 B/C。

## 条件 B：bwrap（Linux）

提供：独立 PID/UTS/IPC 命名空间；`/usr /etc /lib /lib64 /bin /sbin` 只读绑定；`/tmp` 为 tmpfs；
工作区可写绑定；`shell=False` 执行。

**如实声明的边界**：
- **网络未隔离**（配置未含 `--unshare-net`）——沙箱内命令可访问网络。
- bwrap 基于 Linux user namespace；macOS 无此工具，配置 B 在 macOS 上 fail-closed 拒执行。

## 条件 C：docker 容器（macOS 可用的唯一容器路径）

`docker run --rm --network=none --read-only --cap-drop ALL --pids-limit 256 \
--tmpfs /tmp --user <uid>:<gid> -v <workdir>:<workdir>:rw -w <workdir> <image> sh -c <command>`

- 断网（`--network=none`）；rootfs 只读，仅工作区与 `/tmp` 可写。
- `--user uid:gid` 与宿主当前用户一致：容器内新建文件在宿主上保持原属主，不产生 root 属主文件。
- 镜像默认 `python:3.13-slim`，可用 `EXEC_SANDBOX_IMAGE` 覆盖（命令依赖的运行时决定选型）。
- **如实声明的边界**：docker daemon 以较高权限常驻（本方案隔离的是**命令**，不是 daemon 自身）；
  工作区 bind-mount 对容器完全可写；`--user` 之外的宿主 HOME 等路径不可达（未挂载）。
  daemon 未启动时命令如实失败，不降级。

## 与既有防护的关系（对所有条件成立）

- `CatastrophicGuard` 硬阻断：前置于一切执行路径。
- 环境变量脱敏（`execute_command_scrubs_env`）、工作目录白名单、超时与输出截断：独立于沙箱条件。
- 沙箱 note 会如实写进回执（`已启用 bwrap/docker 沙箱…`），模型与审计方可见。

## 升级路径（记录，非承诺）

container 方案后续可扩展：CI runner 上以条件 B/C 为门禁（未启用沙箱的执行视为环境异常）；
受限镜像白名单（按任务类型锁定可用运行时）；`--unshare-net` 纳入 bwrap 配置以对齐 C 的网络边界。

## auto 解析与平台矩阵（2026-10-25，P2-1/S2-6）

`EXEC_SANDBOX` 默认值从空/none 改为 `auto`。auto 在**首次执行时**按平台顺序解析，
结果**进程内缓存**，并写一次日志（解析到 none → warning，明确列出全部原因，绝不静默）：

- **darwin**（P1-1，Rule28 修复轮）：`sandbox-exec` → `docker` → `none`。
  顺序理由：docker-on-darwin 运行的是 Linux 镜像（`--network=none` 的
  `python:3.13-slim`），宿主 `.venv`（Mach-O）在容器内 exec-format 失败，且首个
  用户会被 image pull 卡住；macOS 原生 sandbox-exec 无此问题，故 darwin 上首选。
  auto 落到 docker-on-darwin 时打一条 `logger.warning`（提示显式设
  `EXEC_SANDBOX=none/docker` consciously）。
- **其余平台**（维持既有顺序不变）：`bwrap`（`shutil.which("bwrap")` 命中）→
  `docker`（docker CLI 存在且 `docker info` 在 2s 内成功；探测结果进程内缓存）→
  `sandbox-exec`（仅 darwin，其余平台恒不可用）→ `none`。

`EXEC_SANDBOX_STRICT=1`：auto 解析到 none → 命令 fail-closed 拒绝执行（RuntimeError，回执如实失败）。
默认不 strict——docker daemon 未启动等场景下常规命令仍可用（落到次优后端，或 none + 告警），
避免默认配置把本机命令全部锁死。显式 `none` 不受 strict 影响（明确意图不拦截）。

### 平台矩阵

| 平台/环境 | auto 实际落到 | 隔离强度 | 网络隔离 | 回执 note |
|---|---|---|---|---|
| Linux + bwrap 已装 | `bwrap` | 命名空间 + 只读系统目录 + 工作区可写 | 无 | 已启用 bwrap 沙箱：只读系统目录/工作区可写/未隔离网络 |
| Linux（无 bwrap）+ docker daemon 运行 | `docker` | 容器边界 + 断网 + 只读 rootfs + 工作区可写 | 有 | 已启用 docker 沙箱：断网/只读 rootfs/工作区可写 |
| darwin + sandbox-exec 可用（即使 docker daemon 也在跑） | `sandbox-exec` | **仅写域约束**（工作区 + /tmp + /dev + 缓存目录） | 无 | 已启用 macOS sandbox-exec 沙箱：仅允许写工作区与缓存目录/未隔离网络 |
| darwin + sandbox-exec 不可用 + docker daemon 运行 | `docker`（附 warning：宿主 venv 不兼容，建议显式选择） | 容器边界 + 断网 + 只读 rootfs + 工作区可写 | 有 | 已启用 docker 沙箱：断网/只读 rootfs/工作区可写 |
| 全无 | `none` | 无内核隔离（仅 CatastrophicGuard deny-list） | 无 | 不加任何"已隔离"措辞 |

### 条件 D：sandbox-exec（macOS）如实边界

- profile：`(version 1)(allow default)(deny file-write*)(allow file-write* (subpath <root>))`
  ——**只约束写**。可写根 = 工作区 + `/tmp` + `/private/tmp` + `/dev` + `~/.cache` +
  `~/Library/Caches` + `~/.npm`，可用 `EXEC_SANDBOX_MACOS_WRITABLE`（os.pathsep 分隔）追加；
  路径在 profile 中做 S 表达式转义（双引号/反斜杠），防策略注入。
- **不隔离网络、不限制读**：沙箱内进程可联网、可读用户全部可达文件（含 `~/.ssh`、`.env`）——
  外泄面必须依赖出站闸门与环境脱敏，**不能**指望本后端。
- 执行形态：`/usr/bin/sandbox-exec -p <profile> /bin/bash -lc <command>`（shell=False）。
- 非 darwin 平台或 sandbox-exec 不可用时显式配置 → fail-closed 拒绝执行。

### worktree 语义（S2-6）

`execute_command(isolation=true)` 是 git worktree **施工面**隔离（防未提交改动互扰），
**不是系统沙箱**：命令经绝对路径/跨目录操作仍可越界。工具描述与回执附注统一携带
"（worktree 隔离，非系统沙箱）"从句，防止调用方把 `isolation=true` 误读为安全隔离。
