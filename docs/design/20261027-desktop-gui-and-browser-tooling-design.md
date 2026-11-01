# LFL 桌面 GUI 能力与浏览器工具补强 · 需求实现设计书

> **路径脱敏**：本文中的 `$HOME` 表示用户主目录的实际绝对路径（原文为具体用户名路径）。shell 命令可直接展开；出现在 JSON 参数或工具回执引文中时，需按实际主目录展开后再使用。

| 项 | 内容 |
|---|---|
| 版本 | v0.2（M0 探测收口后修订，未实施） |
| 日期 | 2026-10-27 |
| 作者 | LFL（本会话） |
| 状态 | D0 已判定（分支 A′，见 `20261027-d0-desktop-capability-report.md`）；Q1/Q3 已裁决；桌面实现待批准 |
| 适用代码根 | `$HOME/Project/llm-first-loop-mirror`（见 F10，HEAD 待复核） |
| 读者 | 决策者（用户）、后续实现会话/子代理、独立审查者 |

---

## 0. 证据分级与写作纪律

本文每条"现状"陈述都带级别。级别决定它能被用来做什么：

| 级别 | 含义 | 允许的用法 |
|---|---|---|
| **A 实测** | 本会话工具回执（命令 + 输出） | 可直接作为设计依据 |
| **B 源码** | 当前工作树 `文件:行` | 可作实现落点；实施前必须复核 HEAD |
| **C 卡片** | experience/method 的 stable ref | 作经验依据；须核适用条件 |
| **D 推断** | 未验证假设 | **禁止**作为实施依据，必须挂实验（M0 或第 11 章） |

写下这份文档的直接原因：上一轮分析里有一部分是工具合同审读推断出来的（D 级），如果直接当需求开工，会把"看起来缺"当成"确实缺"，也会漏掉真正的硬约束（TCC 权限、Retina 坐标、云端视觉外传）。本轮的补充主要来自两条线：**环境实测** 和 **源码核对**。

---

## 1. 问题陈述

### 1.1 被真实任务踩实的断点（A/C 级）

| # | 断点 | 发生位置 | 后果 |
|---|---|---|---|
| PR1 | 无文件上传动作 | 头条/公众号发文，ProseMirror 编辑器插图 | 全链路降级人工交接 |
| PR2 | 富文本直接赋值不可靠 | contenteditable / ProseMirror | 内容丢失或字数统计不一致 |
| PR3 | 视觉证据缓存锁死 | 后台审核状态页 | 拿到的是旧图，不能当当前状态 |
| PR4 | 大页 capture 失败（帧超限） | 大后台页面 | 感知全瘫，无法裁剪重试 |
| PR5 | 跨应用动作无通道 | 原生文件选择器、确认弹窗 | 必须人来做 |

### 1.2 两类缺口的性质不同（这是本设计的分层依据）

- **浏览器侧 = 合同缺口。** CDP 层大多已经具备能力（下载事件、JS 对话框事件、Frame 树都已采集），只是没有暴露成模型可用的合同。改造成本低、风险可控、可独立交付。
- **桌面侧 = 架构缺口。** 需要新进程、系统级权限（TCC）、新的安全面（鼠标键盘是真的会点到别处），并且当前 `execute_command` 处于 sandbox-exec 内，AX 通道已实测被拒。**不能**按"再加一个工具"来估工。

结论：两件事必须分开排期，浏览器侧先做且不依赖桌面侧；桌面侧先做**权限归因实验**，未通过则整个 D 系列不进入实现。

---

## 2. 目标与非目标

### 2.1 目标（可测）

| ID | 目标 | 度量 |
|---|---|---|
| G1 | 发文链路可在无人工介入下完成"填正文 + 上传图片" | 端到端用例通过，人工交接次数 = 0 |
| G2 | 视觉/感知证据可信：同一 ref 必然对应同一页面状态 | 故意变更页面后取证据，sha 必变 |
| G3 | 大页可裁剪感知：失败时能定位到帧/子树 | 失败回执必须含"共 N 帧，已投影 M" |
| G4 | 桌面感知在**只读**模式下可用（看得到前台应用、窗口、控件） | 授权后 `desktop_perceive` 返回窗口树 |
| G5 | 桌面操作在窄口径下可用（白名单应用 + 干跑确认） | 白名单内点击成功，白名单外被拒 |
| G6 | 所有新增写动作可审计、可回放、可拒 | 审计日志字段齐全，负例全部被拦 |

### 2.2 非目标（明确不做，避免范围蔓延）

| ID | 不做 | 理由 |
|---|---|---|
| N1 | 全量"任意操控"桌面 | 风险面最大、边际价值最低（多数需求 CLI 已更好） |
| N2 | 系统级快捷键（Cmd+W / Cmd+Q / Cmd+Tab） | 会摧毁用户现场，且不可撤销 |
| N3 | 登录窗口、锁屏、FileVault、系统设置里的删除/重置流程 | 灾难不可逆 |
| N4 | 密码管理器、支付确认、验证码输入 | 隐私与授权红线 |
| N5 | 绕过用户确认的"自动连续点击" | 与 RULE-AI 的授权边界冲突 |
| N6 | 远程/跨机桌面 | 授权模型完全不同，另立项 |
| N7 | 用桌面点击替代已有 CLI/API 通道 | 脆弱且更贵，见 6.5 路由规则 |
| N8 | 无授权的云端视觉读图 | 见 F5 隐私约束 |

---

## 3. 事实基线

> 全部为本轮实测或源码核对结果。行号以 2026-10-27 工作树为准，实施前复核。

| ID | 事实 | 级别 | 证据 |
|---|---|---|---|
| F1 | `execute_command` 运行在 macOS `sandbox-exec` 内，仅允许写工作区与缓存目录 | A | 每次回执头部的沙箱提示 |
| F2 | `screencapture -x` 在沙箱内**可用**，产出 8,174,642 字节 PNG | A | `.tmp-verify/probe-shot.png` |
| F3 | 截图为 3024×1964 **物理像素**；显示器为 3024×1964 Retina，即逻辑 1512×982 **点**，scale=2.0 | A | PNG IHDR + `system_profiler SPDisplaysDataType` |
| F4 | `osascript` 驱动 System Events 报 `-10004 权限违例` | A | 实测输出 |
| F5 | 当前会话模型 `deepseek/deepseek-v4-flash`，base_url 为云端 `api.deepseek.com`，标注 multimodal | A | `model_catalog` 回执 |
| F6 | 无 `pyobjc/Quartz`、无 `cliclick`、无 `pyautogui`、无 `tesseract` | A | `python3 -c import Quartz` + `command -v` |
| F7 | `browser_operate` 的 `do` 枚举仅 6 项：navigate/click/set_text/append_text/select/scroll；无 upload / press_key / hover / dialog | A+B | 当前 schema；`browser_semantic_operation.py:319` |
| F8 | 底层**已有** `Page.downloadWillBegin → download_started`、`Page.javascriptDialogOpening → dialog_opened` 的边界事件映射，但只用于记录边界事件 | B | `browser/cdp_action_host.py:108-112`、`:329` |
| F9 | 底层**已有** Frame 树采集：`_flatten_frames()` 产出 `frame_id/loader_id/url/security_origin/parent`，并以 `frames` 字段进入 capture 结果 | B | `browser/perception.py:2876-2897`、`:2061` |
| F10 | 无 `DOM.setFileInputFiles`、无 `Input.dispatchKeyEvent` / `Input.insertText` 调用 | B | 全仓 grep 无命中 |
| F11 | vision 证据按**内容 sha256** 落盘命名：`vision/<digest>.png`，ref 为 `vision://browser/v0.1/<digest>` | B | `perception.py:2094-2115` |
| F12 | 运行代码根候选为 `$HOME/Project/llm-first-loop-mirror`（web pid 6647 的 cwd），但该目录 `git log -1` = `be9413318`，而运行时记录为 `2894beda7`；两者不一致 | A | `lsof -a -p 6647 -d cwd` + `git log` |
| F13 | 会话内并发/独占：浏览器工具为"单 host-bound page + 单分发"，无 rebind 语义 | C | `experience:EXPERIENCE-20260920-lfl-sha` （卡片片段未水合；该结论另有当前 schema 直接支持） |
| F14 | 大页 capture 失败根因曾被判定为**帧超限**而非超时 | C | `experience:EXPERIENCE-20260918-browser-action-target-id-id-grounding-ref` （来源为上一轮分析结论与卡片标题，**未水合卡片正文**） |

**由 F11 推出的一个纠偏（重要）**：vision 证据是**内容寻址**，不是缓存键。所以"跨不同页面返回同一 ref/sha"有两种可能：(a) 两页像素确实完全相同（空白页、同一页面未变化）；(b) 采样链路在别处复用了旧 payload。经验卡把结论定为"缓存锁死"，但**当前证据不足以区分 (a)/(b)**。因此 B10 需求写成"复现 + 元数据可判定"，不写成"直接改缓存键"——后者可能改错地方。

**由 F3 推出的硬约束（上一轮方案漏掉的）**：AX 与 CGEvent 用**点**，截图与视觉模型给**像素**，本机差 2 倍。任何"视觉定位 → 点击"的链路若无 scale 归一，必定点偏。这条必须进合同，不能留到实现期"顺手处理"。

**由 F5 推出的硬约束**：截图读入模型 = 图片离开本机送往云端 DeepSeek。桌面截图天然含私聊、邮件、密码框。因此"感知层复用 `vision=evidence`"这条**不能无条件成立**（上一轮方案的第 1 条主张需要加限制条件）。

---

## 4. 需求清单

优先级：**P0** = 修正确性缺陷或解锁已断业务；**P1** = 高频能力缺口；**P2** = 体验/效率。

### 4.1 浏览器工具（B 系列）

| ID | 需求 | 优先级 | 依据 | 验收判据（可执行） |
|---|---|---|---|---|
| B1 | `do=upload`：向 `input[type=file]` 注入本地文件 | P0 | PR1/A | 本地测试页收到字节，sha256 与服务端一致；`/etc/passwd`、`~/.ssh/**` 被拒且**不发起任何网络请求** |
| B2 | `do=type`：字符级输入（走真实输入事件，不写 DOM 属性） | P0 | PR2/C | ProseMirror 测试页输入 2000 字，页面字数计数 = 2000，撤销栈可用 |
| B3 | `do=press_key`：页面级按键/组合键 | P1 | 推断 D→M0 | Enter 提交成功；`Meta+W`、`Meta+Q` 被合同拒绝（负例必须被拦） |
| B4 | `do=hover`：移动到元素中心触发悬停 | P1 | 推断 D | 悬停后菜单出现，snapshot diff 可见新增节点 |
| B5 | `do=dialog`：accept/dismiss 阻塞中的 JS 对话框 | P1 | F8/B | 有 dialog 时 accept 后页面继续；无 dialog 时确定性失败并给 guidance |
| B6 | 下载合同：会话级下载目录 + `wait` 完成条件 | P1 | F8/B | 点击下载后 `wait` 返回 `path/size/sha256`，且文件在目录内可读 |
| B7 | `wait` 负条件：`state=absent` + `settle_ms` | P1 | 推断 D | 消失即成功；**抖动页面**不得误判（连续 300ms 稳定才算成立） |
| B8 | iframe 寻址：对象带 `frame_id`；操作可显式指定 frame | P1 | F9/B | 主帧与子帧同名按钮可分别寻址；未指定 frame 且跨帧重名 → 确定性歧义拒绝 |
| B9 | 只读页面清单：返回全部 page 的 id/url/title/是否绑定 | P1 | A（仅 miss 回执带清单） | 健康状态下也能列清单；**不改变当前绑定**（调用前后 binding 一致） |
| B10 | vision 证据可判定：证据元数据带 page_id + world_version + captured_at | P0 | F11/B | 改页面后取证据 sha 必变；两页像素完全相同则回执显式标注"内容与上次一致" |
| B11 | 大页分帧投影：`projection_kinds` + 游标，失败回执带"共 N 帧，已投影 M" | P1 | F14/C | 超限页面返回可继续的 cursor；不得整体失败 |
| B12 | `vision=evidence` 支持区域：`region=ref` 或 `bbox` | P2 | 成本/精度 | 区域截图尺寸 ≈ 元素 bbox × scale（±2px） |
| B13 | 受限批量：`do=steps[]`（≤8，identity 寻址优先，失败即停） | P2 | 推断 D | 第 3 步失败时回执含 `completed_steps=2` + 失败点；不得重放已完成步骤 |
| B14 | 死锁降级：连续 N 次 capture 超时 → 带内降级回执 | P2 | C `cdp-env-target-id` | 回执含 `degraded=true` + 建议动作；不静默重启 |
| B15 | 无名元素后备寻址（icon-only 按钮） | P1 | C 方法卡判据③ | 无 accessible name 的按钮可用确定性后备键寻址；**跨 world_version 失效**须在回执标注 |

### 4.2 桌面能力（D 系列）

| ID | 需求 | 优先级 | 说明 |
|---|---|---|---|
| D0 | **权限归因实验（先决）** | P0 | 判定 F4 的 -10004 属 TCC 未授权、还是 sandbox-exec 拦截 Mach IPC。三分支见 7.3.1 |
| D1 | 桌面宿主进程 | P1 | 独立受管服务（`service_control` 管生命周期），`LFL_DESKTOP_ENABLE=1` opt-in；**不在 execute_command 里起** |
| D2 | 感知分级 L0/L1/L2 | P1 | L0 窗口元数据（无需 AX）；L1 AX 树；L2 截图+视觉（最贵、需单独授权） |
| D3 | 坐标合同 | P1 | 对外只用**点**；capture 回执带 `scale`；像素→点必须除 scale |
| D4 | 窗口绑定 | P1 | 绑定 `CGWindowID` + bundle id；绑定期内前台窗口变化 → 拒绝执行。**匹配规则（2026-10-28 修订）**：`title_exact` > `title_relaxed`（较短标题是较长标题的前缀）+ bounds 差 ≤ 2pt > `bounds_only`（仅当 CG 标题不可用）；多命中一律 `window_ambiguous` 拒绝，`AxView.binding` 记录依据，`title_relaxed` 追加 `degraded=["ax_title_relaxed"]` |
| D5 | 动作集（窄） | P1 | click / type / press_key / scroll；不含 drag、不含系统快捷键 |
| D6 | 三级安全门控 | P1 | see / act / irreversible，见 6.2 |
| D7 | 用户在场检测 | P1 | HID idle < 60s → 默认拒 mutate，`force=true` 需一次性授权 |
| D8 | 隐私脱敏 | P0 | 敏感应用名单拒绝截图；截图默认**只落盘不读入模型** |
| D9 | 审计 | P1 | append-only JSONL，字段见 6.4 |
| D10 | 锁屏/多显示器 | P2 | 锁屏拒绝操作；多显示器按 `display_id` 定位 |

**D 系列的诚实结论（v0.2 修订，A 级实测）**：D0 已判定为**分支 A′**——TCC 权限已具备（`AXIsProcessTrusted()`=true、`CGPreflightScreenCaptureAccess()`=true），sandbox-exec 拦的只是 **AppleEvent → System Events** 通道（`-10004`）；AX API 直调、`CGWindowListCopyWindowInfo`、`screencapture`（全屏/区域/窗口级）在当前进程内全部可用。

**因此"D1 独立宿主进程"不是前置条件**：只读侧可在现有进程内实现，动作侧只需避开 AppleEvent 路径。v0.1 的"开发量≈一个受管服务"估算不成立。详见 `20261027-d0-desktop-capability-report.md`。

---

## 3.1 补充事实基线（本轮追加；编号接第 3 章）

| ID | 事实 | 级别 | 证据 |
|---|---|---|---|
| F15 | `lsappinfo list` 在沙箱内**可用**，能列出应用名、`bundleID`、可执行路径 | A | 实测输出含 `com.apple.loginwindow` 等条目 |
| F16 | `swiftc --version` 报 `permissionDenied` | A | 实测；现场编译 Swift helper 这条路当前不通 |
| F17 | `python3` 为 **3.9.6**（系统 Xcode 版），`pip 21.2.4` 可用；无 pyobjc | A | `python3 -V` / `python3 -m pip --version` |
| F18 | `screencapture -R 0,0,200,100` 产出 **400×200 像素** | A | 直接证明：`-R` 输入是**点**，输出是**像素**，比值 2.0 |
| F19 | `screencapture -l 0` 报 `could not create image from window` | A | 窗口级截图必须先拿到真实 `CGWindowID` |

**F15+F19 合起来推出 D2 的可行子集（v0.1 推算）**：应用清单走 `lsappinfo`，不需要 AX 权限；但窗口 id / 几何 / 控件树需要 `CGWindowListCopyWindowInfo` 与 AX，前者需要 pyobjc（F17 缺失）或 Swift helper（F16 被拒）→ 第一版只能是 **L0-lite：应用级 + 区域截图级**。

**v0.2 推翻了上述推算（A 级实测）**：CoreGraphics 与 AX 都可 **ctypes 直调**（标准库，零新依赖），F16/F17 的缺口不构成障碍。

| ID | 事实 | 级别 | 证据 |
|---|---|---|---|
| F20 | sandbox 内 `AXIsProcessTrusted()` = **true**；`CGPreflightScreenCaptureAccess()` = **true** | A | `d_probe_trust.py` |
| F21 | sandbox 内 `CGWindowListCopyWindowInfo` 返回 **31 个窗口**，id/owner/title/layer/alpha/bounds(点)/pid 齐全 | A | `d_probe_cgwindow.py` |
| F22 | 全屏 `screencapture -x` = **3024×1964 px**；主屏 `CGDisplayPixels*` = **1512×982 点** → scale=2.0 | A | 截图 + `d_probe_ax2.py` |
| F23 | 窗口级 `screencapture -l 115037` = **3024×1754** = bounds 1512×877 点 ×2；读图确认只含目标窗口 | A | `win-chrome.png` + read_image |
| F24 | `AXUIElementCreateApplication` 可读 AXWindows / AXTitle / AXChildren / AXFocusedWindow / AXPosition | A | `d_probe_axapi.py` |
| F25 | `AXUIElementCopyActionNames(AXButton)` = `["AXPress"]`（**只读枚举，未投递动作**） | A | `d_probe_ax2.py` |
| F26 | `osascript ... System Events` 仍报 `-10004`，而普通 `osascript` 正常 → 被拦的是 **AppleEvent 通道**，不是 AX 能力 | A | §7.3.1 |
| F27 | 语义对象已带帧归属字段，但名字是 **`frame_token`**（值形如 `frame:<frameId>`，主帧为 `None`），**不是** `frame_id`；帧树经 `_flatten_frames()` 以 `frames` 字段进入 capture | A | `perception.py:2876-3022`（HEAD `07fa4fe29`） |
| F28 | 当前**生产运行时**工具面仍是 M1 之前：`browser_operate.do` 只有六值，无 upload/type 动词；施工树 HEAD 已有 upload/type | A | 本会话工具 schema + `browser_semantic_operation.py:48` |

**由 F27 的纠偏**：B8（iframe 寻址）**复用既有 `frame_token`**，不新增 `frame_id` 字段——否则会造出两套帧标识，寻址与会话状态各认一套。设计书 §4.1/B8 文案里的 `frame_id` 一律按 `frame_token` 落地。

**由 F28 的约束**：M2 的能力**无法在当前运行时做 live 验收**（工具 schema 未暴露新动词）。验收只能落在施工树的单元/集成测试与门禁上；live 验证必须等部署后单独安排，不得混入 M2 完成判据。

**由此 D2 可用级别上移**：L0（窗口元数据）与 L1（窗口 / 浏览器 chrome 层 AX 树）当前可用。**未验证**：AX 树到网页内容（AXWebArea，4 层遍历只见 AXGroup）、真实 AXPress 投递（属 mutation，本轮无授权）。

---

## 5. 接口合同草案

> 以下为**草案**，用于评审，不代表已实现。字段命名与现有工具风格一致（snake_case，显式枚举，单动作分发）。

### 5.1 `browser_operate` 扩展

保留现有三选一寻址与单分发语义，新增五个 `do`：

```
do=upload      target: {kind:"input", name*}|{grounding_ref}
               paths: [str]            # 1..8 个；realpath 必须落在允许根内
               scope: "workspace"|"granted"   # 默认 workspace

do=type        target: 同现有寻址
               text: str
               mode: "insert_text"|"keys"     # 默认 insert_text（走 Input.insertText）

do=press_key   keys: str                # "Enter" | "Escape" | "Tab" | "Meta+A"
               target?: 同现有寻址        # 省略则作用于当前焦点

do=hover       target: 同现有寻址

do=dialog      action: "accept"|"dismiss"
               prompt_text?: str          # accept 且为 prompt 类型时必填
```

回执新增公共字段（详见 5.5）：

```
world_version_before / world_version_after
post_capture_sha256                 # 动作后截图证据（落盘，不进模型）
applied_steps / completed_steps      # 批量时使用
degraded: bool                      # 降级执行（如投影裁剪）
guidance: str?                      # 不可执行时的下一步建议
```

**B3 的按键黑名单（硬编码，不可配置放宽）**：`Meta+W`、`Meta+Q`、`Meta+Tab`、`Meta+Shift+Q`、`Ctrl+Cmd+Q`、`Meta+Alt+Esc`。理由：这些会关闭/退出/切换宿主现场，且不可撤销。

### 5.2 `browser_perceive` 扩展

```
action=pages                          # 新增：只读页面清单
  → [{page_id, url, title, is_bound, is_visible}]

wait kind=object_state
  state=absent                        # 新增负条件
  settle_ms=300                       # 稳定窗，默认 300ms

wait kind=download_state              # 新增
  expected: "completed"|"failed"

snapshot vision=evidence
  region: {grounding_ref} | {x,y,w,h} # 新增区域化（单位：CSS 像素）
```

**B9 的硬约束**：`action=pages` 只读，**不得**改变当前绑定；需要切页仍走显式 `target_id` 换绑（沿用 EVO-20261007 的独立动作语义）。这一条是为了不让"列清单"变成隐式 rebind。

### 5.3 `desktop_perceive`（新工具草案）

```
{
  action: "apps" | "windows" | "snapshot" | "hydrate" | "wait",
  window_id?: str,          # snapshot/hydrate/wait 必填
  depth?: int,              # AX 树深度，默认 3，上限 6
  vision?: "evidence"|"none",   # 默认 none（隐私默认关闭，见 D8）
  display?: int
}
```

返回分级：

| 级别 | 内容 | 依赖 | 当前可用性（v0.2 实测） |
|---|---|---|---|
| L0-lite | app 列表、bundleID、pid、是否前台 | `lsappinfo` | **可用**（F15） |
| L0 | 窗口 id、标题、bounds(点)、层级、pid | `CGWindowListCopyWindowInfo` via **ctypes** | **可用**（F21；推翻 v0.1「缺依赖」） |
| L1 | AX 树（role/title/children/focused/position） | AX API via **ctypes** + 授权 | **可用**（F24），限窗口与浏览器 chrome 层；**网页层未验** |
| L2 | 截图（全屏 / 区域 / **窗口级**）+ scale 元数据 | `screencapture` | **可用**（F22/F23）；读入模型需显式授权（Q3 已裁决允许） |
| 动作 | AXPress / 键入 | AX API / CGEvent | **未验证**（只枚举到 AXPress，未投递） |

> **运行时复测（2026-10-28，服务进程 pid 21464，部署 `dfb627bee`）**：`snapshot` 返回 `ax.available=false`、`degraded=["ax_window_unbound"]`、`node_count=0`；同一链路上 `windows`（L0）正常、`screen_capture_granted=true`（L2 授权成立）。失败形态是**绑定未命中**而非 `-25211` 未授权，两者在现有回执里不可区分 ⇒ 当时归因未定。
>
> **归因已定（2026-10-28 09:39，同一台机器）**：不是授权问题。① 服务进程对 MCP Console 窗口 `snapshot` 正常返回 6 节点；② 同二进制子进程 `AXIsProcessTrusted()` 为 `True`；③ 活动监视器窗口的 CG bounds 与 AX bounds 逐字段相等，仅标题不同（CG `活动监视器` / AX `活动监视器 – 所有进程`），旧规则要求标题完全相等 ⇒ 判成未命中。修法见 §D4，验证见 `20261028-live-smoke-b3-b5-b7-dialog-and-ax-binding.md` §5（新进程 E2E：`binding=title_relaxed`、17 节点）。
>
> 注意回执口径：`permissions.ax_trusted` 是原始 trust 位（服务进程内缓存，仍报 `false`），而 `capabilities.can_read_ax` 是实测探针（`true`）。两者不一致时**以探针为准**，这条差异本身也该在文档里写死，避免下次又被"false"误导成权限问题。

### 5.4 `desktop_operate`（新工具草案）

```
{
  do: "click" | "type" | "press_key" | "scroll",
  window_id: str,                     # 必填：绑定期内前台窗口变化 ⇒ 拒绝
  target: {ax_ref: str} | {point: {x:int, y:int}},   # 单位：点
  text?: str,
  keys?: str,
  dry_run: bool,                      # 默认 true
  confirm_token?: str,                # dry_run 后签发的一次性令牌
  force?: bool                        # 绕过在场检测，需一次性授权
}
```

回执字段：`risk_class`（see/act/irreversible）、`pre_sha256`、`post_sha256`、`target_identity`、`applied`、`needs_confirmation`、`privacy_blocked`。

> **2026-10-31 投递通道实测（沙盒内，TextEdit 临时窗口）**：`AXPress` 真实投递**已验证**（对原生 `AXCloseButton` 执行 `AXPress` → err=0，窗口数 1→0）；AX 键入（`AXSetAttributeValue(kAXValue)` 写 AXTextArea）**已验证**（写入串回读一致）。CGEvent 键入**通道通但输出被当前输入法污染**——本机输入源为 `com.apple.inputmethod.SCIM`（拼音 ABC），逐字母输入被拆成「a␣s␣d」，带 shift 的大写不受影响，纯 unicode 事件无输出。故实现应**优先走 AX set-value**，CGEvent 兜底路径必须处理 IME。Chrome 网页层仍不可达：沙盒内起独立 `--force-renderer-accessibility` 实例会因 profile 锁的 socket 目录不可创建而 abort；现存服务 Chrome 的 AX 树 `AXWebArea=0`。明细见交接书 §11.7。

### 5.5 公共回执与错误码

| 错误码 | 含义 | 是否可重试 |
|---|---|---|
| `path_not_allowed` | upload 路径不在允许根内 / 符号链接逃逸 | 否（改路径） |
| `key_not_allowed` | 命中按键黑名单 | 否 |
| `frame_ambiguous` | 跨帧重名且未指定 frame | 否（补 frame） |
| `window_unbound` / `foreground_changed` | 绑定失效 | 是（重新绑定） |
| `privacy_blocked` | 敏感应用/窗口，拒绝截图或操作 | 否 |
| `user_present` | 用户正在输入 | 是（force 或稍后） |
| `degraded_projection` | 投影被裁剪 | 是（带 cursor 继续） |
| `ax_unavailable` | AX 通道不可用 | 否（需 D0 解决） |
| `paths_count_invalid` | upload `paths` 数量不在 1..8 | 否（改参数） |
| `upload_args_invalid` | upload 参数键集/类型不合法 | 否 |
| `type_text_too_long` | type 文本超过 2000 字符 | 否（分段） |
| `type_args_invalid` | type 参数键集/类型不合法 | 否 |

> 后 4 个码为 M1 实现期新增（review 待定项 3 裁定「保留」），已并入上表。

### 5.6 as-built 差异（截至部署 `dfb627bee`，2026-10-28）

第 5 章各表描述的是**设计意图**。下表记录**已部署代码与设计的实际差异**，防止把草案读成已实现。

| 设计项 | 已部署状态 | 依据 |
|---|---|---|
| `do=dialog` 的 `prompt_text` | **未实现**：v1 合同 `args={action}` 为闭合键集，prompt 型对话框 accept 走 Chrome 默认值 | M2a dev 报告「后续项 2」 |
| `desktop_perceive` 的 `hydrate` / `wait` | **未实现**（M3 委派明确不做） | M3 dev 报告「未做项 2」 |
| `desktop_operate`（§5.4） | **未实现**（M4 未进入；L1 AX 当前不可读） | §5.3 运行时复测注 |
| L1 AX 树 | 设计称「可用（F24，限窗口与 chrome 层）」；**2026-10-28 运行时复测不可读** | 同上 |

> **2026-10-31 口径更新（覆盖上表中的过期行）**：M3 桌面只读侧**已交付并上线**（部署 `b008c9fae`），`desktop_perceive` 的 L0/L1 本机实测可用——AX 树可读；CG 标题与 AX 标题不相等时按 `title_relaxed` 降级绑定（见 §11.8）。`desktop_operate`（§5.4）**仍未实现**：M4 写动作于 **2026-10-31 15:11 获用户授权**，按交接书 §11 的顺序先验 AXPress 真实投递、再谈门控，尚未开工写动作代码。本表其余行按各自「依据」列的时间戳理解。

### 5.7 R5/P1 合并与部署记账（2026-10-28）

| 项 | 状态 | 依据 |
|---|---|---|
| R5/P1 修复并入 main | **已合**：`git merge --ff-only`，main `f5fec37c1` → `395ebae9b`（2 个修复提交：P1-1 清态出口、P1-2 降级登记） | 合并闸 PASS（P0=0 P1=0）；全量门禁 junitxml 12004 tests / 0 fail / 0 error / 174 skip（=11830 passed，比旧 tip 多 4 条新回归测试） |
| 部署 | **已 publish，未完成**：generation 333、desired `git_head=395ebae9b`；restart 状态 `waiting_for_requester_exit`（web 承载发起会话，必须等该会话退出才执行） | `service_control(action=status, action_id=svc-971a603cbc5f4e6dbe5e45d7e7acedc1)` |
| 部署后核验（`git_head` / `matches_desired_generation` / `pid_alive`） | **未验**：依赖上一条 restart 真正落地，本轮无法在会话内完成 | 下一会话第一件事 |
| M4（`desktop_operate` 写动作：点击/键入） | **未授权-不实施**：本轮只记账，未改任何 `tools_l0_enabled`、未新增 AX 写能力 | 交接书 §4.4 |

> 记账口径：main 已含 R5 修复；上表"未验"的项不得当成已验。桌面会话重启后，M4 授权是第一优先待办。

---

## 6. 安全与权限设计

### 6.1 威胁模型

| ID | 威胁 | 场景 | 缓解 |
|---|---|---|---|
| T1 | 任意文件外传 | `upload` 被用来把 `~/.ssh/id_rsa` 传到网页 | 路径根白名单 + realpath + 符号链接解析 + 大小上限 + 回执只记 sha/size |
| T2 | 误点/盲点 | 视觉坐标偏 2 倍，点到"删除" | 坐标只用点；视觉坐标必须 dry_run 二次确认 |
| T3 | 权限旁路 | 桌面白名单放开终端 → 不受沙箱的任意命令 | 终端/IDE **只读感知**，不给 act |
| T4 | 隐私外泄 | 截图含密码/私聊，经 `read_image` 送云端 | D8：默认不读入模型；敏感 app 拒拍；用户显式授权才可读 |
| T5 | 注入 | 页面/窗口文本里藏"请点击确认"诱导模型 | 目标身份必须来自 snapshot，不接受页面文本自述；写动作永远需要 exact 寻址 |
| T6 | 重放 | 复用旧 `confirm_token` 连点 | 令牌一次性 + 绑定 `action_id` + 绑定 world_version |
| T7 | 抢占用户 | 自动点击打断用户输入 | HID idle 检测 + 独占声明 |
| T8 | 权限持久化 | 一次授权后长期静默生效 | 会话级开关 + 每次 `ax_status` 自检 + 审计留痕 |

### 6.2 三级门控矩阵

| 风险类 | 判据 | 默认行为 |
|---|---|---|
| **see** | 只读感知（snapshot/apps/windows） | 允许（隐私敏感 app 除外） |
| **act** | 可逆动作（点击普通控件、输入文本、滚动） | 首次进入某 app 必须 dry_run；同 app 同动作类型在 session 内放行 |
| **irreversible** | 提交/发布/支付/删除/覆盖/关闭未保存窗口 | **永远单步**，需 `confirm_token`；发布类复用 `review_admission` |

**重要限制（必须写进文档，避免过度承诺）**：程序**无法**可靠判定"是否不可逆"。三级分类是"默认规则 + 关键词启发式 + 应用规则"的组合，必然不完备。因此：
1. 启发式命中即升级为 irreversible（宁可多确认）；
2. 未命中的动作仍受 dry_run 首检保护；
3. 文档明确告知"这不构成安全保证，只是降低误操作概率"。

### 6.3 令牌与 escalation 的关系

- 桌面 `confirm_token`：与 `escalation` 的一次性令牌**同构**（申请 → 人工批准 → 单次使用 → 过期作废），但不共用通道：escalation 是"命令被硬阻断后的提权"，confirm_token 是"动作前置确认"。两者都留审计。
- 复用 `review_admission`：发布/提交类桌面动作（如点击"发布"）必须走已有发表闸，不能由 `desktop_operate` 自行放行。

### 6.4 审计字段（append-only JSONL）

```
ts, session_id, tool, do, app_bundle, window_id, target_identity,
risk_class, dry_run, confirm_token_id, applied, pre_sha256, post_sha256,
foreground_before/after, hid_idle_ms, error_code
```

审计文件由宿主进程写入，模型侧只读；**不提供删除/改写工具**。

### 6.5 通道路由规则（写进规则而非工具）

优先级：**CDP/HTTP API > CLI > 桌面 GUI**。理由：

- 桌面点击是像素级脆弱（布局变化即失效）、贵（截图+视觉）、慢（每步往返）；
- 已有 CLI 能做的事用桌面点击替代，是纯负收益。

规则应落到 `docs/ai_rules.md` 或工具描述里，而不是靠模型自觉。

---

## 7. 实现设计

### 7.1 模块落点

| 需求 | 主要落点 | 改动性质 |
|---|---|---|
| B1 upload | `browser/cdp_action_host.py`（`_ALLOWED` 增 `DOM.setFileInputFiles`）、`browser/action.py`、`tools/builtin/browser_semantic_operation.py` | 新增动作 + 路径策略 |
| B2 type | `cdp_action_host.py`（`Input.insertText` / `dispatchKeyEvent`）、`action.py` | 新增动作 |
| B3 press_key | `cdp_action_host.py` + 黑名单常量 | 新增动作 |
| B4 hover | `cdp_action_host.py`（`Input.dispatchMouseEvent` moved） | 新增动作 |
| B5 dialog | `cdp_action_host.py`（已有 `dialog_opened` 事件，补 `Page.handleJavaScriptDialog`） | 事件已有，补动作 |
| B6 download | `cdp_action_host.py`（已有 `download_started`，补 `Browser.setDownloadBehavior` + `Page.downloadProgress`）、`browser_wait.py` | 事件已有，补合同 |
| B7 wait absent | `browser/predicate.py`、`tools/builtin/browser_wait.py` | 扩展枚举 + 稳定窗 |
| B8 frame | `browser/perception.py`（对象挂 `frame_id`）、`action.py`（frame 上下文） | 已有帧树，补寻址 |
| B9 pages | `tools/builtin/browser_perceive.py`、`browser/cdp_host.py`（`Target.getTargets`） | 新增只读端点 |
| B10 vision 元数据 | `perception.py:2094` `store_vision_evidence()` | 加 `page_id/world_version/captured_at` |
| B11 分帧投影 | `perception.py` 投影层 + `browser_perceive` 参数 | 已有 kind 过滤，补失败回执 |
| B15 后备键 | `perception.py`（`normalize_semantic_name` 同层） | 新增派生键 |
| D1-D10 | 新包 `src/llm_loop/desktop/` + `tools/builtin/desktop_*.py` + `tools/registry.py` 注册 | 新增子系统 |

### 7.2 数据流（桌面侧）

```
desktop_perceive / desktop_operate（工具层，与现有主进程同栈）
  ├─ ax_status       → CGPreflightScreenCaptureAccess / AXIsProcessTrusted（每次调用前自检）
  ├─ window_source   → lsappinfo（L0-lite）/ CGWindowList via ctypes（L0）
  ├─ ax_tree         → AX API via ctypes（L1；窗口/chrome 层，网页层待验）
  ├─ capture         → screencapture -R / -l（点→像素 ×scale）
  └─ actuation       → AX 动作（主通道）/ CGEvent（兜底），点坐标
        ↑
模型（结构化树 + 证据 ref；像素仅在显式授权时读入）
```

> **v0.2 变更**：删除「desktop_host 独立进程 + service_control 生命周期」。原设计假定「沙箱拦截 AX 能力」，D0 实测已推翻——被拦的仅是 AppleEvent 通道。不新增进程 ⇒ 审计仍写主进程 append-only，R2 风险消除。

### 7.3 关键算法与判定

#### 7.3.1 D0 归因结果（v0.2：已完成，分支 A′）

**原三分支（v0.1）已被实测替换**。v0.1 把「非沙箱成功 + 沙箱失败」直接判为「必须做独立宿主进程」，但漏了一步：**要先问被沙箱拦的是哪条通道**。

| 通道 | sandbox 内实测 | 是否被拦 | 影响 |
|---|---|---|---|
| AppleEvent → System Events（`osascript` UI 脚本） | `-10004` 权限违例 | **是** | 只影响「用 System Events 做 UI 自动化」这条旧路径 |
| AX API 直调（`AXUIElementCreateApplication` / `CopyAttributeValue`） | 可读窗口/标题/子元素/焦点/位置 | 否 | D2 L1、D4 窗口绑定 |
| 截图（`screencapture` 全屏/区域/窗口级） | 成功，像素真实 | 否 | D2 L2、D3 scale |
| 窗口元数据（`CGWindowListCopyWindowInfo`） | 31 窗口，字段齐全 | 否 | D2 L0 |
| 应用清单/前台（`lsappinfo`） | 返回 bundleID | 否 | D2 L0-lite、D7 判据 |

**判定：分支 A′——TCC 已授权（`AXIsProcessTrusted`=true、`CGPreflightScreenCaptureAccess`=true），sandbox 只拦 AppleEvent 通道。**

**对设计的三条硬结论**：
1. **D1 独立宿主进程不再是前置**——只读与 AX 动作都可在主进程完成；只需绕开 AppleEvent 路径。
2. **权限自检必须做成工具级 `ax_status`**：`screencapture` 在无「屏幕录制」授权时**不报错**（产出黑图/桌面壁纸），只能靠 `CGPreflightScreenCaptureAccess()` 判定；`AXIsProcessTrusted()` 同理。
3. **授权不随代码走**：TCC 绑定「负责进程」。若将来以 launchd 拉起独立服务，首次调用会再触发系统弹窗——这是**运行期一次性授权**，不是开发期可消除的依赖。

**遗留未验**（M3/M4 实现期必须先做）：真实 AXPress/键入投递生效、AX 树到网页内容（AXWebArea）、锁屏态、跨显示器 scale。

#### 7.3.2 坐标归一

- 对外唯一单位：**点**（point）。
- capture 回执必带 `scale`（本机 2.0，F3/F18 实测）。
- 像素 → 点：`pt = px / scale`；点 → 像素：`px = pt * scale`。
- 校验：点击前断言 `0 ≤ x < width_pt`，否则 `coordinate_out_of_bounds`。
- **禁止**把视觉模型返回的像素坐标直接当点击坐标——必须先除以 scale，且首次必须 `dry_run`。

#### 7.3.3 后备寻址键（B15）

- 生成顺序：`aria-label` → `title` → 可见文本 → `placeholder` → `alt` → **区域序号** `{kind}#{ordinal}`。
- `ordinal` 按当前 snapshot 的确定性遍历序（DOM 顺序，跨帧时先帧序后元素序）。
- 稳定性声明：**仅在当前 `world_version` 内有效**；回执必须带 `stable_within=world_version`，跨版本命中即拒绝并要求重新 snapshot。

#### 7.3.4 负条件稳定窗（B7）

- `state=absent` 成立条件：从请求时刻起连续 `settle_ms`（默认 300ms）内，该 ref 的 identity 未在任何 snapshot 中出现。
- 不满足则继续轮询至超时；超时回执 `state=present`（明确失败，不返回"可能已消失"）。

#### 7.3.5 下载完成判定（B6）

完成 = `Page.downloadProgress.state == "completed"`；若事件缺失，退化判据 = 文件存在 且 无 `.crdownload` 后缀 且 大小在 ≥200ms 间隔的两次采样中相同。回执带 `path/size/sha256/completed_by`。

#### 7.3.6 敏感应用判定（D8）

- bundle id 前缀名单：`com.1password.*`、`com.apple.keychainaccess`、`com.apple.Passwords`、银行类（用户可维护）；
- 窗口标题关键词：`密码`、`Password`、`支付`、`Payment`、`验证码`；
- 命中 → `privacy_blocked`，**不落盘截图**（避免"已存但未读"的伪安全）。

---

## 8. 实施计划

| 里程碑 | 内容 | 交付物 | 退出判据 | 依赖 |
|---|---|---|---|---|
| **M0** | 探测与复现（不改产品代码） | 探测报告：B10 复现结论、B1 技术可行性、D0 归因结果 | 三个问题都有**确定结论**（不是"大概"） | 用户终端执行 D0 命令 |
| **M1** | P0 修复 | B1、B2、B10 + D8 策略 | 发文链路用例通过；隐私负例被拦 | M0 结论 |
| **M2** | P1 浏览器能力（**分两批**） | 批A：B3 press_key / B4 hover / B5 dialog / B6 download；批B：B7 wait absent+settle / B8 frame / B9 pages 只读 / B15 后备寻址 | 对应用例表全绿；负例全拦 | M1 |
| **M3** | 桌面只读 | D2（L0+L1+L2）、D3、D4（**不含 D1**） | 窗口元数据 + 窗口级截图可读；`ax_status` 自检可用；无权限/无 GUI/锁屏三类失败各有确定性回执 | **D0 已完成（A′）**；待 Q1 批准 |
| **M4** | 桌面窄操作 | D5、D6、D7、D9 | 白名单内点击成功，白名单外/敏感 app/用户在场 全部被拦 | M3 |

**为什么 M0 单独成期**：B10 的根因（内容寻址 vs 采样复用）决定改哪一层；B1 的可行性取决于 `DOM.setFileInputFiles` 在当前 CDP 会话是否被 allowlist 放行（`cdp_action_host.py` 有 `_ALLOWED` 白名单，未核）；D0 决定 D 系列是"改代码"还是"改授权"。这三个都不适合边写边试。

---

## 9. 验收用例

> 标注"应拦"的用例是负例。按 RULE-AI-35 的口径：**护栏类改动必须实测"应拦输入确实被拦"**，仅"正常路径能跑通"不算生效。

| ID | 用例 | 输入 | 期望 | 类型 |
|---|---|---|---|---|
| U1 | 上传正例 | 工作区内 200KB PNG → 本地测试页 | 服务端收到字节，sha256 一致 | 正 |
| U2 | 上传拒绝系统文件 | `paths=["/etc/passwd"]` | `path_not_allowed`，且**无网络请求** | 应拦 |
| U3 | 上传拒绝符号链接逃逸 | 工作区内 symlink → `~/.ssh/id_rsa` | `path_not_allowed`（realpath 解析后判定） | 应拦 |
| U4 | 富文本输入 | ProseMirror 页输入 2000 字 | 计数 = 2000，撤销栈可用 | 正 |
| U5 | 按键黑名单 | `press_key "Meta+W"` | `key_not_allowed`，标签页仍存在 | 应拦 |
| U6 | 对话框处理 | 页面 `alert()` 阻塞后 `dialog accept` | 页面脚本继续执行 | 正 |
| U7 | 下载合同 | 点击下载 1MB 文件 | `wait` 返回 `path/size/sha256`，文件可读 | 正 |
| U8 | 负条件稳定窗 | 元素 200ms 后移除 | 300ms 稳定窗后判 absent；抖动页面不误判 | 正 |
| U9 | 跨帧歧义 | 主帧与子帧同名按钮 | `frame_ambiguous`（要求显式 frame） | 应拦 |
| U10 | 页面清单只读 | 打开 3 页调用 `pages` | 返回 3 条；调用前后 binding 不变 | 正 |
| U11 | 证据随页面变化 | 修改页面后取 `vision=evidence` | sha 必变（若不变需 `content_unchanged` 标注） | 正 |
| U12 | 大页投影 | 5000 节点页面 | 返回 cursor + "已投影 M/N"，不整体失败 | 正 |
| U13 | 敏感应用拒拍 | 前台为密码管理器 | `privacy_blocked`，**无截图文件落盘** | 应拦 |
| U14 | 白名单外应用 | 前台为未授权 app | `app_not_allowed` | 应拦 |
| U15 | 用户在场 | HID idle = 5s 时 `click` | `user_present`，需一次性 `force` | 应拦 |
| U16 | 前台漂移 | dry_run 后切换窗口再 confirm | `foreground_changed`，令牌作废 | 应拦 |
| U17 | 令牌重放 | 同一 `confirm_token` 二次使用 | 拒绝并记审计 | 应拦 |
| U18 | 权限自检失败 | 撤销「屏幕录制」授权后调 `desktop_perceive` | `capture_unavailable` + 修复指引，**不产出黑图** | 应拦 |
| U19 | 坐标换算一致性 | 对 1512×877 点窗口截图 | 返回 3024×1754 px 且 `scale=2.0`；点坐标不越界 | 正 |
| U20 | 前台漂移（只读） | 绑定 window_id 后切到别的 app | 回执 `foreground_changed`，返回的仍是绑定窗口而非新窗口 | 应拦 |

---

## 10. 风险登记

| ID | 风险 | 概率 | 影响 | 缓解 | 触发信号 |
|---|---|---|---|---|---|
| R1 | 授权随启动方式漂移（launchd 拉起时需重新授权） | 中 | 中 | M3 首条验收 = `ax_status` 自检 + 修复指引；自检 false 时拒绝后续动作 | 自检 false 但动作仍执行 |
| R2 | ~~独立宿主进程形成审计盲区~~（v0.2 消除：不新增进程） | 低 | 低 | 审计仍在主进程 append-only | 审计条数 < 动作条数 |
| R3 | 多显示器/外接屏 scale 不同 | 高 | 中 | 按 `display_id` 各自取 scale；跨屏后强制重取 | 点击偏移 > 4pt |
| R4 | 截图经云端模型外传 | 中 | 高 | Q3 已裁决「允许读」，但实现仍默认 `vision=none`、逐次显式 `vision=evidence`；敏感 app 拒拍（D8）；每次读图记审计 | 出现无 `vision` 参数的读图 |
| R5 | "不可逆"判定不完备 | 高 | 高 | 启发式命中即升权 + 首检 dry_run + 明确声明非安全保证 | 误点后无 dry_run 记录 |
| R6 | `DOM.setFileInputFiles` 被 CDP allowlist 拒 | 中 | 中 | M0 先验；退化为桌面桥接（依赖 D） | M0 探测失败 |
| R7 | 批量动作半完成 | 中 | 中 | `completed_steps` + 不重放 + 显式告知 | 回执缺少已完成步数 |
| R8 | vision 同 sha 真因判断错 | 中 | 中 | M0 复现优先，不先改代码 | 修复后仍复现 |
| R9 | **页面弹 alert/confirm 后标签页对 CDP 与键盘永久失联**（P0，不是能力缺失而是把用户页面搞死） | 高（真实站点确认框常见） | 高 | R1 超时不 drop + R2 click 事件优先 + R3 门禁自愈（§11.3）；验证须覆盖「click→accept→同 target 再 capture 正常」 | `capture_channel_degraded[mode=timeout]` 后 `dialog accept` 回 `dialog_not_open`，Enter 也无效 |

---

## 11. 未决问题（需用户裁决）

| ID | 问题 | 选项 | 我的建议 |
|---|---|---|---|
| Q1 | 桌面能力是否纳入本轮？ | (a) 只做 M0 探测；(b) 做到 M3 只读；(c) 做到 M4 窄操作 | **(a) ✅ 已裁决**：只做 M0 探测；M3/M4 待 D0 报告评审后再定 |
| Q2 | 白名单首批 app | 建议：Finder / Safari / Chrome / Preview；**不含**终端与 IDE 的 act | 采纳建议；终端只读 |
| Q3 | 是否允许云端模型读桌面截图 | (a) 永不；(b) 逐次授权；(c) 白名单 app 内允许 | **(b) ✅ 已裁决**：允许云端模型读桌面截图；实现仍默认关、逐次显式、敏感 app 拒拍 |
| Q4 | 是否接受批量动作的半完成语义 | (a) 接受（带 completed_steps）；(b) 只做单步 | **(b) 先单步**，B13 延后到有真实需求 |
| Q5 | upload 允许根 | (a) 仅工作区；(b) 工作区 + Downloads；(c) 显式授权目录 | **(a)** 起步，后续按需加 |
| Q6 | B10 若复现"内容确实相同" | (a) 仍算 bug 并修；(b) 只在回执标注 | **(b)**：内容寻址本身正确，缺的是元数据 |

### 11.1 M2 交付回填（2026-10-27 夜间收口，接口形态以交付为准）

M2 已按「批A / 批B」两批交付并通过整仓门禁（批A `820eeb1b9`、批B `61a54ae85`，全量 11689 passed）。以下三条是**落地形态与本文初稿的差异**，以本表为准：

| 项 | 本文初稿 | 实际交付 | 理由 |
|---|---|---|---|
| B7 wait 负条件 | `state=absent` | **`kind=object_absent`** + `settle_ms`（默认 300，50–10000）；回执 `predicate_result.state=absent/present` | 扁平 wait 语法以 `kind` 作判别式（B6 `download_state` 先例）；在 `object_state` 里加第二 state 会破坏既有以 kind 为键的分支索引 |
| B9 页面清单 | 预期需要 `Target.getTargets` | **复用既有 `/json/list` 只读通道**（`action=pages`），`_ALLOWED` **零增量**，传 `target_id` 即拒 | 通道更窄：无 CDP 方法、无新会话 |
| B15 后备键 | 顺序未定键形 | `title → 可见文本 → placeholder → alt → {kind}#ordinal`（ordinal 数该 kind 全部对象）；标注落 `attributes.fallback_stable_within`，**排除出 content_sha256** | 若进哈希，"同世界两次捕获哈希相等"合同会被逐次变动的标注打破 |

**B8 帧标识**：按 F27 复用 `frame_token`，全仓无并行 `frame_id`（已 grep 核验，`frame_id` 仅存在于 feishu 无关模块）。

**M2 之后未做的事**：live 行为未验证（F28 生产运行时仍是 M1 前形态）；M3/M4 未启动（Q1 仍为 (a)）。

### 11.2 M3 交付回填（2026-10-28 收口，接口形态以交付为准）

M3 按「一个工具 + 一层封装」交付只读感知（`desktop_perceive`：`status` / `apps` / `windows` / `snapshot`），未引入宿主进程、未引入三方依赖（ctypes + `lsappinfo` / `screencapture` 子进程）。以下为与初稿的差异：

| 项 | 本文初稿 | 实际交付 | 理由 |
|---|---|---|---|
| 自检入口 | 独立 `ax_status` | **`action=status`**（同一工具） | 一个工具一个命名空间；自检是每次调用前的动作，不是并列能力 |
| 能力真值 | 以 `AXIsProcessTrusted()` 判 AX 可用 | **实测探针**：对前台 pid 读 `AXWindows`，`err==0` 即可用；授权位仅作最后回退 | 该 API 实测**假阴性**：同一进程内 4/4 次 `trusted=false` 而 `ax_snapshot` 返回 `available=true`/22 节点。用授权位判能力会把可用能力报成不可用，并把用户赶去授权 |
| 窗口标题 | 未定义缺权限时的形态 | 无屏幕录制时 `title: null, title_available: false` | `kCGWindowName` 在缺权限时为空串，拿 app 名冒充标题等于编数据 |
| 隐私名单 | D8 只说「默认拒绝」 | 核心名单**硬编码**（1password/bitwarden/lastpass/dashlane/keychain/SecurityAgent/Passwords/loginwindow）+ 配置**只能追加**；`see_allowlist` 默认空=全允许，非空时非名单 app → `app_not_allowed`（优先级低于 `privacy_blocked`） | 配置可删核心项等于把隐私默认值交给环境变量 |
| 分级失败 | 未细化 | `snapshot` 允许部分成功：L0 拿到即 `ok=true`，AX 缺失记 `degraded`；仅 `vision=evidence` 且截图不可用时 `ok=false, error_code=capture_unavailable` | 缺 L1 不该让 L0 一起失败 |
| 截图前置 | 未写死 | `CGPreflightScreenCaptureAccess()` 为 false 时**直接拒绝，不调 `screencapture`** | 缺权限时 `screencapture` 报 `could not create image from display` 或静默黑图，事后无法与真图区分 |
| 坐标 | 点/像素双单位 | `bounds_pt` + `width/height/scale`；`abs(w - bounds_pt.w*scale) > 2px` 记 `capture_size_mismatch` 入 `degraded` | 混 DPI 时静默错位比报错更贵 |

**M3 权限现状（2026-10-28 08:0x 补验后）**：屏幕录制已授予运行时解释器，**L2 截图 live 通过**——工具层 `snapshot vision=evidence` 产出 3024×1754 px PNG，与 `bounds 1512×877 pt × scale 2.0` 偏差 **0 px**，`degraded=[]`；`windows` 标题可读 **30/31**。AX 按 app 实测：系统设置 10 节点、终端 9–13 节点可读，**Chrome 0 节点 + `ax_window_unbound`**（Chromium 惰性建树，M4 需先解决 AX 激活，否则只能坐标点击）。显示器 1512×982 pt → 全屏 3024×1964 px。恢复步骤与判据见 `20261027-desktop-permission-runbook.md`，证据见 M3 报告 §12.6。

> **2026-10-28 09:39 追加（口径纠正）**：原文把「Chrome 0 节点」读成单一原因，实测有**两个不同原因**，别混。
> ① **Chrome 本身**：`AXWindows` 直接返回 `-25211`（`kAXErrorAPIDisabled`，Chromium 惰性建树、accessibility 未激活）——**原判断成立**，M4 要用 Chrome 的 AX 树仍需解决激活（例如以 `--force-renderer-accessibility` 启动）。
> ② **普通 App 的"未命中"**：活动监视器窗口的 CG bounds 与 AX bounds 逐字段相等，仅标题不同（CG `活动监视器` / AX `活动监视器 – 所有进程`），旧规则要求标题完全相等 ⇒ 判成 `ax_window_unbound`。这是**匹配规则 bug，与授权/激活无关**，已修（§D4）。
> ③ 对照：MCP Console（两侧标题一致）在**同一个服务进程**里直接返回 6 节点 ⇒ "服务进程没有辅助功能授权"这个前提不成立。
> 修法与验证见 `20261028-live-smoke-b3-b5-b7-dialog-and-ax-binding.md` §5（新进程 E2E：`binding=title_relaxed`、17 节点）。

**M3 未做的事**：`hydrate` / `wait` / `desktop_operate`（AXPress、键入、滚动、坐标点击）均属 M4；live 端到端（生产运行时）未验证——当前生产运行时仍是 M1 前工具面。

### 11.3 B5 `dialog` 生命周期判定与修复（TASK-009，2026-10-28）

**判定结论（A 级，判定实验）**：Chrome/CDP 的 dialog 能力**完好**（8/8 主矩阵 + 9 组生命周期对照），缺陷全部在我方会话生命周期。上一轮"根因未定，(a) 延迟显示 / (b) 被抑制"两个候选**均被否定**——那是在 `_drop_session()` 之后才取证，取证对象已自毁。

| 判定项 | 结果 | 证据 |
|---|---|---|
| Chrome 能否开 alert/confirm/prompt | 能（8/8） | `Page.javascriptDialogOpening` 0.05–0.08s 到达，`handleJavaScriptDialog` 全部成功 |
| 是否依赖前台/可见/用户手势 | 不依赖 | 后台标签、`hasFocus=false`、`userActivation.hasBeenActive=false` 同样成功 |
| `Runtime` 已挂死时能否 handle | 能 | 同连接 `Runtime.evaluate` 挂死，`handle` 仍成功，页面 31ms 后继续 |
| 超时本身是否致命 | 不致命 | 模拟 2s 超时但不断连 → 随后 handle 成功 |
| **drop session 是否致命** | **致命且不可逆** | 断连重连后 `No dialog is showing`，renderer 仍阻塞，真 Enter 也救不回 |
| 多连接断一条是否丢 dialog | 不丢 | 两条连接断任一条，幸存连接 handle 成功（3/3） |

**代码根因（三处叠加）**

| # | 位置 | 缺陷 |
|---|---|---|
| C1 | `cdp_host.py:55` `_CONNECTION_LOST_ERRORS` 含 `OSError`；`capture()` / `dispatch()` / `settle()` 的 except 无条件 `_drop_session()` | recv 超时抛 `TimeoutError`（`OSError` 子类）⇒ 被当成连接丢失 ⇒ 断掉唯一能救 dialog 的连接。`_classify_connection_loss` 已把 `timeout` 单独分类，调用方分类完照样 drop |
| C2 | `cdp_action_host.py` click 走 `Runtime.callFunctionOn('this.click()')` | alert 同步模态占住 renderer ⇒ 该响应永不产生 ⇒ 5s 超时 ⇒ 触发 C1 |
| C3 | `_dialog_open` 只在 drain 收到事件时置真，drain 在 dispatch 尾部 | dispatch 已卡死，那次 drain 永不执行 ⇒ dialog 动词永久 `dialog_not_open`，无自愈路径 |

**完整失败链**：click → Runtime 挂起 → 5s 超时判丢连 → drop mutation 连接 → capture 撞模态 20s 超时 → drop observation 连接 → 两条连接都没了 → dialog 失去控制且该标签页对 CDP 与键盘永久失联（只能关）。`capture_channel_degraded[mode=timeout]` 只是第 3 步的**表象**，不是原因。

**修复规格与状态**

| 项 | 内容 | 优先级 | 状态 |
|---|---|---|---|
| R1 | 超时不再 drop：仅 `frame_too_large` / `connection` 才 drop | 必须 | **已完成**（commit `919b9881f`） |
| R2 | click 等待改「事件优先」：recv 循环收到 `javascriptDialogOpening` 即提前返回，回执 `acknowledged` + `dialog_opened`，不等 Runtime 响应；工具层 post-capture 跳过并标注 `post_capture.skipped=dialog_open` | 必须 | **已完成**（同上） |
| R3 | dialog 门禁自愈：状态未知时先 drain 一次，仍无则允许盲发一次 handle，`No dialog is showing` 如实映射 `dialog_not_open` | 应做 | **已完成**（同上） |
| R4 | click 改真实鼠标 `Input.dispatchMouseEvent`，彻底不依赖 renderer 响应；代价是失去 `this.click()` 对 `display:none`/未布局元素的触发能力（对外语义变更） | 可选 | **待用户裁决**，本轮不做 |

**验收口径（缺一不可）**：① 单测：超时后 `_session` 仍非 None、`frame_too_large`/真断连仍 drop、提前返回置 `_dialog_open`、`dialog_not_open` 兜底只发一条命令；② live 正例：产品工具路径 `click` 弹 alert → `acknowledged + dialog_opened` → `dialog accept` 成功 → 页面恢复（`__t1` 可读）→ 同 target 后续 capture 正常、无 `capture_channel_degraded`；③ live 负例：无 dialog 页面 `dialog accept` 返 `dialog_not_open` 且 target 后续 capture 正常。

**实施结果（2026-10-28，TASK-011）**

| 验证 | 回执 |
|---|---|
| 单测 | 新增 18 条（R1 保活 3 / R1 真断连仍 drop 5 / R2 3 / R3 3 / R2 端到端 4）+ M2-A 用例有意更新 2 条；browser 全量 **720 passed, 0 failed** |
| live 正例 A（click 弹 alert） | click `0.03s` 返回 `acknowledged + dialog_opened`，`post_capture.skipped=dialog_open`；accept 后 `__t0=50 / __t1=40125` 证明页面恢复；同 target 裸 capture 正常、无 degraded。**修复前**：5s 超时 → drop → 20s capture 超时 → 二次 drop → 标签页永久失联 |
| live 正例 B（页面自弹 alert，从未观测到 opening） | `dialog accept` 经 R3 自愈成功（非 `dialog_not_open`），页面恢复 |
| live 负例 C（无 dialog） | `dialog_not_open`（错误码不变），同 target 随后 snapshot/capture 正常，两 session 存活 |
| 主机独立复跑 | 干净进程复跑同一 harness：A/B/C 三流全 PASS（需 host-owned `LFL_BROWSER_ALLOWED_HOSTS=127.0.0.1`，否则 `navigate` 按设计被 SSRF 守卫拦为 `ip_blocked`） |

**有意语义变更（已在报告与测试内双重记录）**：M2-A 的「未开 dialog 时零 CDP」保证取消——`dialog_not_open` 路径现会先探一次 `Page.handleJavaScriptDialog`。理由：页面自主弹窗在旧语义下无任何恢复路径；无 dialog 时 Chrome 回 `No dialog is showing`，页面侧零副作用。

**遗留（未修，按证据记录）**
- **R5（性能）**：已实施，见 §11.4。
- **grounding 回退是跨页面状态**：冻结页走「会话最新持久 world」回退（B' 用例里是 `about:blank` 的 world）。light-mode 前置比对声明版本、actuator 恒定绑定精确 target，语义安全，但属 light-mode 语义延伸，M2 文档需标注。
- **compact 回执不携带拒绝原因**：`navigate` 被 SSRF 守卫拦时 compact 只显示 `action_receipt_status:rejected`，原因（`ip_blocked`）只在 full receipt 的 `completeness.reasons` 里——诊断成本高，建议后续把 `completeness.reasons` 上浮到 compact。

### 11.4 R5 dialog 快路径（2026-10-28，commit `4d63a3b85`）

**做法**：不缩短 `capture()` 的 20s 超时（那会掩盖真实捕获故障），只在「已知 dialog 打开」时前置短路，把事件事实直接回给调用方。

| 层 | 改动 | 位置 |
|---|---|---|
| 观察面 | 新增只读 `dialog_state()`（schema `smc.browser_dialog_state.v0.1`），复用 `_dialog_open`/`_dialog_detail`；message 只回当前调用、不落盘 | `cdp_action_host.py` |
| perceive | snapshot / vision 在首次 capture 前探测；open 时返 `observation_status=blocked_by_dialog` + `objects=[]` + dialog 类型/文案，**零 capture** | `browser_perceive.py` |
| operate 定位 | `_ground_page` 探测 open 时直接用会话最新 world ref；无既有 world 则快速抛 `dialog_open_no_prior_world` | `browser_semantic_operation.py` |
| adapter 前置 | `verb=dialog` 且 open 时跳过注定失败的 capture，直接 light-mode + 声明版本比对 | `action.py` |
| 接线 | 三处探针均注入 `_browser_actuator.dialog_state`（perception-only 模式不挂） | `factory.py` |

**实测（真实 Chrome 9229，主机独立复跑同一 harness）**

| 验证 | 回执 |
|---|---|
| 单测 | 新增 19 条全通过；browser 面 **976 passed, 84 skipped, 0 failed**（17.7s，主机复跑同数字） |
| 接线 | perceive / operate / adapter 三处探针均为 True（独立 boot_check 读取） |
| dialog 打开时 snapshot | **55ms** → `blocked_by_dialog`、`objects=[]`、`degraded=false`、`dialog={type:alert,message:r5-alert}`（修复前 20s `capture_channel_degraded`） |
| `do=dialog accept` | **140–150ms** → `completed`；随后 snapshot **73ms / 16 objects** 恢复（修复前全链 40.2s） |
| click 弹 alert | 52ms；`boundary_events=[Page.javascriptDialogOpening]`，工具层按既有语义 `halted / undeclared_structural_transition` |

**R5 边界（不得当成已覆盖）**：若 dialog 打开时 mutation 会话**已不存在**（重启后/被回收），`_dialog_open` 无从得知——实测此时 `Page.enable` 会阻塞 3s+，没有廉价探测通道，该路径仍走原 20s 超时。R5 只加速「已知 dialog」，不改变 `capture()` 的 20s 兜底。

**为什么不用「短超时探测渲染进程是否卡住」**：会把慢页面误判成冻结页，等于用猜测替换观察；且 perceive 的 `blocked_by_dialog` 是事实断言，不能由超时推断。

**未覆盖（不得当成已验证）**：`iframe` 内 alert、`beforeunload`、头条号真实 `confirm` 流、多标签并发 dialog。

**取证教训**：先 drop、后取证 = 取证对象已自毁。判"框架 API 是否支持"必须先以**最小自建客户端**建基线，再用产品路径对比；顺序反了拿到的是被污染的证据。判定细节见 `20261028-task009-dialog-verdict.md`。

### 11.5 M1 门禁重构（R5 合入前，2026-10-28，commit `ac8d5e018`）

R5 首次提交被 M1 门禁打回：新增代码把 4 个函数顶过 ratchet 登记值。**没有放宽阈值**，改为在 §7.1 已定的落点内抽 helper。

| 函数 | 门禁值 | R5 首版 | 重构后 | 抽出的东西 |
|---|---|---|---|---|
| `factory.build_engine` | ≤ 2151 | 2154 | **2151** | `_attach_dialog_probes`（三处探针接线的单点） |
| `browser_perceive.execute` | ≤ 371 | 377 | **350** | `_accept_legacy_wait_aliases`（url/object_ref 历史别名归一，原为两段内联兼容块） |
| `cdp_action_host._dispatch_locked` | < 120 | 148 | **113** | `_blind_dialog_self_heal`、`_dispatch_dialog` |
| `action.execute` | ≤ 393 | 475 | **388** | `_observe_before_dispatch` + `_BeforeObservation`（FR-1 门 + capture/light-mode 证据） |

**测量口径**：`ast` 的 `end_lineno - lineno + 1`（与门禁同一口径），未用 cloc/tokei（会把 docstring 按显示行计，口径不一致）。

**一处行为修正（不是纯搬运）**：全部观察通道失败时的兜底分支原先只在 `else` 里给 `before_raw` 赋值，异常路径上该名字未绑定；接线 review authorizer 时会在极窄路径抛 `UnboundLocalError`。重构后恒初始化为 `{}`，把「崩溃」变成「可审计的拒绝/降级」。这是唯一与"零行为变更"不同的点，已在 commit message 记录。

**验证**：`tests/unit -k "smx or m2a or dialog or perceive or semantic or browser"` = **1196 passed, 0 failed**（主机复跑）；R5 新增 19 条全通过。

### 11.6 live 实测回执（2026-10-29，generation 335 / `26e6f831`）

**口径**：本节是**实测**，不是单元测试复跑结论。被测算子 = 当前会话 agent 实际调用的 `browser_operate`/`browser_perceive`（其快照已暴露 `frame_token`/`fallback_key`，即 P1 代码在跑）；自建测试页 `~/lfl-workspace/browser-selftest/{t2,t3}.html`，测试标签页经 CDP `/json/new` 打开、绑定后取证，事后已 `/json/close` 关闭，未触碰用户既有 4 个标签页。

| 项 | 验收口径（§2） | 实测动作 | 结果 |
|---|---|---|---|
| B3 | Enter 提交成功 | t3：点输入框 → `type abc` → `press_key Enter` | **PASS**：`document_generation_changed`，随后 `pages` 显示 URL 变为 `ok.html?q=abc`、title `已提交` |
| B3 | Meta+W / Meta+Q 契约拒绝 | `press_key Meta+W` | **PASS**：`reason=key_not_allowed`，零 CDP 派发 |
| B5 | 有对话框可解除 | t2：点 `confirm` 触发器 → `do=dialog accept` | **PASS**：click 回执 `halt_reason=dialog_opened`；accept 回执 `status=completed`，`diff changed` |
| B8 | 主帧/子帧同名按钮可分别寻址 | t3 主帧+子帧各一个「同名按钮」 | **PASS**：`frame_token=null` → 主帧 `match_count=1` completed；`frame_token=frame:AD33…` → 子帧 `match_count=1` completed |
| B8 | 未指定 frame 且跨帧重名 → 确定性歧义拒绝 | 省略 `frame_token` 点「同名按钮」 | **PASS（带一个可用性缺陷，见下）**：`halt_reason=ambiguous_target`，`match_count=2` |
| B9 | 健康状态下列清单、不改变绑定 | 绑定 t3 后调 `pages`，紧接着不传 `target_id` 直接点主帧按钮 | **PASS**：`read_only=true`、`bound=true`、`world_version` 不变；后续点击仍命中 t3。另 `pages` 携带 `target_id` 被 `fields_mismatch` 拒绝（只读清单不接受换绑字段） |
| B15 | 无名按钮可用后备键寻址 | t3 点 `fallback="输入后回车提交"`(input)、`"button#4"`(无名 button) | **PASS**：均 completed |
| B15 | 跨 `world_version` 失效须标注 | 表单提交跳转后，用旧 `bsnap-809-2318127d9d43a897` 的 `button#4` 再点 | **PASS**：`fallback_addressing.status=stale` + 要求重新取快照，**未**盲重试 |

**两处实测暴露的缺口（都不阻塞上述 PASS，已定位不改）**

1. **B8 歧义回执的候选窗口不按"命中优先"排**：`match_count=2`，但 `candidates` 共 28 条、只回前 20（`max_projection=20`），子帧那个「同名按钮」落在窗口外；窗口内两条同名候选 `frame_token` 分别是缺失与 `null`。结果是回执告诉调用方"请指定 frame_token"，却不给能用于区分的目标。属 P2 可用性缺陷（§2 B8 只要求"确定性拒绝"，未要求候选可用）。
2. **`navigate` 的拒绝不带原因**：对 `file://…/t2.html` 与 `http://127.0.0.1:8931/t2.html` 两次导航，均 `halt_reason=action_receipt_status:rejected`、`steps_executed=1`，且事后 `pages` 显示 URL 未变（未发生导航）。`check_url` 默认拒绝 loopback、另有 `navigate_url_scheme_rejected`，所以**很可能**是策略拒绝，但回执未给 `reasons`（`browser_semantic_operation.py:2058` 只投影 receipt 汇总状态）。定论需要属主流补一声，我不按"宿主重分析"处理。

**B15 一条口径澄清（非缺陷）**：`fallback` 的版本护栏按 `browser_semantic_operation.py:553` 注释实现——**只有"解析成功但版本护栏失败"才标 `stale`**。因此早前观察到"用旧版本 `fallback_key` 在新 world 版本上仍命中"是 as-built 行为，不是与本条不一致。

**门禁状态（同批次）**：`ci_gate` **328 通过 / 1 失败**，唯一红项 `test_kernel_import_edges_match_frozen_baseline`：`未登记新增 edge: runtime->introspection`。主机独立复跑 `tests/unit/test_arch_guards.py` = **39 passed, 1 failed**，红项一致；`git log -S` 定位该 import 由 **`4e109a468`（doctor/rules 流）**引入，`26e6f831` 的 `doctor.py` 无此 import ⇒ **非浏览器补强引入**。且护栏用 `ast.walk`（含函数内局部 import），**"函数内延迟 import"绕不过**；`test_kernel_import_edges_baseline_only_decreases` 又禁同提交登记基线 ⇒ 属主流只有两条路：runtime 侧定义 Protocol/callable 由组合根注入，或把 `doctor.py` 移出 runtime 平面。**当前部署未含该提交**（gen 335 = `26e6f831`），故 1 红不阻塞 live；但 `HEAD=4e109a468` 已越出部署版本，下次发布前必须先清。

---

### 11.7 复验与 `navigate` 拒绝原因深挖（2026-10-29，generation 337 / `7ca66e86`）

**A. 门禁红项已清（实测，替换 §11.6 门禁段的口径）**

- 本机复跑 `tests/unit/test_arch_guards.py` = **40 passed**（§11.6 记录时为 39 passed / 1 failed），红项 `test_kernel_import_edges_match_frozen_baseline` 已消失。
- 修复提交 `6f19699ca`（"规则卡深度探测依赖倒置——runtime 不再依赖 introspection"）经 `git merge-base --is-ancestor 6f19699ca 7ca66e86` 确认**已在部署版本内**；`service_control status`：stable gen 337、`matches_desired_generation=true`、`succeeded_at=2026-10-29T08:43:53+08:00`、`admission_barriers=[]`、`restart_required=false`。
- 走的是 §11.6 预判的两条路之一：**runtime 侧定义注入点、由 cli 应用壳组装注入**（`doctor.py` 改为由调用方注入探测函数），不是把 `doctor.py` 移出 runtime 平面。
- 遗留（不影响本次验收）：`HEAD=67704b794` 仍领先部署 `7ca66e86`，其间另有两个其他流的提交（`0b6138833`、`67704b794`）；下次发布前须单独确认这两个提交不带红项。

**B. 失败动作屏障（复验）**

- 现状：`terminal_action_barrier=null`、`admission_barriers=[]`、`reasons=[]`，由 gen 337 的成功动作 `svc-8c600b42…` 接替。
- **未核实的部分（如实标注）**：旧失败动作 `svc-9c38605a…` 的**显式结项记录**——我只有截断 id，`data/` 内 jsonl/json 按该片段检索无命中，拿不到完整 32 位 id。因此本节只确认"它不再形成屏障"，**不**确认"已被登记关闭"。

**C. `navigate` 拒绝原因：不是丢数据，是少一跳（已定性）**

§11.6 缺口 2 的"很可能"在此作废。五段链路逐段实测/读码如下：

| 段 | 事实 | 依据 |
|---|---|---|
| 1 生产者 | 拒绝码 `navigate_host_blocked:ip_blocked:127.0.0.1（私网）`，出自 `net_guard.check_url` 单一事实源 | `browser/action.py:737-756`；`net_guard.py:173,205-228` |
| 2 落 receipt | 该串写入 `completeness.reasons[0]` 与 `retry.reason`，`status=rejected` | live hydrate 回执（下） |
| 3 汇总 | `halt_reason = action_receipt_status:rejected`——只投影状态，不带原因 | `browser_semantic_operation.py:2056-2059` |
| 4 紧凑投影 | 透出 `receipt_ref`/`world_version`/`diff`/`boundary_events`/`match_count`/`candidates`/`fallback_addressing`；**不**透出 `completeness.reasons` 与 `retry.reason` | `_compact_projection` `:1834-1950` |
| 5 可回取 | `browser_perceive hydrate` 接受 `browser-operation-receipt://v0.1/…`，返回完整 receipt（含 reasons） | `factory.py:1471` 注入 `receipt_store.hydrate`；**live 复现** |

**live 复现（2026-10-29）**：新建 `about:blank` 标签 → 显式 `target_id` 绑定 → `navigate http://127.0.0.1:8931/t2.html` → 紧凑回执 `{"status":"halted","halt_reason":"action_receipt_status:rejected","steps_executed":1,"receipt_ref":"browser-operation-receipt://v0.1/a5d57f4e…"}`；随后 `browser_perceive hydrate` 该 `receipt_ref`，得 `completeness.reasons=["navigate_host_blocked:ip_blocked:127.0.0.1（私网）"]`、`retry.reason` 同串、`after_version=null`。测试标签已 `/json/close`，CDP 页面清单回到用户既有 5 个。

**结论（P2，不阻塞）**：原因**可观测但不可发现**。`receipt_ref` 明明在模型可见回执里，但全仓 `receipt_ref` 只出现在生产者模块内部，没有任何模型可见 schema/描述说过"halted 时可 hydrate 它取原因"——所以调用方只能看到 `rejected`，分不清是 scheme/loopback/重复 action_id/版本前置条件中的哪一种。

**建议（供属主流裁决，本轮不改码）**

1. **首选、最小改动**：`_compact_projection` 在 `status=halted` 且末 clause 的 `action_receipt.status != "ok"` 时，新增 `rejection_reason` 字段（取 `completeness.reasons[0] or retry.reason`，截断 200 字符）。**不动 `halt_reason` 词表**——`action_receipt_status:*` 已被现有用例与消费者钉住，就地扩写会破兼容。
2. 备选：在 `browser_operate` 的工具描述里补一句"halted 且带 `receipt_ref` 时，可 `browser_perceive hydrate` 该 ref 取完整原因"，把这一跳变可发现（属工具面文案，须与 Schema 真值源同步改）。
3. **不成立的"缺陷"**：`（私网）` 这类中文标签不是问题——`classify_ip` 按命中类别返回 `<ip>（类别）`，与 `web_fetch` 旧行为对齐，且被 `tests/test_net_guard.py:115`、`tests/test_browser_site_policy.py:64` 等用例钉住，属 as-designed。

---

### 11.8 10-28～10-30 四笔修复回填与部署后 live 复验（2026-10-31）

**A. 四笔修复的提交与真实日期（订正交接书口径）**

| 提交 | 内容 | 真实日期 | in-deployed（`b008c9fae`） |
|---|---|---|---|
| `4d63a3b85` | R5 dialog 快路径（消除 20s 捕获超时） | 2026-10-28 13:30 | ✅ |
| `919b9881f` | B5 dialog 生命周期三缺陷修复 | 2026-10-28 12:25 | ✅ |
| `55aff5b73` | `type` 上限移出 schema + D4 绑定降级标注 `title_relaxed` | 2026-10-28 11:17 | ✅ |
| `4d7dc24ef` | 紧凑回执被拒整类提升 `reject_reason` + 候选窗口补 `frame_token` | 2026-10-30 19:34 | ✅ |

> 交接书 §2 / §8 原写「10-30/31 的四笔修复」——只有 `4d7dc24ef` 出自 10-30，其余三笔出自 10-28。逐个 `git merge-base --is-ancestor <commit> b008c9fae` 核过，四笔**全部**在部署内（含 `919b9881f`）。

**B. §11.7 的 P2 建议已落地，但与建议稿有四处差异（按落地为准）**

- 字段名是 **`reject_reason`**（不是建议稿写的 `rejection_reason`）。
- 取值来源是**拒绝码单一真值源**（`browser/action.py` / `net_guard.py`），不是自由文本。
- 触发条件：动作被拒时把原因从「只投影状态」提升为可发现。
- **不做 200 字符截断**（建议稿里的截断建议未采纳）。
- 附带：候选窗口同时补齐 `frame_token`（B8 帧归属）。

**C. TASK-010 部署后 live 复验（A 级实测；部署 `b008c9fae` / stable gen 349，`matches_desired_generation=true`，`admission_barriers=[]`）**

| # | 验收项 | 实测结果 | 判定 |
|---|---|---|---|
| 1 | `type` 超过上限 | 送 2222 字符 → `[failure] contract rejected; reason=type_text_too_long`；本会话工具 schema 中 `type.text` **无 `maxLength`**，而 `press_key.keys` 仍为 `maxLength=32`（限制机制仍在，仅 type 不再声明） | PASS |
| 2 | D4 降级绑定 | 活动监视器（window_id 89051；CG 标题 `活动监视器` / AX 根标题 `活动监视器 – 所有进程`）→ `binding=title_relaxed`、`degraded=["ax_title_relaxed"]`、33 节点、`clipped_depth=false` | PASS |
| 3 | 标题一致对照组 | 微信（window_id 120905；CG / AX 根标题均为 `微信`）→ `binding=title_exact`、`degraded=[]`、13 节点（D4 未误降级） | PASS |
| 4 | 无副作用 | 被拒后 hydrate 目标 textarea，回执**无** `value_text`（同页文件输入框对照有），元素仍为空 | PASS |

上限真值源：`_TYPE_MAX_TEXT_LENGTH = 2000`（`browser/action.py:60`）；两层拒绝点＝契约层 `browser_semantic_operation.py:426-427` + adapter `browser/action.py:767-768`。

**D. M4 投递通道首轮探针（2026-10-31 15:16–15:19，沙盒内实测）**

M4 于 2026-10-31 15:11 获用户授权。授权前唯一事实是「AXPress 动作名可枚举」（A 级只读）；本轮在**临时 TextEdit 窗口**上补验了真实投递：

| # | 探针 | 结果 | 判定 |
|---|---|---|---|
| 1 | **AXPress 真实投递**：对原生 `AXCloseButton` 执行 `AXPress` | err=0，窗口数 `1 → 0`，动作确实生效 | **PROVEN** |
| 2 | **AX 键入投递**：`AXSetAttributeValue(kAXValue)` 写文档 AXTextArea | 写入串回读完全一致 | **PROVEN** |
| 3 | **CGEvent 键入通道** | 键事件送达，但输出被**输入法污染**：本机输入源为 `com.apple.inputmethod.SCIM`（拼音 ABC），`a s d` 被拆成「a␣s␣d」；带 shift 的大写不受影响；纯 unicode 事件（keycode=0）无输出 | **通道通，输出有缺陷** |
| 4 | **Chrome AX 激活**：独立 `--force-renderer-accessibility` + 独立 `--user-data-dir` | 本沙盒内**起不来**：`Failed to create a socket directory` → `Failed to create a ProcessSingleton` → 主动 abort（profile 锁目录不可创建） | **受阻** |
| 5 | 现存服务 Chrome 能否到网页层 | 服务 Chrome（pid 96579）主窗口 33 节点但 **AXWebArea=0 / AXStaticText=0**；另一实例 AXWindows 直接报错（`-25211`） | **确认不可达** |

**对实现的直接影响**：键入**优先走 AX set-value**（已验证可靠），CGEvent 仅作兜底且**必须处理 IME**；AXPress 通道可用，M4 的核心风险从「投递不了」转为「三级门控 / 一次性令牌 / 审计怎么设计」。Chrome 网页层要可达，需在沙盒外起带 `--force-renderer-accessibility` 的实例，或给服务 Chrome 加该 flag——属**环境/部署决策**，本轮未动。探针原始日志见 `<MIRROR>/data/deliverables/20261031/20261031-m4-probe-log.md`。

**E. 本节未验证的边界（不得当作已验）**

- `type` 的 **=2000 接受侧**未做 live 测试（会向真实发布表单写入 2000 字符，为不污染发布表单而跳过）；阈值以源码常量为准。
- D4 **多命中**时的 `window_ambiguous` 歧义拒绝未重测。
- **M4 动作代码尚未写**：投递通道已 PROVEN，但三级门控 / 一次性令牌 / 审计三件套尚未设计落地。
- **Chrome 网页层 AX 仍不可达**（`-25211` 未变，`AXWebArea` 未验证）；M4 在该问题裁定前只能覆盖原生 app，不能覆盖浏览器网页目标。
- **CGEvent 键入在中文输入法下输出被污染**：兜底路径未处理 IME 前，不得声称「CGEvent 键入可用」。





### 11.9 M4 `desktop_operate` 落地、审核结论与未验证边界（2026-10-31 16:05–20:1x）

> 本节覆盖两处**过期口径**：§5.6 表中「`desktop_operate`（§5.4）**仍未实现**」，以及 §11.8 D/E 段里「M4 动作代码尚未写」。以本节为准。

**A. 用户裁决（路线 A，2026-10-31 16:05）**

Chrome 网页层改走**既有 CDP 通道**（`browser_operate` 已有 DOM+AX sensor），M4 的 macOS AX **只服务原生 app（Finder/Preview/TextEdit）+ Chrome 窗口 chrome 级动作**；不新增 CDP 通道、不改部署、不需用户在场。依据：既有 CDP 9229 实例 12 个 page target 全部 `Accessibility.enable` 成功、`getFullAXTree` 出 8463 节点网页层；而 macOS AX 侧 Chrome 始终只到窗口级（`AXWebArea` 缺失 / `-25211`），沙盒内无法激活（沙盒禁 unix domain socket → Chrome `ProcessSingleton` abort；`open -na` 静默丢弃、不派生子进程）。

**B. 交付物与位置**

| 项 | 值 |
|---|---|
| 分支 / 提交 | `feat/m4-desktop-operate-20261031` @ `6613b0c5a`（父 `66f093dfe`，基线 `55b53ab81`） |
| 工作区 | `<MIRROR>/.worktrees/m4-desktop-operate-20261031`（隔离 worktree；未动主工作树，未碰活跃写者文件） |
| 新增 | `desktop/{operate.py,hid_idle.py,macos_actuate.py}`、`tools/builtin/desktop_operate.py`、`tests/unit/test_desktop_operate_m4_v01.py` |
| 修改 | `config.py`、`factory.py`、`tools/registry.py`、`desktop/backend_macos.py`、`desktop/models.py` |
| 部署 | **未上线**（部署仍 `b008c9fae`；本线不发 restart——另一条线有 in-flight 未提交工作） |
| 开发报告 | `<MIRROR>/data/deliverables/20261031/20261031-m4-dev-report.md` |

**C. as-built 工具契约（与 §5.4 的差异逐条登记）**

| 项 | §5.4 草案 | as-built |
|---|---|---|
| do | click/type/press_key/scroll | 同（闭合键集，未扩展） |
| args 键集 | window_id / target / text / keys / dry_run / confirm_token / force | **多第 8 键 `force_credential`**（承载用户预置的一次性 force 凭据；§5.4 闭合键集之外的偏离，已登记） |
| window_id | string | **integer** |
| target | {ax_ref} 或 {point:{x,y}} | 同；`press_key` **可省略** target（作用于绑定窗口当前焦点）；`type` **只接受 ax_ref** |
| scroll 方向 | 未定义 | 复用 `keys` 字段（`":down"` 等） |
| type 语义 | 未定义 | **整体替换**（非追加） |
| action_id / world_version | 设计定义 | 实现改为稳定寻址 + world 指纹（窗口身份 / 前台归属 / 目标身份 / AX 节点行；value 不入 pre 指纹） |

**D. 门控与安全设计（as-built，R6 后）**

| 机制 | as-built 行为 |
|---|---|
| 写开关 | **默认关**：`LFL_DESKTOP_OPERATE_ENABLED=1` 才允许真实投递；dry_run 与只读探测不受限（T8） |
| 首次 dry_run | act 类动作首次必须 dry_run；同 app 同 do 在 session 内放行 |
| 一次性令牌 | irreversible 永远单步 + `confirm_token`（绑定 action_id + world_version）；**任何兑换尝试都会烧毁已知令牌**（重放即拒） |
| point 通道 | **每次 apply 都要新令牌**，不享受 session 免令牌 |
| session 免令牌记账 | R6 起按 **(app, do, 目标身份)** 记账：换目标必须重新要令牌；免令牌路径**跳过 world 指纹比对**（设计 §6.2 字面允许），已显式披露为残余风险 |
| 关闭按钮 | 真机编码 `AXRole=AXButton` + `AXSubrole=AXCloseButton` → 判为 **irreversible**，且**永不享受 session 免令牌**（R6 修） |
| 用户在场 | HID idle < 60s → `user_present` 拒绝；force 需一次性凭据（env `LFL_DESKTOP_FORCE_CREDENTIAL`，宿主无桌面审批通道 → 缺口如实登记） |
| 前台判据 | R5 起：**前台 app**（`lsappinfo front` + ASN 匹配）必须等于目标窗口所属 app；取不到即 fail-closed 拒绝。旧口径「CG 序第一个 layer-0 窗口」已废弃（CG 序 ≠ app 焦点） |
| 路线 A 边界 | ax_ref / point / scroll / press_key 四通道：命中 AXWebArea 网页内容层 → `web_target_not_allowed` → browser_operate；**无法证明在网页区外时按拒绝处理**（fail-closed） |
| 发布/提交/支付类 | **fail-closed 拒绝**（`review_required`）：本工具 token 不放行发布类动作（宿主 `review_admission` 当前只接 `execute_command`，接入桌面发布动作列为后续项） |
| EXEC_MODE | `blocked` / `readonly` / `allowlist` 不含本工具 → `exec_mode_blocked` 拒绝；默认 exec_mode 为空时行为不变 |
| 审计 | append-only JSONL，每个终局一行（含早期拒绝）；`token_id` = sha256 前 16 位十六进制（**不写令牌明文片段**）；force 凭据与键入文本不入审计/回执 |
| 隐私默认值 | 不变：截图默认不读模型、核心敏感名单硬编码不可删、`see_allowlist` 优先级低于 `privacy_blocked` |
| 字母键通道 | **明确不提供**（CGEvent 字母键被中文输入法污染）；闭合键集只含命名键 |

**E. 审核结论与修复轮（截至 R6）**

| 轮次 | 提交 | 宿主审核（RULE-AI-28） | 本轮修的内容 |
|---|---|---|---|
| R0 | `66f093dfe` | REVISE（P0=0 / P1=1 / P2=10） | 初版：点通道越过路线 A 边界、风险误分类、session 放行面过大 |
| R1 | `6613b0c5a` | REVISE（P0=0 / P1=1 / P2=7） | 覆盖上轮必修 + 10 项建议修；本轮 P1：`KEY_KEYCODES` 的 F1–F12 用了推导式 `122+i-1`（真值 F2=120 / F3=99 / F4=118 / F5=96 / F6=97 / F7=98 / F8=100 / F9=101 / F10=109 / F11=103 / F12=111） |
| R2 | `d6dd65115` | REVISE（P0=0 / P1=1 / P2=10，冻结产物 `eacca9c3…`） | F 键表改字面量 + 5 项低成本建议修（门控顺序文档漂移 / cg_post_click 部分失败补偿 / 死状态 key_flags / 令牌 TTL 与淘汰 / world 指纹纳入 focused） |
| R3 | `6969c0e47` | 与 R4+R5 合并准入 | **P0 所有权修复**：`resolve_window_element` 的 finally 释放了它正要返回的元素（`_ref` 置 0）→ 所有 `ax_ref` 投递必然 `window_unbound`；同批修两处所有权泄漏（AXChildren 兄弟节点 retain 泄漏、ax_readable_probe 的 value 泄漏）；补「回退修复则测试变红」自证；新增可复用 live 冒烟脚本 |
| R4+R5 | `d34e49a8f` | REVISE（P0=0 / P1=1 / P2=4，冻结产物 `daf9d927…`） | R4：`_dispatch` 576 行 → 拆成 ≤120 行的分责函数（`load_settings` 391 → 370，护栏棘轮转绿，**未改护栏阈值/基线**）；R5：**前台判据**改为「`lsappinfo front` + ASN 匹配出的前台 app」，取不到即 fail-closed；live 冒烟脚本加锁屏/权限自检与退出码分类 |
| R6 | `4bc6cdec` | **PASS**（冻结产物 `c5ed9bc2…`） | P1：`classify_risk` 只认 `role == "axclosebutton"`，真机是 `AXRole=AXButton` + `AXSubrole=AXCloseButton` → 关闭点击被误判为普通 act 且可走 session 免令牌；改为同时匹配 subrole 且**关闭点击永不免令牌**；session 免令牌记账收紧到 (app, do, **目标身份**)；披露全局 HID 投递残余风险；登记 3 条未验证边界；冒烟脚本改 `mktemp -d` + 异常映射退出码 |

> 父会话在审核之外**自查追加**的三条（审核未覆盖）：审计曾写令牌明文前 12 字符；`desktop_operate` 不在 `registry._is_destructive_tool` 集合 → `EXEC_MODE=readonly` 约束不到桌面真实投递；**R3 的 P0 所有权缺陷**（live 实测暴露，见 §11.9-G）。三条均已修。

**F. 本节未验证的边界（不得当作已验）**

1. **正向投递的 live 证据：已取得**（R6 代码 `4bc6cdec`，真实机器，dry_run → 令牌 → apply applied=true → 目标窗口消失 → 审计落盘，见 §11.9-G 用例 10）。**但只覆盖 `click` + AXCloseButton 一条路径**：`type` 键入、`scroll`、`press_key`、`point` 坐标点击仍无真机投递证据；且复跑需要「解锁 + 用户静默 ≥60s」。
2. `type` 的 **=2000 接受侧**未 live 测；`type` 为**整体替换**语义（会静默覆盖字段原内容，已在工具描述与残余风险显式标注）。
3. `scroll` 方向符号（`CGEventPostToPid`）**从未 live 验证**；CGEventPost 投递**不可观测**（工具无投递确认，只能事后核对世界/窗口状态）。
4. `point` 点击与 `press_key` 走全局 HID tap，world 指纹不含 Z 序/键盘焦点 → 即使目标 app 在前台，覆盖其上的浮层仍可能收到事件（已显式披露为残余风险）。
5. session 免令牌路径**跳过 world 指纹比对**（设计 §6.2 字面允许），换目标即换靶的风险通过「免令牌按 (app, do, 目标身份) 记账」收敛，但结构漂移仍可换靶——已显式披露。
6. Chrome 网页层走既有 CDP（路线 A），**网页内元素的 AX 动作不由本工具提供**；`web_target_not_allowed` 路由到 `browser_operate`。
7. 键入**只走 AX set-value**（已验证可靠）；CGEvent 键入**明确不提供**（中文输入法污染）。
8. 锁屏态、多显示器跨屏 scale、非整数缩放：均未验证（本机单屏 2.0x）。

**G. live 实测（真实机器，2026-10-31 18:05–20:2x）**

本节记录**在用户真实机器上**跑出来的证据，与静态审核结论分开。

| # | 用例 | 实测 | 判定 |
|---|---|---|---|
| 1 | 非白名单 app 的投递尝试 | TextEdit（临时文件，非 act 白名单）→ `do=click` 连续 3 次 → 全部 `error_code=app_not_allowed`，且**每次都写了一条审计行** | PASS（门控按设计生效） |
| 2 | 白名单 app 的正向投递（R2 代码） | Preview 打开临时 PNG → `do=click target={"ax_ref":"1.2"}`（AXCloseButton）→ dry_run **成功**（risk_class=act、签发 confirm_token、pre_sha256=9540e73…、target_identity.role/subrole 正确）→ apply **失败**：`error_code=window_unbound` | **FAIL → 暴露 P0** |
| 3 | P0 定位（只读） | `resolve_window_element` 返回元素的 `_ref = 0`；`ax_read_attr(el.ref,"AXChildren")` → err **-25201**（kAXErrorInvalidUIElement）；role/title 均 None | — |
| 4 | P0 根因 | `macos_actuate.resolve_window_element` 的 `finally` 里 `el.release()` 释放了**它正要返回的那个元素**；`MacAxElement.release()` 会把 `_ref` 置 0 → 交付给调用方的元素已失效 → `resolve_element_by_axref` 必然 `ax_ref_not_found` → 映射为 `window_unbound` ⇒ **M4 的 act-time ax_ref 寻址链路实际从未跑通** | — |
| 5 | 「此前投递已 PROVEN」的口径订正 | 上一会话的 AXPress PROVEN 证据来自**独立临时探针直接调 AX API**，**不经过本工具的寻址路径**；该声称应限定为「macOS AX 通道本身可用」，不能用于「工具可投递」 | — |
| 6 | 假绿成因 | 离线单测用的 fake 元素 release 语义与真包装类不同（不会置 0、不会被 finally 释放）→ `resolve_window_element → resolve_element_by_axref` 这条链在离线测试里「假绿」 | — |
| 7 | 修 P0 后的 live 复跑（R3 代码） | AX 快照恢复正常（24 节点）；dry_run 成功（pre_sha256=b6355eda…、target_identity 正确）；apply 被拒 `error_code=foreground_changed`，`foreground_before=com.apple.Preview`、`foreground_after=null` | **FAIL → 暴露前台判据缺陷** |
| 8 | 前台判据根因 | apply 路径用 `fresh_window.is_foreground` 判「目标是否在前台」，而该标志的定义是 **CGWindowList 顺序里第一个 layer==0 且在屏的窗口**；同一时刻连测三次，CG 序第一个是 **Chrome**（window 121487），Preview 不在前 4 个 → 门控把**合法投递误拒**。同时实测真实前台 app 是 Preview（`lsappinfo front` → ASN `asn:0x0-0xa9a3999` → list 记录 bundle_id=com.apple.Preview）⇒ **CG 窗口序 ≠ app 焦点** | — |
| 9 | R4+R5 代码的 live 复跑 | 屏幕再次自动锁定 → 冒烟脚本按 R5 的新归因报「屏幕已锁定（screen_locked=true）」并以环境不可用退出码退出（不再误判成「需辅助功能授权」）；用 **R2 代码复跑同样失败** → 判定为环境约束，**非回归** | 环境约束 |
| 10 | **R6 代码的正向投递（A 级证据）** | 目标窗口 Preview `lfl-m4-live.png`（window_id 121608）→ 快照 24 节点，关闭钮 `ax_ref=0.2` / role=AXButton / **subrole=AXCloseButton** → 前台 app（lsappinfo 口径）= com.apple.Preview → dry_run `ok=true`、**risk_class=irreversible**、`needs_confirmation=true`、签发 confirm_token、`pre_sha256=c1de2d11…` → apply **`ok=true`、`applied=true`、`error_code=null`**、`foreground_before=after=com.apple.Preview`、`hid_idle_ms=152053`、`post_sha256=55c41f45…`（世界已变）→ 校验「**窗口 121608 已消失: True**」→ 审计行 `applied=true` 落盘 → 脚本 exit 0 | **PASS** |
| 11 | D7 在场门（负例） | 用户在操作机器时（`hid_idle_ms=2454`）apply 被确定性拒绝 `error_code=user_present`；用户静默 ≥60s 后同一路径成功（用例 10） | PASS（门控按设计生效） |
| 12 | 验证口径修正（P2，脚本侧） | 仓内冒烟脚本的「窗口已消失」判定只看 **CGWindowList**，而该列表对**已销毁窗口有残留条目** → 第一次成功投递后脚本误报「已消失: False」并给出误导性的清理提示；事后独立复核（Preview 窗口列表为空）证明窗口**确实已关闭**。改为「CG 列表缺失 **或** AX 侧解析不到该窗口」后，判定稳定为 True | 脚本 P2 |

> 用例 7/8 是本轮最有价值的产出：两次「门控拒绝」都不是误报，而是**判据本身错了**——第一次是所有权缺陷（元素被提前释放），第二次是前台语义错误（拿 CG 序当 app 焦点）。两次都是**静态审核与离线单测无法覆盖**的类型。用例 10 则是 M4 首次取得的**端到端 A 级正向投递证据**（dry_run → 令牌 → 投递 → 世界变化 → 目标窗口消失 → 审计落盘）。

**H. 事实边界（正向证据已取得）**

- **已取得**：R6 代码（`4bc6cdec`）在真实机器上完成一次完整正向投递（用例 10），含 dry_run 风险分级=irreversible、一次性令牌、前台口径校验、世界指纹前后变化、目标窗口消失、审计行落盘。
- **未取得**：网页层目标（路线 A 下由既有 CDP 承担，网页内元素动作不由本工具提供）、`type` 键入、`scroll`、`press_key`、`point` 坐标点击的**正向** live 证据（这些通道只有离线单测与设计约束，无真机投递记录）。
- **环境约束**：屏幕反复自动锁定（`desktop_perceive(status)` → `screen_locked`；`lsappinfo front` → `com.apple.loginwindow`），锁屏下 AX 读取与投递均被拒；live 正向复跑需要「解锁 + 用户静默 ≥60s（否则 D7 在场门会确定性拒绝）」。
- **脚本 P2 待下一轮同步**：仓内 `scripts/desktop_operate_live_smoke.py` 的窗口消失判定需按用例 12 改为 AX 侧兜底（本次在本地副本验证有效，未改动已过门禁的产物）。

**I. 门禁与验收状态（2026-10-31 20:1x）**

| 项 | 结果 |
|---|---|
| 最终提交 | `4bc6cdec`（R6；基线 `55b53ab81`；worktree `<MIRROR>/.worktrees/m4-desktop-operate-20261031`；未合并、未 push） |
| RULE-AI-28 准入 | 第 5 轮 **PASS**（冻结产物 `c5ed9bc2…`）；前 4 轮均 REVISE 并逐条修复后重审 |
| 全量门禁 | `bash scripts/ci_gate.sh` → **exit 0**「✅ ci_gate 全链路通过（ruff + env-pin 声明门禁 + pyright + tier0 预检 + 全量门禁）」；ruff new=0 / pyright new=0 / 护栏两条（`test_function_lines_ratchet_within_baseline`、`test_global_redline_300`）均绿 |
| 父会话独立复验 | ruff PASS(new=0)、pyright PASS(new=0)、护栏 + M4 + M3 单测 **227 passed** |
| 变更规模 | 相对基线 12 文件、+5329 / -30（含 2115 行新单测与 378 行 live 冒烟脚本） |
| 部署 | **未上线**：部署仍 `b008c9fae` / wecom stable gen 349；本线**未发 restart**（另一条线在 `<MIRROR>` 有 in-flight 未提交工作：`write_scope.py` / `sandbox.py` / `command_scope_guard.py` 等） |
| 待用户裁决 | ① M4 上线时机（合并 `4bc6cdec` + 发布，或等其它线收口）；② restart 通道（web 承载会话会停在 `waiting_for_requester_exit`）；③ 仓内冒烟脚本 P2 是否本轮内补 |

### 11.10 M4 合并安全核验（2026-10-31 20:4x）

M4 分支 `4bc6cdec` 与当前 main `511ae9075` 的合并已核验（在独立 scratch 合并树 `/private/tmp/lfl-m4-merge-check` 实测，**不碰 main、不碰 M4 worktree**）：

| 检查 | 口径 | 结果 |
|---|---|---|
| 合并冲突 | `git merge-tree --write-tree main 4bc6cdec` | rc=0，无冲突 |
| Ruff | `ruff check`（M4 的 12 个改动 `.py`） | All checks passed |
| Pyright（权威） | `scripts/check_static_diagnostics.py --tool pyright` | **PASS**：`new=0`、`changed_file_diagnostics=0` |
| pytest | M4 + `test_arch_guards` + `test_write_scope_contract` + `test_command_scope_guard` | **718 passed, 1 failed** |

唯一失败项 `test_function_lines_ratchet_within_baseline` 在**只含 main 的干净检出**上同样失败、报错一致 → 属另一条线的既存红灯（function-size 基线未重登记），**不是 M4 回归**。

已核验合并提交 `d64c2fd5fd`（父 `511ae9075` + `4bc6cdec`），指针分支 `feat/m4-desktop-operate-20261031-merged`。**未合并、未 push、未发布**；发布须先由另一条线重登记 function-size 基线。明细见交接书 §14。
### 11.11 M4 合入 main 的执行、复验与发布前置（2026-10-31 21:2x–21:4x）

**A. 执行**（用户 21:29 裁决：快进入 main、不发布）：main `511ae9075` → `d64c2fd5fd`（合并提交，父 = `511ae9075` + `4bc6cdec`），CAS `update-ref` 移动，**未发布**。唯一碰撞点 `src/llm_loop/factory.py`（M4 加 `desktop_operate` 注册；另一条线改 schedule `model_override`），两侧同基线 blob `6a3d49f63`、hunk 不重叠 → `git merge-file --diff3` rc=0、0 冲突标记，双向差集精确等于对方 → 先 `git checkout d64c2fd5fd -- <12 文件>` 对齐 index，再写回 merged，最后 CAS 移动 main。**脏文件数 104→104**，M4 的 12 个文件合并后干净，他人在制品原样保留。

**B. 合并后复验**（干净检出 detached `d64c2fd5fd`）：

| 项 | 结果 |
|---|---|
| ruff | All checks passed |
| R9 棘轮 ruff / pyright | 均 **PASS**（new=0、changed_file_diagnostics=0、changed_python_files=12） |
| 定向 pytest | 799 passed, 1 failed（`test_function_lines_ratchet_within_baseline`） |
| 归因 | 对照：只含合并前 main（`511ae9075`）的干净检出跑同一条用例**同样失败、文本逐字一致** ⇒ 既有红，非 M4 引入 |

**C. 既有红的内容**：基线 `tests/guards/function_size_baseline.json`（mtime 10-31 02:36，由 `24b238967` 登记）记 `settlement.py::_submit_one=147` / `review_host_admission.py::_source_snapshot=173` / `::start=190`；合并后 main 实测 **152 / 222**。对方压缩集树 `62939c22` 上还多 `::start` 190→192 与未登记函数 `::poll`（124 ≥ 120）。**两棵树都红**。

**D. 与对方压缩集的兄弟关系**：对方 21:22 的压缩单提交 `62939c22`（父 `55b53ab81`）与本线 `d64c2fd5fd` **同父兄弟、互不为祖先**；`62939c22` **不含 M4**，在飞 restart 发布的正是这棵不含 M4 的树（live=`b008c9fae`、desired=`62939c22`、`matches_desired_generation=false`、`restart_required=true`、admission_barrier=web/restart、feishu/learning/wecom stage=failed、web=waiting_for_idle）。要让 M4 上线必须**另发一次含 M4 的 desired**。

**E. 发布前置**：① 另一条线重登记 function-size 基线（`regen_function_size_baseline.py`）→ 两棵树转绿；② main 吸收对方压缩集（内容不重叠，预计干净合并；主树工作区该文件与其提交版逐字节一致，不覆盖在制品）；③ RULE-AI-28 对当时产物取独立审核 PASS（M4 自身第 5 轮 PASS 见 §11.9）；④ restart 通道裁决；⑤ 冒烟脚本 P2 裁决。

**F. 未验证边界**：本轮**未做 M4 live 动作复验**（只做代码层核验；真机投递证据以 §11.9 用例 10–11 为准）；**未重测** Chrome 网页层 AX（口径沿用 §12.5）；M4 与那 10 个提交**均未上线**。

### 11.12 M4 上线（gen 353）与部署后 live 复验（2026-11-01 收口）

**A. 发布事实**（2026-11-01 10:02 / 10:17 两次 `service_control status` 实测）

- 部署 head = **`ce205a4da`**（merge `integrate/main-20261031` into main）；wecom stable **gen 353**（started `2026-10-31T22:36:45+08:00`，pid 53803 存活）；`matches_desired_generation=true`、`admission_barriers=[]`、`restart_required=false`；feishu / web / wecom stage 均 `succeeded`。
- **M4 在部署内**：`git merge-base --is-ancestor 4bc6cdec ce205a4da` → in-deployed；浏览器侧基线 `b008c9fae` ⊆ `ce205a4da`（同法实测）；对方压缩集 `62939c22` 亦已并入。
- learning 的 durable 回执仍为 `failed`（gen 352 在飞重启失败的遗留），live 进程 `matches_desired_generation=true`——属**回执滞后**，非服务故障。

**B. 发布与 §11.11-E 前置的偏差（如实记录）**

- 「仓库转绿」未满足即发布：function-size 棘轮在发布树 `ce205a4da` 上仍红（2026-11-01 10:02 实测 `test_function_lines_ratchet_within_baseline` 1 failed）。归因同 §11.11-B/C：既有红、非 M4 引入、两棵树同红，基线登记权在另一条线。
- 发布动作发生于 10-31 22:36，本线该时段无运行回执；发布决策与执行细节不在本文档视野内，不做推断。

**C. 部署后 live 复验（2026-11-01 10:03–10:05；工具进程 = mirror `.venv/bin/python` pid 66151，即部署代代码）**

| # | 项 | 实测 | 判定 |
|---|---|---|---|
| 1 | `status` 自检 | ok=true；can_list_windows=true；TCC 位 false（已知假阴性，判据以探针为准）；单屏 1512×982 pt / scale 2.0 / macOS 26.5.1 | PASS |
| 2 | `windows` 枚举 | ok，窗口清单正常（含 Chrome window_id 121392） | PASS |
| 3 | `snapshot` AX | Terminal 窗口 `yyj`：ax.available=true、26 节点、`binding=bounds_only`、`clipped_depth=false` | PASS |
| 4 | `desktop_operate` dry_run ×2 | Chrome 121392、`do=scroll`、point (600,300) / (30,300)：ok=true，各签发一次性 confirm_token（sha256 摘要）、`needs_confirmation=true`、world 指纹绑定、**零投递** | PASS（令牌门控在部署面 live 生效） |

**D. 用户裁决（2026-11-01 10:18）**：接受「fail-closed 验证 + 开发期投递证据」为已足，不做部署后真机 apply 复验。真机投递证据以 §11.9-G 用例 10（`click`+AXCloseButton 端到端）为最终口径；`type` / `scroll` / `press_key` / `point` 的正向投递维持「未验证」边界（§11.9-H）。

**E. TASK-008 收口**：最终验收总结见同目录 `20261101-m0-m4-final-acceptance.md`（M0–M4 交付证据汇总 + 终局未验证边界）。

## 附录 A · 拷问记录（本轮新增的完善点）

> 每条都是"上一轮方案没覆盖、本轮逼出来的"。左边是我的追问，右边是它改变了设计的哪一处。

| # | 拷问 | 结论 | 改动位置 |
|---|---|---|---|
| Q-01 | AX 失败到底是 TCC 未授权，还是 sandbox 拦截？ | 两者修复路径完全不同；**当前工具面内无法区分**（所有命令都过沙箱），必须人工在终端跑一次 | 新增 D0 + 7.3.1 三分支 + Q1 |
| Q-02 | 截图坐标和点击坐标是同一套单位吗？ | 不是。实测 `-R 0,0,200,100` → 400×200 px，**输入是点、输出是像素 ×2** | 新增 D3 + 7.3.2（上一轮完全没有） |
| Q-03 | 截图进模型意味着什么？ | 当前模型是云端 DeepSeek（F5），截图 = 私人屏幕内容出机器 | 新增 D8 + 5.3 默认 `vision=none` + Q3 |
| Q-04 | 桌面感知能照搬浏览器 `vision=evidence` 吗？ | 不能无条件照搬，隐私前提不同 | 5.3 分级 + 敏感 app 拒拍 |
| Q-05 | 白名单放开终端会怎样？ | 等于给出"不受沙箱的任意命令"，比 `execute_command` 更宽 | T3 + Q2：终端只读 |
| Q-06 | 程序怎么知道"不可逆"？ | 判不了。只能启发式 + 首检 + 声明不完备 | 6.2 三级门控 + R5 |
| Q-07 | 自动点击会不会打断用户？ | 会（鼠标键盘是共享资源） | D7 + T7 + U15 |
| Q-08 | `upload` 会不会变成任意文件外传？ | 会，这是新增攻击面 | T1 + 路径白名单 + U2/U3 |
| Q-09 | `press_key` 打到系统级会怎样？ | Cmd+W/Q 会摧毁用户现场且不可撤销 | B3 黑名单 + U5 |
| Q-10 | dialog/下载是从零做吗？ | 不是。`cdp_action_host` 已采 `downloadWillBegin` / `javascriptDialogOpening`，只是没开合同 | B5/B6 成本下调；F8 |
| Q-11 | 下载"完成"怎么判定？ | 事件完成态 or 文件稳定双采样 | 7.3.5 |
| Q-12 | iframe 是从零做吗？ | 不是。帧树已采集并进入 capture | B8；F9 |
| Q-13 | 批量动作的 ref 会不会跨步失效？ | 会（第一步点击改变 DOM） | B13：identity 优先 + 失败即停；Q4 建议延后 |
| Q-14 | 负条件 wait 会不会立即为真？ | 会（元素本来就不在） | 7.3.4 稳定窗 300ms |
| Q-15 | "列页面清单"会不会变成隐式 rebind？ | 会，如果实现图省事 | 5.2 只读约束 + U10 |
| Q-16 | 死锁时静默重启可以吗？ | 不可以，等于掩盖故障 | B14：`degraded` 回执 + 建议动作 |
| Q-17 | 浏览器能做为什么还要桌面点击？ | 大多数场景不该用 | 6.5 路由规则（CDP > CLI > GUI） |
| Q-18 | 验收只写正向用例够吗？ | 不够，护栏必须验证"该拦的拦住" | 8 条应拦用例 + RULE-AI-35 |
| Q-19 | vision 同 sha 一定是缓存 bug 吗？ | 不一定。内容寻址下"像素相同"是正确行为，真因未定 | M0 复现优先 + Q6 |
| Q-20 | 我能确定改的就是线上代码吗？ | 不能。目录 HEAD `be9413318` 与运行时 `2894beda7` 不一致 | F12：实施前复核 |
| Q-21 | 桌面依赖齐吗？ | 不齐：无 pyobjc / 无 cliclick；`swiftc` 被拒 | F16/F17 → L0-lite 只能做应用级 |
| Q-22 | 有没有不需要新依赖就能用的通道？ | 有：`lsappinfo` 可列 app（够白名单判定）；`screencapture -R` 可区域截图 | F15/F18 → D2 可行子集 |

**由拷问带来的三个方向性修正**（如果只读原方案会漏掉）：

1. **桌面能力的"感知先行"在当前环境下只能先做到应用级 + 区域截图级**，控件级（AX）卡在权限与依赖两道门上，不能承诺。
2. **隐私从"可选加固"上升为 P0 前置**：默认不读图，不是实现完再补的策略。
3. **坐标系是硬缺口，不是实现细节**：不定义就会点偏，而且偏得很隐蔽（2 倍）。

---

## 附录 B · 证据索引

### B.1 本轮实测（A 级）

| 事实 | 回执 ref |
|---|---|
| 沙箱/screencapture 全屏 | `evidence://v1/468a057a7cff374a91114fc566630fd8b7416607e264107151d73bb12539b0ab` |
| 区域截图点→像素 | `evidence://v1/881fb1a1c6cdb3900dc021b8e880effb023e2c73329fa84740fe9c1dfdd8c000` |
| lsappinfo / swiftc / pip | `evidence://v1/a78fa5a3ab4c941516ed5dcf697bd8f1c65abc18cd6ad50947416dfd49b5749a` |
| 模型目录（云端） | `evidence://v1/eb8554f5fe02f8af84f5e7159a18519e68ddec3269e01eecc788edcf2d699275` |
| 代码根与 HEAD 不一致 | `evidence://v1/e77e0ea6d14967c049bbd39012ba2dde2a2ca2ee0fffa6493929e8444203f622` |

### B.2 源码核对（B 级）

| 事实 | 位置 |
|---|---|
| download / dialog 事件已映射 | `src/llm_loop/browser/cdp_action_host.py:108-112`、`:329` |
| 帧树采集与 flatten | `src/llm_loop/browser/perception.py:2876-2897` |
| `frames` 进入 capture | `src/llm_loop/browser/perception.py:2061` |
| vision 内容寻址落盘 | `src/llm_loop/browser/perception.py:2094-2115` |
| `browser_operate` 定义与 do 枚举 | `src/llm_loop/tools/builtin/browser_semantic_operation.py:319` |

### B.3 经验卡（C 级：本轮检索命中，**未水合正文**）

- `experience:EXPERIENCE-20260920-lfl-sha`（单 host-bound page + 单分发）
- `experience:EXPERIENCE-20260918-browser-action-target-id-id-grounding-ref`（大页帧超限）

### B.4 上一轮分析引用但**本轮未复核**的卡（引用前须水合）

> 这些是上一轮对话里提到的，本轮没有重新读取，不作为本文事实依据，仅备注线索。

- `method:rich-editor-automation-feasibility-gate`（判据⑤：无上传能力）
- ProseMirror 六坑 lesson 卡
- vision 缓存锁死 experience 卡
- `EXPERIENCE-20260918-cdp-env-target-id...`（CDP 死锁恢复）
- `EXPERIENCE-20260816-hermes...`（code-as-action 调研）

---

### B.5 2026-10-31 复验证据索引（TASK-010）

| 事实 | 依据 |
|---|---|
| 部署 `b008c9fae` / stable gen 349 / `matches_desired_generation=true` / `admission_barriers=[]` | `service_control(action=status, target=all)` 同会话 2026-10-31 15:0x 回执 |
| `type` >2000 → `type_text_too_long`；schema 不再声明 `maxLength`（`press_key.keys` 仍为 32） | `browser_operate` 回执 + 本会话工具 schema |
| D4 `title_relaxed` 实测（活动监视器，33 节点） | `desktop_perceive(action=snapshot)` 回执，window_id 89051 |
| 标题一致对照组 `title_exact`（微信，13 节点） | 同上，window_id 120905 |
| 四笔修复 in-deployed（含 `919b9881f`） | `git merge-base --is-ancestor <commit> b008c9fae` 四次分别回执 |
| 上限常量与两层拒绝点 | 源码 `browser/action.py:60`、`:767-768`；`browser_semantic_operation.py:426-427` |

> 本表只登记「哪条事实由什么证明」；逐条工具回执的稳定 ref 留在会话 Evidence，不在此复制。


## 附录 C · 与既有规则/流程的对应

| 规则/流程 | 本文对应 | 说明 |
|---|---|---|
| RULE-AI-01 完成诚实 | 0 章证据分级、第 3 章事实基线 | 全文区分实测/源码/推断；推断不进实施依据 |
| RULE-AI-24 防退化 | 7.1 落点、M1 退出判据 | 扩展 `do` 枚举不得改变现有 6 个动作语义 |
| RULE-AI-28 发表审查 | 6.2 irreversible、6.3 | 发布类桌面动作复用 `review_admission` |
| RULE-AI-35 护栏实测 | 第 9 章 8 条应拦用例 | "已生效"= 应拦输入被实测拦住 |
| escalation 闭环 | 6.3 | `confirm_token` 与提权令牌同构但分通道 |

---

## 附录 D · 一页摘要（给决策者）

- **浏览器侧**：7 个真实缺口，其中 3 个（上传、富文本输入、视觉证据）直接卡住发文链路，建议本轮就做；下载/dialog/iframe 底层已有事件与帧树，成本比看上去低。
- **桌面侧**：价值真实但门槛在权限与依赖，不在代码。建议只投 M0 探测，拿到 D0 结论再决定。
- **三个必须先补的硬缺口**：坐标系（点 vs 像素 ×2）、隐私默认（截图不出机器）、不可逆判定不完备（必须声明非保证）。
- **需要你拍板 6 件事**：见第 11 章。



