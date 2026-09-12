# 执行隔离边界声明（Execution Isolation Boundary）

> 状态：v0.6.14 起生效。本文如实声明 `execute_command` 在不同配置下的**实际**隔离能力与边界，
> 不宣称未实现的安全性。代码实现见 `src/llm_loop/tools/sandbox.py`。

## 三种运行条件（由 `EXEC_SANDBOX` 决定）

| 条件 | 配置 | 平台 | 隔离强度 | 网络隔离 |
|---|---|---|---|---|
| A. 个人受信宿主（默认） | `EXEC_SANDBOX` 空 | 任意 | 无内核隔离 | 无 |
| B. bwrap 沙箱 | `EXEC_SANDBOX=bwrap` | 仅 Linux | 命名空间 + 只读系统目录 | **无**（未 unshare network） |
| C. docker 容器 | `EXEC_SANDBOX=docker` | macOS/Linux | 容器边界 + 断网 + 只读 rootfs | 有（`--network=none`） |

**fail-closed 契约**：显式配置 B/C 而对应后端（`bwrap`/`docker` CLI）缺失 → 命令**拒绝执行**，
不静默降级到无沙箱路径。

## 条件 A：个人受信宿主（当前默认）

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
