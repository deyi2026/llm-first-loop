# Deepin LFL 远程接管与多实例协同：分析与实现设计

- 日期：2026-11-07
- 类型：分析 + 实现设计（Analysis & SDD）
- 状态：**设计草案 v3（2026-11-07 拷问修订 + 检查单/schema 落地）；未实现、未独立 Reviewer PASS、未授权生产变更**
- 已确认约束（用户 2026-11-07 回答）：**deepin 为 X11 会话**、**两机同一内网**、**必须支持无人值守**
- 源码核查基线：`main @ ee475a352`（本机 mirror 工作区，本次只做只读核查）
- 实机核查基线（引用既有文档，非本次新测）：Deepin 25 / Linux 6.6.155-amd64 / x86_64 / LFL wheel 0.6.40
- 事实口径：本文每条"现状"均给出证据位置；无法核查的一律进 §10「未决与待确认」，不写成事实。

---

## 0. 结论先行

### 0.1 一句话结论

**可以做，但前提是把"远程接管"这个提法拆开。** 你现在说的这一个词，实际混着四个技术路径完全不同、风险等级差三个数量级的能力。混在一起设计，必然得出"上一套远程桌面"这种又重又危险的结论；拆开之后，其中两层今天就能用，一层需要一个中等改动，一层有硬技术上限、建议明确降级。

### 0.2 四层拆解与逐层结论

| 层 | 能力 | 用户直觉描述 | 现状（已核查） | 结论 |
|---|---|---|---|---|
| **L1 会话接管** | 在另一台设备上继续同一个 LFL 会话、下指令、看输出 | "我在手机上/公司电脑上接着指挥家里那台" | Web 服务已具备完整会话面（FastAPI + Durable Human Turn Queue + WS 实时通道），鉴权 fail-closed | **今天就能用**，零代码改动。缺口只在网络可达性与鉴权配置，不在 LFL |
| **L2 任务接管** | mac 上的 LFL 把一件事派给 deepin 上的 LFL 执行，拿回结果 | "让它俩分工干活" | **没有对等入口**：LFL 只能向外派（dsh_task / codearts_dispatch），不能被外部 agent 派；A2A admission 是 offline-only 骨架，无 HTTP route、无 dispatch | **核心缺口**，需要一个中等改动。这是"互联互通"的真正着力点 |
| **L3 桌面接管** | 远程看到并操作 deepin 的图形界面（点按钮、填表单） | "像向日葵一样接管那台机器" | `src/llm_loop/desktop/` **只有 macOS 后端**，非 darwin 一律 `unsupported_platform`；目录内无任何 Linux/X11/Wayland 代码 | **X11 已确认 → 技术可行，但授权粒度崩塌**。L3 是 L2 沙盒的旁路，必须独立授权域 + 首版 click-only（§4.3 / D11） |
| **L4 能力互操作** | 两个 LFL 互相调用对方的工具（这边的浏览器、那边的构建机） | "能力打通" | MCP **只有 client 侧**（stdio/HTTP/legacy SSE + OAuth + 装配），LFL 自身不暴露为 MCP server | 中期正确方向，但不建议第一步做 |

### 0.3 推荐路线（拷问后修订：三条约束已确认，路线重新排序）

用户于 2026-11-07 确认：**deepin 为 X11 会话**、**两机同一内网**、**必须支持无人值守**。这三条改了两处：

- 「只读首版」不再是产品形态，只是**技术验证切片**（无人值守要的就是写类任务，"损失可控"这条退路不存在了）；
- L3 从"有硬上限、建议降级"变成"**技术可行但授权粒度崩塌**"，因此不是提前，而是**加更硬的限制**（见 §4.3、D11）。

```
P0（1 天内，零代码）：内网直连 + SSH 仅隧道 + Web 鉴权加固
   └─ 效果：L1 会话接管可用。人在任何设备上指挥 deepin 上的 LFL。
   └─ 硬约束：SSH 只许 -L 转发，禁止 ssh host <cmd>（否则绕过 P1 全部闸，见 D12）。

P1（核心，3~4 周）：Peer 任务通道（LFL↔LFL，单向主从）+ 无人值守授权模型
   └─ 效果：L2 任务接管可用。mac 派单 → deepin 执行 → 产物引用回传，夜间无人干预。
   └─ 关键约束：① 远端任务必须落"不可变准入记录"，不得直接注入 prompt；
                ② 授权全部事前签署，事中零点击（见 §5.7）；
                ③ 授权必须有界：到期/超限即停，续期需人再签。
   └─ 技术验证切片（第 1 周）：先只做 fs.read 一个只读 kind，验证四道闸与审计链；
      这是"验证链路"，不是交付形态，第 2 周即进入写类 kind。

P2（3~4 周）：Linux 桌面后端（像素面）+ MCP server 化（工具面）
   └─ 效果：L3 在 X11 下可用；L4 工具互操作。
   └─ L3 硬限制：首版 click-only，禁止文本键入（见 D11）。
   └─ 前置：必须接受发版依赖；必须接受 L3 是独立授权域，不与 L2 共用 Grant。
```

### 0.4 最重要的三条判断

1. **先主从，后对等。** 不要一上来做双向网状互通。双向对等会让授权模型从"一条链"变成"n² 条链"，在没有节点身份体系前无法说清"谁有权让谁做什么"。mac=控制端、deepin=受控端的单向模型，能以最小授权面覆盖你 90% 的实际场景。
2. **先任务级，后像素级。** 如果 deepin 那台机器主要是跑服务、构建、脚本、文件处理，L2 就够用了；GUI 接管只在"必须操作只有图形界面的国产软件"时才真正必要，而它恰好是技术上最难、风险最高的那一层。
3. **不要用文件同步做跨机协调。** 现有协作原语（coordination board / help_request / lane / fleet）都建立在**本机文件系统 + fcntl 锁**上。Syncthing/NFS 共享过去看起来"能用"，实际会丢锁语义（Syncthing 无锁、NFS fcntl 依赖 lockd 且延迟不可控）。跨机协调必须换成有明确语义的请求-应答通道，见 D5。

---

## 1. 问题澄清：为什么必须拆成四层

### 1.1 四个问题的技术形态完全不同

**L1 会话接管**是"人 → agent"的输入通道问题。它只需要：网络可达 + 身份认证 + 会话状态。这三件事 LFL 的 Web 层已经全部具备。它的失败模式是"连不上"或"被拒"，没有权限升级风险（因为操作者仍是人）。

**L2 任务接管**是"agent → agent"的委派问题。它的核心不是传输，而是**授权**：一个远端 agent 提交的文本，凭什么能成为本地 LFL 的任务上下文？如果这个问题的答案是"因为它通过了认证"，那你就把 RULE-AI-14 建立的边界拆掉了——外部消息存在 ≠ 用户当前指令。

**L3 桌面接管**是"程序 → 操作系统输入子系统"的问题。它取决于显示服务器协议（X11 vs Wayland），不取决于 LFL 的架构。在 Wayland 下，任何进程都不能静默向其他窗口注入键鼠事件，这是设计上的安全属性，不是待修的 bug。

**L4 能力互操作**是"工具命名空间联邦"的问题。它要求两边的工具 schema、权限语义、失败语义能对齐。LFL 工具有 100+ 个且带复杂授权（write_scope、bwrap 沙盒、审批闸），一次性全量暴露是不现实的。

### 1.2 混在一起会导致的三个具体错误

| 错误结论 | 为什么错 |
|---|---|
| "上一套 VNC/向日葵方案就行" | 它解决 L3，完全覆盖不了 L2；而且把整机像素流暴露出去，攻击面远大于任务级通道 |
| "既然有 MCP，把 LFL 变成 MCP server 就互通了" | MCP 是**工具调用**协议，没有任务生命周期、没有授权准入、没有产物回传语义。用它传"帮我构建一版"这种任务，会丢掉所有可审计性 |
| "共享 data/ 目录就能协同" | 见 0.4-3。锁语义丢失后，lane 的 CAS、fleet 的 fencing、queue 的 claimed 状态全部退化为不可信 |

---

## 2. 现状基线（已核查事实）

### 2.1 部署事实

| 项 | 事实 | 证据 |
|---|---|---|
| 本机（开发/控制侧） | macOS Darwin 25.5.0 arm64，工作区 `~/Project/llm-first-loop-mirror`（工作区根，绝对路径以本机 pwd 为准） | 本次 `uname -a` / `pwd` |
| Deepin 侧（执行侧） | Deepin 25 / Linux 6.6.155-amd64 / x86_64 / LFL **wheel 0.6.40** | `docs/DESIGN-20261107-linux-managed-upgrade-restart-sandbox-authorization.md` §0 实机核查基线 |
| Deepin 服务形态 | Web / Feishu / Learning 三服务，`systemd --user` 管理 | 同上 |
| 源码与制品分离 | deepin 跑 wheel 发行版，源码在 mac 侧开发 | 同上 |

**这条"源码/制品分离"是本设计最重要的落地约束**：任何在 deepin 侧新增的代码，都必须经过"改源码 → 测试 → 打包 wheel → 升级 → 重启服务"这条链，而不是改文件重启。P1 的功能上线因此**依赖**同日的另一份设计（发行控制面/服务控制面）。

### 2.2 已有能力矩阵（跨机视角）

这张表是本设计的起点：**凡是"跨机不可用"的，才需要新做**。

| 能力 | 入口 | 机制 | 跨机可用性 |
|---|---|---|---|
| 会话对话 / 下达任务 | WebUI（`WEB_HOST` 默认 `127.0.0.1`，`WEB_PORT` 8903） | FastAPI + Human Turn Queue（durable JSON，`queued→claimed→completed/failed`） | ✅ 可达即用（需鉴权配置） |
| 实时事件流 | `src/llm_loop/web/realtime_ws.py` | WS，`accept` 前显式校验，拒绝码 4401/4403/4404/4405 | ✅ 可达即用，但**会话仅存进程内存** |
| 命令执行 | `execute_command` | 本地 shell（含隔离模式） | ⭕ 各自机器本地，不互通 |
| 桌面感知 / 操作 | `desktop_perceive` / `desktop_operate` | macOS CG/AX（`backend_macos.py`，非 darwin → `unsupported_platform`） | ❌ deepin 无后端 |
| 浏览器感知 / 操作 | `browser_perceive` / `browser_operate` | CDP | ⭕ 各自本地浏览器 |
| 向外部 agent 派活 | `dsh_task` / `codearts_dispatch` | 独立进程/会话；远端平台 HTTP | ✅ **单向外发** |
| 工具扩展 | MCP client（stdio / HTTP / legacy SSE + OAuth） | `tools/mcp_transport.py`（1052 行）+ `mcp_assembly` | ⭕ **单向**：LFL 调外部，外部不能调 LFL |
| 跨会话协调 | `coordination_status` / `help_request` / `lane_*` | **本机文件** + fcntl + 原子替换 | ❌ 跨机失效 |
| 子代理编队 | `spawn_subagent` / `fleet` | 同进程 fleet lease（磁盘 `state.json` + generation fencing） | ❌ 同机 |
| 外部任务准入 | `src/llm_loop/web/a2a_task_admission.py`（298 行） | 自述 **"Offline-only … no HTTP route or dispatch"** | ❌ 未接线 |
| 服务运维 | `service_control` | 本机 desired-state / generation CAS | ❌ 单机 |

### 2.3 三个硬缺口

**G1 — 没有对等 ingress（最关键）**
LFL 是"单实例闭环"：所有输入都来自"本地真人 ingress"（Web 输入框 / 飞书 / 定时授权）。外部 agent 无法向它提交一个可执行任务。现有 A2A 代码是一份**刻意的离线骨架**，其文件头明确写着集成前置条件未满足：真实 Huawei A2A host principal 的权威校验、Web 会话/工作区授权、以及要求 `newly_reserved=True` 的 dispatch 路径。

**G2 — 没有 Linux 桌面后端**
`desktop` 包以 `sys.platform == "darwin"` 构造后端，其余返回 `unsupported_platform`；包内模块全部围绕 CGWindowList / Accessiblity / screencapture。deepin 上这两个工具目前**确定性地不可用**，不是"权限没开"。

**G3 — 协作原语锚定本机文件系统**
`coordination_status` 读本机 lane 账本；`help_request` 是 L3 文件收件箱；`lane_*` 的 CAS 靠文件版本；`fleet` 明确"磁盘是唯一权威 + fcntl 跨进程锁"。这些在单机内是**正确的设计**（简单、可审计、无网络依赖），但它们是跨机协同的天然边界。

### 2.4 一条已经确立、必须继承的授权原则

现有 A2A admission 的设计说明里有一句话，价值高于它本身的代码：

> "This store records an exact, immutable human ingress **BEFORE any side effect**."

它把"远端任务"的合法性来源锁定为**不可变的人类准入记录**，而不是"通道认证通过"。这与 RULE-AI-14 完全一致（外部消息存在 ≠ 用户当前指令；只有经用户显式授权入口才可成为任务上下文），也与常驻授权条款一致（只能由未委派的真人 ingress 签发，定时与子代理不得递归签发）。

**本设计的所有 peer 任务路径都必须遵守这条：传输层认证只证明"是本机的合法对端"，不证明"这个任务该被执行"。执行前必须有本地准入记录。** 见 §5.4。

---

## 3. 目标、场景与边界

### 3.1 三个真实场景（用它们做验收，而不是用"功能列表"做验收）

**S1 — 通勤途中接管会话**
人在手机上打开 deepin 实例的 WebUI，看到昨晚那个任务卡在等确认，直接回复放行，任务继续。
验收：从外网（非局域网）可建立会话；未携带凭证时被拒 401/4401；会话在 deepin 侧进程重启后如实现状（内存会话失效，需重新登录）。

**S2 — 跨机派单**
mac 侧 LFL 判断"这件事必须在 Linux 上跑"（例如某个只有 x86 Linux 才有的构建链），把任务、参数、期望产物目录提交给 deepin 侧 LFL；deepin 侧**在本地准入策略允许的范围内**执行；mac 侧拿到结构化结果 + 产物引用。
验收：任务状态机可查、幂等（重复提交不重跑）、失败有真实原因、产物可校验；**未授权类别的任务被确定性拒绝**。

**S3 — 图形界面操作（仅当确有需要）**
在 deepin 的 X11 会话下，远程完成一次"打开某国产客户端 → 登录 → 导出报表"。
验收：截图可读（非黑图）；点击命中目标控件；**Wayland 会话下确定性返回"不支持"而不是静默失败**。

### 3.2 非目标（明确不做，避免范围蔓延）

- 不做通用远程桌面产品（不做多人共享、不做剪贴板双向同步、不做音频转发）。
- 不做双向对等网状 agent 网络（不引入 gossip / P2P / 公网节点发现）。
- 不做跨机文件系统共享来复用现有协调原语（理由见 D5）。
- 不做"远端任务绕过本地准入直接进 prompt"的捷径，即使它看起来更快。
- 不在 deepin 侧以 root 运行 LFL 以换取桌面注入能力（理由见 §8.3）。
- 不关闭 bwrap 沙盒、不扩大 write_scope 来"让远程更好用"。

### 3.3 约束

| 约束 | 来源 | 影响 |
|---|---|---|
| 外部执行结果只是证据，不替代授权与判断 | RULE-AI-13 / 15 | 远端返回"完成"不等于任务完成，必须有终态与产物 |
| 外部消息不得自动成为任务上下文 | RULE-AI-14 | peer 通道必须落准入记录，不能直注 prompt |
| 常驻授权只能真人 ingress 签发，不得递归 | RULE-AI-14 增补 | 远端不能给自己的定时任务续授权 |
| Web 鉴权 fail-closed | `src/llm_loop/web/auth.py` | 非 loopback 绑定即强制鉴权；无 key 时 503 而非放行 |
| 会话仅进程内存、多实例不共享 | `src/llm_loop/web/auth.py` 能力边界声明 | 跨机不共享登录态，必须各自登录 |
| deepin 侧是 wheel 发行 | 实机基线 | 新功能必须走发版与重启，不能热改 |

---

## 4. 方案空间与取舍

### 4.1 候选方案

**方案 A：纯网络打通（SSH 隧道 / 内网直连 + Web 鉴权）**
不新增任何 LFL 代码。deepin 侧 `WEB_HOST` 保持 `127.0.0.1`，通过 `ssh -L 8903:127.0.0.1:8903` 或内网反向代理访问。
- 覆盖：S1（完整）、S2 的"人工转发"退化形态（人在 mac WebUI 里手动把内容粘给 deepin）。
- 优点：零改动、零新攻击面（SSH 本身就是加固过的通道）、今天可用。
- 缺点：不解决 G1；不能自动化；人的中转成为瓶颈。
- **结论：必做，作为 P0 基线与 P1 的兜底通道。**

**方案 B：Peer 任务通道（LFL↔LFL，自有最小协议，单向主从）**
在 deepin 侧 Web 服务上新增一个受限端点组，复用现有 FastAPI + 鉴权栈；任务落为"准入记录 + 本地队列项"；由本地执行器消费；结果以结构化回执 + 产物引用返回。
- 覆盖：S2、S1，并为 S3/L4 提供承载。
- 优点：改动集中在一个新 router + 一个 admission store + 一个 dispatcher；复用全部既有鉴权/审计/队列能力；可精确控制白名单任务类别。
- 缺点：自有协议意味着与 A2A/MCP 生态不对齐，未来需要一层适配；需要 deepin 侧发版。
- **结论：推荐主路径（P1）。**

**方案 C：标准协议优先（A2A server + MCP server）**
把 LFL 同时暴露为 A2A server（接任务）与 MCP server（接工具调用）。
- 优点：生态兼容，外部 agent 可直接接入，长期最省适配。
- 缺点：① A2A 的集成前置在代码注释中被明确标为"未满足"（需要权威平台 principal 校验），不是补个路由就能上线；② MCP server 化需要把 100+ 工具与 write_scope/bwrap/审批闸语义映射出去，权限面爆炸；③ 两者都不解决"任务生命周期 + 产物回传"，仍要在内部补一层。
- **结论：作为 P2 的方向，不作为第一步。** 但 P1 的消息 schema 要**刻意贴着 A2A 的 Task 语义设计**，让未来适配只做字段映射而不是重新建模。

**方案 D：桌面接管专用通道（屏幕流 + 输入注入）**
自建像素流（截图→编码→传输→渲染）+ 输入注入（XTest / uinput / portal）。
- 优点：唯一能覆盖"只有 GUI 的软件"的路径。
- 缺点：Wayland 硬限制（见 §4.3）；带宽与安全面显著增大；需要一套完整的会话/权限/剪贴板/多显示器处理；工程量远超 L2。
- **结论：P2，且限定 X11 会话 + 窗口级（非全屏流）。**

**方案 E：共享文件系统复用现有协作原语**
把 `data/` 挂到 NFS/Syncthing，让 coordination/lane/fleet 直接跨机工作。
- 优点：零新协议，语义现成。
- 缺点：**fcntl 锁语义在同步目录中不成立**（Syncthing 无锁；NFS 的 fcntl 依赖 lockd，跨机延迟与故障模式不可控，且与本仓库大量"原子替换 + 版本 CAS"假设冲突）。一旦丢锁，`lane` 的 CAS 与 `fleet` 的 generation fencing 会从"正确"退化为"偶然正确"。
- **结论：明确否决。** 理由写入 D5。

### 4.2 评分矩阵

评分 1–5，越高越好；"风险"列越高越危险（反向）。

| 维度 | A 网络打通 | B Peer 通道 | C 标准协议 | D 桌面接管 | E 共享 FS |
|---|---|---|---|---|---|
| 覆盖场景（S1/S2/S3） | S1 | S1+S2 | S1+S2+部分L4 | S3 | S1+S2（不可靠） |
| 实现成本（越高越省） | 5 | 3 | 2 | 1 | 4 |
| 安全可控性 | 5 | 4 | 2 | 1 | 1 |
| 可验收性 | 5 | 4 | 3 | 2 | 1 |
| 与现有架构一致性 | 5 | 4 | 3 | 2 | 1 |
| 长期维护成本（越高越省） | 5 | 3 | 4 | 1 | 1 |
| **综合** | **P0 基线** | **P1 主路径** | **P2 方向** | **P2 限定** | **否决** |

### 4.3 显示协议：X11 已确认可行，但"可行"不等于"可授权"

用户已确认 deepin 运行 **X11** 会话，因此原判断（Wayland 硬上限）不再适用于当前部署。X11 下 L3 技术上可行：

| 显示协议 | 截图 | 静默键鼠注入 | 本设计结论 |
|---|---|---|---|
| **X11（当前部署）** | 任意窗口可读（XGetImage） | XTest 扩展可注入，**无需特殊权限** | 技术可行；但授权粒度问题严重，见下 |
| Wayland（含 deepin 25 默认 treeland） | XDG Portal `ScreenCast`，每次需确认 | `RemoteDesktop` portal（需确认）或 `/dev/uinput`（需 root） | 仍明确不支持（无人值守下 portal 与自主执行冲突） |

**必须说清楚的新风险：X11 没有应用间隔离。**

这是本节最重要的判断，也是拷问暴露的核心问题。X11 的安全模型是**"连上 display 就是自己人"**。任何能访问 `:0` 的进程可以：

1. 向**任何**窗口注入键鼠事件（XTest 不做目标校验，事件进的是焦点窗口）；
2. 读取**任何**窗口的像素内容（XGetImage 不受窗口权限限制）。

由此产生一个致命推论：**L3 是 L2 沙盒的旁路。**

若 L2 的 `execute_command` 受 `write_scope` + bwrap + 审批闸约束，而 L3 允许"向焦点窗口键入文本"，那么一次注入到终端窗口的键入，等价于在 deepin 上执行任意命令，**且绕过全部四道闸**。一个"允许你截图"的授权，实际隐含了"允许你在这台机器上执行任意操作"。

这不是理论风险，是授权模型的结构性缺陷：**L3 的能力无法用"任务类别白名单"表达**，因为它的能力空间是"任意 UI 交互"，不是"某类任务"。

因此 L3 的处理原则见 D11（独立授权域 + 首版 click-only + 禁止键入）。**"能做"与"允许做"必须分开决策，不因技术上通了就顺手放开。**

**关于 Wayland 的保留结论**（若未来切换会话类型，此段立即生效）：portal 要求每次会话用户确认，与无人值守天然冲突；且 `docs/installation.md:398-409` 的实机记录（向日葵在 treeland 下采集不到、需切 X11）是该协议的旁证，不是待修的 bug。届时 L3 应返回确定性的 `unsupported_display_protocol`，**不做 portal 兜底、不伪造成功**。

---

## 5. 推荐架构

### 5.1 分层

```
┌───────────────────────────────────────────────────────────────┐
│ 控制端（mac LFL，orchestrator）                                │
│  · 判断"这件事该在哪台机器做"（模型决策，程序不代劳）            │
│  · 组装任务：effect_id + 类别 + 参数 + 期望产物 + 期限          │
└──────────────────────────┬────────────────────────────────────┘
                           │ ① Peer 任务提交（HTTPS + 双向凭证）
                           ▼
┌───────────────────────────────────────────────────────────────┐
│ 受控端（deepin LFL，executor）                                 │
│                                                               │
│  ┌─ 闸1 传输 ──────────┐  节点身份/双向 TLS 或 HMAC + 时间窗    │
│  ┌─ 闸2 准入 ──────────┐  不可变 admission 记录（先落盘，后动作）│
│  ┌─ 闸3 策略 ──────────┐  任务类别白名单 + 路径/命令范围 + 配额   │
│  ┌─ 闸4 副作用 ────────┐  write_scope / bwrap / 审批闸（原样复用）│
│                                                               │
│  admission store → 本地 durable 队列 → 本地 run（真人 ingress   │
│  同款执行栈）→ 结构化回执 + 产物引用                            │
└──────────────────────────┬────────────────────────────────────┘
                           │ ② 回执（状态机 + 产物 artifact ref）
                           ▼
                  控制端核验终态（RULE-AI-13/15：远端"完成"仅是证据）

呈现面（可选，P2）：
   deepin X11 会话 ──窗口截图──► 控制端 read_image
                  ◄──点击/键入──  受限注入（XTest）
```

**关键点：peer 任务不进入 LFL 的 prompt 流，而是进入"与真人 ingress 同款的本地执行栈"。** 这样 RULE-AI-14 的边界不需要重新论证，直接继承既有实现。

### 5.2 节点模型（最小）

只引入三个概念，且都落在既有模式上（对齐 `fleet` 的"磁盘权威 + generation"与 `service_control` 的"desired/actual"）：

| 概念 | 字段（最小集） | 语义 |
|---|---|---|
| `PeerNode` | `node_id`、`display_name`、`role`（`orchestrator`/`executor`）、`capabilities[]`、`public_key_fingerprint`、`enabled` | 一端的身份与能力声明。**能力声明是控制端做路由判断的依据，不是权限** |
| `PeerGrant` | `node_id`、`allowed_task_kinds[]`、`allowed_paths[]`、`max_concurrency`、`expires_at`、`issued_by`(真人)、`effect_scope` | 控制端对"这个对端可以让我做什么"的授权。**必须由真人在本地签发**（对齐 RULE-AI-14 增补） |
| `PeerTask` | `effect_id`、`kind`、`params`、`expect[]`、`deadline`、`state`、`attempt`、`result_ref`、`admission_id` | 一次委派。`effect_id` 幂等；`admission_id` 指向不可变准入记录 |

状态机（刻意与 Human Turn Queue 同构，便于复用 reaper 逻辑）：

```
submitted → admitted → queued → running → succeeded
                    ↘ rejected            ↘ failed
                                          ↘ blocked（需人决策）
                    ↘ denied（策略不符）
任意非终态 → cancelled
```

不变量：
1. `admitted` 之前**不得有任何副作用**（对齐 A2A admission 的 "BEFORE any side effect"）。
2. 状态只能由受控端推进；控制端不得"猜"进度。
3. `succeeded` 必须携带 `result_ref` 且校验通过；否则视为 `failed`（fail-closed）。
4. 同一 `effect_id` 重复提交返回既有记录，不重跑。

### 5.3 协议草案（自有最小协议，贴 A2A 语义）

传输：HTTP/JSON over TLS（或 SSH 隧道内），复用 FastAPI。
认证：双向凭证（控制端持 `X-Peer-Node-Id` + HMAC 签名含时间窗与 body 摘要；受控端校验指纹白名单）。**不使用 WebUI 的 Bearer key 直接复用**——那是人的凭证，权限面不同。

| 端点 | 方法 | 语义 |
|---|---|---|
| `/peer/v1/manifest` | GET | 返回受控端能力清单与策略摘要（只读，仍需认证） |
| `/peer/v1/tasks` | POST | 提交任务；`Idempotency-Key: effect_id`；返回 `admission_id` + 状态 |
| `/peer/v1/tasks/{id}` | GET | 查状态（唯一进度真值） |
| `/peer/v1/tasks/{id}/cancel` | POST | 请求取消（协作式，不保证立即） |
| `/peer/v1/tasks/{id}/artifacts` | GET | 列产物引用（不内联大文件） |

响应信封（统一，便于失败归因）：

```json
{
  "schema": "lfl.peer.v1",
  "task_id": "...", "effect_id": "...", "admission_id": "...",
  "state": "queued|running|succeeded|failed|blocked|denied|cancelled",
  "reason_code": "policy_task_kind_not_allowed|admission_rejected|sandbox_denied|timeout|...",
  "result": {"summary": "...", "artifacts": [{"ref": "artifact://v1/...", "sha256": "...", "bytes": 0}]},
  "observed_at": "2026-11-07T12:00:00+08:00"
}
```

**硬性要求：`reason_code` 是封闭枚举**，不允许自由文本当错误码（否则控制端无法做程序化判断，只能靠模型读字符串）。

### 5.4 授权四道闸（全部 fail-closed）

| 闸 | 判什么 | 失败时 | 复用 |
|---|---|---|---|
| 闸1 传输 | 节点身份、签名、时间窗、重放 | 401 / 拒绝，无任何副作用 | 新增（指纹白名单） |
| 闸2 准入 | 是否允许该 `kind`；`PeerGrant` 是否有效未过期；是否超配额 | `denied`，落 admission 拒绝记录 | 沿用 A2A admission 的 CAS 语义 |
| 闸3 策略 | 路径是否在 `allowed_paths`、命令是否白名单、是否要求人工确认 | `blocked`（等人）或 `denied` | 新增策略层 |
| 闸4 副作用 | `write_scope` / bwrap 挂载 / 审批闸 | 拒绝并如实回执 | **原样复用现有文件工具与沙盒** |

**要点**：闸4 不是新写的，是把现有机制"接上"。这一点很重要——远程通道不应成为绕过本地沙盒的第二条路。**任何"远程专用"的旁路都是设计缺陷**，不是便利。

### 5.5 数据面：产物不内联

- 截图、构建产物、日志包一律走 `artifact://v1/...` 引用 + `sha256` + `bytes`。
- 控制端按需拉取（`/peer/v1/tasks/{id}/artifacts`），不塞进任务回执 JSON。
- 理由：① 现有 `read_file` 已支持 `artifact://` 不可变快照；② 回执体一旦内联大文件，会同时污染审计记录与模型上下文（对齐 RULE-AI-25 的上下文经济纪律）。

### 5.6 与现有机制的对齐（避免造第二套）

| 现有机制 | 本设计如何复用 | 不做什么 |
|---|---|---|
| Human Turn Queue | 队列状态机与 reaper 思路 | 不把 peer 任务混进 human 队列（身份不同、审计不同） |
| A2A admission（298 行） | 直接复用"先落盘准入、后动作"的 CAS 语义 | 不改造成"通用任务表"，保持其不可变准入语义 |
| `service_control` generation CAS | peer 节点配置/授权的版本化 | 不让 peer 通道去重启服务 |
| `write_scope` / bwrap | 闸4 原样接入 | 不为远程放宽任何 scope |
| `artifact://` | 产物回传 | 不新造对象存储 |
| 现有 Web 鉴权栈 | TLS/Origin/会话边界 | 不把人的 Bearer key 给机器用 |

### 5.7 无人值守的授权生命周期（回答"授权操作要简单"）

"简单"的正确解法不是"每次少点几下"，而是**让授权只在配对时发生一次**。这与系统既有的常驻授权模式同构：有界次数 + 有界期限 + 只能由真人签发（`wake_fires` / `wake_expires_in_days` / 不得递归签发）。

```
① 配对（一次，人在场，≤5 分钟）
   受控端生成 keypair → 显示短指纹（如 4×4 字符分组）
   控制端人工核对短指纹 → 双向写入白名单
   └─ 产出：PeerNode ×2（互相登记）

② 授权（一次，人在场，≤2 分钟）
   在受控端签发 PeerGrant：
     allowed_kinds[] / allowed_paths[] / max_concurrency
     expires_at（必须填，不允许永久）
     max_tasks（必须填，不允许无限）
   issued_by 必须是真人 ingress（对齐 RULE-AI-14 增补：不得由定时/子代理递归签发）
   └─ 产出：一份有界租约

③ 日常运行（零点击，无人值守）
   控制端派单 → 受控端四道闸自动判定 → 执行 → 回执
   无需任何人工交互
   └─ 唯一例外：blocked（有 deadline，超时即 failed + 通知，见 D10）

④ 到期 / 超限 / 撤销（自动，零点击）
   到期      → 新任务 denied/grant_expired
   满 max_tasks → denied/grant_exhausted
   撤销      → 立即生效（不等下次任务），已入队任务转 cancelled
   └─ 续期是一次新的 ②，不是自动续
```

**配对为什么不能用 TOFU**：TOFU 在无人值守下是危险的——首次连接时无人核对，中间人可长期驻留。所以配对必须是**一次性的人工动作**，但不要求两台机器同时有人：只要短指纹能通过任一可信渠道（当面看屏、电话读码）核对即可。

**可验收的易用性指标**（对应 §9.4）：首次配对 ≤ 5 分钟人工且只需核对一次短码；日常派单人工交互次数 = **0**；扩权/续期 ≤ 2 分钟人工；撤销 ≤ 10 秒生效且不依赖对端配合。

#### 5.7.1 状态对象与五条不变量

配对状态机：

```
unpaired → offered(≤300s) → confirmed → paired
              ↘ expired                ↘ unpaired(人工解绑)
```

租约状态机：

```
none → active → expired | exhausted | revoked
```

五条不变量是评审与实现的验收点，不是口号：

| ID | 不变量 | 违反时的行为 |
|---|---|---|
| G1 | 单调降权：`allowed_kinds` ⊆ `manifest.kinds`；签发时含未声明 kind 直接拒绝 | `policy_task_kind_not_allowed`（不静默求交集） |
| G2 | 有界：`expires_at` 与 `max_tasks_total` 均必填，schema 无 null 分支 | `grant_unbounded` |
| G3 | 撤销本地生效：tombstone 写入受控端即生效，不等控制端确认 | 下一请求 `grant_revoked` |
| G4 | 续期即新建：新 `grant_id`，旧记录保留 | 审计可回溯"哪次续期放宽了什么" |
| G5 | 只真人签发：`issued_by.kind=human_ingress`，非真人路径拒绝 | `grant_issuer_not_human` |

G5 的可执行含义：签发入口必须能判断调用者是否为真人 ingress。实现上不新增一套判定，直接复用 RULE-AI-14 的"常驻授权与 wake 只能由当前真人 run 签发"，把它前移到 `grant issue` 入口。

#### 5.7.2 配对协议

三条消息 + 一次人眼核对。首版单向（D1），故只有一对密钥。

```
executor 本机                        orchestrator
  |                                   |
  |  1. PAIR-OFFER  (public_key, short_fingerprint, nonce, expires_at)
  | --------------------------------->|   经 SSH -L 隧道（loopback）
  |                                   |   2. 人眼核对短指纹（8 组 × 4）
  |                                   |
  |  3. PAIR-CONFIRM (public_key, short_fingerprint, nonce,
  |                   confirm_phrase, link_secret K_oe)
  | <---------------------------------|
  |  4. 落盘 nodes/<node>.json         |   4. 落盘 nodes/<node>.json
  |                                   |
  |  5. PAIR-ACK (paired_at) --------->|   6. 控制端确认对端已落盘
```

关键设计点（都是选择，不是疏漏）：

1. **配对阶段的认证是"隧道 + 人眼"，不是密码学**。此时还没有共享密钥，无法签名。所以 offer/confirm 只接受 loopback 来源 + 300s 窗口 + 一次性 nonce。
2. **短指纹防的是 SSH 主机密钥已被替换**。SSH 首次连接本身也是 TOFU，人眼核对是打破它的唯一手段——这就是配对不能全自动的原因。
3. **`confirm_phrase` 是摩擦设计，不是安全边界**（脚本同样能写出该常量）。它让自动补全/顺手调用无法静默完成配对；写进 schema 只是让它显式可见。
4. **`link_secret` 只允许出现在配对消息里**，落盘 `data/peer/secrets/`（0600），不得进入常规审计与请求日志。审计只记 `node_id` + `short_fingerprint`。
5. **首版单密钥 `K_oe`**（控制端→受控端）。若 P2 开反向请求，必须新立 `K_eo`，不得复用同一密钥——否则一方向泄露即双向沦陷。

#### 5.7.3 可执行检查单

图例：

- `[实测]` 本次会话真实执行并取得回执
- `[已核实]` 依赖端点/默认值已在仓库源码定位，未在 deepin 执行
- `[规格]` P1 待实现命令，此处形态即验收规格

执行位置约定（**与 D12 一致，最容易搞错的一点**）：

- `受控端本机`：deepin 的物理终端，或 VNC 桌面里的终端。**不经由 SSH 命令通道**。
- `控制端`：mac 上的 LFL 会话（模型调工具）。
- 只有 `curl` 类只读探活允许从控制端经隧道发起。

理由：D12 用 `no-pty,permitopen=...` 关掉 `ssh host <cmd>`。若允许"SSH 远程执行 grant issue"，任何拿到该 key 的程序都能重新签发租约，四道闸全部归零。所以**人工授权必须走受控端本机**，SSH 只保留端口转发。

**A. 前置（PRE）**

PRE-1 确认 X11（决定 L3 是否可用）

```bash
# 执行位置：受控端本机，图形会话内的终端（不要在 ssh 会话里判断）
echo "$XDG_SESSION_TYPE"                              # 期望: x11
ls -l /tmp/.X11-unix/                                 # 期望: 存在 X0
DISPLAY=:0 timeout 5 xdpyinfo 2>/dev/null | head -3   # 期望: 有 name of display
```

- 期望：`x11` 且 `xdpyinfo` 有输出。
- 判据：以 `XDG_SESSION_TYPE` 为主。**`xdpyinfo` 成功不足以排除 Wayland**——Wayland 下 XWayland 同样提供 `:0`（§6 D11）。
- 失败处置：`wayland` → L3 关闭（`unsupported_display_protocol`），P1 仍可交付 fs/build 类。
- 状态：`[已核实]` 该机历史采集在 Wayland 下返回 `not_supported`（`docs/installation.md:398-409`）；X11 结论来自你的回答，未在 P1 重新实测。

PRE-2 服务只监听 loopback

```bash
# 执行位置：受控端本机
ss -ltnp | grep -E ':8903\b'
```

- 期望：`127.0.0.1:8903`。出现 `0.0.0.0:8903` 或 `[::]:8903` 立即停，先改回 loopback。
- 状态：`[已核实]` 默认端口 8903（`src/llm_loop/web/__init__.py:535`）。

PRE-3 服务健康

```bash
# 执行位置：任一侧
curl -sS http://127.0.0.1:8903/health | python3 -m json.tool
```

- 期望：`"status": "ok"`（其余 `service/version/build/knowledge/identity` 为既有输出）。
- 状态：`[已核实]` 端点实现 `src/llm_loop/web/routes.py:2759`。

PRE-4 隧道只做端口转发

```bash
# 执行位置：控制端
ssh -N -L 8903:127.0.0.1:8903 deepin &
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8903/health
```

- 期望：`200`。
- 状态：`[已核实]`（命令形态）；deepin 侧未实测。

PRE-5 证明 shell 通道已关闭（**最容易漏的一条**）

```bash
# 执行位置：控制端
ssh deepin 'id'; echo "exit=$?"
```

- 期望：非 0 退出，输出含 `PTY allocation request failed` 或 `administratively prohibited`。
- 若返回 `uid=1000(...)`：D12 未落实，**P1 不要继续**。此时"四道闸"对任何拿到该 key 的程序都不存在。
- 状态：`[规格]` 需配置 `authorized_keys` 的 `no-pty,permitopen="127.0.0.1:8903"`。

PRE-6 闸4 基线：写域应为只读

```bash
# 执行位置：受控端 LFL 会话
verify_path_scope()
```

- 期望：`scope` 为空或仅含授权路径。`write_scope` 未配时语义是只读执行域——空 allow 集合不放行任何写。
- 状态：`[已核实]` 工具存在且只读（本会话可用）；空 allow 语义见 `src/llm_loop/workspace/file_service.py:142-171`。

**B. 配对（PAIR）**

PAIR-1 生成节点身份

```bash
# 执行位置：受控端本机
lfl peer keygen --home "$HOME/.lfl/peer"
```

- 期望：输出 `node_id`（如 `deepin-01`）与 `short_fingerprint`（8 组 × 4，字符集 `A-Z2-7`）。
- 失败处置：目录已存在则不覆盖；轮转需显式 `--rotate`（会作废旧白名单，须重新配对）。
- 状态：`[规格]`

PAIR-2 生成 offer（300s 窗口）

```bash
# 执行位置：受控端本机
lfl peer offer --out /tmp/peer-offer.json --ttl 300
python3 -c "import json;d=json.load(open('/tmp/peer-offer.json'));print(d['short_fingerprint'])"
```

- 期望：打印短指纹；`expires_at - issued_at = 300s`。
- 状态：`[规格]`

PAIR-3 控制端取 offer

```bash
# 执行位置：控制端（经 PRE-4 隧道）
curl -sS http://127.0.0.1:8903/peer/v1/pair/offer -o /tmp/offer.json
python3 -m json.tool /tmp/offer.json
```

- 期望：含 `public_key` / `short_fingerprint` / `nonce` / `expires_at`。
- 状态：`[规格]`

PAIR-4 人眼核对（**不可脚本化**）

- 动作：把 PAIR-2 终端上的指纹与 PAIR-3 回执逐组比对（8 组）。
- 期望：完全一致。
- 失败处置：**停止**，不要重试 confirm。不一致意味着拿错 offer，或 SSH 主机密钥已被替换。
- 状态：人工步骤

PAIR-5 提交 confirm

```bash
# 执行位置：控制端
lfl peer confirm --peer deepin-01 --offer /tmp/offer.json \
  --fingerprint K4M2-P7QX-7TB3-R7WN-2C5V-6HJD-7FSA-3LQE \
  --phrase I-HAVE-VERIFIED-THE-SHORT-FINGERPRINT
```

- 期望：200 + `paired_at`；两侧 `nodes/` 各新增 1 条 `enabled=true`。
- 负例：改一组字符 → `pair_fingerprint_mismatch`；超过 300s → `pair_nonce_expired`。
- 负例（已实测）：手写指纹含 `8`/`9` 会被 schema 拒（`^([A-Z2-7]{4}-){7}[A-Z2-7]{4}$`）。指纹只能由 `keygen` 打印，不得手抄。
- 状态：`[规格]`

PAIR-6 双向落盘校验

```bash
# 执行位置：受控端本机 / 控制端各一次
lfl peer nodes list --json
```

- 期望：两侧都显示对方 `enabled=true`，且 `fingerprint` 相同。
- 状态：`[规格]`

PAIR-7 负例：无签名请求

```bash
# 执行位置：控制端（不带任何 X-Peer-* 头）
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8903/peer/v1/manifest
```

- 期望：`401` + `peer_unknown_node`。
- 状态：`[规格]`

PAIR-8 负例：重放

- 动作：把用过的一次签名请求原样重发。
- 期望：第二次 `401` + `peer_replay_detected`。
- 注意：任务层幂等重放**不是**这个错误——同 `effect_id` 重提应由任务层返回原记录（RUN-3）。
- 状态：`[规格]`

**C. 授权（GRANT）**

GRANT-1 签发有界租约

```bash
# 执行位置：受控端本机（物理/VNC 终端，或本机浏览器控制台）
lfl peer grant issue \
  --kinds fs.read \
  --paths $HOME/project \
  --expires-in 7d --max-tasks 20 --max-concurrency 2
```

- 期望：输出 `grant_id`（`gr_...`）+ 完整 `expires_at` / `max_tasks_total`。
- 状态：`[规格]`

GRANT-2 拒无期限

```bash
lfl peer grant issue --kinds fs.read --paths $HOME/project --max-tasks 20
```

- 期望：非 0 退出 + `grant_unbounded`（缺 `--expires-in`）。
- 状态：`[规格]`

GRANT-3 拒无限次

- 动作：`--max-tasks 0` 或省略。
- 期望：`grant_unbounded`。
- 状态：`[规格]`

GRANT-4 拒未声明 kind

```bash
lfl peer grant issue --kinds shell.exec --paths $HOME/project \
  --expires-in 1d --max-tasks 1
```

- 期望：`policy_task_kind_not_allowed`（G1：不静默求交集）。
- 状态：`[规格]`

GRANT-5 拒非真人签发

- 动作：从控制端经 peer 通道请求签发；或由定时任务/子代理调用。
- 期望：`grant_issuer_not_human`。
- 状态：`[规格]`

GRANT-6 读回

```bash
lfl peer grant list --json
```

- 期望：`state=active`、`tasks_used=0`、`expires_at` 与签发时一致。
- 状态：`[规格]`

**D. 运行与撤销（RUN / REV）**

RUN-1 只读派单（零点击）

- 动作：控制端 `peer_list()` → `peer_dispatch(peer_id="deepin-01", kind="fs.read", params={"path": ".../README.md", "max_bytes": 65536})`
- 期望：`state=succeeded` + `result.artifacts[0].ref`（`artifact://v1/...`）。
- 状态：`[规格]`

RUN-2 审计可追溯

```bash
# 执行位置：受控端本机
grep -F "eff_20261107_9f3c1a" data/peer/*.jsonl | head
```

- 期望：提交 / 准入判定 / 终态三条记录，含同一 `effect_id` 与 `task_id`。
- 状态：`[规格]`

RUN-3 幂等重放

- 动作：用**同一** `effect_id` 再派一次同 kind 同 params。
- 期望：返回原 `task_id`；审计里实际执行记录仍为 1 条。
- 负例：同 `effect_id` 但改 params → `idempotency_conflict`。
- 状态：`[规格]`

RUN-4 越界双闸

- 动作：`params.path = "/etc/shadow"`。
- 期望：`denied` + `path_outside_allowed_paths`；构造绕过闸3 的测试时，闸4 应独立返回 `sandbox_denied`。
- **两条都要测**：只测一条无法区分"闸3 生效"与"闸4 生效"（两者返回不同 `reason_code`：`path_outside_allowed_paths` vs `sandbox_denied`）。
- 状态：`[规格]`

REV-1 撤销（两条路径，均为降权，无需审批）

```bash
# 路径 a：受控端本机
lfl peer grant revoke --grant-id gr_7c1d9e4a3b52
# 路径 b：控制端自撤（POST /peer/v1/grant/revoke，带签名）
```

- 期望：`state=revoked` + `revoked_at`；**≤10s 内**下一次派单得 `denied` + `grant_revoked`；已入队任务转 `cancelled`。
- 状态：`[规格]`

REV-2 到期

```bash
lfl peer grant issue --kinds fs.read --paths $HOME/project --expires-in 60s --max-tasks 5
# 等 60s 后派单
```

- 期望：`grant_expired`。必须与 `grant_revoked` 可区分——否则无法判断是人工干预还是自然到期。
- 状态：`[规格]`

REV-3 满额

- 动作：`--max-tasks 1`，连派两次。
- 期望：第二次 `grant_exhausted`。
- 状态：`[规格]`

#### 5.7.4 验证状态汇总

| 状态 | 条数 | 含义 |
|---|---|---|
| `[实测]` | 2 | `verify_peer_schemas.py` 30 checks PASS / 1 skipped；手写指纹被 schema 拒（§5.8.6） |
| `[已核实]` | 5 | PRE-1..PRE-6 依赖的端点/默认值已在源码定位 |
| `[规格]` | 21 | P1 待实现，形态即验收规格 |
| 人工 | 1 | PAIR-4 人眼核对 |

前 27 条即 §5.7.3 的条目（PRE 6 + PAIR 8 + GRANT 6 + RUN 4 + REV 3）；`[实测]` 的 2 条来自 §5.8.6 的契约校验，不占条目计数。

这张表的意思是：**本检查单目前只能保证"规格自洽 + 契约可校验"，不能保证"在 deepin 上跑通"**。第 1 周技术验证切片的目标，就是把 `[规格]` 里的 PRE + PAIR + GRANT-1..2 + RUN-1..2 + REV-1 变成 `[实测]`。

#### 5.7.5 故障处置

| 现象 | 最可能原因 | 处置 | 不要做 |
|---|---|---|---|
| 配对成功但请求全 401 | 两端时钟偏差 > 300s | 校时后重签 | 不要放宽时间窗 |
| 撤销后仍能派单 | 只改控制端，未写受控端 tombstone | 在受控端 `revoke` 再验 | 不要只信控制端状态 |
| 重启后 grant 消失 | grant 未落盘（磁盘权威缺失） | 检查 `data/peer/grants/` | 不要用内存态补 |
| 突然全量 `audit_unavailable` | 磁盘水位到顶 | 清审计 + 查水位闸 | 不要关审计继续跑 |
| 总返回 `executor_unhealthy` | 水位/依赖故障 | 看 `manifest.health` 与 `health_detail` | 不要重试堆队列 |
| 每次指纹都不同 | 每次 `offer` 重新生成 keypair | 固定 `--home` | 不要重配覆盖旧身份 |

### 5.8 P1 接口 schema（机器可校验的契约）

本节不是散文描述，产物在 `docs/schemas/lfl.peer.v1/`，可被 CI 校验。

#### 5.8.1 契约产物与校验入口

| 文件 | 作用 |
|---|---|
| `manifest.schema.json` | 能力与策略摘要（`inject_type` 用 `const:false` 锁死 D11） |
| `task-submit.schema.json` | 派单请求 |
| `receipt.schema.json` | 回执（状态机 + 封闭 `reason_code` + 条件必填） |
| `grant.schema.json` | 有界租约（`expires_at`/`max_tasks_total` 必填） |
| `pair-offer.schema.json` / `pair-confirm.schema.json` | 配对两阶段 |
| `reason-codes.json` | 36 条封闭错误码 + 每条 `guidance` |
| `examples/*.json` | 7 个正例 |
| `scripts/verify_peer_schemas.py` | 自校验入口 |

```bash
python3 scripts/verify_peer_schemas.py
```

三条原则：

1. **schema 只保证形状，不保证授权**。`kind` 白名单不写进 schema——否则每加一个 kind 都要改 schema，反而妨碍冻结。授权封闭由受控端注册表 + Grant 在闸2 完成，schema 层只校验 `kind` 的语法形态。
2. **`additionalProperties: false` 全线开启**。未知字段直接拒，不允许"多带一个字段就被静默忽略"的兼容。
3. **无法用 JSON Schema 表达的约束，用脚本兜住并显式标注**（§5.8.6 的 `invariant` 行），不假装 schema 管了。

#### 5.8.2 端点契约

| 方法 | 路径 | 请求 | 响应 | 认证 |
|---|---|---|---|---|
| GET | `/peer/v1/pair/offer` | — | `pair-offer` | 无（loopback + 300s + 一次性 nonce） |
| POST | `/peer/v1/pair/confirm` | `pair-confirm` | `{paired_at, node_id}` | 无（同上 + 人眼核对） |
| GET | `/peer/v1/manifest` | — | `manifest` | HMAC |
| POST | `/peer/v1/tasks` | `task-submit` | `receipt` | HMAC |
| GET | `/peer/v1/tasks/{task_id}` | — | `receipt` | HMAC |
| POST | `/peer/v1/grant/revoke` | `{grant_id}` | `grant` | HMAC |

`POST /peer/v1/tasks` 直接返回 `receipt` 而不是 `task_id`：让调用方一次拿到准入结论。若已受理未完成，`state ∈ {submitted, admitted, queued, running}`，用 GET 轮询——不允许在 POST 上阻塞等待执行完成。

`grant/revoke` 只需 HMAC 不需人工审批：撤销是降权，任何方向都安全。

#### 5.8.3 请求签名（HMAC-SHA256）

```
X-Peer-Node-Id: mac-lfl
X-Peer-Ts:      1794028800
X-Peer-Nonce:   9c4f2a7b1d8e3f506a2c9b4d7e1f8203
X-Peer-Sig:     base64(HMAC-SHA256(K_oe, canonical))

canonical = METHOD + "\n" + PATH + "\n" + SHA256_HEX(BODY) + "\n" + TS + "\n" + NONCE
```

- `METHOD` 大写；`PATH` 含 query、不含 host；`BODY` 为空时对空串求 SHA256。
- 时间窗 ±300s（`peer_stale_signature`）。
- nonce 缓存 600s，按 `node_id` 分桶，LRU 上限 10000（`peer_replay_detected`）。
- 签名比较用常量时间比较。

为什么不是每请求 Ed25519：配对已建立共享密钥，HMAC 足够且便宜；非对称只用于身份表达（公钥/短指纹）。

#### 5.8.4 reason_code 分组（36 条，封闭）

| 组 | 条数 | 代表 |
|---|---|---|
| 认证/配对 | 8 | `peer_bad_signature`、`pair_fingerprint_mismatch` |
| 准入 | 12 | `grant_expired`、`requires_supervised_execution`、`audit_unavailable` |
| 策略 | 4 | `path_outside_allowed_paths`、`policy_desktop_type_not_allowed` |
| 沙盒 | 1 | `sandbox_denied` |
| 执行 | 7 | `timeout`、`unknown_outcome`、`artifact_digest_mismatch` |
| 取消/兼容 | 4 | `cancelled_by_grant_revocation`、`unsupported_display_protocol` |

新增 code 的唯一合法路径：改 `reason-codes.json` → 重跑 receipts 生成器 → `verify_peer_schemas.py` 通过。**禁止**在实现里 `raise ValueError("something")` 后把它当 code 返回——`receipt.schema.json` 的 enum 会拒。

`guidance` 的写法要求：一步可执行、不承诺重试、不假设调用方读过文档。例：

```
"policy_task_kind_not_allowed": "kind 不在 PeerGrant.allowed_kinds。先调用 peer_list 读取实际可用 kind，不要猜。"
```

#### 5.8.5 工具签名（模型面）

```python
peer_list() -> {
  "peers": [{
    "peer_id": "deepin-01",
    "health": "ok",
    "display_protocol": "x11",
    "kinds": [{"kind": "fs.read", "idempotency_class": "idempotent",
               "supervised_only": False, "params_schema_hint": "path(abs), max_bytes<=1048576"}],
    "grant": {"grant_id": "gr_...", "expires_at": "...", "tasks_remaining": 17}
  }]
}

peer_dispatch(peer_id, kind, params, expect=[], deadline_s=30) -> receipt
peer_task(peer_id, task_id) -> receipt
peer_fetch(peer_id, ref, to_path=None) -> {local_path, sha256, bytes}
```

三个关键决定：

1. **不给 `execute_command` 加 `peer=` 参数**。模型会在一部分调用里误以为默认本机、另一部分误以为默认远端，而错误机器的代价不对称（本机全权、远端受限）。独立工具族让"我在操作远端"永远显式。
2. **`kind` 的 enum 由 `peer_list` 结果动态生成**。模型编不出白名单外的值——不是提示词约束，是协议层拒绝。
3. **`effect_id` 由程序派生，不由模型输入**。程序对"同一 run 内同一 (peer, kind, params) 的重试"复用同一 `effect_id` 并持久化。理由：D6 说幂等键不是内容哈希，但也不能靠模型记忆——模型重试时抄错一个字符就变成新任务。所以**键的生成权在程序，语义表达留给模型**（模型可用 `retry_of=<task_id>` 显式声明"这是重试"）。

`peer_fetch` 独立存在，不把产物塞进回执：回执只带 `ref` + `sha256`，字节流按需拉取。这保证回执大小与产物大小无关，避免回执随产物体积膨胀。

#### 5.8.6 自校验回执（本次真实执行）

```
$ python3 scripts/verify_peer_schemas.py
[schema] grant.schema.json                 ok
[schema] manifest.schema.json              ok
[schema] pair-confirm.schema.json          ok
[schema] pair-offer.schema.json            ok
[schema] receipt.schema.json               ok
[schema] task-submit.schema.json           ok
[example] ...                              ok   (7 个)
[negative] ...                             ok   (12 个，均被拒)
[invariant] non_idempotent => supervised_only (desktop.click)   ok
[consistency] reason_code enum == reason-codes.json             ok   36 codes
counts: schema=6, example=7, negative=12, invariant=4, consistency=1, iso-fallback=0
note: rfc3339-validator 未安装，date-time 负例记 skipped；示例时间字段已用 fromisoformat 兜底校验
RESULT: PASS (30 checks, 1 skipped)
```

必须诚实标注的两点：

- **1 skipped**：`date-time` 格式负例未被真正校验（缺 `rfc3339-validator`）。要让它真拦，运行时必须用 `datetime.fromisoformat` 兜底，不能依赖 schema 层 `format`。
- **30 checks 覆盖的是契约自洽，不是运行时闸门**。闸门是否生效只能按 §5.7.3 的 `[规格]` 条目在 deepin 上逐条实测——对齐 RULE-AI-35：宣称"生效"前必须实测应拦输入。

12 条负例中有一条来自本次真实踩坑：手写短指纹含 `8`/`9` 被 `^([A-Z2-7]{4}-){7}[A-Z2-7]{4}$` 拒绝。这不是我事先设计的用例，是实现时写错 example 才发现的——它反过来证明"指纹必须由 `keygen` 打印、不得手抄"这条规定有实际价值。


---

## 6. 关键设计决策

### D1 先主从，后对等（否决首版双向网状）

**决策**：首版只支持 `orchestrator → executor` 单向派单；executor 不得主动向 orchestrator 派单。
**理由**：对等意味着任意两节点都要有授权关系（n²）。在没有节点身份体系、没有跨机审计归并前，这会让"谁有权让谁做什么"无法回答。单向模型下授权只有一条链，可验证。
**代价**：executor 侧发现问题无法自动"反向求助"。缓解：允许 executor 在回执里带 `blocked` + `suggested_next`，由控制端决定下一步（模型决策，不是程序）。
**何时推翻**：当出现两个以上 orchestrator 且确有反向委派需求时，重新设计节点信任模型。

### D2 不自造 RPC，但首版也不等标准协议

**决策**：首版用最小自有协议（HTTP/JSON + 封闭 `reason_code`），字段语义刻意贴 A2A Task；不引入 gRPC/消息队列/服务网格。
**理由**：① 引入 gRPC 会带进 proto 编译链与新的运维面，收益与"一个 JSON 端点"差不了多少；② 消息队列（RabbitMQ/Redis Stream）在单对单场景是纯负担；③ 但字段要贴 A2A，让未来适配变成映射而非重新建模。
**代价**：未来接 A2A 时要写适配层。这个代价是显式接受的。

### D3 A2A 只做"外部准入"，不做"内部编排"

**决策**：A2A 协议只用于"外部 agent/平台向 LFL 提交任务"的边界，LFL 之间的日常协同不走 A2A。
**理由**：现有 A2A 骨架的设计意图就是"不可变人类准入"，它是边界设施，不是编排设施。把它当内部总线会破坏其 fail-closed 语义（内部调用会倾向于"跳过准入以提高效率"，这正是要防的）。
**同时说明**：A2A 的现有集成前置（权威 platform principal 校验）**未满足**，因此短期内不承诺"兼容华为 A2A 生态"，只承诺"语义可映射"。

### D4 桌面后端必须自报显示协议，不伪造能力

**决策**：新增 `backend_linux.py` 时，`status` 必须返回当前会话的显示协议（`x11` / `wayland`）、`DISPLAY`、合成器名、截图能力、注入能力。Wayland 下 `desktop_perceive.vision` 与 `desktop_operate` 返回确定性的 `unsupported_display_protocol`，附修复指引（切换 X11 会话），**不尝试 portal 兜底、不伪造成功**。

**理由**：portal 需要每次会话用户确认，与无人值守语义冲突；伪装支持会产生"演示可用、无人值守失败"的落差，属于诚实性缺陷而非能力缺陷。

**与 v1 的差异**：v1 把本节定位为"限定 X11 + 窗口级"，隐含"X11 下可以做"。用户确认 X11 后，真正的问题不再是"支不支持"，而是**X11 没有应用间隔离**，L3 会成为 L2 沙盒的旁路。因此权限限制从本节移到 **D11**（独立授权域 + click-only + 禁止键入），本节只保留"如实自报能力"这一条。
### D5 明确否决共享文件系统做跨机协调

**决策**：不把 `data/` 挂到网络文件系统让现有原语跨机工作。
**理由**：
- `fleet` 明确以"磁盘是唯一权威 + fcntl 跨进程锁 + 原子替换写"为正确性基础；NFS 的 fcntl 依赖 lockd，故障模式下会退化为无锁；Syncthing 类同步根本无锁语义。
- 仓库内多处依赖"版本 CAS + 原子替换"（lane、queue、fleet、service_control）。锁一旦不可靠，这些从"正确"变成"偶然正确"，且**失败是静默的**——最坏的一类缺陷。
**替代**：跨机一律走显式请求-应答（D2），把"共享状态"改成"查询对方状态"。

### D6 幂等键是 `effect_id`，不是任务内容哈希

**决策**：幂等由控制端生成的稳定 `effect_id` 保证；受控端按 `effect_id` 去重。
**理由**：内容哈希在参数顺序/时间戳/临时路径变化时会误判为新任务，导致重复执行（对有副作用的操作是灾难）。`effect_id` 由发起方语义决定，配合"先核是否已完成、不重放"的既有纪律。
**实现要求**：去重记录必须在**产生任何副作用之前**落盘（与 admission 同一次写）。

### D7 回执只承载"事实 + 引用"，不承载"叙事"

**决策**：peer 回执里只有状态、封闭原因码、产物引用、时间戳。不写"我已经帮你完成了 XX，效果很好"这类叙述。
**理由**：叙述会诱导控制端模型直接采信（RULE-AI-13：外部输出不自动获得裁决权）。事实 + 引用让控制端必须自己核验。

### D8 peer 任务走独立审计流，不混入 human ingress 审计

**决策**：新增 `data/peer/` 审计（append-only），记录每次提交、准入、拒绝、执行、回执的完整链。
**理由**：出事时要能回答"这条指令是谁、以什么身份、在什么授权下进来的"。混进 human 流会让这个问题无法回答。对齐现有 `submit_evolution` 审计与 A2A admission 的"不同 principal 隔离"。

### D9 不新增常驻守护通道

**决策**：不做长连接心跳/反向隧道常驻服务。控制端按需发起请求（或复用 SSH 隧道）。
**理由**：常驻通道意味着常驻攻击面与常驻运维负担（重连、认证刷新、半开连接）。单对单、低频派单场景下，请求-应答足够；需要低延迟时用 SSH 隧道保活，由 SSH 承担。
**例外条件**：若未来需要秒级双向事件推送（如远程观察到本地告警立即反应），再评估 WS 长连接；届时必须复用现有 `realtime_ws` 的握手鉴权与拒绝码规范。
### D10 无人值守 = 事前授权，不是事中审批

**决策**：peer 通道的授权以"事前签署的有界租约"为唯一合法来源；执行期间**不设计任何需要人工点击的同步确认**。`blocked` 仅用于"不可自动决定且可安全等待"的情形，且必须有超时。

**理由**：无人值守的语义是"人不在场"。任何"事中审批"要么让任务永久挂起，要么诱导实现者加一条"超时自动放行"的暗门——后者等于没有审批。两条路都不可接受。

**实现要求**：
1. `PeerGrant` 必须显式声明：允许的 `kind[]`、路径/命令范围、**最长有效期与最大次数**（对齐既有常驻授权模式：`wake_fires` + `wake_expires_in_days` 的有界设计）。
2. 租约**到期即停**，不自动续期；续期是一次新的真人签署动作。
3. `blocked` 必须有 `blocked_deadline`；超时转 `failed / blocked_timeout` 并投递通知，**不得静默挂起**。
4. 需要人现场决定的事项必须在**派单时即拒**（`denied / requires_human_presence`），而不是先接单再卡住。

**代价**：扩权需要人重新签署，不能"临场决定"。这是无人值守换来的，必须接受。

### D11 L3 是独立授权域，首版 click-only 且禁止文本键入

**决策**：
1. L3 授权**不与 L2 共用 `PeerGrant`**，必须单独签发 `DesktopGrant`（独立 scope、独立有效期、独立吊销）。
2. 首版 L3 **只允许 click + 截图**，**禁止 `type`（文本键入）**，返回确定性 `policy_desktop_type_not_allowed` 并附理由。
3. 若后续确需键入，必须满足：目标窗口在**显式窗口白名单**内（`WM_CLASS` + 标题匹配），注入前断言焦点窗口属于白名单；断言失败即拒绝，不做"尽力而为"。

**理由**：见 §4.3。`type` 的能力空间是"任意字符串进入任意输入框"，等价于任意命令执行；`click` 的能力空间是"触发已存在的 UI 元素"，受限于界面上真实存在的控件（无法凭空创造按钮）。两者风险差一个数量级，不能同档授权。

**残余风险（诚实声明）**：click-only 仍可点到"终端历史命令"或"确认删除"按钮。这不能完全消除，只能靠：① 目标窗口白名单；② 点击前后各留一帧截图进审计流（可事后复盘）；③ 不接受"坐标由远端自由指定"，坐标必须来自本端采集帧的定位结果。

### D12 SSH 只做隧道，不做执行通道

**决策**：SSH 唯一允许用途是端口转发（`ssh -N -L`）。**禁止** `ssh host <command>`、交互 shell、`scp`/`rsync` 作为派单或产物传输手段。

**理由（拷问暴露的最大运维风险）**：SSH key 的权限粒度是"登录即全权"。若允许 `ssh host <cmd>`，持有该 key 的任何进程都可完全绕过 P1 的四道闸、绕过 admission、绕过审计——**P1 的安全设计在 SSH 面前归零**。

**实现要求**：
1. deepin 侧 `~/.ssh/authorized_keys` 条目加限制：`no-pty,no-agent-forwarding,no-X11-forwarding,permitopen="127.0.0.1:8903"`。
2. 隧道只允许转发 Web 端口（L1）与 peer 端口（P1 若走隧道）。
3. 产物传输一律走 `artifact://` HTTP 端点，不走 `scp`（否则产物脱离审计）。
4. **残余风险必须写进运维文档**：能修改 `authorized_keys` 的人（有 sudo 或就是该用户）依然能绕过一切。这是本设计的信任根，无法用本设计消除。

### D13 不承诺 exactly-once，承诺 at-most-once + 可核验终态

**决策**：peer 任务按幂等性分两类：
- `idempotent: true`（读文件、构建、查询）：崩溃后可安全重试，状态收敛到终态。
- `idempotent: false`（"删除这批文件"、"发送这条消息"）：**不自动重试**；崩溃后进入 `unknown_outcome` 终态，等待核验。

**并且**：无人值守场景下，`idempotent: false` 的 `kind` **必须自带前置可回滚手段**（先快照、或先移动到隔离目录），否则不得进入无人值守白名单。

**理由**：分布式系统里 exactly-once 不存在。原 §5.2 不变量 4 与 T7 只覆盖了"未开始执行"，**没有覆盖"执行到一半崩溃"**——那时代码既不能重跑（重复副作用），也不能假定未执行（可能已改了一半）。承认这个事实并显式建模，比承诺一个做不到的保证更安全。

**代价**：`unknown_outcome` 需要人核验，与无人值守冲突。真正的解法是**在准入阶段把这类任务挡在无人值守白名单外**，而不是在执行阶段补救。

### D14 工具面：新增独立工具族，不给现有工具加 peer 参数

**决策**：新增 `peer_list` / `peer_dispatch` / `peer_task` / `peer_fetch` 四个工具，**不**给 `execute_command`、`read_file` 等现有工具增加 `peer=` 参数。

**理由**：
1. **语义混淆直接导致事故**：模型若在 `execute_command` 上看到可选 `peer` 参数，会在一部分调用里误以为默认本机、另一部分误以为默认远端。而错误机器上的代价不对称（本机全权、远端受限），不能指望模型每次读对。
2. **授权语义不同**：现有工具绑定本机 `write_scope`/bwrap/审批闸，远端是另一套 `PeerGrant`。混在一个 schema 里会让"本机全权 vs 远端受限"的差别在参数层消失。
3. **AI 友好性的正确做法是"可发现 + 不可编造"**，不是"参数少"：
   - `peer_list` 零参数，模型开局就会调，返回每个 peer 的 `node_id`、`online`、`kinds[]`（**直接给出可用 kind 枚举**）；
   - `peer_dispatch` 的 `kind` 用 JSON Schema `enum` 由 `peer_list` 结果动态生成，模型**无法编造**不在白名单的 kind；
   - 失败返回封闭 `reason_code` + 一行 `guidance`（如"该 peer 不支持 build.run，可用：fs.read, query.build_status"），让模型自纠而不是读长文档。

**代价**：模型需认识 4 个新工具。用零参数的 `peer_list` 作入口，可把学习成本压到"调一次就知道"。

### D15 内网不等于信任域：强制双向认证

**决策**：peer 通道一律双向认证（mTLS 或双向 HMAC + 节点指纹白名单），**禁止**任何"内网所以免认证"或"只验服务端证书"。

**理由**：同内网降低的是可达性成本，不降低认证必要性。内网存在同事机器、访客 WiFi、IoT 设备；ARP 欺骗与 DNS 劫持在内网是常规手段。只验 server 还会带来**反向风险**：伪造的 deepin 可以接受 mac 的派单并返回投毒产物，而控制端会把产物当证据采信。

**实现要求**：
1. 双向：控制端持私钥、受控端持公钥指纹白名单；至少受控端必须验控制端。
2. 禁裸 HTTP：即使在内网，peer 端点也只监听 TLS，或仅绑 `127.0.0.1` + SSH 隧道。
3. 首次配对必须人工核对短指纹（见 §5.7），不用 TOFU 静默信任。



---

## 7. 分阶段实施计划

### P0 — 会话接管（零代码，1 天内）

**范围**：让 S1 真实可用。

| 步骤 | 动作 | 验收 |
|---|---|---|
| P0-1 | 确认 deepin 侧 `WEB_HOST` 仍为 `127.0.0.1`（不直接暴露） | `ss -ltnp` 只见 loopback |
| P0-2 | 建 SSH 隧道（`ssh -N -L 8903:127.0.0.1:8903 <deepin>`），并按 D12 收紧 `authorized_keys`：`no-pty,no-agent-forwarding,no-X11-forwarding,permitopen="127.0.0.1:8903"` | mac 侧 `curl http://127.0.0.1:8903/` 返回登录页；**`ssh <deepin> 'id'` 被拒绝**（证明 shell 不可用） |
| P0-3 | deepin 侧配置 `WEB_API_KEY` + `WEB_AUTH_REQUIRE=1` | 不带凭证 → 401；带错误凭证 → 401；正确 → 200 |
| P0-4 | 顺带确认 Deepin 桌面问题不会被误判为 LFL 故障 | 引用 `docs/installation.md:398-409` 的 Wayland/dde-lock 排障项 |

**不做**：不改任何代码，不发版。
**回滚**：关隧道即可，无状态变更。
**风险**：若用公网暴露（Cloudflare tunnel 等），必须确认 `WEB_ORIGIN_ALLOWLIST` 与 `WEB_CANONICAL_HOST` 已配置，否则 `_CanonicalOriginMiddleware` 的"http→https 升级"判定会误伤（`src/llm_loop/web/__init__.py:137-184` 的既有约束）。

### P1 — Peer 任务通道 + 无人值守授权模型（核心，3~4 周）

**范围**：S2 端到端可用。

| 工作项 | 内容 | 验收 | 预估 |
|---|---|---|---|
| P1-1 | `PeerNode` / `PeerGrant` 存储（磁盘权威 + 版本 CAS，对齐 fleet 模式） | 并发写不丢更新；旧版本写被拒 | 3d |
| P1-2 | `/peer/v1/manifest` + 节点认证（HMAC + 时间窗 + 重放拒绝） | 篡改 body / 过期时间戳 / 重放 → 401 | 3d |
| P1-3 | `PeerTask` 状态机 + admission store（副作用前落盘） | 崩溃重启后状态可恢复；未准入无副作用 | 4d |
| P1-4 | 执行器：把准入任务翻译成本地执行（复用现有工具栈与沙盒） | 闸4 生效：越界路径被 `write_scope` 拒 | 5d |
| P1-5 | 产物回传（`artifact://` + sha256） | 大产物不内联；校验失败判 failed | 2d |
| P1-6 | 控制端工具 `peer_list` / `peer_dispatch` / `peer_task` / `peer_fetch`（按 D14：独立工具族，不给现有工具加 `peer=` 参数） | `kind` 由 `peer_list` 结果动态生成 enum，模型无法编造；失败返回封闭 `reason_code` + `guidance` | 3d |
| P1-7 | 审计流 `data/peer/` | 每次提交可追溯到 `admission_id` | 1d |
| P1-8 | 发版与 deepin 升级 | wheel 升级后服务健康；`service_control` 身份校验通过 | 依赖同日发行设计 |
| P1-9 | 幂等性声明 + `unknown_outcome` 终态（D13） | 非幂等类别崩溃后不自动重试；无回滚手段的类别进不了无人值守白名单 | 2d |
| P1-10 | 一次性配对流程（短指纹核对 + 双向白名单，§5.7.2 / §5.7.3） | 配对 ≤5 分钟人工；错误短码被拒；**不支持 TOFU 静默信任** | 2d |
| P1-11 | 审计轮转 + 磁盘水位闸（F7） | 水位 >90% 时 `manifest.health=degraded` 且新任务被拒；审计链不断裂 | 2d |
| P1-12 | 契约 schema 与自校验（§5.8） | `verify_peer_schemas.py` PASS；新增 `reason_code` 必须过 enum 一致性；`inject_type` 被 const 锁死 | 1d |

**关键验收（都应拦而拦住）**：
1. 未在白名单的 `kind` → `denied / policy_task_kind_not_allowed`
2. `PeerGrant` 过期 → `denied`
3. 目标路径越出 `allowed_paths` → `denied`，且**沙盒层也独立拒绝**（双保险）
4. 同一 `effect_id` 重放 → 返回原记录，**执行次数仍为 1**
5. 伪签名 / 旧时间戳 → 401，**零副作用**
6. 受控端在 `admitted` 后**尚未开始执行**时崩溃 → 重启收敛到终态，**执行次数 ≤ 1**。
7. 受控端在**执行中**崩溃（已产生部分副作用）→ 状态为 `unknown_outcome`，**不自动重试**（对齐 D13 / U5）。
8. `PeerGrant` 已用满 `max_tasks` → `denied / grant_exhausted`（对齐 U2）。
9. 审计目录不可写 → `denied / audit_unavailable`，**执行次数 0**（对齐 U10）。
10. 手写或错一组字符的短指纹 → 被 `pair-offer`/`pair-confirm` 的 schema 拒绝（**已实测**，见 §5.8.6）。

**回滚**：端点默认关闭（`PEER_ENABLED=0`）；关闭后所有请求 404/503，不影响既有功能。

### P2 — 工具面与像素面（3~4 周，L3 受 D11 硬限制）

**P2-A MCP server 化（工具面）**
- 只暴露**显式白名单**的只读工具子集（先 `read_file` / `search_files` / `browser_perceive`），写入类一律不暴露。
- 每个暴露的工具必须带等价于本地 `write_scope` 的边界；不得因为"是 MCP 调用"而放宽。
- 验收：越界读取被拒；未列入白名单的工具不出现在 `tools/list`。

**P2-B Linux 桌面后端（像素面）**
- 新增 `src/llm_loop/desktop/backend_linux.py`，实现与 macOS 后端同构的最小接口（`status` / `windows` / `capture_window` / `click` / `type`）。
- `status` 必须报告：显示协议（x11/wayland）、DISPLAY、合成器名、截图能力、注入能力。
- X11：截图用 `import`/`xwd` 或 Xlib；注入用 XTest。
- Wayland：确定性 `unsupported_display_protocol`。
- 验收：X11 下截图非黑图、点击命中；Wayland 下明确拒绝并给指引。

**P2-C A2A 适配（外部准入面）**
- 仅在 P1 的 admission 语义稳定后做字段映射；不改变准入模型。

---

## 8. 安全分析

### 8.1 威胁模型

| 威胁 | 入口 | 缓解 |
|---|---|---|
| 未授权节点提交任务 | `/peer/v1/tasks` | 双向凭证 + 指纹白名单 + 时间窗 + 重放拒绝（闸1） |
| 合法节点提交越权任务 | 同上 | `PeerGrant` 白名单 + 类别策略 + 配额（闸2/3） |
| 任务执行越出文件边界 | 执行器 | `write_scope` + bwrap（闸4），与本地调用同款 |
| 重放导致重复副作用 | 同上 | `effect_id` 幂等 + 副作用前落盘（D6） |
| 控制端被攻陷后横向移动 | 控制端 → 受控端 | 单向模型 + 受控端独立策略；受控端不因"对端可信"而放宽本地边界 |
| 大文件/上下文污染 | 产物回传 | 一律 `artifact://` 引用（D7） |
| 审计不可追溯 | 全链路 | `data/peer/` append-only + `admission_id` 贯穿（D8） |
| 远程通道变成沙盒旁路 | 实现走偏 | 硬性架构约束：闸4 必须复用现有机制；代码评审强制检查 |
| 伪造对端接受派单并返回投毒产物 | 内网劫持（ARP/DNS） | 双向认证 + 短指纹人工核对（D15）；控制端独立核验产物 sha256 |
| SSH 全权凭证绕过全部闸 | `ssh host <cmd>` | 仅许 `-L` 转发 + `authorized_keys` 限制（D12）；残余风险明示 |
| L3 注入成为 L2 沙盒旁路 | XTest 向焦点窗口注入 | 独立授权域 + click-only + 禁止键入（D11） |
| 执行到一半崩溃，状态不可知 | 执行器被杀 / 掉电 | `unknown_outcome` 终态 + 不自动重试 + 非幂等类别要求前置快照（D13） |
| 审计持续增长撑爆磁盘导致静默停摆 | 长期无人值守 | 审计轮转 + 水位闸 + `manifest.health`（F7 / U6 / U10） |
| 重放窗口被利用 | 内网抓包重放 | 时间窗（300s）+ **持久化** nonce 缓存，TTL ≥ 2× 窗口（F5） |

### 8.2 fail-closed 清单（任何一条不满足即拒绝，不得降级放行）

1. 节点指纹不在白名单 → 拒绝。
2. 签名校验失败 / 时间窗超出 / 重放 → 拒绝。
3. `PeerGrant` 缺失 / 过期 / 被撤销 → `denied`。
4. 任务 `kind` 不在白名单 → `denied`。
5. 目标路径不在 `allowed_paths` → `denied`（沙盒层再拒一次）。
6. admission 写入失败或结果不确定 → **拒绝派发**（结果不确定不等于成功）。
7. `succeeded` 但产物校验失败 → 降级为 `failed`。
8. 状态查询超时 → 如实报"未知"，不得推断"应该完成了"。
9. 审计不可写（磁盘满 / 只读挂载）→ `denied / audit_unavailable`，**不得无审计执行**。
10. 执行器健康水位不达标（磁盘 >90% / 队列积压超阈）→ `denied / executor_unhealthy`。
11. `blocked` 超过 `blocked_deadline` → `failed / blocked_timeout`；**不得无限等待，更不得超时自动放行**。
12. `idempotent:false` 且无回滚手段的 `kind` 出现在无人值守白名单 → **准入阶段即拒**（不是在执行阶段补救）。
13. 非幂等任务执行中崩溃 → `unknown_outcome`，**不得自动重试**，也不得推断为成功或失败。

### 8.3 明确不做（安全红线）

- 不以 root 运行 LFL 换取 `uinput` 注入能力。
- 不为远程通道关闭 bwrap 或扩大 `write_scope`。
- 不把 WebUI 的人类 Bearer key 复用为机器凭证。
- 不允许受控端执行"任意 shell"类 `kind`（必须是有语义的白名单任务类别）。
- 不允许控制端直接读取受控端的会话内存/prompt 内容（只读任务回执与产物）。
- 不在 Wayland 下用"看起来能用"的方式伪造注入成功。
- 不把 SSH 交互 shell / `ssh host <cmd>` 当作执行通道（D12）。能修改 `authorized_keys` 的人仍是本设计的信任根，此风险写入运维文档，不假装消除。
- 不为"某软件必须输入才能用"放宽 L3 的 click-only 限制（D11）；应改走有人在场模式，与无人值守严格分离。
- 不在 `idempotent:false` 且无前置快照的任务上自动重试（D13）。

---

## 9. 验收与测试设计

### 9.1 应拦输入实测（RULE-AI-35：宣称"生效"前必须实测）

以下每条都必须有一条**真实的、构造出来的应拦输入**跑过，拿到拒绝回执，才能说"闸生效"：

| 编号 | 应拦输入 | 期望回执 | 反例（说明未生效） |
|---|---|---|---|
| T1 | 伪造 `X-Peer-Node-Id` | 401 `peer_unknown_node` | 200 |
| T2 | 签名正确但 `timestamp` 为 10 分钟前 | 401 `peer_stale_signature` | 200 |
| T3 | 同一请求原样重放两次 | 第二次返回同一 `admission_id`，执行次数 1 | 执行两次 |
| T4 | `kind=shell.exec`（不在白名单） | `denied / policy_task_kind_not_allowed` | `queued` |
| T5 | `params.path=/etc/shadow` | `denied` + 沙盒层 `sandbox_denied` | 读到内容 |
| T6 | `PeerGrant.expires_at` 为昨天 | `denied / grant_expired` | `queued` |
| T7 | 受控端在 `admitted` 后 kill -9，重启 | 状态恢复为 `queued` 或 `failed`，**不重复执行** | 重复执行 |
| T8 | 产物 sha256 被篡改 | `failed / artifact_digest_mismatch` | `succeeded` |
| T9 | Wayland 会话下调用 `desktop_operate` | `unsupported_display_protocol` + 指引 | 返回成功 |
| T10 | 匿名（无凭证）访问 `/peer/v1/manifest` | 401 | 200 |

### 9.2 测试分层

- **单元**：签名/时间窗/幂等键/状态机转移/`reason_code` 封闭性。
- **契约**：端点响应 schema 与 `lfl.peer.v1` 一致；未知字段不导致 5xx。
- **故障注入**：磁盘满、admission 写入中断、执行中 kill、产物损坏。
- **端到端**：mac → deepin 真实派单一次（用无害任务，如 `fs.read` 白名单路径）。
- **回归**：确认 peer 通道关闭时，既有 Web/Feishu/Learning 行为完全不变。

### 9.3 完成定义（DoD）

- 上述 T1–T10 全部有真实拒绝回执。
- 端到端一次成功派单 + 一次被拒派单，均在 `data/peer/` 审计中可追溯。
- `PEER_ENABLED=0` 时既有测试全绿。
- 独立 Reviewer 对"闸4 未成为沙盒旁路"给出 PASS（对齐 RULE-AI-28）。

### 9.4 无人值守专项验收（对应 D10 / D13 / D15）

| 编号 | 场景 | 期望 |
|---|---|---|
| U1 | 租约已到期，控制端派单 | `denied / grant_expired`，**执行次数 0** |
| U2 | 已用满 `max_tasks` | `denied / grant_exhausted` |
| U3 | `idempotent:false` 的 kind 不在无人值守白名单内被派单 | `denied / requires_supervised_execution` |
| U4 | 任务进入 blocked 且超过 deadline | 转 `failed / blocked_timeout` 且投递通知；**不得静默挂起** |
| U5 | 执行中 kill -9（已产生部分副作用） | 重启后状态为 `unknown_outcome`（非 succeeded/failed），**不自动重试** |
| U6 | 磁盘水位 >90% | `manifest` 的 health 标记 degraded，新任务 `denied / executor_unhealthy` |
| U7 | L3 请求 `type` 键入 | `denied / policy_desktop_type_not_allowed` |
| U8 | 撤销 PeerGrant 后 1 秒内派单 | `denied / grant_revoked`；已入队任务转 cancelled |
| U9 | 伪造 deepin 侧证书（模拟中间人） | 控制端拒绝连接且不发出派单；**不得降级为明文** |
| U10 | 审计目录写入失败（模拟只读挂载） | 新任务 `denied / audit_unavailable`，**不得无审计执行** |


---

## 10. 未决与待确认（本文未核实项，不得当事实使用）

以下每一项都会实质影响方案选择，需要实机或你确认后回填：

| 编号 | 未决问题 | 为什么重要 | 默认假设（未确认时按此设计） |
|---|---|---|---|
| Q1 | ~~登录会话是 Wayland 还是 X11？~~ | — | **已确认：X11**（2026-11-07 用户回答）。L3 技术可行；但授权粒度问题见 §4.3 / D11，不因技术可行而放开 |
| Q2 | ~~是否同一内网 / 有无组网工具？~~ | — | **已确认：同一内网**。P0 走内网直连 + SSH 隧道；不引入公网暴露与第三方组网 |
| Q3 | ~~是否需要无人值守？~~ | — | **已确认：需要**。§5.7 事前授权模型为必需项；portal 路径彻底排除 |
| Q4 | deepin 侧 LFL 是否以普通用户运行、是否有 sudo？ | 决定能否做系统级操作，以及安全红线 | 按**普通用户、无 sudo** 设计 |
| Q5 | 是否接受"功能上线依赖 wheel 发版 + 服务重启"？ | P1 的落地代价；替代方案是临时 SSH 包装（功能受限） | 按**接受发版**设计 |
| Q6 | deepin 上真正需要 GUI 操作的软件有哪些？能否 CLI 化？ | GUI 需求强度决定 L3 是否值得做 | 按"多数可 CLI 化"设计，L3 降为可选 |
| Q7 | 是否要求兼容华为 A2A 生态（有真实 platform principal）？ | 决定 P2-C 是否启动 | 按**不承诺生态兼容、只承诺语义可映射**设计 |
| Q8 | 跨机任务是否需要互相看实时进度（秒级）？ | 决定 D9 是否要推翻 | 按**不需要**设计（请求-应答） |
| Q9 | §5.7.3 的 21 条 `[规格]` 条目尚未在 deepin 上执行 | 决定 P1 能否宣称「闸生效」 | 按**逐条实测通过才算完成**设计；未过的条目不写进交付 |
| Q10 | schema 层 `date-time` 校验依赖 `rfc3339-validator`（当前缺失，1 条负例 skipped） | 影响「非法时间戳被拦」的可验证性 | 运行时用 `datetime.fromisoformat` 兜底，不依赖 format |

**已核实、无争议的项**：desktop 仅 macOS（`backend_macos.py` 平台判定）；A2A 无 HTTP 路由（文件头自述）；MCP 仅 client 侧；Web 默认 loopback + fail-closed 鉴权；协作原语锚定本机文件。

---

## 11. 与既有文档 / 既有机制的关系

| 文档 / 机制 | 关系 |
|---|---|
| `docs/DESIGN-20261107-linux-managed-upgrade-restart-sandbox-authorization.md` | **前置依赖**。P1 的代码要上 deepin，必须走它的发行控制面与服务控制面；本文不重复设计升级通道 |
| `docs/installation.md` §Linux 桌面环境排障（Deepin 25） | **实机证据来源**。Wayland 采集失败、`dde-lock` 黑窗两条记录直接支撑 §4.3 与 Q1 |
| `docs/DESIGN-20260919-fleet-minimal-slice.md` | **模式参考**。磁盘权威 + fcntl + generation fencing 的写法被 P1-1 沿用 |
| `src/llm_loop/web/a2a_task_admission.py` | **语义来源**。"不可变准入先于副作用"直接继承；本文不改造该模块 |
| `src/llm_loop/web/human_turn_queue.py` | **状态机参考**。peer 队列刻意同构，便于复用 reaper 思路；但不混流（D8） |
| `tools/mcp_transport.py` | **未来复用点**。P2-A 用它反向实现 server 侧，不新写传输层 |
| `desktop/backend_macos.py` | **接口模板**。P2-B 的 `backend_linux.py` 与之同构，`unsupported_platform` 语义保持一致 |
| RULE-AI-13 / 14 / 15 | **授权边界**。三处约束贯穿 §5.4 与 §8.2 |

---

---

## 12. 拷问记录（2026-11-07 修订依据）

本节记录修订前的假设、拷问发现、以及**被推翻的旧结论**。保留这些不是存档，是让后来者能区分"想过之后仍然这么定"与"当时没想清楚"。

### 12.1 被推翻的旧结论（必须显式记账）

| 旧结论（v1） | 为什么错 | 现在的结论 |
|---|---|---|
| "首版只做只读任务类别，损失上限可控" | 无人值守要的就是夜里干写类活。只读是"技术验证切片"，不是可交付形态；当最终形态等于交付一个不能用的东西 | 只读仅用于第 1 周验证四道闸；第 2 周进入写类（受 D13 约束） |
| "X11 下 L3 可实现窗口级接管"（隐含"因此可以做"） | 技术可行 ≠ 可授权。X11 无应用间隔离，XTEST 注入到终端 = 任意命令执行 = 绕过 L2 全部闸 | L3 独立授权域 + 首版 click-only + 禁止键入（D11） |
| "SSH 隧道作为 P0 方案，简单可靠"（未限制用途） | SSH key 是全权凭证。允许 `ssh host <cmd>` 会让 P1 四道闸全部归零 | SSH 仅许 `-L` 转发 + `authorized_keys` 限制（D12） |
| "幂等由 effect_id 保证，重复提交不重跑"（不变量 4 / T7） | 只覆盖"未开始执行"，没覆盖"执行到一半崩溃"。exactly-once 不存在 | at-most-once + `unknown_outcome` + 不可幂等类别必须前置快照（D13） |
| "同内网 → 传输风险低，可简化认证" | 内网有同事机器/访客 WiFi/IoT；ARP 欺骗是常规手段；只验 server 会被伪造 deepin 投毒 | 强制双向认证（D15） |
| "blocked 等人决策" 作为常规状态 | 无人值守时没人来解，任务永久挂起并占配额 | blocked 必须有 deadline，超时 failed + 通知（D10） |

### 12.2 十项拷问与处置

| # | 拷问 | 发现 | 处置 |
|---|---|---|---|
| F1 | L3 与 L2 的授权粒度能否统一？ | **不能**。L3 能力空间是"任意 UI 交互"，无法用任务类别白名单表达；且它是 L2 沙盒的旁路 | D11：独立授权域 + click-only |
| F2 | 无人值守时 blocked 怎么办？ | 原设计会永久挂起，且实现者会加"超时自动放行"暗门 | D10：deadline + 超时通知；需人现场决定的类别**派单时即拒** |
| F3 | SSH 与任务级准入是否冲突？ | **冲突且严重**：SSH 全权绕闸 | D12：仅隧道 + authorized_keys 限制 + 残余风险明示 |
| F4 | 内网能否视为信任域？ | 不能 | D15：双向认证 |
| F5 | 重放窗口如何设？ | 时间窗太短→长任务重投失败；太长→重放面大。且 nonce 缓存必须持久化，否则重启即失效 | 时间窗（建议 300s）+ 持久化 nonce 缓存（TTL ≥ 2× 窗口） |
| F6 | 执行到一半崩溃怎么办？ | 原不变量未覆盖；exactly-once 不可能 | D13 |
| F7 | 无人值守长跑的头号故障是什么？ | **磁盘满**：audit append-only 增长 → admission 写不进 → fail-closed 拒绝一切 → 静默停摆 | 审计轮转 + 水位闸（>90% 先告警再降级）+ `manifest` 暴露 health |
| F8 | 工具面如何 AI 友好？ | 给现有工具加 `peer` 参数会导致"在错误机器上执行"，且本机/远端代价不对称 | D14：独立工具族 + `peer_list` 零参数入口 + `kind` 用 enum |
| F9 | "授权简单"怎么做？ | 每次弹窗与无人值守矛盾；若把"简单"理解成"减少确认"，方向就是错的 | §5.7：一次性配对/授权 + 日常零点击 + 有界租约 |
| F10 | 断网时审计如何闭合？ | 任务可能已执行但回执未达，控制端会误判 | 受控端本地审计是权威，回执只是通知；恢复后 `peer_task` 查本地账本 |

### 12.3 尚未闭合的问题（诚实标注，不得当已解决）

1. X11 焦点窗口白名单的 `WM_CLASS` 匹配在 DDE 下是否稳定？**未实测**。
2. `authorized_keys` 的 `permitopen` 限制与 deepin sshd 版本行为是否一致？**未实测**。
3. 磁盘水位闸阈值（90%）与审计轮转策略需按 deepin 实际磁盘容量定。**未实测**。
4. click-only 能否覆盖真实 GUI 场景（如某客户端必须键入账号密码登录）？**很可能不够**。若不够，应单列"有人在场"模式并与无人值守严格分离，**不得放宽 D11**。

---

*本节结论均为设计推演，未经实机验证。任何按本文实施的改动，须先经独立 Reviewer 审查并按 §9.1 / §9.4 完成应拦输入实测，方可宣称"闸生效"。*


---

## 附录 A：本文事实索引（便于复核）

| 事实 | 证据位置 |
|---|---|
| 本机为 macOS arm64 | 本次 `uname -a` |
| 源码基线 HEAD | 本次 `git log --oneline -1` = `ee475a352` |
| deepin 实机基线（Deepin 25 / 6.6.155 / wheel 0.6.40） | `docs/DESIGN-20261107-linux-managed-upgrade-restart-sandbox-authorization.md` §0 |
| desktop 仅 darwin | `src/llm_loop/desktop/backend_macos.py:5-6,98-102`；`desktop/models.py:32`（`UNSUPPORTED_PLATFORM`） |
| desktop 包无 Linux/X11/Wayland 代码 | 本次 `grep -rln 'xdotool\|ydotool\|uinput\|XTest\|Xlib\|wayland' src --include=*.py` → 零命中 |
| Deepin Wayland 采集失败 / dde-lock 黑窗 | `docs/installation.md:398-409` |
| Web 默认 loopback / 端口 8903 | `src/llm_loop/web/__init__.py:532-535` |
| Web 鉴权 fail-closed 三触发条件 | `src/llm_loop/web/auth.py` 模块 docstring |
| 会话仅进程内存、多实例不共享 | `src/llm_loop/web/auth.py` 能力边界段 |
| WS 拒绝码 4401/4403/4404/4405 | `src/llm_loop/web/realtime_ws.py` 模块 docstring |
| Human Turn Queue 状态机与 reaper | `src/llm_loop/web/human_turn_queue.py:1-20` |
| A2A offline-only、无 HTTP route | `src/llm_loop/web/a2a_task_admission.py:1-11` |
| MCP 传输三实现 + OAuth | `src/llm_loop/tools/mcp_transport.py:1-19`；`mcp_auth.py` |
| coordination board 只读 + 装配层鉴权 | `src/llm_loop/web/coordination_routes.py:1-25` |
| fleet 磁盘权威 + fcntl + fencing | `docs/DESIGN-20260919-fleet-minimal-slice.md` §机制 |
| interop 文件式 inbox 目录 | 本次 `find data/interop` → `lfl_to_dsh` / `dsh_to_lfl` / `session`，各含 `pending`/`done` |
| RULE-AI-13/14/15 正文 | `docs/ai_rules.md:245-271` |

---

## 附录 B：一次完整派单的时序（P1 目标形态）

```
控制端 mac LFL                受控端 deepin LFL
     │                              │
     │ 1. GET /peer/v1/manifest     │  （读能力 + 策略摘要，判断能不能派）
     │─────────────────────────────►│
     │◄─────────────────────────────│  {kinds:[fs.read, build.run], limits:{...}}
     │                              │
     │ 2. 模型决策：这件事该在 Linux 做 │  （程序不代劳）
     │                              │
     │ 3. POST /peer/v1/tasks       │
     │    Idempotency-Key: effect-7f3a
     │─────────────────────────────►│
     │                              ├─ 闸1 认证/时间窗/重放
     │                              ├─ 闸2 写 admission 记录（不可变，先落盘）
     │                              ├─ 闸3 策略：kind 白名单？路径？配额？
     │                              └─ 入本地队列（durable）
     │◄─────────────────────────────│  202 {admission_id, state:queued}
     │                              │
     │                              ├─ 本地 run（human ingress 同款执行栈）
     │                              ├─ 闸4 write_scope / bwrap 生效
     │                              └─ 产物落 artifact:// + sha256
     │ 4. GET /peer/v1/tasks/{id}   │
     │─────────────────────────────►│
     │◄─────────────────────────────│  {state:succeeded, result:{artifacts:[...]}}
     │                              │
     │ 5. GET .../artifacts         │  （按需拉，不内联）
     │─────────────────────────────►│
     │◄─────────────────────────────│  产物字节流 / 引用
     │                              │
     │ 6. 控制端核验 sha256 与内容  │  （远端"完成"只是证据，不是裁决）
     └──────────────────────────────┘
```

失败分支（都必须在回执里可区分，不得合并成"失败"）：
- `denied / policy_task_kind_not_allowed` — 策略不允许，**没有执行过**
- `denied / grant_expired` — 授权过期，**没有执行过**
- `blocked / needs_human_decision` — 需要人在 deepin 侧点确认
- `failed / sandbox_denied` — 执行器启动后被沙盒拒绝
- `failed / artifact_digest_mismatch` — 产物损坏
- `unknown` — 状态查询超时，**不得推断为成功或失败**

---

## 附录 C：Deepin 特有的落地注意事项

来自 `docs/installation.md:398-409` 的实测记录，与本设计直接相关：

1. **默认 Wayland（treeland）会话下，第三方远控无法采集屏幕。** 这不是 LFL 的问题，也不是权限没开；需要切到登录界面的 X11（deepin）会话。因此 §4.3 的判断有实机旁证，不是理论推演。
2. **X11 自动登录后 `dde-lock` 可能残留全屏黑窗**（进程在、窗口不退），SSH 执行 `kill $(pgrep -f dde-lock)` 可恢复；若每次复现需关闭自动锁屏。
   - 对 L3 的直接影响：**任何"远程接管"方案都必须先有一个"确认画面真的在渲染"的探针**，否则会把 dde-lock 黑窗误判为"接管成功但内容为空"。这与 macOS 侧 `screencapture` 无授权时产黑图、必须做预检的教训**完全同构**（`desktop/macos_capture.py:1-6,76`），应复用同一套"先预检、不产黑图"的诚实性约束。
3. **不要用"远控工具能用"作为"LFL 桌面后端可用"的证据。** 前者是整机像素流，后者是窗口级感知 + 注入，两者的授权模型与失败模式都不同。

---

## 附录 D：如果只能做一件事（**已被 §12.1 推翻，保留供对照**）

> ⚠️ **本附录结论已失效。** 原文建议"首版只做只读任务类别"并称"这是唯一一条错了也不会造成破坏的路径"。该建议成立的前提是"首版形态可以只读"，而用户已确认**必须无人值守**——无人值守要的就是夜里干写类活，只读不能作为交付形态。请以 §0.3 与 D13 为准。
>
> 保留原文的理由：它仍然正确的一点是**顺序**——先用只读验证四道闸的通路，再放开写类。错的只是把"验证切片"当成了"最终形态"。

**原文（v1，已推翻）**：做 P1 的闸1+闸2+闸3 三件（认证、准入、策略）加上一个只读任务类别（`fs.read` 白名单路径），理由是可在一周内验证跨机派活是否走得通、且损失上限可控。

**修正后（v2）**：第 1 周仍先做 `fs.read` 单类别，但明确定位为**技术验证切片**；第 2 周必须进入写类 `kind`，并按 D13 引入 `idempotent` 声明与 `unknown_outcome` 终态。"闸4 不得成为沙盒旁路"仍是全流程红线。

*本文为设计草案。所有"现状"陈述均基于 2026-11-07 的只读核查与两处既有文档引用；未核实项集中在 §10。任何按本文实施的改动，须先经独立 Reviewer 审查并按 §9.1 完成应拦输入实测，方可宣称"闸生效"。*

