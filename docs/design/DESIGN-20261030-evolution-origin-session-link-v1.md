# 演进建议「来源会话本地连接」实现设计书 v1

- 文档类型：design（含需求审查）
- 日期：2026-10-30
- 状态：已实施并经独立审查 **PASS**（P0=0 / P1=0 / P2=7；回执 `reports/review-20261030-evolution-origin-session-link.md`，被审提交 20e6db475）
- 关联规则：RULE-AI-01（事实与完成诚实）、RULE-AI-23（授权边界）、RULE-AI-24（防退化）

## 0. 结论摘要

1. **建议本身已保存完整来源会话标识**：`submit_evolution` → `EvolutionStore.submit()` 会把 `bound_session_id()` 原样写入 `session_id` 字段（`src/llm_loop/introspection/tools_evolution.py`、`src/llm_loop/introspection/evolution.py`），未截断、非短号。当前数据 231 条中 174 条带该字段，57 条为历史记录缺失。
2. **缺口在投影与交互，不在数据**：web 端列表、详情、单条审批、批量审批四个出口都不返回 `session_id`，前端类型里也没有该字段，因此审批者看不到、也点不开来源会话。
3. **"本地连接"应落成"会话深链"，不是连接对象**：浏览器 WebSocket 连接无法在审批时刻跨进程保留；可持久化的真值是 `session_id`，深链在渲染时用当前 `location.origin + ?session=<id>` 生成（不存端口/主机，避免换端口失效）。
4. **跨工作区不是边缘情况，而是主路径**：`?session=` 深链依赖当前工作区的 `sessions_dir`。实测 174 条有 `session_id` 的建议中，161 条来源会话属于 `<home>/lfl-workspace`，仅 10 条在当前 mirror 工作区。只做深链，约 93% 的建议点开后落空。必须新增轻量"会话定位器"并按需切换到目标工作区。
5. **"点开即粘贴"不新增发送行为**：只切会话 + 把回执填入输入框并聚焦，是否发送由人决定（不代发，符合授权边界）。已有草稿一律追加而不覆盖。

## 1. 需求与解读

### 1.1 原始诉求

> web 端演进建议应该保留完整会话的本地连接，例如，这样审批后知道是哪个连接提交的。最好审批后复制按钮下面可以直接点开该连接进行粘贴。

### 1.2 可验收分解

| 编号 | 诉求 | 验收口径 |
|---|---|---|
| R1 | 保留完整会话标识 | 每条建议可读出完整 `session_id`（UUID 全量），新旧记录行为明确 |
| R2 | 审批后知道来源 | 审批面板的条目/回执区展示来源会话标识，可复制 |
| R3 | 复制按钮下可直接点开 | 回执区"复制回执"下方有入口，点击后落到来源会话输入框（回执已粘好） |

### 1.3 边界澄清（必须先说清）

- **"连接"= 会话 + 本地深链**，不是浏览器/WebSocket 连接对象，也不是审批者当前的 tab。审批者与提交者可能不是同一个人、同一浏览器。
- **不保存完整 URL 字符串**：web 端口可变（dev/prod/重发布），持久化 `http://127.0.0.1:xxxx/?session=...` 会过期；只存 `session_id`，链接实时构造。
- **不自动发送**：填入输入框即止。"点开就能粘贴"指的是省掉手工粘贴，不是代发。
- **历史 57 条无法回填**：该信息从未落盘，只能标注"未记录"。

## 2. 现状核实（当前代码快照）

| 事实 | 位置 |
|---|---|
| 提交时写入完整 `session_id`（`bound_session_id()`） | `src/llm_loop/introspection/tools_evolution.py`（submit 调用处） |
| 存储字段模型含 `session_id` | `src/llm_loop/introspection/evolution.py`（`EvolutionStore.submit`） |
| 列表投影不含 `session_id` | `src/llm_loop/web/routes.py:2993` 起的 `out.append` |
| 详情投影不含 `session_id` | `src/llm_loop/web/routes.py:3041` 起 detail 返回体 |
| 单条审批响应不含 `session_id` | `src/llm_loop/web/routes.py:3120-3228`（`return {"ok": True, "text": text, "reviewed": reviewed}`） |
| 批量审批结果不含 `session_id` | `src/llm_loop/web/routes.py:3232` 起，results 仅 `id/ok/message` |
| 审计只记审批动作，不记被审批建议的来源 | `_log_web_review`（`routes.py:3084` 附近） |
| 前端类型无 `session_id` | `webui/src/components/sidebar/EvolutionPanel.tsx:10-34`（`EvoItem`/`EvoDetail`） |
| 回执状态仅 `{text, hint}`，复制按钮在回执块内 | 同上 `:165`（状态）、`:342-367`（回执渲染）、`:358-365`（复制按钮） |
| 会话深链能力已存在 | `webui/src/core/sessionUrl.ts`（`buildSessionShareUrl` 用 `?session=`） |
| 跨工作区打开会话能力已存在 | `webui/src/components/sidebar/WorkspaceGroups.tsx:120-140`（先切 workspace 再开会话）、`Sidebar.tsx:398` |
| 工作区切换 API 存在 409 `workspace_busy` | `src/llm_loop/web/routes.py:4938` 起 `workspace_transition` |
| 跨工作区会话列表 API 已存在 | `src/llm_loop/web/routes.py:4862` 起 `/api/v1/workspaces/{id}/sessions` |
| 输入框预填机制已存在（草稿可编辑、不自动发送） | `webui/src/core/conversation.ts:109`（`prefillComposer`）、`Composer.tsx:219-250` |
| 切会话会重置预填（关键竞态） | `conversation.ts:151-190`：`composerPrefill` 被重置为 `deferredWithdrawals.get(next) ?? null` |

### 2.1 数据实况（已实测）

- `data/audit/evolution_suggestions.jsonl`：231 条，其中 174 条含非空 `session_id`，57 条缺失；`session_id` 为完整 UUID，无截断。
- 会话文件布局：`data/sessions/<workspace-slug>/<session_id>.json`（每个工作区一个目录，另有 `data/sessions/.identity` 身份会话目录）。因此**不能用 session_id 拼路径**，必须按工作区定位。
- 来源会话分布（174 条有 sid 的记录，按 `data/sessions/*/<sid>.json` 实测）：
  - 172 条可在已注册工作区目录找到；1 条仅存在于 `.identity`；1 条已彻底不存在。
  - 其中 **161 条属于 `--Users-<user>-lfl-workspace--`**（`<home>/lfl-workspace`），10 条属于当前 mirror 工作区，1 条属于 `<home>/Project/research`。路径以 `<home>` 代指用户主目录，避免绝对路径进入文档。
  - 结论：**跨工作区打开是主路径（约 93%），不是边缘情况**。若只做 `?session=` 深链，绝大多数建议点开后都会落空。
- `data/workspaces.json` 中当前工作区为 `--Users-<user>-Project-...releases-8c11...--`，共注册 38 个工作区，`--Users-<user>-lfl-workspace--` 已注册、可切换。

## 3. 差距与审查发现

- **F1（阻断 R2/R3）**：四个后端出口都不返回 `session_id`，前端拿不到来源。
- **F2（R3 会落空，实测确认）**：来源会话可能属于其他工作区；`?session=` 深链只对当前工作区的 `sessions_dir` 生效。实测 172 条可定位来源中 161 条在其他工作区（`<home>/lfl-workspace`），只做深链则 93% 的建议点不开。必须做"定位 + 按需切工作区"，且切换属于全局上下文变更（`engine.set_workspace`），需在按钮上显式标注目标工作区。
- **F3（数据一致性）**：`submit_evolution` 的 `session_id` 来自工具执行绑定会话，若工具在无会话上下文（批处理/脚本）调用则为空串——UI 必须按"未记录"处理而不是显示空标签。
- **F4（草稿风险）**：`Composer` 的预填是"追加到当前草稿"（`Composer.tsx:219-231`）。若目标会话已有用户草稿，直接覆盖会丢输入；直接追加会产生"旧草稿 + 回执"的混合文本。需明确规则并提示。
- **F5（批量语义）**：批量审批一次可能批多个来源会话的建议，单个"打开该连接"按钮语义不成立，需要按来源分组。
- **F6（审计缺口）**：审批审计只记录审批者与建议 id，不记录建议的提交会话，事后无法把"谁提的"与"谁批的"对上。

## 4. 方案设计

### 4.1 数据契约

- 真值：`session_id`（建议记录内已有字段），**不新增 URL 字段、不新增端口字段**。
- 深链构造：`buildSessionShareUrl(sessionId)`（已存在），落点为 `<origin>/?session=<session_id>`。
- 工作区归属**不落盘**（首版）：由定位器在点击时反查已注册工作区，避免改 `submit` 签名与工具上下文，且历史 174 条立刻受益。
- 可选 P1：`submit` 额外落 `session_workspace_id`，用于工作区被删除/移动后仍能给出准确原因；不进入首版范围。

### 4.2 后端改动（最小面）

1. `GET /api/v1/evolution/list`：每行加 `"session_id": d.get("session_id", "")`。
2. `GET /api/v1/evolution/detail`：返回体加 `"session_id": d.get("session_id", "")`。
3. `POST /api/v1/evolution/review`：返回体加 `"session_id": (cur_after or cur).get("session_id", "")`。
4. `POST /api/v1/evolution/review-batch`：`results[]` 每项加 `session_id`（取审批后条目；无则空串）。
5. 新增 `GET /api/v1/evolution/session-locator?session_id=<sid>`：
   - 参数校验：`session_id` 必须是 `^[0-9a-fA-F-]{8,64}$`（拒绝 `/`、`..`、空串），否则 400 `invalid_params`——这里直接拼文件名，必须先做形状校验防路径穿越。
   - 定位方式：**只做 `isfile` 探测，不调用 `list_sessions_in`**（后者要解析目录内全部会话 JSON，38 个工作区代价过大）。逐工作区检查 `Path(settings.sessions_dir) / ws.id / f"{sid}.json"`。
   - 顺序：当前工作区（`engine.workspace_store.get_current()`）优先 → 其余 `store.list()`；命中即返回并附 `current: true/false`。
   - 命中：`{"ok": true, "available": true, "session_id": sid, "workspace_id": ws_id, "workspace_path": ws.path, "current": bool}`。
   - 未命中：`{"ok": true, "available": false, "reason": "not_found"}`（200；"定位不到"是正常结果）。
   - 只存在于 `data/sessions/.identity/<sid>.json`：返回 `reason: "identity_only"`，web 侧不可打开（身份会话不在工作区会话列表），UI 明确提示而不误导。
   - 归档会话：文件仍在工作区目录（`include_archived` 只是元数据过滤），因此 isfile 命中；前端是否允许打开由会话列表是否可见决定，不可见时按"不可直接打开"处理。
   - 异常：`{"ok": true, "available": false, "reason": "locator_failed"}`，fail-open，不 500。
   - 性能：一次调用 ≤ 38 次 `stat`，微秒级；不做文件系统递归猜测。
6. `_log_web_review` 增加可选入参 `suggestion_session_id`，写入审计行；调用处传 `cur/cur_after.get("session_id", "")`。这是可追溯性的补齐，不改变审批语义。

### 4.3 前端改动

1. 类型：`EvoItem`/`EvoDetail` 加 `session_id?: string`；新增 `EvoSessionLocator`。
2. 回执状态：`reviewReceipt` 由 `{text, hint}` 扩为 `{text, hint, origins: Array<{sessionId: string; evoIds: string[]}>}`。
   - 单条审批：用响应里的 `session_id`（空串则不产生 origin）。
   - 批量审批：用 `results` 中 `ok` 且有 `session_id` 的项，按 `session_id` 去重分组。
3. 回执区渲染（复制按钮正下方）：
   - 首行："来源会话：`<完整 sid>`"（等宽、可选中复制；空则"来源会话未记录（旧记录）"）。
   - 按钮：「打开来源会话并粘贴」，每来源一个（最多 3 个，其余显示"等 N 个"），`data-testid="evo-open-origin-session"`。
   - 无可达来源（旧记录）时不渲染按钮。
4. 点击处理 `openOriginSession(sessionId)`：
   1. `GET session-locator`；
   2. 不可达（`not_found` / `identity_only` / `locator_failed`）→ 不导航，按钮转 disabled + 按 reason 给不同原因（会话已被删除 / 属于身份会话，web 不可打开 / 定位失败请重试），完整 sid 仍可见可复制；
   3. 跨工作区（实测主路径，约 93%）：按钮先显示"打开来源会话（切换到 `<workspace_path>`）"；点击 → `POST /api/v1/workspaces/switch` → 成功后 `setCurrentSession(sid)`；`409 workspace_busy` → 提示"当前会话运行中，暂不能切换工作区"，保留复制入口；`403 workspace_not_allowed` → 提示目标工作区不在允许根内，无法切换；切换失败一律**不导航**；
   4. `sessionStore.setCurrentSession(sid)`（`App.tsx:118` 的 effect 会同步 URL）；
   5. `prefillComposer(receipt.text)`；
   6. 依据点击前 `localStorage['lfl-draft-' + sid]` 是否为空给不同提示（见 4.5）；
   7. 不自动发送、不自动关闭会话、不注入消息。
5. 条目/详情展示（可选 P2）：来源 `sid` 前 8 位 + 完整值 tooltip，便于人工核对。

### 4.4 时序（竞态已核实）

`conversation.ts:151-190` 在会话变更时把 `composerPrefill` 重置为 `deferredWithdrawals.get(next) ?? null`，因此：

1. 必须**先** `setCurrentSession(sid)`，**后** `prefillComposer(text)`；顺序颠倒会被重置清空。
2. 同一事件内 React 批处理时，`Composer` 的草稿恢复 effect（`:203-213`）先执行、预填 effect（`:219-250`）后执行，最终文本 = 目标会话草稿 + 换行 + 回执（草稿为空则纯回执）。
3. 若两步落在不同 tick（例如定位/切工作区 await 之后），仍是"先渲染新会话、再收到预填"，不丢内容。
4. 跨工作区切换会重建后端会话上下文，必须在切换**成功回执**后再 `setCurrentSession`，不能并行。

### 4.5 草稿保护规则

- 目标会话草稿为空 → 回执**替换**式填入（视觉上就是"粘好了"）。
- 目标会话已有草稿 → **追加**到末尾，并提示"该会话已有草稿，回执已追加在末尾"。绝不静默丢弃用户草稿。
- 不做自动备份键（`lfl-draft-backup-*`）：追加策略本身不丢数据，额外键会引入清理负担。
- 不改 `prefillComposer` 现有 append 语义（撤销编辑等路径依赖它），避免退化。

### 4.6 跨工作区、不可达、批量

- 跨工作区（主路径）：先切工作区再生效，失败给原因；不隐式改数据目录；切换会改变 web 全局当前工作区（会话列表、工具根、文件预览根跟随），按钮文案必须提前表明。
- 不可达（会话被删 / 仅存在于 `.identity` / 属于另一个 data 目录）：只读展示 sid + 禁用打开；不静默落到"新会话"，避免把回执发错上下文。
- 批量：按来源会话分组，按钮并列；同一会话多条建议只出现一次；跨多个工作区时逐个按钮标注目标工作区。

## 5. 失败模式矩阵

| 场景 | 行为 | 用户可见结果 |
|---|---|---|
| 建议无 `session_id`（历史 57 条） | 不渲染打开按钮 | "来源会话未记录（旧记录）" |
| 定位器命中当前工作区 | 直接切会话 + 预填 | 输入框出现回执，光标就位 |
| 定位器命中其他工作区（实测 93%） | 切工作区 → 切会话 → 预填 | 成功后同上；失败给 409/403 原因 |
| 定位器不可达（`not_found`） | 按钮禁用 | 明确原因 + 完整 sid 可复制 |
| 仅存在于 `.identity` 身份会话 | 按钮禁用，`reason=identity_only` | "属于身份会话，web 不可打开" |
| 目标工作区不在允许根（403） | 不切换 | 提示无法切换，复制入口保留 |
| 定位器接口异常 | `available=false` + reason | 提示稍后重试，复制入口不受影响 |
| 目标会话已有草稿 | 追加 + 提示 | 原文保留，回执在末尾 |
| 批量混合来源 | 按会话分组，≤3 个按钮 | "等 N 个"折叠，不误导 |
| 点击后用户手动改会话 | 预填跟随点击目标会话，不跨会话漂移 | 不串会话 |

## 6. 验收标准

1. 新提交建议在 list/detail 中返回完整 UUID `session_id`；旧记录返回空串且不报错。
2. 单条审批后，回执区出现"来源会话"行与「打开来源会话并粘贴」按钮，位于「复制回执」下方。
3. 点击按钮后：当前会话 = 来源会话；输入框含回执全文；焦点在输入框；**未**自动发送。
4. 来源会话已有草稿时：最终文本 = 原草稿 + `\n` + 回执，并出现追加提示。
5. 跨工作区来源会话（实测主路径）：按钮标注目标工作区路径；切换成功后可打开并预填；`409 workspace_busy` / `403 workspace_not_allowed` 时给出原因且不导航。
6. 不可达/旧记录：不出现可点击跳转，原因可见，sid 可复制。
7. 批量审批：按钮按来源会话去重并列，最多 3 个，其余折叠。
8. 审计行含 `suggestion_session_id`，可与提交记录对上。

## 7. 测试计划

后端（`tests/web/test_evolution_review_batch.py` 扩展 + 新用例）：
- list/detail 返回 `session_id`（有值 / 空串两种记录）。
- review 与 review-batch 响应含 `session_id`。
- locator：当前工作区命中、其他工作区命中（用真实工作区 id 构造临时文件）、未命中（`available=false`）、仅 `.identity` → `identity_only`、缺参数/非法形状（含 `../`、`/`）→ 400 且不越权、异常 fail-open。
- 审计行写入 `suggestion_session_id`（有/无来源）。

前端（`webui/src/evolution-panel.test.tsx` 扩展）：
- 回执区渲染"打开来源会话"按钮；无 session_id 时不渲染。
- 点击 → 断言 `sessionStore.currentSessionId` 变更、`prefillComposer` 被调用、文本一致。
- 定位器不可达 → 按钮 disabled + 原因文案，且不发生会话切换。
- 已有草稿 → 提示文案为"追加"。
- 批量混合来源 → 分组去重，≤3 个按钮。

回归：
- `npm --prefix webui run test`、`npx tsc --noEmit`、`python -m pytest tests/web -q`。
- 重点回归：撤销编辑的预填仍为 append（`Composer.tsx:219-250` 未被改写）、会话切换重置逻辑未变。

## 8. 兼容、回滚、非目标

- 兼容：新增字段全部可选；旧 jsonl 不迁移、不改写；locator 是新增端点，旧前端不受影响。
- 回滚：前端隐藏按钮 + 后端字段保留即可，无数据迁移。
- 非目标：不保存 WebSocket/浏览器连接对象；不持久化完整 URL；不自动发送回执；不回填 57 条历史记录；不做跨 data-dir 的会话读取。

## 9. 影响面与工作量

| 层 | 文件 | 规模 |
|---|---|---|
| 后端投影 | `src/llm_loop/web/routes.py`（4 处字段 + 1 个新端点 + 审计入参） | 约 80-110 行 |
| 后端测试 | `tests/web/test_evolution_review_batch.py` 等 | 约 120 行 |
| 前端面板 | `EvolutionPanel.tsx`（类型、回执、按钮、点击流程） | 约 90-120 行 |
| 前端核心 | `conversation.ts` 仅可能新增"跨会话预填"辅助（非必需，视时序实现而定）、`sessionUrl.ts` 复用 | 约 0-30 行 |
| 前端测试 | `evolution-panel.test.tsx` | 约 100 行 |

## 10. 需用户裁决的三个点

1. **回执文案是否附带来源**：建议在回执文本末尾加一行"来源会话：<完整 sid>"，这样把回执复制给 AI 时也能定位上下文；代价是既有回执断言需同步更新。默认建议：加。
2. **打开方式**：默认 SPA 内跳转（便于预填 + 立即发送）。若希望保留当前会话继续工作，可加"在新标签打开"链接（不带预填）。默认建议：先做 SPA 内跳转，新标签作为 P2。
3. **跨工作区切换是否需要二次确认**：默认不弹确认，仅在按钮上明示"将切换到 `<workspace_path>`"（实测 93% 会走这条路径，逐次弹窗会把主流程变成两步）。若你更看重"不擅自改全局工作区"，可改为首次点击弹一次确认、同会话内不再重复。默认建议：不弹窗，靠按钮文案交代清楚。
