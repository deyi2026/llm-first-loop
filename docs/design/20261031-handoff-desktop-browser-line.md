# 交接文档：桌面 GUI 能力与浏览器工具补强（GOAL-20261027-c78e2aac）

| 项 | 内容 |
|---|---|
| 生成时间 | 2026-10-31 14:50 +08（本会话收口） |
| 交接原因 | 原会话过长（3900+ 消息）；且工具进程运行在 `sandbox-exec` 内，桌面 AppleEvent 通道被阻断，桌面写动作无法在本会话验证 |
| 新会话用途 | 在**无沙盒 / 已授权**的工作区接续：桌面 M4 验证、部署后 live 复验、最终验收 |
| 读者 | 接续的 LFL 会话。**先读本文再动手**；文中事实均标注来源与日期，"实测 / 源码 / 推断"分开 |
| 路径约定 | `$HOME` 为主目录实际路径；`<WS>` = `$HOME/lfl-workspace`（工作区，可写）；`<MIRROR>` = `$HOME/Project/llm-first-loop-mirror`（生产仓，沙盒内只读） |

---

## 0. 一页摘要（接手 60 秒版）

1. **浏览器侧全部交付并已上线**：P0（B1 upload / B2 type / B10 vision 元数据）+ P1（B3-B9、B15）+ B5 dialog 三缺陷修复 + R5 dialog 快路径，均在部署版本 `b008c9fae` 内（逐个 `git merge-base --is-ancestor` 核过）。
2. **桌面侧走到 M3（只读）并已上线**：`desktop_perceive`（`status` / `apps` / `windows` / `snapshot`）落地，无宿主进程、无三方依赖（ctypes + `lsappinfo` / `screencapture`）。**M4（点击/键入）于 2026-10-31 15:11 获用户授权**，尚未开工写动作代码（先验 AXPress 真实投递，见 §11）。
3. **D0 关键结论（推翻了设计书原假设）**：TCC 权限本来就有——屏幕录制 ✓ 辅助功能 ✓；沙盒拦的只是 `AppleEvent → System Events`（`-10004`），**不是** AX 能力。AX 直调、`CGWindowList`、`screencapture` 在沙盒内全部可用。所以"必须做独立宿主进程"的必要前提不成立。
4. **卡点不在代码，在通道与授权**：桌面真实动作投递（AXPress / 键入）从未验证（原始授权只到"读"）；Chrome 的 AX 树默认不可读（`-25211 kAXErrorAPIDisabled`，Chromium 惰性建树）。
5. **新会话第一件事**：不是写代码，是**核快照 + 判断写者线是否活跃 + 做 TASK-010 部署后 live 复验**。见 §7。

---

## 1. 目标与用户裁决（授权边界，先看这节）

**Goal**：按 `<WS>/docs/design/20261027-desktop-gui-and-browser-tooling-design.md` 交付「桌面 GUI 能力 + 浏览器工具补强」。
**Goal id**：`GOAL-20261027-c78e2aac`（新会话 `get_goal` 读取，任务图用 `task_frontier`）。
**治理**：开发由 dev 子代理（glm-5.3）执行，父会话只做裁决 / 验收 / 记账。

### 1.1 已裁决项（设计书 §11 表，勿重开）

| ID | 问题 | 裁决 |
|---|---|---|
| Q1 | 桌面能力范围 | **(a) 只做 M0 探测** — 注：D0 结论 A′ 出来后实际推进到 M3，见 §2；扩张有 checkpoint 记录 |
| Q2 | 白名单首批 app | Finder / Safari / Chrome / Preview；**终端与 IDE 只读**，不给 act |
| Q3 | 云端模型能否读桌面截图 | **(b) 允许读**；实现仍**默认关 + 逐次显式 + 敏感 app 拒拍** |
| Q4 | 批量动作半完成语义 | **(b) 先只做单步**，B13 延后 |
| Q5 | upload 允许根 | **(a) 仅工作区** |
| Q6 | B10 "内容确实相同" | **(b) 只标注，不算 bug** |

### 1.2 明确未授权（红线）

- **M4 已授权**（2026-10-31 15:11，用户裁决「M4 进」）：红线由「未授权」改为「已授权、但门控未落地」。至今未改任何 `tools_l0_enabled`，仍无 AX 写能力代码（`desktop_operate` 未开工）。进入前须告知的三件事见 §11.3；执行顺序与当前阻断见 §4 与 §12.3。
- 桌面隐私名单**核心项硬编码**（1password / bitwarden / lastpass / dashlane / keychain / SecurityAgent / Passwords / loginwindow），配置**只能追加不能删**——这是设计决定，不要"优化"成可配置删。

---

## 2. 里程碑状态（含验证方式）

| 里程碑 | 状态 | 验证方式 / 依据 |
|---|---|---|
| M0 探测 | ✅ done | `<WS>/docs/design/20261027-d0-desktop-capability-report.md`（13 条 A 级证据链）；探针在 `<WS>/work/m0-probe/desktop/` |
| M1（B1/B2/B10） | ✅ done + 已上线 | 独立审核 PASS + 全量门禁；live：`20261028-live-smoke-b1-b2-b10.md` |
| M2a / M2b（B3-B9、B15） | ✅ done + 已上线 | `20261027-m2a-dev-report.md` / `20261027-m2b-dev-report.md`；live：`20261028-live-smoke-b3-b5-b7-dialog-and-ax-binding.md` |
| B5 dialog 缺陷 | ✅ 已修 | 判定实验 `20261028-task009-dialog-verdict.md`（Chrome 侧 8/8 完好，缺陷全在我方会话生命周期） |
| M3（桌面只读） | ✅ done + 已上线 | `20261027-m3-dev-report.md` §12.6；L2 截图 live 通过（3024×1754 px 对 `1512×877 pt × 2.0`，偏差 0 px） |
| R5（dialog 快路径）+ M1 门禁重构 | ✅ done（2026-10-31 15:3x 收口） | 提交 `4d63a3b85`(R5)、`395ebae9b` / `c7d2e0ffe`；`git merge-base --is-ancestor 4d63a3b85 b008c9fae` → **in-deployed**；`TASK-...-012` 已置 done（evidence_verification=verified） |
| 10-30/31 补丁 | ✅ 已上线 | `55aff5b73`（type 上限移出 schema + D4 `title_relaxed` 标注）、`4d7dc24ef`（`reject_reason` 整类提升 + 候选窗补 `frame_token`） |

### 2.1 部署版本内容（`b008c9fae`，逐个核实）

```
4d63a3b85 R5 dialog 快路径             → in-deployed ✅
919b9881f B5 dialog 三缺陷修复         → in-deployed ✅
55aff5b73 type 上限 + D4 title_relaxed → in-deployed ✅
4d7dc24ef reject_reason + frame_token  → in-deployed ✅
```

---

## 3. 代码与运行态（2026-10-31 14:4x 实测）

### 3.1 部署

- 部署 head = **`b008c9fae`**；`wecom` stable gen **349**（started `2026-10-31T10:07:17+08:00`，pid 54712 存活）。
- `matches_desired_generation=true`、`restart_required=false`、`admission_barriers=[]`、`terminal_action_barrier=null`。
- 四服务 `stage_facts` 均 `succeeded`。

### 3.2 仓

- `<MIRROR>` HEAD = **`55b53ab81`** = 部署 head + **1 个提交**（"补齐 write-scope 线漏改的签名等 7 条 pyright 新红（R9 棘轮转绿）"），差异仅 `command_scope_guard.py` / `routes.py`，8+/4-。
- **工作树是脏的**：19 个 `reports/**` JSON + `src/llm_loop/core/write_scope.py` + `src/llm_loop/tools/sandbox.py`。

> ⚠️ **活跃写者警告（2026-10-31 15:3x 复核，该线仍活跃）**：`write_scope.py` mtime 仍 **14:38**、`sandbox.py` 仍 **14:16**（两个文件约 50 分钟未动），但该线**并未停**——同一时段新增 `tests/test_scope_roots_sampling.py`(14:49)、`docs/REPORT-20261031-orchestration-gate-friction.md`(15:00)、`data/methods/*`(15:04/15:10)、`data/methods/*`(**15:25**)。它在推进「scope roots 采样」新特性。**不要抢这两个文件，不要 `git stash` / `git checkout --` / 提交别人的改动**；动手前先 `stat` 看 mtime。**因该线有 in-flight 未提交工作，本线不发 restart**（重启时机见 §5-2）。

> **2026-10-31 16:0x 复核（本次续接会话）**：`write_scope.py` mtime 已从 14:38 变为 **15:29**（另一条线仍在推进），`sandbox.py` 仍 14:16；另见 `command_scope_guard.py`、两个测试文件、未跟踪的 `.patches/` 与 `data/methods/*`(4 个)。**本会话未改动上述任一文件，也未做任何会覆盖他人改动的版本控制操作**，未发 restart。

### 3.3 部署待办（已裁决延后）

最近一次 checkpoint 记录：**部署重启放到下一会话（不在上一轮发 restart）**。即 `55b53ab81` 尚未发布。
注意：发 `restart` 时 `web` 承载发起会话，会停在 `waiting_for_requester_exit`——**不要在同一条 web 会话里发完就等**；要么从别的通道发，要么接受它等该会话退出。

---

## 4. 未完成事项（任务图 4 open / 12）

| 任务 | 状态 | 要做的事 | 前置 |
|---|---|---|---|
| `TASK-...-010` 部署后 live 复验 | ✅ done（2026-10-31 15:0x） | ① `type` 超 2000 字符 → 期望 `type_text_too_long`（不再被 schema `maxLength` 抢先拦截）；② `desktop_perceive snapshot` 对"CG 标题 ≠ AX 标题"的 app 期望 `binding=title_relaxed` | 实测全 PASS：`type` 上限拒绝码 + D4 `title_relaxed` + 标题一致对照组 + 无副作用；明细见 §11 与设计书 §11.8 |
| `TASK-...-012` R5 收口 | ✅ done（2026-10-31 15:3x） | 已核：`4d63a3b85` in-deployed（`merge-base --is-ancestor` 回执），任务已置 done | — |
| `TASK-...-007` M4 桌面窄操作 | ⛔ blocked（2026-10-31 16:0x；根因已定位） | **已授权（15:11）；投递通道已验**（AXPress 真实生效、AX set-value 键入回读一致，均 PROVEN）。**Chrome 网页层 AX 在沙盒内不可激活，根因已定位**：① 直接启动带 `--force-renderer-accessibility` 的独立实例 → Chrome 报 `Failed to create a socket directory` → `Failed to create a ProcessSingleton for your profile directory` → abort（沙盒拒创建 unix socket，普通文件写入是通的）；② `open -na "Google Chrome" --args …` 在沙盒内 exit 0 但**不派生子进程**（无新 pid、profile 目录全空），即 LaunchServices 交接被沙盒静默丢弃。**替代通道已验证可用**：CDP 9229 实例 12 个 page target 全部 `Accessibility.enable` 成功，`getFullAXTree` 出 8463 节点网页层；但 macOS AX 侧 Chrome 仍只到**窗口级**（AXWindow / AXGroup / AXButton close·min·fullscreen），**无 AXWebArea**，开完 CDP AX 复测仍无变化。需用户裁定走哪条（见 §12.5）。**裁定前不写动作代码** | 用户裁定 Chrome 网页层通道（AX 需沙盒外实例 / 改用既有 CDP） |
| `TASK-...-008` 最终交付验收与总结 | ▶ ready | 父会话负责。至少含：① 把 10-30/31 补丁回填设计书（正文止于 10-29，见 §8 陷阱 2）；② 汇总 M0-M4 交付证据；③ 声明未验证边界 | 上面三项收口后 |

---

## 5. 待裁决 / 未决

1. **M4 是否进** → **已进（2026-10-31 15:11）**。进入前必须让用户知道三件事（15:11 已当面向用户复述）：
   - 真实 AXPress / 键入投递**从未验证**（原授权只到读）；
   - Chrome AX 树默认不可读，需 `--force-renderer-accessibility` 或等价激活，否则 M4 只能退化为坐标点击；
   - 动作通道以 AX 动作为主、CGEvent 兜底；门控 / 令牌 / 审计沿用设计书 §6，不新增进程。
2. **部署重启时机**（`55b53ab81` 上线）。
3. **桌面截图外传**已裁决允许（Q3），但实现必须保持"默认关 + 逐次显式 + 敏感 app 拒拍"，不要因为"已授权"就放松默认值。

> CI 红灯 / gitee 推送凭据等属**另一条线**，见 `<MIRROR>/docs/design/20261031-handoff-ci-red-and-gate-state.md`。**别混进本线**。

---

## 6. 沙盒限制清单（本会话踩过的坑，新会话必读）

| 通道 / 能力 | 沙盒内 | 结论与做法 |
|---|---|---|
| `osascript` → `System Events`（AppleEvent UI 脚本） | ❌ `-10004` | **不要走这条路**。这不是权限缺失，去系统设置点授权也不会好 |
| `osascript` 本身（纯 AppleScript 计算） | ✅ | 说明被拦的是 AppleEvent 发送，不是 osascript |
| AX API 直调（`AXUIElementCreateApplication` / `CopyAttributeValue`） | ✅ | M3 就靠它，无需 pyobjc / Swift |
| `screencapture`（全屏 / 区域 / 窗口 `-l`） | ✅ | `CGPreflightScreenCaptureAccess()` 实测 true |
| `CGWindowListCopyWindowInfo` | ✅ | 31 个窗口，id / owner / title / layer / alpha / bounds / pid 齐全 |
| `lsappinfo front` / `info` | ✅ | 前台 app 判定不依赖 AX |
| **真实动作投递**（AXPress / 键入 / 点击） | ⚠️ 未验 | 属 mutation，原始授权只到"读"。**新会话在无沙盒环境，这是唯一真正需要补验的能力** |
| 写 `<MIRROR>` | ❌ 只读 | 开发走 `<WS>` 下的 worktree / dev 子代理，不要直接改生产仓 |
| `restart` 部署 | ⚠️ 受限 | web 承载会话时会等 requester 退出 |

### 6.1 三个"看起来像 bug 其实不是"的坑

1. **`AXIsProcessTrusted()` 假阴性**：同一进程内实测 4/4 次 `false`，而 `ax_snapshot` 同时返回 `available=true` / 22 节点。**判能力要用探针**（对前台 pid 读 `AXWindows`，`err==0` 即可用），不要用授权位。
2. **`screencapture` 无权限不报错**：会静默产出黑图 / 桌面壁纸，`exit 0`。**必须用 `CGPreflightScreenCaptureAccess()` 前置判断**，不能靠退出码。
3. **`AXWindows` 对 Chrome 返回 `-25211`**：Chromium 惰性建树，不是授权问题。普通 app 的"未命中"还有独立原因——CG 标题与 AX 标题不完全相等（活动监视器：`活动监视器` vs `活动监视器 – 所有进程`），已修为 `title_relaxed`。

---

## 7. 新会话第一步（按序执行，命令级）

```bash
# 1) 快照：部署与仓
#    service_control(action=status, target=all)
cd <MIRROR> && git log --oneline -3 && git status --porcelain | head -20

# 2) 判断写者线是否仍活跃（决定能不能动 write_scope / sandbox）
stat -f '%Sm %N' -t '%m-%d %H:%M' src/llm_loop/core/write_scope.py src/llm_loop/tools/sandbox.py
#    mtime 距现在 < 10 分钟 → 视为活跃：只报告不抢文件

# 3) 核部署版本是否含待验修复
git merge-base --is-ancestor 55aff5b73 b008c9fae && echo type+D4 in-deployed
git merge-base --is-ancestor 4d7dc24ef b008c9fae && echo reject_reason in-deployed
```

4. **做 TASK-010 live 复验**（浏览器侧任意会话可做；桌面 D4 需要 `desktop_perceive` 工具面可用）。
5. **收口 TASK-012**（核 R5 合入 + 部署事实后更新状态）。
6. 若用户批 M4：**先激活 Chrome AX**（`--force-renderer-accessibility` 起可控实例），在**测试 app** 上验 AXPress 投递，拿到"动作真的生效"的 A 级证据，再谈门控。
7. 全部收口后再做 TASK-008 最终验收，并把 §8 的补丁回填设计书。

---

## 8. 陷阱与禁令（省时间用）

1. **不要把设计书 §5.6 "as-built 差异"当现状**：它写于 10-28 15:49，说"M3 未实现、L1 AX 不可读"。**M3 已交付并上线**，该表已被 §11.2 取代。
2. **设计书正文只回填到 2026-10-29 10:07（§11.7）**——这句只对了一半。**已回填**：§11.3（B5）、§11.4（R5，含提交号）、§5.3（D4 归因）。**真正没回填**的是 `type` 上限契约变更 + D4 标注本身、`reject_reason` 整类提升 + `frame_token` 补齐——已在 §11.8 补齐（2026-10-31）。
3. **`halt_reason=action_receipt_status:rejected` 现在有因可查**：`4d7dc24ef` 已加 `reject_reason`（整类提升）。上一轮"原因可观测但不可发现"的 P2 **已闭环，不要重做**。
4. **`navigate` 被拒不是 bug**：`ip_blocked:127.0.0.1（私网）` 是 `net_guard.check_url` 的设计行为，`tests/test_net_guard.py` 锁着。要访问本机页面得走允许路径或用静态文件。
5. **`-10004` ≠ 没授权**（见 §6）；**`screencapture` exit 0 ≠ 有权限**（见 §6.1-2）。
6. **`<MIRROR>` 只读 + 有活跃写者**：不 `stash`、不 `reset`、不提交别人改动。
7. **任何对外推送**：先过 RULE-AI-28（`review_admission(kind=git_push)` 对**当时**产物取 PASS），并按 push-review-gate 跑 `scripts/knowledge_flush.py` 把待入库卡并成一笔。旧 PASS 不可复用。
8. **桌面隐私默认值不许放松**：截图默认关、逐次显式、核心名单硬编码、`see_allowlist` 空 = 全允许但优先级低于 `privacy_blocked`。

---

## 9. 证据与文档索引

### 9.1 设计 / 报告（`<WS>/docs/design/`）

| 文件 | 内容 |
|---|---|
| `20261027-desktop-gui-and-browser-tooling-design.md` | 主设计书（843 行；§11 裁决表、§11.1-11.7 交付回填、附录 A 拷问记录、附录 B 证据索引） |
| `20261027-d0-desktop-capability-report.md` | D0 归因：通道矩阵、能力矩阵、未验证项、生命周期风险 |
| `20261027-desktop-permission-runbook.md` | 权限恢复步骤与判据（含 M4 前置） |
| `20261027-m0-probe-report.md` | M0 探测原始记录（29KB） |
| `20261027-m1-dev-report.md` / `20261027-m1-review.md` / `20261027-m1-milestone.md` | M1 开发 / 独立审核 / 里程碑 |
| `20261027-m2a-dev-report.md` / `20261027-m2b-dev-report.md` | M2 两批交付 |
| `20261027-m3-dev-report.md` | M3 交付（§12.6 为 live 证据） |
| `20261028-live-smoke-b1-b2-b10.md` | B1 / B2 / B10 live 实测 |
| `20261028-live-smoke-b3-b5-b7-dialog-and-ax-binding.md` | B3 / B5 / B7 + AX 绑定（§5 为 `title_relaxed` 新进程 E2E） |
| `20261028-task009-dialog-verdict.md` | B5 判定实验 |
| `20261028-p2-narrow-review.md` | 12 行 P2 对账（无阻塞项） |
| `20261028-deploy-closure-status.md` | 10-28 部署收口（部分口径已被 10-29 后取代） |
| `20261028-handoff-browser-tooling-merge-deploy.md` | 10-28 上一版交接（**已被本文取代**） |
| `20261031-handoff-desktop-browser-line.md` | **本文** |

### 9.2 代码锚点（`<MIRROR>`）

| 事实 | 位置 |
|---|---|
| `browser_operate` 定义 / do 枚举 | `src/llm_loop/tools/builtin/browser_semantic_operation.py:319` |
| 紧凑投影 `_compact_projection` | 同文件 `:1834-1950` |
| `halt_reason` 汇总点 | 同文件 `:2056-2059` |
| 拒绝码单一真值源 | `src/llm_loop/browser/net_guard.py:173,205-228`；`browser/action.py:737-756` |
| receipt hydrate 注入 | `src/llm_loop/factory.py:1471` |
| 桌面模块 | `src/llm_loop/desktop/`（`macos_ax.py` / `macos_capture.py` / `privacy.py` 等 10 个 .py，release 内实存） |
| 架构护栏 | `tests/unit/test_arch_guards.py`（本机 40 passed） |

---

## 10. 事实边界（不得越界声明）

1. **M4 的动作能力**：只有"AXPress 动作名可枚举"（A 级只读），**没有**"点击/键入真的生效"的证据。
2. **Chrome 网页层 AX**：4 层遍历只见 `AXGroup`，无 `AXWebArea`；需激活才可能建树，**未验证**。
3. **锁屏态、多显示器跨屏 scale、非整数缩放**：均未验证（本机单屏 2.0x）。
4. **TCC 授权归属**：按启动链归属，工具面内无法确定 responsible process；换 launchd 方式拉起会**再次弹窗**。所以 M3 交付的是 `action=status` 自检，不是"默认可用"假设。
5. **部署版本 ≠ 仓 HEAD**：部署 `b008c9fae`，HEAD `55b53ab81`，差 1 个类型修复提交，**未上线**。
6. **上一轮 `svc-9c38605a…` 失败动作**：只有"不再形成屏障"（barrier 为空）这一条，**没有**"已显式登记结项"的证据（截断 id 无法检索）。

---

---

## 11. 续记：TASK-010 收口 + M4 授权 + 设计书回填（2026-10-31 15:00–15:2x）

### 11.1 TASK-010 已完成并置 done（evidence_verification=verified）

| 验收项 | 实测 | 判定 |
|---|---|---|
| ① `type` 超上限 | 送 2222 字符 → `[failure] contract rejected; reason=type_text_too_long`；本会话工具 schema 中 `type.text` **无 `maxLength`**，而 `press_key.keys` 仍有 `maxLength=32`（限制机制在，仅 type 不再声明） | PASS |
| ② D4 降级绑定 | 活动监视器（window_id 89051；CG `活动监视器` / AX `活动监视器 – 所有进程`）→ `binding=title_relaxed`、`degraded=["ax_title_relaxed"]`、33 节点、`clipped_depth=false` | PASS |
| ③ 标题一致对照组 | 微信（window_id 120905）→ `binding=title_exact`、`degraded=[]`、13 节点（未误降级） | PASS |
| ④ 无副作用 | 被拒后 hydrate 目标 textarea 无 `value_text`（同页文件输入框对照有），元素仍为空 | PASS |

上限真值源 `_TYPE_MAX_TEXT_LENGTH = 2000`（`browser/action.py:60`）；两层拒绝点＝契约层 `browser_semantic_operation.py:426-427` + adapter `browser/action.py:767-768`。

### 11.2 三处口径订正（本文原文与实测不符）

1. 四笔修复**不是「10-30/31」**：只有 `4d7dc24ef` 出自 2026-10-30 19:34，其余三笔出自 10-28（13:30 / 12:25 / 11:17）。四笔**全部** in-deployed（含 `919b9881f`）。
2. **「四笔都没有文档回填」不准确**：§11.3 已记 B5、§11.4 已记 R5（含提交号）、§5.3 已记 D4 归因；真正缺的只有 `type` 上限契约变更 + D4 标注、`reject_reason` 整类提升 + `frame_token`。
3. §11.7 的 P2 建议已落地，但与建议稿有四处差异：字段名 `reject_reason` ≠ `rejection_reason`、取值来源、触发条件、覆盖范围；且**不做 200 字符截断**。

### 11.3 M4 已授权（2026-10-31 15:11）

用户裁决：**M4 进**。进入前须告知的三件事已当面向用户复述：

1. 真实 **AXPress / 键入投递从未验证**（原授权只到「读」；当前只有「AXPress 动作名可枚举」这一 A 级只读事实）；
2. **Chrome AX 树默认不可读**（`-25211 kAXErrorAPIDisabled`），需 `--force-renderer-accessibility` 或等价激活，否则 M4 只能退化为坐标点击；
3. 动作通道**以 AX 动作为主、CGEvent 兜底**；门控 / 令牌 / 审计**沿用设计书 §6**，不新增进程。

执行顺序（沿用本文 §7 第 6 步）：① Chrome AX 激活（可控实例）→ ② 在**测试 app** 上验 AXPress 真实投递，拿到「动作真的生效」的 A 级证据 → ③ 再谈三级门控与令牌。**未拿到 ② 的 A 级证据前，不写 `desktop_operate` 动作代码。**

### 11.4 设计书回填的交付方式（补丁，非直接落盘）

本会话的工作区根指向生产仓的 release worktree，`$HOME/lfl-workspace` **两条独立证据都不可写**（`edit_file` 快照报 `WorkspaceScopeMismatch`；shell 写探针返回 `Operation not permitted`），因此回填以**补丁**交付。

> ⚠️ **2026-10-31 15:3x 订正**：此前会话曾声称「补丁已应用到工作区」，**该声称不成立**。核验依据：工作区两份文档 mtime 分别为 10-29 10:07 与 14:53，**均早于**补丁生成时间；且逐条 grep 确认新增章节（设计书 §11.8 / 附录 B.5、交接书 §11）在工作区文件中**不存在**。`git apply --check` 通过只证明「可干净应用」，**不等于已写入**。
>
> 同批还有两份**互相冲突**的补丁（15:06 与 15:21 版本改同一 hunk）。现已合并为**唯一 canonical 补丁**：
>
> ```bash
> cp $HOME/Project/llm-first-loop-mirror/data/deliverables/20261031/20261031-ws-backfill-desktop-browser-line.patch \
>    $HOME/lfl-workspace/docs/design/
> cd $HOME/lfl-workspace
> git apply --check docs/design/20261031-ws-backfill-desktop-browser-line.patch   # 预演
> git apply docs/design/20261031-ws-backfill-desktop-browser-line.patch
> ```
>
> 补丁内容：设计书新增 §11.8（回填 + live 复验 + 未验证边界）、§5.6 加「2026-10-31 口径更新」注、附录 B 加 B.5；本文新增 §11，并订正 §0 / §2 / §3 / §4 / §8。**未 commit**（另一条线正在改 `write_scope.py` / `sandbox.py`，且有 in-flight 未提交工作）。

### 11.5 未验证边界（不得当作已验）

- `type` 的 **=2000 接受侧**未 live 测（会向本地「视频描述」输入框真写 2000 字符，为不污染发布表单而跳过）；阈值以源码常量为准。
- D4 **多命中**的 `window_ambiguous` 歧义拒绝未重测。
- **M4 / `desktop_operate` 未开工**：授权有了，但**动作代码尚未写**；投递通道虽已验（见 §11.7），**门控 / 令牌 / 审计三件套尚未设计落地**。
- Chrome 的 `-25211` 未变；AX 树到网页内容（`AXWebArea`）仍未验证。
- **CGEvent 键入在中文输入法下输出被污染**（§11.7 探针 3）：兜底路径必须处理 IME，未处理前不得声称「CGEvent 键入可用」。

### 11.6 当前运行态快照（2026-10-31 15:0x–15:2x 实测）

- 部署 `b008c9fae` / wecom stable gen **349**（started `2026-10-31T10:07:17+08:00`，pid 54712 存活）、`matches_desired_generation=true`、`admission_barriers=[]`、`restart_required=false`、四服务 `stage_facts` 均 `succeeded`。
- 仓 HEAD = `55b53ab81`（2026-10-31 12:47，pyright 类型修复）= 部署 + 1 个提交，**未上线**（重启时机：等完善后一起，用户 15:11 裁决）。
- 活跃写者：`write_scope.py` mtime 14:38、`sandbox.py` mtime 14:16，截至 15:15 **未再变动**；本会话不碰这两个文件，也未 stash / reset / 提交他人改动。

### 11.7 M4 首轮探针结果（2026-10-31 15:16–15:19，沙盒内实测）

| # | 探针 | 结果 | 判定 |
|---|---|---|---|
| 1 | **AXPress 真实投递**：TextEdit 原生 `AXCloseButton` 执行 `AXPress` | err=0，窗口数 `1 → 0`，动作确实生效 | **PROVEN** |
| 2 | **AX 键入投递**：`AXSetAttributeValue(kAXValue)` 写文档 AXTextArea | 写入串回读完全一致 | **PROVEN** |
| 3 | **CGEvent 键入通道** | 键事件**送达**（字符进了文档），但输出被**输入法污染**：本机当前输入源是 `com.apple.inputmethod.SCIM`（拼音 ABC，见 `AppleSelectedInputSources`），`a s d` 被拆成「a␣s␣d」；带 shift 的大写（`ASD`）不受影响；纯 unicode 事件（keycode=0）无输出 | **通道通，但需 IME 处理** |
| 4 | **Chrome AX 激活**：`--force-renderer-accessibility` + 独立 `--user-data-dir` | 本沙盒内**起不来**：Chrome 报 `Failed to create a socket directory` → `Failed to create a ProcessSingleton` → 主动 abort（profile 锁目录不可创建） | **受阻** |
| 5 | 现存 Chrome 的 AX 树能否到网页层 | 服务自带 chatgpt-web Chrome（pid 96579，profile `data/runtime/chatgpt-web-chrome-profile`）主窗口 33 节点但 **AXWebArea=0 / AXStaticText=0**；另一实例（pid 26881）AXWindows 读取直接报错（对应 `-25211`） | **确认不可达** |

**副作用与残留**（探针只碰临时窗口，已复原）

- 全部在**临时 TextEdit 窗口**上做；结束时窗口数回到 0（与探针前一致），TextEdit 进程（pid 45500）探针前就已在运行。
- 临时文件 `/tmp/lfl-m4-*.txt`、`/tmp/lfl-m4-page.html`、`/tmp/lfl-chrome-m4` 已删除。
- 早先一次 `open -na "Google Chrome"` 尝试**没有**在用户/服务 Chrome 里打开探针页（AX 树无探针标题），无残留标签页。

**对实现的直接影响**

1. 键入**优先走 AX set-value**（已验证可靠），CGEvent 仅作兜底，且兜底路径必须处理 IME（切 ASCII 输入源，或逐字符回读校验）。
2. AXPress 通道**已可用**——M4 的核心风险从「投递不了」转为「门控 / 一次性令牌 / 审计怎么设计」。
3. Chrome 网页层要可达，需在**沙盒外**起带 `--force-renderer-accessibility` 的实例，或给服务自带 Chrome 加该 flag 重启；两者都是部署/环境决策，本轮未动。

### 11.8 续接会话收口（2026-10-31 15:26–15:4x）

本节由**续接会话**写入，记录该会话核验到的事实与两处订正。

**A. TASK-010 独立二次复验（PASS，与 §11.1 同结论，不同执行）**

| 验收项 | 本次实测 | 判定 |
|---|---|---|
| ① `type` 超 2000 字符 | 送 >2000 字符 → `[failure] contract rejected; reason=type_text_too_long`；本会话 `type.text` 参数**仍无 `maxLength`** 声明 | PASS |
| ② D4 `title_relaxed` | `desktop_perceive(action=snapshot, window_id=89051)` → `binding=title_relaxed`、`degraded=["ax_title_relaxed"]`、`node_count=9`（depth=1）、`clipped_depth=false`；AX 根标题 `活动监视器 – 所有进程` vs CG 标题 `活动监视器` | PASS |

**B. TASK-012 收口**：`git merge-base --is-ancestor 4d63a3b85 b008c9fae` → **in-deployed**（同批复核 `919b9881f` / `55aff5b73` / `4d7dc24ef` 亦全部 in-deployed）。任务已置 done。

**C. TASK-007 置 blocked**：投递通道已 PROVEN（AXPress / AX set-value），但 **Chrome 网页层 AX 激活在沙盒内不可完成**，需用户裁定路径（见 §4 表格与 §5-1）。**这是环境决策，不是代码问题**——M4 的动作代码在裁定前不写。

**D. 订正 1：此前「补丁已应用到工作区」的声称不成立**（见 §11.4）。工作区两份文档 mtime 均早于补丁生成时间，新增章节 grep 不存在。

**E. 订正 2：两份补丁并存且互相冲突**（15:06 / 15:21 改同一 hunk）。已合并为唯一 canonical 补丁，落在 `<MIRROR>/data/deliverables/20261031/`。

**F. 运行态（15:27 实测）**：部署仍 `b008c9fae` / wecom stable gen **349**、`matches_desired_generation=true`、`admission_barriers=[]`、`restart_required=false`；仓 HEAD 仍 `55b53ab81`（= 部署 + 1 提交，未上线）。**因另一条线有 in-flight 未提交工作，本线不发 restart**。

## 12. 续接会话实测记录（2026-10-31 15:54–16:0x）

### 12.1 工作区回填**已在 15:53 落盘**（订正 §11.4 的「未落盘」口径）

| 核验项 | 实测 | 判定 |
|---|---|---
| 前向 `git apply --check` | 失败（`patch does not apply`） | —
| **反向** `git apply --check --reverse` | **通过** | 补丁**已完整应用**；前向失败是重复应用，非冲突 |
| 设计书 | 916 行（对工作区 HEAD 为 +190 行）；§11.8 在 751 行、附录 B 在 843 行、B.5 在 882 行、§5.6 口径注在 323 行 | 回填已在 |
| 交接书 | §11（11.1–11.8）已在 | 回填已在 |
| 两份文档 mtime | 均 **15:53** | 落盘时间 |
| 工作区 git 状态 | 设计书 `M`、交接书 `??`、补丁文件 `??`（未提交到版本库） | 提交与否待定 |

> 用户 15:55 的 `cp` + `git apply` 失败属**预期**：目标是已应用同一补丁，工作区无需再改。`docs/design/20261031-ws-backfill-desktop-browser-line.patch`（工作区未跟踪副本）可删可留，仅是记录。

### 12.2 TASK-010 第三次独立 live 复验（PASS，与 §11.1 / §11.8 同结论）

| 验收项 | 本次实测 | 判定 |
|---|---|---
| ① `type` 超上限 | 送 2120 字符（目标：本会话 Web UI 的「搜索会话…」输入框）→ `[failure] contract rejected; reason=type_text_too_long`；本会话 `type.text` 参数仍**无 `maxLength`** | PASS |
| ② 无副作用 | 被拒后 `hydrate` 同一输入框：**无 `value_text`**（未写入） | PASS |
| ③ D4 `title_relaxed` | `desktop_perceive(snapshot, window_id=89051)`（活动监视器 pid 71527）→ `binding=title_relaxed`、`degraded=["ax_title_relaxed"]`、33 节点、`clipped_depth=false`；AX 根标题 `活动监视器 – 所有进程` vs CG 标题 `活动监视器` | PASS |

### 12.3 Chrome 网页层：沙盒内不可激活（根因已定位），替代通道已验证

| # | 探针 | 结果 | 判定 |
|---|---|---|---
| 1 | `open -na "Google Chrome" --args --force-renderer-accessibility --user-data-dir=<新目录> …` | exit 0，但**无新 Chrome pid**、profile 目录全空 → LaunchServices 交接被沙盒静默丢弃 | 受阻 |
| 2 | 直接启动 `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --force-renderer-accessibility …` | `Failed to create a socket directory.` → `Failed to create a ProcessSingleton for your profile directory` → **abort**；同期普通文件写入（/tmp、Caches、profile 内 BrowserMetrics）正常 | **根因：沙盒禁创建 unix domain socket**（Chrome singleton 必需） |
| 3 | CDP 9229（`/json/list` 可达，12 个 page target） | 对**全部 12 个** target 发 `Accessibility.enable` → 全部 ok | 可用 |
| 4 | CDP `Accessibility.getFullAXTree`（LLM-First Loop · Web V2 target） | **8463 节点**，含 button / heading / link 等网页层角色 | **网页层语义在 CDP 通道完整可得** |
| 5 | macOS AX 复核 Chrome（window 115037 / pid 96579、window 121487 / pid 61931） | `available=true`，但只有 AXWindow / AXGroup / AXButton(close·min·fullscreen)，**无 AXWebArea、无网页内容节点**；**开完 CDP AX 后复测仍无变化** | AX 通道只到窗口级 |

**结论（对本线的意义）**：

1. 沙盒内**任何**方式都起不了带 flag 的 Chrome 实例 ⇒ 文档 §4/§5 里的选项 ①「沙盒外手起可控实例」必须由**人在自己终端**执行；选项 ②「给服务 Chrome 加 flag 并 restart」会与另一条线的 in-flight 工作撞车。
2. Chrome 网页层的语义**不必**依赖 AX API：既有 CDP 通道已能给出完整网页层 AX 树（8463 节点）。macOS AX 在 Chrome 上只适合做窗口 chrome 级动作（关窗/最小化/全屏按钮，均可见）。
3. 故 M4 的 Chrome 覆盖面有两条候选路线（见 §12.5），需用户裁定后才写动作代码。

### 12.4 本次会话运行态快照（16:0x 实测）

- 部署仍 `b008c9fae` / wecom stable gen **349**（started `2026-10-31T10:07:17+08:00`，pid 54712 存活）、`matches_desired_generation=true`、`admission_barriers=[]`、`restart_required=false`、四服务 `stage_facts` 均 `succeeded`。
- 仓 HEAD 仍 `55b53ab81`（= 部署 + 1 提交，**未上线**）；工作树脏且写者线仍活跃（见 §3.2 复核注）。**本会话未发 restart。**
- 探针残留已清理：临时 Chrome profile / 探针页已删；**无残留 Chrome 实例**（`pgrep` 仅 61931、96579 两个原有进程）。

### 12.5 仍待用户裁定的一件事（Chrome 网页层通道）

| 选项 | 做法 | 代价 | 备注 |
|---|---|---|---
| **A（推荐）** | M4 的 Chrome 网页层**走既有 CDP 通道**（`browser_operate` 已有 DOM+AX sensor）；M4 的 AX 通道只服务**原生 app**（Finder / Preview / TextEdit 等）+ Chrome 窗口 chrome 级动作 | 无需动部署、无需用户起进程 | 已实测网页层语义完整可得 |
| B | 人在自己终端起带 `--force-renderer-accessibility` 的独立 Chrome 实例，M4 继续走 macOS AX | 需人在场；实例生命周期与 profile 归人管 | 沙盒内**不可能**完成，已实测 |

> 裁定后本线才写 `desktop_operate` 动作代码；门控 / 一次性令牌 / 审计沿用设计书 §6，不新增进程。

---

## 14. 合并安全核验与发布待裁决（2026-10-31 20:4x，续接会话二）

### 14.1 事实基线已变：main 已前进 10 个提交

| 项 | 值 | 观测 |
|---|---|---|
| `<MIRROR>` HEAD | `511ae9075`（= `55b53ab81` + 10 提交） | 20:4x |
| 这 10 个提交 | write-scope D1/D2/D12 + T05 + `ci_gate.sh` 执行位 + gstack / frontend-design 技能移植 + `docs/SETTLEMENT-REF-FORMAT.md` | 同上 |
| 部署 | 仍 `b008c9fae` / wecom stable gen 349 / `matches_desired_generation=true` / `admission_barriers=[]` / `restart_required=false` | 20:38 |
| 写者线 | `write_scope.py` 18:25、`sandbox.py` 16:10、`command_scope_guard.py` 18:24（**已随提交入库**）；主树脏文件仅 `reports/**` + `docs/promotion/PLAN-20261011-*.md`，**与 M4 改动文件无交集** | 20:4x |

> 工作区两份文档的 §11.9 / §13 已由用户在沙盒外 apply 成功（本轮核验：设计书 1033 行、交接书 449 行，mtime 20:37，`git apply --check --reverse` → REVERSE_OK）。
>
> main 是**移动靶**：20:38 观测为 `06906c2a8`，20:4x 已到 `511ae9075`（其间新增提交只改 `docs/SETTLEMENT-REF-FORMAT.md`，与 M4 无交集）。指针分支按当时 main 生成，**合并前需重新对齐并重跑核验**。
>
> 文档小缺陷（未改）：本文存在**两个 `## 13`**（`13. M4 落地与审核` 与 `13. 续记二`），为前一批回填所致；本节不重编号以免打断交叉引用。

### 14.2 M4 合并安全核验（scratch 合并树，不碰 main、不碰 M4 worktree）

核验对象：`git merge-tree --write-tree main 4bc6cdec` → 无冲突；在 `/private/tmp/lfl-m4-merge-check`（detached from main + merge）实测：

| 检查 | 口径 | 结果 |
|---|---|---|
| 合并冲突 | `git merge-tree --write-tree main 4bc6cdec` | rc=0，无冲突文件 |
| Ruff | `ruff check`（M4 的 12 个改动 `.py`） | **All checks passed** |
| Pyright（权威） | `scripts/check_static_diagnostics.py --tool pyright` | **PASS**：`new=0`、`changed_file_diagnostics=0`、`changed_python_files=12`（M4 分支单跑同值 PASS） |
| pytest | M4 + `test_arch_guards` + `test_write_scope_contract` + `test_command_scope_guard` | **718 passed, 1 failed** |

**那 1 个 failed 不是 M4 引入的**：失败项为 `tests/unit/test_arch_guards.py::test_function_lines_ratchet_within_baseline`（`settlement.py::_submit_one` 登记 147→实测 152；`review_host_admission.py::_source_snapshot` 登记 173→实测 222）。在**只含 main 的干净检出**（`/private/tmp/lfl-main-baseline-check`，HEAD `06906c2a8`，不含 M4）上同一条用例**同样失败、报错文本一致** → 属另一条线已提交工作未重登记 function-size 基线，**不是 M4 回归**。

> 口径订正：`pyright` CLI 直接跑 M4 改动文件会看到 20 条 raw error（ctypes 动态属性 + 测试辅助函数的联合类型）；**仓库权威口径是 R9 棘轮**（冻结 ledger `b7ed6806d661`，`ancestry_enforced=True`），判定这些指纹已在历史账内 → `new=0`、改动文件零新诊断。两个数字不矛盾，引用时必须写清口径。

### 14.3 结论与待裁决

1. **M4 合进当前 main 无回归**：无冲突、静态门禁过、测试仅剩一条与 M4 无关的既存红灯。
2. **但仓库当前整体是红的**（那条 function-size 棘轮在 main 干净检出上即红）→ **发布不能只等 M4**，需另一条线先重登记基线（`python scripts/regen_function_size_baseline.py`）。
3. 已生成**已核验的合并提交** `d64c2fd5fd`（父 `511ae9075` + `4bc6cdec`），指针分支 `feat/m4-desktop-operate-20261031-merged`（只加引用指针，未动任何工作树）。用户侧快进：
   ```bash
   cd $HOME/Project/llm-first-loop-mirror
   git merge --ff-only feat/m4-desktop-operate-20261031-merged   # 与脏文件无交集，不覆盖他人改动
   ```
   （main 若再前进，需先重跑 14.2 的核验再快进。）
4. **仍未做**：未 push、未发 restart、未改任何 `tools_l0_enabled`。
5. 三个裁决点见 §13.5（上线时机 / restart 通道 / 冒烟脚本 P2）；其中上线时机现在多了「另一条线基线红灯」这一前置。
*本文为会话交接快照，事实截至 2026-10-31 20:4x（§11 续记 + §11.8 续接会话收口 + §12 续接会话二实测 + §13 M4 落地与审核 + §14 合并安全核验与发布待裁决）。新会话核验后请更新 §3 / §4，并把本文标为已归档。*

---

## 13. M4 落地与审核（2026-10-31 16:05–18:2x，续接会话）

本节记录路线 A 裁决后的 M4 交付、三轮审核与修复、父会话独立复验结果，以及**仍未验证/待裁决**的部分。

**13.1 路线 A 裁决（用户，16:05）**：Chrome 网页层走既有 CDP（`browser_operate` 已有 DOM+AX sensor）；M4 的 macOS AX 只服务原生 app + Chrome 窗口 chrome 级动作；不新增 CDP 通道、不动部署、不需用户在场。

**13.2 交付位置**：分支 `feat/m4-desktop-operate-20261031`，隔离 worktree `<MIRROR>/.worktrees/m4-desktop-operate-20261031`；R0 `66f093dfe` → R1 `6613b0c5a` → R2（见 13.4）。**未上线**（部署仍 `b008c9fae`）。开发报告：`<MIRROR>/data/deliverables/20261031/20261031-m4-dev-report.md`。设计书回填见 §11.9。

**13.3 三轮审核 → 修复**：

- R0（`66f093dfe`）：RULE-AI-28 宿主审核 **REVISE**（P0=0/P1=1/P2=10）；独立只读 reviewer **PASS** 但列 3 条「开写开关前必修」的 P1（发布类动作未接宿主发表闸 / 未纳入 `_is_destructive_tool` 逃逸 EXEC_MODE / point-scroll-press_key 的 Chrome 边界缺口）。
- R1（`6613b0c5a`）：修完上述全部必修项 + 10 项建议修；宿主审核仍 **REVISE**（P0=0/P1=1/P2=7）：F1–F12 键码表用推导式 `122 + i - 1`（f2 会送出左箭头键码）。父会话自查追加 2 条（审计写令牌明文前 12 字符；不纳入破坏性工具集合 → EXEC_MODE 约束不到桌面投递）也已在 R1 修掉。
- R2：外科修复轮（F 键表改字面量 + 门控顺序文档漂移 / cg_post_click 部分失败补偿 / 死状态 key_flags / 令牌 TTL 与淘汰 / world 指纹纳入 focused）。

**13.4 父会话独立复验（不采信自述）**：ruff PASS(new=0)、pyright PASS(new=0, changed_file_diagnostics=0)、`pytest tests/unit/test_desktop_operate_m4_v01.py tests/unit/test_desktop_perceive_m3_v01.py` → **150 passed**（R1 态）。RULE-AI-28 准入对 R1 判 REVISE，故**全量门禁尚未执行**（未获准入授权）。

**13.5 未验证边界（不得当作已验）**：本分支的**真实投递 live 证据仍缺**——17:32 实测 `desktop_perceive(status)` 返回 `screen_locked`（屏幕锁定，锁屏下感知与投递均被拒）；scroll 方向映射、press_key 对 Chrome chrome 级的可达性、CGEvent 兜底键入（中文输入法污染）、force 凭据的真正一次性审批通道、发布类宿主发表闸接入，均未验证/未实现。

**13.6 待裁决**：(1) M4 上线时机——需发 restart，而另一条线在主工作树有 in-flight 未提交工作（`write_scope.py` 等），本线不发；(2) live 投递复验需要解锁屏幕（当前 `screen_locked`）。


---

## 13. 续记二：M4 开发落地与 live 验收（2026-10-31 16:05–20:2x，本会话）

### 13.1 本会话做了什么

1. **接上 §12 的裁定**：路线 A（Chrome 网页层走既有 CDP，AX 只服务原生 app + Chrome 窗口 chrome 级动作）由用户于 16:05 拍板。
2. **TASK-007 从 blocked 转 in_progress**，M4 `desktop_operate` 正式开工：6 轮修复（R0–R6）、5 轮 RULE-AI-28 宿主审核（前 4 轮 REVISE、第 5 轮 PASS）、全量门禁通过。
3. **live 实测暴露两个静态审核覆盖不到的缺陷**：P0 所有权缺陷（`resolve_window_element` 释放了它正要返回的元素 → 所有 `ax_ref` 投递必然失败）、前台判据语义错误（拿 CG 窗口序当 app 焦点 → 合法投递被误拒）。两者均已修。
4. **取得 M4 首次端到端 A 级正向投递 live 证据**（真实机器）：dry_run（risk_class=irreversible、签发令牌）→ apply `ok=true / applied=true` → 世界指纹变化 → **目标窗口确实消失** → 审计行落盘。
5. **设计书回填**：§11.9 已补（交付物 / 契约 / 门控 / 六轮审核 / live 实测 / 未验证边界 / 门禁验收状态），并订正 §5.6 与 §11.8 里「M4 未实现」的过期口径。

### 13.2 关键事实订正（对本文前文的覆盖）

| 前文口径 | 订正 |
|---|---|
| §11.3「AXPress / AX set-value 投递已 PROVEN」 | 该证据来自**独立临时探针直接调 AX API**，**不经过本工具的寻址路径**；工具路径首次 live 实测即失败（P0）。声称应限定为「macOS AX 通道本身可用」 |
| §11.7 探针 5「Chrome 网页层 AX 确认不可达」 | 仍然成立；路线 A 已定为既有 CDP |
| §11.5「M4 / desktop_operate 未开工」 | 已过时：**已实现并过门禁**（最终提交 `4bc6cdec`），并已取得一次正向投递 live 证据 |
| §4 表「TASK-007 blocked（需裁定 Chrome 路径）」 | 裁定已完成（路线 A）；当前状态见 §13.5 |

### 13.3 live 证据与仍未验证的边界

- **已取得（正向）**：`click` + AXCloseButton 一条路径的端到端投递（dry_run → 令牌 → apply applied=true → 目标窗口消失 → 审计落盘），真实机器，20:2x。
- **仍未验证**：`type` 键入、`scroll`、`press_key`、`point` 坐标点击的**正向**投递（只有离线单测与设计约束）；网页层目标（路线 A 下由既有 CDP 承担，网页内元素动作不由本工具提供）；`type` =2000 接受侧；`scroll` 方向符号；CGEventPost 投递不可观测。
- **已披露的残余风险**：全局 HID 投递可能落到浮层（world 指纹不含 Z 序/焦点）；session 免令牌跳过 world 比对（记账已收紧到 app+do+目标身份）；`type` 为整体替换语义（破坏性）。
- **环境约束**：屏幕反复自动锁定（`desktop_perceive(status)` → `screen_locked`；`lsappinfo front` → `com.apple.loginwindow`）。live 正向复跑需要「解锁 + 用户静默 ≥60s」，否则 D7 在场门会确定性拒绝（已实测：`hid_idle_ms=2454` → `user_present`）。
- **脚本 P2（待下一轮）**：仓内 `scripts/desktop_operate_live_smoke.py` 的「窗口已消失」判定只看 CGWindowList，而该列表对已销毁窗口有残留条目 → 第一次成功投递后误报 False。改为「CG 缺失 **或** AX 侧解析不到」后判定稳定（本地副本已验证，未改动已过门禁的产物）。

### 13.4 当前仓库/部署态

- `<MIRROR>` HEAD 仍是 `55b53ab81`（部署 + 1 提交，未上线）。M4 分支在隔离 worktree `<MIRROR>/.worktrees/m4-desktop-operate-20261031`，最终提交 `4bc6cdec`（相对基线 12 文件 +5329/-30），**未合并、未 push**。
- 部署仍 `b008c9fae` / wecom stable gen 349 / `matches_desired_generation=true` / `admission_barriers=[]`（20:0x 实测）。
- **活跃写者未变**：`<MIRROR>` 工作树仍脏（`write_scope.py` 15:29、`sandbox.py` 14:16、`command_scope_guard.py`、两个测试文件、19+ 个 `reports/**`、未跟踪 `.patches/` 与 `data/methods/*`）。本会话**未碰这些文件、未 stash / reset / 提交他人改动、未发 restart**。

### 13.5 交给下一会话/用户的裁决点

1. **M4 上线时机**：`4bc6cdec` 何时合并进主仓并发布（随下一次 restart，或等另一条线的 in-flight 工作收口后一起）。
2. **合并方式**：主工作树当前有他人未提交改动，直接合并有覆盖风险——建议由主仓侧在干净树上合并（或等他人线收口）。
3. **restart 通道**：web 承载发起会话时 restart 会停在 `waiting_for_requester_exit`，需另择通道或接受等待。
4. **脚本 P2**：仓内冒烟脚本的窗口消失判定是否本轮补（5 行改动，需重跑门禁）。

> 本文事实截至 2026-10-31 20:2x（§13 本会话续记）。§1–§12 中被本节覆盖的口径以本节为准。


---

## 15. M4 已快进合入 main + 复验 + 与另一条线压缩集的兄弟分歧（2026-10-31 21:2x–21:4x）

### 15.1 裁决与执行

用户 21:29 裁决 **①**：把 M4 指针分支快进合入 main，**不发布**；等另一条线重登记 function-size 基线、仓库转绿后再一起发 restart（裁决 ② restart 通道、③ 冒烟脚本 P2 本轮未答）。

执行结果（21:30–21:31）：

| 项 | 值 |
|---|---|
| main | `511ae9075` → **`d64c2fd5fd`**（合并提交，父 = `511ae9075` + `4bc6cdec`；CAS `git update-ref refs/heads/main`） |
| 发布动作 | **未发**；未改任何 `tools_l0_enabled` |
| 脏文件数 | 104 → **104**（逐项一致） |
| M4 的 12 个文件 | 合并后**干净**（`git status --porcelain -- <12 路径>` 仅 `factory.py` 一行，且是另一条线的改动） |
| 另一条线在制品 | 原样保留；`factory.py` 相对新 HEAD 仅剩其 **6+/1−**（unstaged，量与其原始补丁一致）；其余 103 项未动 |

### 15.2 唯一碰撞点：`src/llm_loop/factory.py`

M4 与另一条线**都改**该文件（M4 加 `desktop_operate` 注册；对方改 schedule 的 `wake_model` → `model_override`）。两侧基线同为 blob `6a3d49f63`，hunk 不重叠。

处置（无冲突；未 stash / 未 reset / 未提交他人改动）：

1. `git merge-file -p --diff3 <M4版> <511ae9075版> <对方工作区版>` → **rc=0、0 个冲突标记**；merged 相对 M4 版 = 对方那 **6+/1−**，相对对方工作区 = M4 那 **29+/7−**（双向差集均精确等于对方）。
2. `git checkout d64c2fd5fd -- <12 个 M4 文件>` → index + worktree 对齐合并提交（这 12 个文件此前均无本地改动）。
3. 把 merged 写回工作树 `factory.py`（保留对方改动，叠加在 M4 基座上）。
4. `git update-ref refs/heads/main d64c2fd5fd 511ae9075`（CAS）移动 main。

### 15.3 合并后复验（干净检出：detached `d64c2fd5fd`）

| 项 | 结果 |
|---|---|
| ruff（M4 改动文件） | **All checks passed** |
| R9 棘轮 `--tool ruff` | **PASS**：historical=67, current=29, **new=0**, resolved=38, changed_file_diagnostics=0, changed_python_files=12 |
| R9 棘轮 `--tool pyright` | **PASS**：historical=45, current=10, **new=0**, resolved=35, changed_file_diagnostics=0, changed_python_files=12 |
| 定向 pytest（M4 + 护栏 + write-scope/守卫 + desktop_perceive） | **799 passed, 1 failed** |
| 唯一失败 | `tests/unit/test_arch_guards.py::test_function_lines_ratchet_within_baseline` |

**既有红的归因（对照实验）**：在**只含合并前 main（`511ae9075`）**的干净检出上跑同一条用例 → **同样失败、报错文本逐字一致** ⇒ 该红**不是 M4 引入**，是另一条线已提交工作未重登记 function-size 基线。

红的内容：基线文件 `tests/guards/function_size_baseline.json`（mtime 10-31 02:36，最后由 `24b238967` 登记）仍记 `settlement.py::_submit_one=147`、`review_host_admission.py::_source_snapshot=173`、`::start=190`；在合并后 main 上实测为 **152 / 222**（`::start` 未超）。在对方的压缩集树上还多两项：`_source_snapshot` 同为 222、`::start` 190→192，外加**未登记函数** `review_host_admission.py::poll`（实测 124 ≥ 120 阈值）。

### 15.4 新事实：另一条线的压缩集与本线是**兄弟分支**（21:32）

| 项 | 值 |
|---|---|
| 对方 desired | **`62939c22`**（`feat(main): 整合待推集为单一提交`，21:22，父 = `55b53ab81`） |
| 是否含 M4 | **否**（祖先判定 `git merge-base --is-ancestor d64c2fd5fd 62939c22` → M4_IN_DESIRED=NO） |
| 关系 | 与本线 `d64c2fd5fd` **同父 `511ae9075` 的兄弟**（互不为祖先） |
| 两棵树差异 | M4 的 12 个文件（对方树里不存在）+ 对方的 `src/llm_loop/tools/review_host_admission.py`(+130) 与 `tests/unit/test_review_host_admission.py`(+162) |
| 对方压缩集相对 `511ae9075` | 仅改这 2 个文件（其余 skills / write-scope / docs 内容已在 main 的 10 个提交里） |
| 主树工作区这 2 个文件 | 与对方提交版**逐字节一致**（`git diff 62939c22 -- <两文件>` 为空）→ 对方在制品已全部落进 `62939c22`，主树这份「脏」只是未并入 main |
| 部署态（21:3x 实测） | live=`b008c9fae`，desired=`62939c22`，`matches_desired_generation=false`，`restart_required=true`，`admission_barriers=[web/restart svc-01242a79b77943f78e0eeda8b3be73b0]`；stage_facts：feishu/learning/wecom=**failed**、web=`waiting_for_idle` |

**含义**：在飞的那次 restart 发布的是**不含 M4** 的树。要让 M4 上线，必须**再发一次含 M4 的 desired**（本线 `d64c2fd5fd` + 对方压缩集内容），不能指望这次 restart 顺带带出。

### 15.5 发布前置条件（本线 checklist）

1. **仓库转绿**：等另一条线跑 `python scripts/regen_function_size_baseline.py` 并提交（`guard(r9)` 前缀提交）。**两棵树目前都红**（§15.3）——包括对方正在发布的那棵。
2. **合并对方压缩集**：让 main 同时含 M4 与对方的 `review_host_admission.py` 改动（内容互不重叠，预计可干净合并；主树工作区该文件与其提交版逐字节一致，合并不会覆盖其在制品）。**本轮未做**——对方 restart 在飞、树仍脏，等其收口后再动，避免把 M4 意外带进在飞的那次发布。
3. **RULE-AI-28 准入**：对**当时**产物取 git_push 门禁的独立审核 PASS（旧 PASS 不可复用；M4 自身的第 5 轮 PASS 见 §13 / 设计书 §11.9）。
4. **裁决 ②**：restart 通道（web 承载本会话会停在 `waiting_for_requester_exit`）。
5. **裁决 ③**：仓内冒烟脚本 P2（窗口消失判定加 AX 兜底；补则重过独立审核）。

### 15.6 本轮未验证的边界

- **未做 M4 的 live 动作复验**：本轮只做代码层核验（ruff / R9 / pytest）；M4 的真机投递证据仍以 §13 用例 10–11 为准，未新增。
- **未重测 Chrome 网页层 AX**：口径沿用 §12.5（沙盒内不可激活；CDP 通道可用）。
- **未发布**：M4 与那 10 个提交**均未上线**（live 仍 `b008c9fae`）。
- 本轮新增的临时检出已 `git worktree remove` 清理；合并前 `factory.py` 的原始副本与补丁留在 `/tmp/lfl-m4-ff/`（可回溯）。


---

## 16. 收口：M4 已上线 gen 353 + 部署后复验 + 最终验收（2026-11-01 10:0x–10:2x，续接会话三）

### 16.1 发布事实与 §15.5 前置对账

- 部署 head `ce205a4da` / wecom stable **gen 353**（10-31 22:36:45 起，pid 53803 存活），`matches_desired_generation=true`、`admission_barriers=[]`、`restart_required=false`。
- **M4 在部署内**：`4bc6cdec` ⊆ `ce205a4da`（祖先判定实测）；浏览器侧基线 `b008c9fae` ⊆ `ce205a4da`；对方压缩集 `62939c22` ⊆ `ce205a4da`（三项 11-01 10:2x 实测）。
- §15.5 前置对账：②「合并对方压缩集」**完成**（`ce205a4da` merge 信息可证）；①「仓库转绿」**未满足**——function-size 棘轮在 `ce205a4da` 上仍红（11-01 10:02 实测 1 failed；既有红、非 M4 引入，登记权在另一条线，见设计书 §11.11-B/C、§11.12-B）；③ RULE-AI-28 准入按 §15.5-3 口径执行与否本线无回执；④ restart 通道：发布已完成（gen 353 stable succeeded），本线无该时段回执，不评过程；⑤ 脚本 P2 **未合入**（`ce205a4da` 版 `desktop_operate_live_smoke.py` 378 行，「窗口已消失」判定未含 AX 兜底——11-01 10:2x 源码核对；若补需重过门禁）。
- learning durable 回执 `failed` 为 gen 352 遗留（live `matches_desired_generation=true`），回执滞后、非故障。
- §13.5 裁决点状态：① 上线时机→**已执行**（10-31 22:36 发布）；② 合并方式→**已执行**（`integrate/main-20261031` → main，merge `ce205a4da`）；③ restart 通道→发布已成功（过程无回执）；④ 脚本 P2→**未补**（遗留）。

### 16.2 部署后 live 复验（2026-11-01 10:03–10:05，全 PASS）

| # | 项 | 实测 | 判定 |
|---|---|---|---|
| 1 | `desktop_perceive status` | ok；can_list_windows=true；TCC 位 false（已知假阴性，§6.1-1 以探针判）；单屏 1512×982 pt / scale 2.0 | PASS |
| 2 | `desktop_perceive windows` | ok（含 Chrome window_id 121392） | PASS |
| 3 | `desktop_perceive snapshot` | Terminal `yyj`：ax.available=true、26 节点、binding=bounds_only、clipped_depth=false | PASS |
| 4 | `desktop_operate` dry_run ×2 | Chrome 121392 scroll point (600,300)/(30,300)：ok=true，各签发一次性 confirm_token、needs_confirmation=true、零投递 | PASS（门控 live 生效） |

明细与设计书 §11.12-C 同源（同一批实测回执）。

### 16.3 用户裁决（11-01 10:18，裁决②）与 TASK-008 收口

- 用户选 ②：接受「fail-closed 验证 + 开发期投递证据」为已足，不做部署后真机 apply 复验（选项 ① 的 `LFL_DESKTOP_OPERATE_ENABLED` 开启 + 静默窗口补测不再执行）。
- 任务图：TASK-007 已收（11-01 10:03 frontier：open=1，11 done）；TASK-008 以本节 + 设计书 §11.12 + 新增 `20261101-m0-m4-final-acceptance.md`（补丁 `20261101-ws-backfill-final-acceptance.patch`）收口。
- 真机投递证据最终口径：`click`+AXCloseButton 端到端一条路径（10-31 用例 10，A 级，含 dry_run→令牌→apply applied=true→窗口消失→审计落盘）；`type`/`scroll`/`press_key`/`point` 无真机投递记录，部署后仅 dry_run 门控验证。

### 16.4 终局未验证边界（不得当作已验）

1. M4 正向投递仅 `click`+AXCloseButton 一条路径有真机证据；`type`/`scroll`/`press_key`/`point` 无真机 apply 记录（部署后未做真实投递）。
2. `type` =2000 接受侧未 live 测；`scroll` 方向符号未 live 验证；CGEventPost 投递不可观测。
3. Chrome 网页层 AX 不可达（`-25211` / `AXWebArea=0`）：网页内元素动作由 `browser_operate`（CDP，路线 A）承担，`web_target_not_allowed` 路由。
4. CGEvent 键入不提供（中文输入法污染）；键入只走 AX set-value。
5. 锁屏态 / 多显示器跨屏 scale / 非整数缩放未验证（本机单屏 2.0x）。
6. D4 多命中 `window_ambiguous` 歧义拒绝未重测。
7. 冒烟脚本 P2（窗口消失判定 AX 兜底）未合入 `ce205a4da`。
8. 发布时 function-size 棘轮仍红（既有红、非 M4 引入）——**移交另一条线**（基线登记 `regen_function_size_baseline.py`）。
9. learning durable 回执 `failed`（gen 352 遗留，live 正常）——回执滞后，待其下次 stable 动作刷新。

### 16.5 归档

*本文就此归档：桌面 GUI 能力与浏览器工具补强线（GOAL-20261027-c78e2aac）交付完成。事实截至 2026-11-01 10:2x（§16 续接会话三收口）。后续会话以 `20261101-m0-m4-final-acceptance.md` 为验收真值，本文仅作过程档案。*
