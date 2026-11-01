# M0–M4 最终交付验收与总结（GOAL-20261027-c78e2aac）

| 项 | 内容 |
|---|---|
| 生成 | 2026-11-01 10:2x（TASK-008 收口，用户裁决②） |
| 验收人 | 父会话（LFL）；开发由 dev 子代理执行；独立审核 5 轮 |
| 基线部署 | wecom stable **gen 353** / `ce205a4da`（2026-10-31 22:36:45 起，pid 53803） |
| 真值源 | 设计书 `20261027-desktop-gui-and-browser-tooling-design.md`（§11.1–§11.12）；过程档案 `20261031-handoff-desktop-browser-line.md`（§11–§16） |

## 0. 一页结论

1. **浏览器侧全部交付并上线**：M1 P0（B1 upload / B2 type / B10 vision 元数据）、M2 批A/批B（B3–B9、B15）、B5 生命周期修复、R5 dialog 快路径、10-28~30 四笔补丁——基线 `b008c9fae` ⊆ 部署 `ce205a4da`（祖先判定实测）。
2. **桌面侧全部交付并上线**：M0 探测（推翻「必须独立宿主进程」假设）、M3 只读感知（`desktop_perceive` 四动作）、M4 窄操作（`desktop_operate`，`4bc6cdec` ⊆ `ce205a4da`）。
3. **M4 真机投递证据**：`click`+AXCloseButton 端到端一条路径（10-31 用例 10，A 级）；其余动作类型按用户 11-01 10:18 裁决②接受「fail-closed 验证 + 开发期投递证据」为已足；部署后 live 复验（感知 3 项 + dry_run 门控 2 连）全 PASS、零投递。
4. **两条已知遗留移交**：function-size 棘轮在 `ce205a4da` 仍红（另一线登记权）；learning durable 回执 `failed`（gen 352 遗留，live 正常）。

## 1. 验收基线（部署事实，11-01 10:02 / 10:17 两次实测）

| 项 | 值 |
|---|---|
| git_head | `ce205a4da`（merge `integrate/main-20261031` into main；含 M4 `4bc6cdec`、浏览器基线 `b008c9fae`、对方压缩集 `62939c22`） |
| wecom stable | gen 353，started 2026-10-31T22:36:45+08:00，pid 53803 存活 |
| 一致性 | `matches_desired_generation=true`、`admission_barriers=[]`、`restart_required=false` |
| stage_facts | feishu / web / wecom = succeeded；learning = failed（gen 352 遗留回执，live `matches_desired_generation=true`，回执滞后） |

## 2. 浏览器侧交付与证据

| 能力 | 交付内容 | 证据 |
|---|---|---|
| M1 P0 | B1 upload（允许根=工作区）；B2 type（≤2000 运行时强制，契约层+adapter 两层拒绝，schema 不再声明 maxLength）；B10 vision 元数据（同 sha 复用标注 `content_unchanged`） | live：`20261028-live-smoke-b1-b2-b10.md` |
| M2 批A | B3 press_key（Meta 系黑名单）、B4 hover、B5 dialog、B6 download_state | 批A `820eeb1b9`；live：`20261028-live-smoke-b3-b5-b7-dialog-and-ax-binding.md` |
| M2 批B | B7 wait absent+settle、B8 frame_token、B9 pages 只读、B15 后备寻址（跨版本 stale 标注） | 批B `61a54ae85`；全量 11689 passed |
| 修复与补丁 | B5 生命周期 `919b9881f`；R5 快路径 `4d63a3b85`；type 上限+D4 `title_relaxed` `55aff5b73`；`reject_reason` 整类提升+候选窗 `frame_token` `4d7dc24ef` | 四笔均 in-deployed（merge-base 逐个实测）；TASK-010 三次独立 live 复验 PASS（交接书 §11.1 / §11.8-A / §12.2） |

## 3. 桌面侧交付与证据

| 里程碑 | 交付内容 | 证据 |
|---|---|---|
| M0 探测 | D0 归因：TCC 本有（屏幕录制/辅助功能 ✓），沙盒只拦 AppleEvent（-10004）≠ AX；推翻「必须独立宿主进程」前提 | `20261027-d0-desktop-capability-report.md`（13 条 A 级） |
| M3 只读 | `desktop_perceive`：status / apps / windows / snapshot；默认零截图；敏感 app 名单硬编码 | `20261027-m3-dev-report.md` §12.6；L2 截图 0px 偏差；D4 `title_relaxed` PASS（TASK-010） |
| M4 窄操作 | `desktop_operate`：click / type / press_key / scroll；dry_run→一次性令牌→apply 三级门控；审计 append-only；`LFL_DESKTOP_OPERATE_ENABLED` 写总开关默认关 | `4bc6cdec`（12 文件 +5329/-30，含 2115 行单测）；5 轮独立审核 PASS（第 5 轮冻结产物）；ci_gate exit 0；父会话复验 227 passed；合并 `d64c2fd5fd` → main；上线 gen 353 |

**M4 真机 live 证据（10-31 18:05–20:2x）**：门控负向（非白名单 3 连拒+审计落盘；`user_present` 在场门实测拒绝）；正向端到端一条路径（用例 10：dry_run→令牌→apply applied=true→窗口消失→审计落盘）。**部署后复验（11-01 10:03–10:05）**：感知 3 项 + dry_run 门控 2 连全 PASS、零投递。

## 4. 裁决记录（不可重开）

| 时点 | 裁决 |
|---|---|
| 10-27 设计期 | Q1(a→实际推进至 M3)、Q2 白名单 Finder/Safari/Chrome/Preview（终端/IDE 只读）、Q3(b) 截图允许读但默认关+逐次显式+敏感拒拍、Q4(b) 单步、Q5(a) upload 仅工作区、Q6(b) 同 sha 只标注 |
| 10-31 15:11 | M4 进（三前置已当面复述） |
| 10-31 16:0x | Chrome 网页层走路线 A（既有 CDP；`web_target_not_allowed` 路由到 `browser_operate`） |
| 10-31 21:29 | M4 快进合入 main、暂不发布 |
| 10-31 22:36 | 发布 gen 353（`ce205a4da`；本线无该时段回执） |
| 11-01 10:18 | 裁决②：接受「fail-closed 验证 + 开发期投递证据」为已足，不做部署后真机 apply 复验 |

## 5. 终局未验证边界（不得当作已验）

1. M4 正向投递仅 `click`+AXCloseButton 一条路径有真机证据；`type` / `scroll` / `press_key` / `point` 无真机 apply 记录（部署后未做真实投递，10:05 两连均 dry_run）。
2. `type` =2000 接受侧未 live 测；`scroll` 方向符号未 live 验证；CGEventPost 投递不可观测（只能事后核对世界状态）。
3. Chrome 网页层 AX 不可达（`-25211` / `AXWebArea=0`）；网页内元素动作由 `browser_operate`（CDP）承担。
4. CGEvent 键入不提供（中文输入法污染）；键入只走 AX set-value。
5. 锁屏态 / 多显示器跨屏 scale / 非整数缩放未验证（本机单屏 2.0x）。
6. D4 多命中 `window_ambiguous` 歧义拒绝未重测。
7. 冒烟脚本 P2（窗口消失判定 AX 兜底）未合入 `ce205a4da`。
8. 发布时 function-size 棘轮仍红（既有红、非 M4 引入）——移交另一条线。
9. learning durable 回执 `failed`（回执滞后，live 正常）。
10. 沙盒内 AppleEvent（-10004）不可用口径不变；`AXIsProcessTrusted` 假阴性，能力以探针判。

## 6. 证据索引

- 设计 / 报告：`docs/design/20261027-desktop-gui-and-browser-tooling-design.md`（§11.1–§11.12）、`20261031-handoff-desktop-browser-line.md`（§11–§16，过程档案）、各里程碑报告与 live smoke 文档（索引见交接书 §9.1）。
- 补丁交付：`<MIRROR>/data/deliverables/20261031/`（四份 ws-backfill + probe log）、`data/deliverables/20261101/20261101-ws-backfill-final-acceptance.patch`（本文 + 设计书 §11.12 + 交接书 §16）。
- 代码锚点：交接书 §9.2（`browser_semantic_operation.py` / `net_guard.py` / `src/llm_loop/desktop/` 等）。
