# MCP Console v0.1.411 SIGABRT 崩溃报告（macOS arm64）

> 生成时间：2026-09-23 15:20 (+0800) · 由用户侧诊断整理，可直接转交开发
> 核心结论：**同一确定性 bug 连续触发 4 次进程 abort**，与 tunnel/cloudflared 生命周期管理高度相关，高度指向 Rust std 侵入式链表 Drop 竞态（`tried to drop node in intrusive list`）。

## 1. 环境

| 项 | 值 |
|---|---|
| 应用 | MCP Console.app（com.mcpconsole.desktop，ad-hoc 签名） |
| 版本 | CFBundleShortVersionString `0.1.411`，CFBundleVersion `0.1.411.2026.09.20.23.36.29`（构建于 2026-09-20 23:36 UTC+8） |
| 崩溃二进制 | `Contents/MacOS/mcp-console`（主服务进程，15,363,952 B） |
| Mach-O UUID | `93b48e64-1656-3f75-b2bf-efa29fdc745a`（4 份崩溃报告一致） |
| 系统 | macOS 26.5.1 (25F80)，Apple Silicon arm64 |
| 运行时 | Rust + tokio（崩溃线程名 `tokio-rt-worker`） |

## 2. 崩溃事件时间线（本地时间 2026-09-22）

| # | 进程启动 | 崩溃捕获 | 存活 | 崩溃线程 | .ips 文件 |
|---|---|---|---|---|---|
| 1 | 08:15:55 | 08:20:03 | ~4 min | `tokio-rt-worker`(T13) | mcp-console-2026-09-22-082004.ips |
| 2 | 08:20:40 | 08:29:44 | ~9 min | `main`(T0) | mcp-console-2026-09-22-082945.ips |
| 3 | 08:29:47 | 08:31:12 | ~1.5 min | `main`(T0) | mcp-console-2026-09-22-083113.ips |
| 4 | 09:15:46 | 09:26:26 | ~11 min | `main`(T0) | mcp-console-2026-09-22-092627.ips |

09:26 之后至本报告生成（9/23 15:14）**未再产生新的 .ips**；当前主进程 PID 56769（今日 14:59 启动）正常监听 127.0.0.1:8790。

## 3. 崩溃统一特征

- 异常：`EXC_CRASH (SIGABRT)`，termination `Abort trap: 6`，ASI：`abort() called`
- **4 份报告的应用层栈帧逐条完全一致**（仅系统帧差异）：

```
__pthread_kill → pthread_kill → abort →
0x88d900  mcp-console   (Rust std 运行时 abort 包装：TLS 访问 + 原子 CAS + vtable 间接调用)
0x88a4b8  mcp-console   (panic/运行时错误第二层包装，尾调用 0x883d6c)
0x5291d4  mcp-console   (调用点紧邻 panic 入口 0x88a4ac，含 backtrace 捕获特征指令)
0x54586c → 0x545828 → 0x545cb0  (内联展开的清理/Drop 路径)
0x880b3c → 0x55226c → 0xa573c → 0x529110  (上层调用链)
```

- 崩溃线程既出现过 `tokio-rt-worker` 也出现过 `main`，同一栈说明该代码路径可从 async worker 与同步 main 两侧进入（或结构被跨线程共享后 drop）。

## 4. 二进制字符串证据（0.1.411 当场核验）

二进制内存在两条与本次崩溃形态直接吻合的致命路径：

1. `fatal runtime error: tried to drop node in intrusive list., aborting`（Rust std 对侵入式链表节点非法 Drop 的运行时保护，直接调用 abort，不走 unwind）
2. `assertion failed: queued.load(Relaxed)` —— **该字符串与 `cloudflared-edge-relay.pid` / `cloudflared.log` / `cloudflared.url` 同一常量池相邻**，属于 tunnel/edge-relay 模块

## 5. 触发条件关联（sidecar 日志，UTC 时间戳，本地=+8h）

崩溃窗口的 `~/.mcp-console/data/sidecar-console.log` 显示每次崩溃前后均有 cloudflared 停止/重启周期：

```
00:15:55Z  INFO tunnel: 启动时清理残留 cloudflared，按当前网络重新建立连接   ← 进程#1 启动
00:20:03Z  ◆ 崩溃 #1（08:20:03 本地）
00:20:50Z  INFO tunnel: Cloudflare Tunnel 传输配置 http2 edge_relay=false static_edges=0  ← 进程#2
00:20:51Z  INFO tunnel: Named Tunnel 已就绪 pid=55585
00:27:51Z  INFO tunnel: 已停止 cloudflared pid=55585 → 启动 cloudflared Named Tunnel  ← 停止-重启
00:29:44Z  ◆ 崩溃 #2（停止/重启后 ~2 min）
...（#3、#4 同样伴随 tunnel 重建）
01:26:32Z  INFO tunnel: 启动时清理残留 cloudflared（崩溃 #4 后新进程）
```

注意：`edge_relay=false`（功能关闭）但 edge-relay 相关结构（含 `cloudflared-edge-relay.pid` 状态与 `queued` AtomicBool 断言）仍被构建/销毁——**建议重点审查 edge relay 结构在禁用状态下仍参与 cloudflared 停止/重启时的 Drop 路径**。

## 6. 跨版本对比

先前会话曾挂载 v0.1.410（2026-09-19 构建）DMG 对比：两版 panic/断言字符串集合各 113 条完全一致（仅版本号字样差异），上述崩溃候选点同样存在，4 帧序列一致。（注：该 DMG 已卸载，本报告生成时未重新挂载复验；如需可复验。）

**降级到 0.1.410 无法规避该 bug。**

## 7. 对开发者的请求

1. 请用 dSYM/LC_UUID `93b48e64-1656-3f75-b2bf-efa29fdc745a` 符号化 4 份 .ips 中偏移 `0x88d900 / 0x88a4b8 / 0x5291d4 / 0x545828 / 0x54586c / 0x545cb0 / 0x880b3c / 0x55226c / 0xa573c / 0x529110`，定位真实函数
2. 重点排查：edge relay / cloudflared 进程管理结构中侵入式链表节点的 Drop 是否与 `queued: AtomicBool` 断言在同一路径；是否存在节点仍 linked 时被 drop（如 tunnel 停止-重启竞态、spawn 的监控任务持有节点）
3. 原始 .ips 位于 `~/Library/Logs/DiagnosticReports/mcp-console-2026-09-22-*.ips`（4 份，可提供）

## 8. 诊断方法说明（可信度）

- 崩溃报告、栈帧、UUID、字符串、日志关联：**官方 .ips + 二进制当场核验，事实级**
- "intrusive list Drop 竞态"定性：基于 abort 包装区字符串 + 帧形态 + 线程分布的高置信推断（二进制无符号，无法直接绑定寄存器到该字符串）
- 0.1.410 对比：先前会话分析，见 §6 标注
