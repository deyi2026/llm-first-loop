# DESIGN-20261005：浏览器通道安全加固（Browser Channel Hardening）

> 状态：**DRAFT v4（2026-10-05 二轮外部评审采纳：GPT 复核意见逐条实核后落档，G1-G13 见 §10；v3=F13-F18 codearts 复核，见 §8）**
> 来源：外部 MCP console（浏览器控制面）只读对照审计 + 本仓 browser 栈实测记录
> 事实基线日：2026-10-05（全部 file:line 当日实核；v3 复核补核：run_fcr 断言面全景、cdp_host target 发现路径、.env 现网三键、Chrome 154.0.8037.93；v4 复核补核：Chromium 主干 getBrowserCommandLine 门控源码、Chrome 官方 Native Messaging 限额、cdp 双 host 独立绑定路径、data/ git 追踪状态）
> 范围：`browser_perceive` / `browser_operate` 的**通道与授权层**。语义层契约（exact grounding_ref、action_id 去重、identity_unstable 预警、wait fail-closed、diff/hydrate）已实测领先，**全部冻结不动**。

---

## 1. 目的

对照 MCP console 的实测经验，本设计只解决三件事：

1. **缩小真实登录态的爆炸半径**：从"用户主力 Chrome 的全部登录态"缩到"专用 profile 内显式登录的账号"。
2. **授权分层**：只读感知 / mutation / 真实登录态三级独立开关；最贵的能力不靠"工具不给用"限制，而是通道层独立门 + 缺授权即 fail-closed。
3. **消除监听端口**（中期）：CDP TCP 端口是本机任意进程全权连接面；专用场景改 pipe，主力浏览器场景改 Native Messaging。

---

## 2. 只读审计基线（2026-10-05 实核）

### 2.1 已具备、不需借鉴的部分

| 维度 | 现状 | 证据 |
|---|---|---|
| 语义层 | exact ref 水合、action_id 内容哈希去重（duplicate rejected）、identity_unstable_objects 事前预警、wait fail-closed（target_not_observed） | `docs/browser-smc-mount-20260918.md:26-60` 模型亲测 |
| 回环强制 | http 与 ws 双向校验：scheme + hostname∈{127.0.0.1, localhost, ::1} + port，缺一即拒；感知与 mutation 通道共用同一对校验器 | `src/llm_loop/browser/cdp_host.py:76,94-110`；`cdp_action_host.py:23-24,104,147` |
| 两级门控 | 感知=CDP URL 非空才注册；mutation=`LFL_BROWSER_ACTION_ENABLED`（默认 False）独立授权，感知永不隐含写权 | `config.py:478-484,1062`；`factory.py:1135-1175` |
| target 锁定 | 绑定后 target_id / websocket_url 任一变化即拒（no silent rebind） | `cdp_host.py:278-285` |
| Web 安全头 | auth 页 `default-src 'none'` + `frame-ancestors 'none'`（比对照面的 `'self'` 更严） | `src/llm_loop/web/auth_routes.py:108-110` |

**更正记录**：早前对照结论"回环绑定未做"不成立——客户端侧已强制。真正缺的是 Host/Origin 校验对象（我们当前无浏览器 HTTP 控制面，见 §4.5）。

### 2.2 缺口（按危害排序）

| # | 缺口 | 事实依据 |
|---|---|---|
| G1 | **真实登录态无独立授权档**：`.env` 的 CDP_URL 指向测试 fixture 还是用户主力 Chrome，授权上完全不可区分 | `.env:243-246` 只有三键；config 无 profile 概念 |
| G2 | **execute_command 旁路**：`playwright_exec` 静态门控挡不住 `execute_command + python connect_over_cdp(9222)` 直连主力 Chrome（Gmail 登录态） | `experiences/EXPERIENCE-20260920-cdp-gmail.md:17` 实证 |
| G3 | **CDP 零认证**（与对照面相同的债）：回环缩小为本地攻击面，但本地攻击面内任何进程可全权连接 | CDP 协议无鉴权；45918/9222 均如此 |
| G4 | **文件权限**：`data/browser_mount_test/chrome.pid`、`chrome.log`、`chrome-restart.log` 实测 644，目录 755；profile 子目录倒已是 700 | 2026-10-05 `ls -la data/browser_mount_test/` |
| G5 | **自建 fixture 无完整性清单**：server.py 等无 SHA256 manifest | 同上目录无清单文件 |
| G6 | web 状态类接口字段最小化：**未审计**（列入 §5 S4 核验项，不预设结论） | — |

---

## 3. 需求

- **R1（P0）专用 profile 约定**：真实登录态操作默认走持久专用 profile（固定路径、700）；连主力浏览器 = 单任务显式授权 + 落档。
- **R2（P0）三级授权开关**：perceive / operate / real-profile 相互独立；real 档缺 ACK 时启动即拒绝注册（fail-closed）。
- **R3（P1）绑定 attestation**：绑定时经 browser 级 ws 读启动命令行，按**默认 profile 树**判别（无 `--user-data-dir`、或落在 OS 默认 profile 树内 ⇒ 主力/默认 profile ⇒ 强制 real 档；隔离 user-data-dir ⇒ dedicated）。把"诚实声明"升级为机械校验。**读命令线的具体机制有已核验的协议前提（`--enable-automation` 门控），须先过 §5 S0 spike 再定**（v4-G2）。
- **R4（P2）去端口化**：专用/临时 profile 走 `--remote-debugging-pipe`（零监听端口）；用户主力浏览器走 Native Messaging 扩展桥（allowed_origins 锁扩展 ID）。
- **R5（P3）未来 HTTP 控制面**：若加围观/远程验收面，照抄 Host 精确匹配 + Origin 拒绝 + 一次性 token 三件套（对照面实测：伪造 Host→403、恶意 Origin→403）。
- **R6（P0/P1）负面清单**：pid/log 600、目录 700、状态接口最小字段（先核验）、自建产物 SHA256 清单。

---

## 4. 方案设计

### 4.1 R1：专用 profile（约定 + 一个 launch 脚本，零框架代码）

**目录约定**：`data/runtime/browser-profiles/<name>/`（700，首启自动 `chmod -R go-rwx`）。任务所需账号由**用户人工**在该 profile 内登录；运行时不采集/存储账号密码。**诚实边界（v4-G1）**：持久 profile 本身即 credential-bearing material——cookie/session token/auth state 落盘是该方案的固有属性，`700` 只是必要条件而非完整凭据保护策略。

**`scripts/launch_browser_profile.sh <name> [--cdp-port N] [--ephemeral] [--headless]`**：
- 固定参数：`--user-data-dir=<绝对路径>` `--remote-debugging-address=127.0.0.1` `--remote-debugging-port=<N>`（**默认稳定端口（v4-G9）**：首次启动随机取 30000-39999 内空闲端口并持久化 `<profile>/port`，此后复用；被未知 PID 占用 → fail-closed 拒绝启动。弃用 v3 的"profile 名哈希派生"——哈希跨 profile 可碰撞；随机首次+持久化同样满足 F7 的"重拉 Chrome 不改 `.env` 不 restart web"；随机 ephemeral 降级为显式 `--ephemeral` 选项）；
- **凭据策略分两档（v4-G1，替换 v3 一刀切）**：`--ephemeral`/qualification 形态保留 `--no-first-run --no-default-browser-check --use-mock-keychain --password-store=basic`（一次性隔离 profile 不唤醒 macOS Keychain，`smc_browser_live_navigation.py:175-186`）；**persistent dedicated profile 默认不携带 `--use-mock-keychain --password-store=basic`**——mock-keychain/basic 会把长生命周期 profile 的凭据静态保护降级为明文级存储，与"该目录承载真实登录态"的定位冲突。仅保留 `--no-first-run --no-default-browser-check`。若 persistent 首启实际触发 Keychain prompt 且干扰自动化，单独做一次 credential-at-rest qualification 后再定，不静默继承测试 flag；
- pid 文件与日志写 `<profile>/chrome.pid|chrome.log`，**600**（umask 077）；
- 退出前打印可直接粘贴 `.env` 的**两行生效键**（CDP_URL / ACTION_ENABLED 提示）+ **注释化的 TARGET_ID 行**——`.env:245` 已注明 TARGET_ID 留空 = 唯一 page 自动绑定、Chrome 重拉免改配置免 restart；诱导用户固化 TARGET_ID 反而丢掉该容忍度（§8-F6）；
- `--headless` 仅用于登录完毕后的纯执行任务；首次登录必须 headed（人工完成，见上）。

**连主力浏览器的单任务流程**（不进 `.env` 常态配置）：用户指令明示 → 本会话落档 audit note（docs/ 下日期命名）→ 配 R2 的 class=real+ACK → 任务完成即撤（授权/撤权各一次 restart，成本记录于 §7）。

### 4.2 R2：三级开关（config.py + factory.py 小改）

现状已是两级（URL 存在=感知 / ACTION_ENABLED=mutation）。新增第三档：

```
LFL_BROWSER_PROFILE_CLASS = "" | "dedicated" | "real"   # 新增；""与"dedicated"同归默认档 dedicated，行为完全一致（F15）
LFL_BROWSER_REAL_PROFILE_ACK = "<subject>|<scope>|<expires YYYY-MM-DD>"   # 新增（v4-G8 结构化）：如 gmail-readonly|perceive+operate|2026-11-05；过期/格式不符 → 拒绝注册（消 stale authorization）
LFL_BROWSER_REAL_PROFILE_PATHS = "" | "none" | "<冒号分隔目录>"   # 新增；R3 判定器 v2 用（§4.3）。留空=内置默认树；非空=**内置默认树 ∪ 操作者目录（只增不替，v4-G7）**；显式 none=fail-closed 全判 real（F15：消除"留空全判 real"与内置默认值的矛盾）
LFL_BROWSER_ATTESTATION_MODE = "shadow" | "enforce"   # 新增（v4-G6），默认 enforce：shadow=只记录 verdict+审计回执不拒绝；enforce=不符即拒。显式模式取代"由 env 键存在与否隐式控制安全逻辑"
```

注册前校验（factory 挂 browser 工具处，violation → 拒绝注册并 log 原因）：
1. `class=real` 且 ACK 空 → **拒绝注册全部 browser 工具**；
2. `class=real` 且 ACK 非空 → 注册；此后每次 `browser_perceive` snapshot 回执携带 `profile_class=real` 与 ACK 摘要（审计可见）。**字段条件附加**：仅 `class=real` 时出现新字段，其余取值（含显式 dedicated）回执逐字节不变（F15）。**回归面实核（F13 修正 F5）**：harness 真正断言的是工具 schema 面——`wire_sha256`/`canonical_kind_sha256`（`run_fcr.py:135-142`）与 `plan_sha256` 冻结常量（`:163`）；`source_sha256` 仅留痕 manifest（`:146-159,206`）不入断言，且 FC2-C runtime `tool_execution: False`（`:213`）根本不执行 browser 工具。硬边界 = **不动工具 schema（工具名/参数/oneOf 分支）**，运行时回执字段在此前提下不触发任何断言。流程前置：改过 src 必须 commit/stash（`_tracked_dirty` 对未提交改动直接 RuntimeError，`:165-167,240`）；复用旧 workdir 会因 manifest drift 拒混样（`:309-312`），须换新 workdir——列入 S2/S5 验收前置；
3. `class≠real` → 走 §4.3 attestation，判定不符即拒绝注册。

改动点：`config.py:478-484` 增三字段（默认空），`config.py:1056-1063` 增三行 env 解析，`factory.py:1135` 起注册块头部增校验。**不新增 restart 语义**：仍走既有"改 `.env` → restart web"链路（Settings 启动装配冻结，refresh_config 不重建工具表，见 `docs/browser-smc-mount-20260918.md:7-8`）。

**授权粒度诚实声明（§8-F4）**：`.env` 键作用于**进程级**——`factory.py:1135-1146` 的工具表与 BrowserPerceptionStore 都是部署单例（session 隔离仅存在于 grounding 层，`perception.py:12`）。因此 real 档窗口期内该部署的**全部会话**（含 feishu/web 并行会话）都可感知主力 Chrome，"单任务授权"实际是"单窗口授权"。缓解：任务完成即撤；窗口期内每次 snapshot 回执带 ACK 摘要（审计可追）；高敏感场景为 real 任务拉独立小部署物理隔离。

### 4.3 R3：绑定 attestation（cdp_host.py 绑定路径内完成）

**实现通道（§8-F1；S0 后以 host 侧为准，本段保留 F1 过程记录）**：`Browser.getBrowserCommandLine` 是 browser 级域；现有感知通道是 page-target ws + 硬方法白名单（`cdp_host.py:65-75,133-134`），Browser 域在 page 会话上不可达。原方案为绑定时短连 browser 级 ws 调一次即关；S0 结论改为 **host 侧取 argv**（见下段），`/json/version` 短连仅保留给 S3a 的 browser ws UUID binding。

**机制前提（v4-G2，v3 遗漏的协议门控）**：Chromium 主干 `content/browser/devtools/protocol/browser_handler.cc:676-695` 实证——浏览器进程命令行**无 `--enable-automation` 时该方法直接返回 ServerError**（"Command line not returned because --enable-automation not set."，2026-10-05 抓取主干源码核验）。而本设计 §4.1 launch 脚本与 qualification（`smc_browser_live_navigation.py:175-186`）均不含该 flag——若照 v3 直上，**所有合法 dedicated 会被判 real 而拒绝注册**，通道自锁。处置：§5 新增 **S0 spike 前置门**，三选一定论：① launch 脚本加 `--enable-automation`（先实测副作用：navigator.webdriver=true、automation infobar、对真实站点反自动化检测面）；② 改走 host 侧进程 attestation（`lsof -i :<port>` → PID → `ps -o command=` 读 argv），不依赖浏览器自报，且与"自报可伪造"威胁模型（下文）解耦更彻底；③ 其他等价机制。**S0 无结论 ⇒ S3 不开工**。**S0 已落定（2026-10-06，结论 ②）**：四态实测矩阵确证门控（无 flag ⇒ ServerError；加 flag ⇒ 成功但 `navigator.webdriver=true` 2/2）——**attestation argv 改由 host 侧进程证据取得**（`lsof -Fp -iTCP:<port> -sTCP:LISTEN` → 唯一 PID → `ps -ww -o command=`），零页面副作用、三类浏览器来源统一、与自报伪造威胁解耦、pipe 时代改 spawn 时记录 argv 平滑演化；实现约束（监听 PID 0 或 >1 ⇒ fail-closed real、argv token 两形态、跨用户边界）见 `docs/S0-RESULT-20261005-browser-attestation-spike.md`。attestation 执行模式由 `LFL_BROWSER_ATTESTATION_MODE`（§4.2）显式控制；S3 上线首段以 shadow soak 观察现网活跃挂载（F17：其 argv 形态未盘点）再切 enforce。

**判定器 v2（§8-F2，替换初稿"根白名单"）**：初稿要求 realpath 落在 `data/runtime/browser-profiles/*` 才算 dedicated——实核发现会误杀我们自己的 qualification Chrome（`smc_browser_live_navigation.py:185-195` 以临时目录作 user-data-dir）及同类 harness 形态。危险对象本是**用户日常默认 profile**，改按默认 profile 树判别：

- argv **无** `--user-data-dir` → 使用默认 profile → `real`（须 class=real+ACK，否则拒绝绑定）；
- argv **有** `--user-data-dir=<p>` 且 `realpath(p)` 不在默认树内 → `dedicated ✓`（隔离 profile 即爆炸半径受限，与 R1 模型自洽：dedicated ≠ 无登录态，= 只有显式登录的那几个账号）；
- `realpath(p)` 落在默认树**内**（含显式指回默认 profile 或其子目录）→ `real`；
- 默认树来自 `LFL_BROWSER_REAL_PROFILE_PATHS`：**留空 = 内置默认树**（macOS `~/Library/Application Support/Google/Chrome`、`~/Library/Application Support/Chromium`；Linux `~/.config/google-chrome`、`~/.config/chromium`——F2 零配置覆盖自建场景的目标）；**非空 = 内置默认树 ∪ 操作者目录（v4-G7：只增不替，防配置遗漏把真默认 profile 判成 dedicated）**；显式 `none` = 全判 real（最严档）；取值调用失败/字段缺失 → fail-closed 判 `real`（F15：与 §4.2 键定义对齐，消除 v2 两处矛盾表述）。**relative `--user-data-dir` 无法可靠解析（Chrome cwd 不可求）→ fail-closed 判 real（v4-G7）**。

- **授权数据流（F14，v3 补）**：`CdpReadOnlyBrowserHost`/`CdpActionHost` 构造器只收 debug_base_url/target_id/注入器（`cdp_host.py:217-226`、`cdp_action_host.py:96-116`），不认识 class/ACK——R2 的授权语义到不了绑定路径，直连入口也没有 `.env` 可读。新增 **BindingPolicy** 注入：host 构造器新增可选 `binding_policy`，缺省 = `deny_real()`（仅许 dedicated，fail-closed）；factory 在 R2 校验通过后注入 `allow_real(ack_digest)`。直连入口零改动即默认 deny-real；合法 real 场景统一经 factory 注入，双入口语义闭合。
- **共享绑定身份（v4-G3，v3 遗漏的结构缺口）**：现状感知 host 与 mutation actuator 各自独立做 `/json/list` 首绑（`cdp_host.py:251-290` vs `cdp_action_host.py:122-158`；`factory.py:1136,1158` 分别构造两个实例）——no-silent-rebind 只保证**各自**不换 target，机械上**不能证明两 host 绑到同一 browser 进程/实例**；TARGET_ID 留空时若感知完成后端口后面的 Chrome 被替换，actuator 首绑会绑到新实例的"唯一 page"（TOCTOU 面；现有 `expected_version+physical backendNodeId` 只是概率性缓解，安全闭环不应建立在 backendNodeId 不巧合上）。新增一等对象 **BrowserChannelBinding**，冻结：browser 级 ws UUID（`/json/version` 的 `webSocketDebuggerUrl` 路径段，browser 进程实例一一对应）、target_id、target ws URL、argv_sha256、profile verdict、generation。**perceive 与 operate 必须持有同一 binding 对象**：由 factory（或首 host）一次性建立并注入两 host；actuator 不再独立首绑，绑定身份任一不匹配 → 拒绝。Chrome 重启 ⇒ UUID 变 ⇒ 两 host 一同按既有 no-silent-rebind 语义断开重建。该对象同时成为后续 TCP/pipe/NM 三种 transport 的统一安全边界。落地切分进 §5 S3a。
- **实现依赖（F16b）**：`/json/version` 返回 **dict**，现有 `_default_http_get_json` 硬要求 list（`cdp_host.py:116-123`）——新增独立 dict 取值 helper，S3 任务明列。
- **落盘**：verdict 写入 BrowserPerceptionStore 首记录：`attestation={argv_sha256, user_data_dir, verdict, checked_at}`；mutation 通道（cdp_action_host）绑定同一 target 时校验 verdict 一致，不符即拒。R3+BindingPolicy 置于 cdp_host 绑定路径 ⇒ **工厂挂载与 qualification/harness 直连两条入口都被覆盖且默认 fail-closed**（直连入口无 `.env` 语义，R2 门对其不生效——F3/F14）。
- **频率与成本**：绑定每 host 生命周期仅发生一次（no-silent-rebind，`cdp_host.py:279-285`；`_drop_session` 重连不重置绑定身份）。attestation = 一次 HTTP + 一次短连 ws + 小响应，量级几十 ms，一次性，不进 capture 热路径。
- **威胁模型边界**：浏览器自报命令行可被"控制了浏览器进程的对手"伪造；user-data-dir 指向任意非默认目录也会被判 dedicated。本设计防的是**误绑日常 profile**（误配置与爆炸半径），不防主动伪装——后者属 G3，由 R4 消端口解决。

### 4.4 R4：去端口化（两段式）

**阶段 A（P2a，transport 替换）**：launch 脚本改 `--remote-debugging-pipe`（Chrome 以 fd 3/4 通信，**零 TCP 监听**）；新增极小 host 进程（spawn Chrome、持有 pipe fd、经 **unix socket（0600）** 转发 CDP 帧）。**威胁模型收窄声明（v4-G5，替换 v3"三类面同时消失"的过度承诺）**：消除 TCP/网络可寻址面（端口扫描、DNS rebinding）并阻断**其他 OS 用户**连接；0600 UDS **不抵抗已在同一 UID 下执行代码的主动攻击者**——该目标需进程身份/能力机制（如 spawn helper 继承 fd），明确不在本设计范围，不靠堆机制对抗同账户完全失陷。**改动面更正（F16，v3）**：pipe 模式下 Chrome **无 /json HTTP 端点**，而现有 target 发现全依赖 `{base}/json/list`（`cdp_host.py:251-272`；`cdp_action_host.py:122-140` 同构），v2"CDP 协议与语义层零改动"不成立。阶段 A 实际需：① host 侧 `Target.getTargets` 等价发现替换 /json/list；② `_normalize_loopback_debug_url`/`_validate_loopback_ws_url`（`cdp_host.py:94-113`）与构造器必填 http 回环 `debug_base_url`（`:217-231`）扩展接受 `unix://` 形态；③ `_default_http_get_json` 的 list 断言对新发现层绕过；④ **pipe 只给 browser 级 CDP**——page 会话必须经 `Target.attachToTarget(flatten=true)` 取 sessionId 并在帧层多路复用（v4-G4：这一步改的是 `_ReadOnlyCdpSession`/`_MutationCdpSession` 的请求/事件路由结构，不只是发现层）。因此阶段 A 拆两步走（§5 S5）：**S5a 先提取 `BrowserCdpTransport` 抽象（list_pages/bind_page/browser_command/page_command/close），TCP 实现`行为逐字节不变`+ S1 盘点圈定的 harness 子集全绿；S5b 才落 pipe 实现**——避免 transport、发现、多路复用、attestation、恢复五件事在一切内纠缠。保持零改动的只有：CDP 方法白名单、no-silent-rebind、capture/degraded 语义。

**新增失效模式（§8-F9）**：host 进程成为单点——崩溃 ⇒ 通道 degraded。处置：host pid 落 `<profile>/host.pid`（600）；通道断开复用既有 `capture_channel_degraded` 分类与同 target 重连语义（`cdp_host.py:309-317`）；launch 脚本提供 `--recover` 重拉整链。**效率评估（§8-F11）**：unix socket 本机 IPC 单跳为 µs 级，snapshot 主成本在 DOMSnapshot 捕获本身（10.4MB 页实测 ~1.4s，`cdp_host.py:138-142` 注释），转发层不构成瓶颈——但结论须以 S5 吞吐对比验收坐实，不预设。

**阶段 B（P2b，仅主力浏览器）**：Native Messaging。**Chrome 侧 CDP 面明确为扩展的 `chrome.debugger` API（v4-G10：官方定义的 CDP 替代 transport，扩展须声明 `debugger` 权限；本设计依赖的 Accessibility/DOM/DOMSnapshot/Page/Runtime/Target 域在其支持范围内——2026-10-05 官方文档核验）**；NM 只承担 host↔扩展消息通道。扩展侧锁定扩展 ID（`allowed_origins` 精确匹配）；本地 host manifest 600。语义层（grounding_ref/action_id/diff/wait）原样架在 NM 消息上——对照面提供安全通道，我们提供精确操作语义，两层互补。主力浏览器无法由我们重启（pipe 不可用），NM 是唯一无端口路径。

**前置 spike（§8-F10；v4-G10 补数值）**：NM 单消息硬上限**方向不对称（2026-10-05 官方文档核验）**：native host→Chrome 方向 1 MB；Chrome→native host 方向 **64 MiB**。大 snapshot 撞的是 64 MiB 入站方向（评审方引"~47MB 单 CDP 帧"为本仓既往实测，**本会话未复验**，以 spike 现场实测峰值为准）；host↔扩展为 stdio 单流串行——是否需分帧协议必须在 S6 动工前用实测峰值消息定论；吞吐同批实测（Gmail 只读节奏预期无压力，不预设结论）。spike 未过 ⇒ S6 不开工。

**明确不做**：CDP TCP 加 token 代理——比 pipe 多一个常驻组件且仍留端口，两阶段落地后无存在必要。

### 4.5 R5：未来 HTTP 控制面（只记决策，不实现）

当前无浏览器 HTTP 控制面，无实施对象。若未来出现围观面板/远程验收面：Host 必须精确匹配、Origin 缺失或非白名单→403、token 一次性下发不落剪贴板、默认 disabled。CSP 沿用 `auth_routes.py:108-110` 现状（已严于对照面）。

### 4.6 R6：负面清单落地

- **权限**：launch/fixture 脚本统一 `umask 077`；存量 `data/browser_mount_test/` 收敛：目录 700、`chrome.pid`/`*.log` 600（对 2026-10-05 实测 644/755 的修正，含一次性收敛命令入 S1）。
- **状态接口**：先核验 web 侧 status 类路由返回字段是否最小化（S4，核验记录落 docs），再决定是否改。
- **清单（v4-G11 更正）**：实核 `data/browser_mount_test/server.py` **不在 HEAD**（`git log` 空）且 `.gitignore` 忽略 `data/`——对它做 SHA256 manifest 只是**本机 drift detector，不是 repository integrity**。改为：fixture 源码迁入 tracked 的 `scripts/fixtures/browser_mount_test/`（运行时复制到 `data/`），launch 脚本本就位 `scripts/`；两者纳入 `scripts/artifacts-manifest.sha256` 后才谈得上入库可校验。迁移前 manifest 措辞一律写"本机 drift 检测"。

---

## 5. 实施切分与验收

| 切片 | 内容 | 验收标准 |
|---|---|---|
| S0（门，v4-G2 新增） | R3 attestation 机制 spike + v4 设计冻结 | 本机 Chrome 154（headed/headless dedicated profile）实测 `Browser.getBrowserCommandLine` 无/有 `--enable-automation` 两态；若加 flag：副作用清单（navigator.webdriver、infobar、真实站点反自动化面）落 docs；若否决：host 侧进程 attestation（lsof→PID→ps argv）路径实测可行；结论三选一落档 ⇒ S3 解锁，无结论 ⇒ S3 阻塞。**✅ 完成（2026-10-06）：门控四态确证、加 flag ⇒ webdriver=true（2/2），选 ② host 侧进程 attestation（21-40ms 全绿），S3 解锁——`docs/S0-RESULT-20261005-browser-attestation-spike.md`** |
| S1（P0） | R1 目录+launch 脚本（v4：凭据策略两档 + 随机首启端口持久化）；R6 存量权限收敛；现网 `.env` 收敛（F17）；harness argv 盘点（F18） | 新 profile 目录 700；pid/log 600；脚本输出两行生效 `.env` 键 + 注释化 TARGET_ID 行（§4.1）；端口稳定（首次随机 30000-39999 持久 `<profile>/port`，同名 profile 二次启动端口一致；被未知 PID 占用拒启）；persistent profile argv **无** mock-keychain/basic、ephemeral **有**（§4.1 v4）；`ls -la data/browser_mount_test/` 无 644 残留；`TARGET_ID` 置空恢复自动绑定容忍度 + PROFILE_CLASS 显式落键；盘点 live 执行型 harness 的 Chrome 启动 argv 是否均带 `--user-data-dir`（不带=判 real，与 S5"全绿"冲突，先修 argv 或调整 S5 期望；`evals/browser_smc_*` 实测 25 目录，v2"四套"系未盘点口径，盘点记录落 docs） |
| S2（P0） | R2 两键 + factory 校验（BindingPolicy 注入点预留，实现归 S3） | class=real 无 ACK → restart 后工具表无 browser_*；有 ACK → 注册且回执带审计字段；回归：ACTION_ENABLED=0 时无 operate、class 空+专用 profile 行为与今日完全一致（跑 harness 前置：工作树干净、src 改动已 commit——F13） |
| S3（P1，前置=S0 结论） | **S3a** BrowserChannelBinding 共享绑定身份（v4-G3：factory 单点建立 binding 注入两 host、actuator 取消独立首绑；TCP 行为不变，S1 圈定 harness 子集全绿）→ **S3b** R3 attestation（判定器 v2，机制按 S0 结论）+ BindingPolicy 注入（F14）+ dict 取值 helper（F16b）+ ATTESTATION_MODE | S3a：两 host 持不同 binding 的注入 → 拒绝（单测）；S3b：无 `--user-data-dir` 的 Chrome 且无 allow-real policy → 拒绝绑定（含直连入口默认态的单测）；qualification 临时 user-data-dir → dedicated（harness 直连入口不回归）；指回默认树内 → real；机制调用失败 → fail-closed real；shadow 模式只记录不拒绝、enforce 拒绝（两态单测）；PATHS 非空=内置∪追加生效；单测覆盖 argv 两种形态（`--user-data-dir=值` / 分隔）、symlink realpath、默认树内/外/无 flag 三态、PATHS 留空/none/自定义三态 |
| S4（P1） | R6 manifest + status 接口核验 | 清单存在且 `sha256 -c` 通过；核验记录落 docs |
| S5（P2a） | **S5a** `BrowserCdpTransport` 抽象提取（list_pages/bind_page/browser_command/page_command/close；TCP 实现，v4-G4）→ **S5b** pipe + unix socket transport + target 发现去 HTTP 化 + attachToTarget(flatten)/sessionId 多路复用（F16） | S5a：TCP 行为逐字节不变，S1 盘点圈定 harness 子集全绿（跑前 commit/stash、换新 workdir——F13）；S5b：`lsof -i` 无 CDP TCP 监听；target 发现不再依赖 /json HTTP（感知与 mutation 两 host 的 Target.getTargets 等价路径就位）；S5a 同一子集复跑全绿；host 进程 kill -9 后下次感知报 `channel_degraded` 且 `--recover` 可恢复；转发层吞吐对比记录落 docs |
| S6（P2b） | NM 桥 + `chrome.debugger` 扩展面（§4.4 前置 spike 通过后才开工） | 扩展 ID 锁定生效；无监听端口；峰值消息不超方向限额（host→Chrome 1 MB / Chrome→host 64 MiB，v4-G10 已核数值）或分帧协议就位；Gmail 只读场景端到端通过；spike 前置含本机 Chrome 154.0.8037.93 兼容核验（F18） |

---

## 6. 边界与明确不做

- **G2（execute_command 旁路）不在 browser 层阻断**：那是 shell 通道的权限问题。缓解 = 本设计让正路（real 档）足够好用，消除绕行动机；高安全部署可用既有 `exec_mode=allowlist`（`config.py:495`）收紧 shell。
- **双入口分工**：R2 门在 factory（`.env` 挂载入口；校验结果经 BindingPolicy 注入 host——F14），R3 门在 cdp_host 绑定路径（直连入口，qualification/harness 自建 host 也被覆盖，缺省 policy=deny-real fail-closed）；直连入口无 `.env` 语义，不吃 R2。
- 不改语义层契约，不动 provider 可见面（仍收敛为 `browser_perceive` + `browser_operate` 两个工具名，`factory.py:1132-1134`）。
- 不替用户保管任何账号凭据；登录永远人工完成。
- G3（CDP 零认证）不在 TCP 上修补——见 §4.4"明确不做"，由 R4 根治。

## 7. 风险与回滚

- **R2/R3 误伤**：用户手起的 fixture Chrome（如 `open -na` 无 `--user-data-dir`）会被判 real——属预期收紧；escape hatch = 用 launch 脚本起，或单任务配 class=real。校验只在**绑定时**跑一次，不做运行时反复检查。
- **判定器 v2 的放宽面（§8-F2）**：`--user-data-dir` 指向任意非默认目录即判 dedicated——若有人用非默认目录长期挂日常数据，会被低估为 dedicated。属威胁模型边界内（防误绑，不防主动伪装）；escape hatch = 把该目录加入 `LFL_BROWSER_REAL_PROFILE_PATHS`。
- **real 档任务的双 restart 成本（§8-F11）**：授权与撤权各一次改 `.env`+restart；接受，real 档预期低频。窗口期内该部署全部会话可见主力 Chrome（§4.2 粒度声明），靠任务即撤+回执审计字段兜底。
- **现网活跃状态（F17）**：`.env:244` TARGET_ID 已固化非空、`:246` ACTION_ENABLED=1——G1"无独立授权档"是现役状态而非假设（当前挂载为 2026-09-18 chatgpt-web live test，`.env:242`；该 profile 启动 argv 形态未盘点，S3 后若判 real 将拒绑——不预设结论，列入 S1 盘点）。S1 收敛：TARGET_ID 置空恢复 `.env:245` 承诺的自动绑定容忍度 + PROFILE_CLASS 显式化。
- **回滚**：配置层回滚 = 删四个新 env 键（CLASS/ACK/PATHS/ATTESTATION_MODE）+ restart web；代码层回滚 = revert 对应 commit（BindingPolicy 缺省 deny-real 与 attestation 属代码行为，删键不撤销——直连入口的 fail-closed 是有意收紧面，v3 起回滚语义区分两层）。中间档逃生（v4-G6）：`ATTESTATION_MODE=shadow` = 代码不动、只停拒绝改观察。launch 脚本与权限收敛不影响运行时。

## 8. 拷问记录（2026-10-05）

方法：`grill_me`（edge_cases/failure_modes/scale/security 四域追问）+ `design_review`（安全/性能/SRE/CDP 专家/回归/DX 六角色）。两工具均只产出追问框架，下表为逐条回答后确认的盲点与处置；除标注外均有当日 file:line 实核。**F13-F18（v3）来自外部评审（codearts）**：其意见先经本会话逐条实核 file:line 再采纳，其中 F13 补了评审也遗漏的两点（同 workdir manifest drift 断言、FC2-C `tool_execution: False`）。

| # | 发现 | 事实依据 | 处置 |
|---|---|---|---|
| F1 | R3 初稿假设 attestation 可挂现有感知会话；实际 Browser 域在 page-target ws 上不可达 | `cdp_host.py:65-75,133-134`（方法白名单 + "One persistent page-target websocket"） | §4.3 更正：绑定时短连 browser 级 ws（/json/version → webSocketDebuggerUrl），调完即关 |
| F2 | 根白名单判定器（realpath∈`data/runtime/browser-profiles/*`）误杀自建 qualification/harness Chrome | `smc_browser_live_navigation.py:185-195` 临时 user-data-dir；evals 内无匹配固定根 | §4.3 判定器 v2：按 OS 默认 profile 树判别；根列表可配置 `LFL_BROWSER_REAL_PROFILE_PATHS` |
| F3 | 双入口盲区：harness/qualification 直连 host 不经 factory，R2 门不生效 | qualification 自建 host；R2 在 factory 注册块 | R3 置于 cdp_host 绑定路径，两入口同覆盖；§6 明示分工 |
| F4 | real 档"单任务授权"实为进程级窗口授权（全部会话可见） | `factory.py:1135-1146` 工具表/store 部署单例；`perception.py:12` session 隔离仅在 grounding 层 | §4.2 粒度诚实声明 + ACK 摘要回执 + 独立部署选项；§7 记录窗口期风险 |
| F5 | 回执无条件加 profile_class 字段触碰 harness 冻结机制 | `run_fcr.py:135-159` | §4.2 字段条件附加：默认档回执逐字节不变（**v3 由 F13 修正事实依据**：断言面在工具 schema，非回执/源哈希） |
| F6 | launch 脚本打印固化 TARGET_ID 行，丢掉"留空自动绑定、Chrome 重拉免 restart"契约 | `.env:245` 注释 | §4.1 改注释化 TARGET_ID 行 |
| F7 | 随机 ephemeral 端口默认值 ⇒ 每次重拉 Chrome 都要改 `.env`+restart web | `.env` 常态三键模式 | §4.1 默认固定派生端口（profile 名哈希 30000-39999，存 `<profile>/port`），ephemeral 降为显式选项 |
| F8 | launch 脚本未继承"隔离 profile 不得唤醒 macOS Keychain"安全契约 | `smc_browser_live_navigation.py:179-183` docstring | §4.1 补 `--use-mock-keychain --password-store=basic` 等四 flag |
| F9 | pipe 方案引入 host 进程单点，初稿未定义失效模式与监督 | 新增组件 | §4.4 host.pid 600 + 复用 `capture_channel_degraded` + `--recover`；S5 验收加 kill -9 用例 |
| F10 | NM 单消息上限与 stdio 串行化对 MB 级 snapshot 的可行性未验证 | NM 协议硬限（S6 前实测定论，不预设数值） | §4.4 前置 spike 作为 S6 开工门 |
| F11 | 效率维度初稿未答：attestation 频率/成本、转发层开销、双 restart、端口策略 | 绑定每 host 一次（no-silent-rebind）；unix socket µs 级 vs DOMSnapshot ~1.4s 主成本（`cdp_host.py:138-142`） | §4.3 成本段 + §4.4 吞吐验收 + F7 端口策略 + §7 双 restart 记录 |
| F12 | 初稿引用 `run_*.py:155-174` 为 env 注入模式，实核为源哈希冻结段 | `run_fcr.py:146-159` | §5 S5 引用改为 `docs/browser-smc-mount-20260918.md` |
| F13 | F5 依据高估 + 评审遗漏两点：断言面实为工具 schema（wire/canonical/plan_sha256 冻结常量）+ `_tracked_dirty` + 同 workdir manifest drift 拒混样；source_sha256 仅留痕；FC2-C `tool_execution: False` 不执行 browser 工具 | `run_fcr.py:135-142,163,165-167,206,213,240,309-312` | §4.2 规则 2 重写（硬边界=不动工具 schema）；S2/S5 加"跑前 commit/stash、换新 workdir"前置 |
| F14 | R3 数据流缺口：host 构造器不收 class/ACK，授权语义到不了绑定路径；v2 的 F3 只解决"是否校验"，未解决直连入口如何表达授权 | `cdp_host.py:217-226`、`cdp_action_host.py:96-116` 构造器签名 | §4.3 BindingPolicy 注入：缺省 `deny_real()` fail-closed，factory 校验通过后注入 `allow_real(ack_digest)` |
| F15 | 文档两处自相矛盾：①PATHS"留空全判 real"vs"默认值覆盖默认树"；②class ""/"dedicated"同义 vs 附加条件写"class≠默认档" | v2 §4.2 与 §4.3 并读 | ①留空=内置默认树、显式 `none`=全判 real；②附加条件改仅 class=real；§4.2/§4.3 同步改写 |
| F16 | R4"CDP 协议与语义层零改动"不成立：pipe 模式无 /json HTTP 端点，target 发现全依赖它（含构造器必填 http 回环 debug_base_url） | `cdp_host.py:94-113,116-123,217-231,251-272`、`cdp_action_host.py:122-140` | §4.4 改动面更正（Target.getTargets 等价发现 + unix:// 扩展 + dict helper）；S5 加"发现去 HTTP 化"验收 |
| F17 | 现网 `.env` TARGET_ID 已固化 + ACTION_ENABLED=1——G1 是现役状态非假设 | `.env:243-246` | §7 新增"现网活跃状态"条目；S1 收敛 TARGET_ID 置空 + PROFILE_CLASS 显式化 |
| F18 | S5"harness 全绿"与 §7"无 flag 判 real 属预期收紧"潜在冲突；"四套 harness"口径未盘点（实测 25 目录）；NM 可行性受 Chrome 版本影响 | `ls -d evals/browser_smc_*`=25 目录；本机 Chrome 154.0.8037.93 | S1 加 argv 盘点项并圈定 live 执行子集；S6 spike 前置加 Chrome 154 兼容核验 |

**拷问后判定非问题**（一句话依据）：时钟偏差——`checked_at` 仅审计不参与判定；并发 100 次绑定——host 实例级 `capture_lock` + 单绑定身份无竞态面；磁盘满/通道断——走既有 `capture_channel_degraded` 分类与同 target 重连；G2 旁路——§6 已明确归 shell 通道权限，不在本设计反弹。

## 9. 事实引用清单

- `src/llm_loop/config.py:478-484`（browser 四字段默认值）、`:1056-1063`（env 解析）、`:495`（exec_mode）
- `src/llm_loop/factory.py:1132-1175`（注册门控与 provider 可见面收敛）；`:1141-1146`（store/工具表部署单例——F4 依据）
- `src/llm_loop/browser/cdp_host.py:76,94-110`（回环校验）；`:65-75,133-134`（感知方法白名单、page-target 会话——F1 依据）；`:278-285`（绑定与 no-silent-rebind）；`:292-317`（drop-session/重连/degraded 分类）；`:138-142`（10.4MB 页 ~1.4s 实测注释——F11 依据）
- `src/llm_loop/browser/cdp_action_host.py:23-24,104,147`（mutation 通道同校验）
- `src/llm_loop/browser/perception.py:12`（grounding 会话隔离范围——F4 依据）
- `src/llm_loop/web/auth_routes.py:108-110`（CSP）
- `.env:243-246`（当前三键；`:245` TARGET_ID 留空=自动绑定契约——F6 依据）
- `scripts/qualification/smc_browser_live_navigation.py:178-195`（qualification Chrome 形态与 Keychain 契约——F2/F8 依据）
- `evals/browser_smc_bounded_semantic_operation_fc2c_v02/run_fcr.py:135-159`（schema/源 sha256 冻结段——F5/F12 依据）
- `evals/browser_smc_bounded_semantic_operation_fc2c_v02/run_fcr.py:163,165-167,206,213,240,309-312`（plan 冻结常量/_tracked_dirty/manifest 留痕/tool_execution=False/行前复验/同 workdir drift 拒混——F13 依据，v3）
- `src/llm_loop/browser/cdp_host.py:94-113,116-123,217-231,251-272`、`cdp_action_host.py:96-140`（回环+ws 校验、list 断言、构造器签名、/json/list 发现依赖——F14/F16 依据，v3）
- `docs/browser-smc-mount-20260918.md:7-12,26-60`（挂载链路、语义层实测）
- `experiences/EXPERIENCE-20260920-cdp-gmail.md:17-19`（旁路实证）
- `data/browser_mount_test/` 目录实测（2026-10-05 `ls -la`：pid/log 644、目录 755、profile 子目录 700）
- Chromium 主干 `content/browser/devtools/protocol/browser_handler.cc:676-695`（`Browser.getBrowserCommandLine` 的 `--enable-automation` 门控——v4-G2 依据，2026-10-05 抓取 googlesource 主干源码核验）
- `developer.chrome.com` Native Messaging / chrome.debugger 官方文档（单消息方向限额 1 MB / 64 MiB；chrome.debugger 为官方 CDP 替代 transport——v4-G10 依据，2026-10-05 抓取核验）
- `git log -- data/browser_mount_test/server.py` 空 + `.gitignore` 含 `data/`（v4-G11 依据，2026-10-05 实核）

## 10. 二轮外部评审采纳记录（GPT，2026-10-05，v4）

评审自评对象为"DRAFT v2"并建议先改 v3 再实施；实核发现**盘上已是 v3**（已吸收 codearts F13-F18），其 5 条"必须先改"中：1 条（transport 范围）v3 已自我修正（F16），1 条（§7 矛盾）v3 已两层化但"env 键隐式控制"批评仍成立，其余经本会话独立核验属实并采纳。逐条结论（GPT 意见 → 本会话实核 → 处置）：

| # | 评审意见 | 本会话实核 | 处置 |
|---|---|---|---|
| G1 | persistent profile 不应继承 `--use-mock-keychain --password-store=basic`（测试契约 ≠ 持久凭据策略） | 属实：v3 §4.1:66 确实一刀切继承；qual 脚本 `:175-186` 该 flag 本为一次性隔离 profile 设计 | **采纳**：§4.1 凭据策略分两档；补"persistent profile 属 credential-bearing material"诚实边界 |
| G2 | `Browser.getBrowserCommandLine` 有 `--enable-automation` 隐藏前提，v3 直上会全员判 real | **属实且关键**：Chromium 主干 `browser_handler.cc:676-695` 无该 flag 直接 ServerError（源码级核验）；launch 脚本与 qual 均无该 flag | **采纳**：§4.3 机制前提段 + §5 S0 spike 前置门（含 host 侧进程 attestation 备选）；S3 以 S0 为前置 |
| G3 | perceive 与 mutation 独立绑定，无同实例机械证明，TOCTOU 面 | 属实：`cdp_host.py:251-290` 与 `cdp_action_host.py:122-158` 各自 `/json/list` 首绑；`factory.py:1136,1158` 分别构造 | **采纳**：§4.3 BrowserChannelBinding 一等对象（browser ws UUID 等六元组冻结、两 host 持同一 binding、actuator 取消独立首绑）；§5 S3a |
| G4 | pipe≠小 transport 替换，需 Target.getTargets + attachToTarget(flatten)/sessionId 多路复用与 transport 抽象 | **部分过时**：发现层依赖 F16（v3）已自我修正；但 v3 确未点到 attachToTarget/sessionId 对 `_ReadOnlyCdpSession`/`_MutationCdpSession` 路由结构的改动 | **部分采纳**：§4.4 补④；S5 拆 S5a（TCP 行为不变抽象提取）/S5b（pipe） |
| G5 | "三类面同时消失"过度承诺：0600 UDS 不防同 UID 进程 | 属实：v3 §4.4:111 原文即过度承诺 | **采纳**：§4.4 威胁模型收窄声明（防其他 OS 用户、不防同 UID；后者明确出范围） |
| G6 | attestation 由 env 键存在与否隐式控制；§7"删键回归无校验"与双入口覆盖矛盾 | **部分过时**：§7 v3 已两层化（删键不撤销代码层）；但"隐式控制"+ 缺 shadow 灰度档仍成立（现网活跃挂载 argv 未盘点，直接 enforce 有误伤面） | **部分采纳**：新增 `LFL_BROWSER_ATTESTATION_MODE=shadow|enforce`（§4.2/§7）；S3b 验收加 shadow soak |
| G7 | `REAL_PROFILE_PATHS` 应内置∪追加而非可替换；relative user-data-dir 需 fail-closed | 属实：v3 §4.2:80/§4.3:101 原为替换语义 | **采纳**：改并集语义 + relative→fail-closed real（§4.3） |
| G8 | ACK 自由文本持久 `.env` 易 stale | 部分成立：摘要已最小化；过期机制缺 | **部分采纳**：结构化 `<subject>\|<scope>\|<expires>` + 过期拒注册；完整 grant_id/fingerprint 机制**暂缓**（attestation 落盘已含 argv_sha256/user_data_dir，增量收益小） |
| G9 | hash(name) 派生端口有碰撞面；应随机首启+持久化+未知 PID fail-closed | 属实：v3 §4.1:65 即哈希派生；F7 的稳定性诉求持久化即可满足 | **采纳**：§4.1 端口策略改随机首启+持久化+未知 PID 拒启 |
| G10 | NM 部分缺 chrome.debugger 定位；限额数值方向不对称（1 MB / 64 MiB） | **限额属实**（官方文档核验：host→Chrome 1 MB、Chrome→host 64 MiB）；chrome.debugger 表述 v3 确缺；其引"~47MB 单帧"**本会话未复验** | **采纳**：§4.4 补 chrome.debugger 定位 + 数值；47MB 标注未复验，spike 以现场实测为准 |
| G11 | `data/browser_mount_test/server.py` 不在 HEAD，manifest 只是本机 drift detector | 属实：`git log` 空 + `.gitignore` 忽略 `data/` | **采纳**：§4.6 fixture 源码迁 tracked `scripts/fixtures/`；迁移前 manifest 措辞改"本机 drift 检测" |
| G12 | 实施顺序建议：设计闭合 → binding/transport 重构 → enforce → pipe → NM | 与本仓"先冻结机械不变量再换实现层"一致 | **部分采纳**：S0 门槛采纳；重构拆为行为不变子步（S3a/S5a）；R3 先于 R4 的优先序保留（安全价值更高且不依赖 transport） |
| G13 | `PROFILE_CLASS` 默认应为 `auto`（attestation 决定实际类别） | 未采纳（当前）：attestation 机制未定论前 auto 无机械依据；""≡dedicated 已是 fail-closed 等价（不符即拒注册），与 auto 的差别仅在报错语义 | S0 落定后重议：机械分类被证明可靠再翻默认值 |

**未采纳/驳回说明**：G13 如上；G8 完整 grant 机器暂缓。评审总评（方向正确、v2 不宜直接实施）与 v3 结论一致；其净增量 = G1/G2/G3/G5/G7/G9/G10/G11 八条实质修正，其中 G2 为阻断级（S3 无 S0 不开工）。
