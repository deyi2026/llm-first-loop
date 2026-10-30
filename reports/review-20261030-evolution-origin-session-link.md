# 代码审查回执 — 演进建议来源会话本地连接（RULE-AI-28 代码闸）

- 被审 SHA：20e6db475（feat(web): 演进建议审批回执区可打开来源会话并预填）
- 设计书：docs/design/DESIGN-20261030-evolution-origin-session-link-v1.md
- 审查方式：独立只读审查（未修改任何 src/tests/webui 代码；仅跑定向测试并写本回执）
- 被审文件（4 个）：src/llm_loop/web/routes.py、tests/web/test_evolution_review_batch.py、webui/src/components/sidebar/EvolutionPanel.tsx、webui/src/evolution-panel.test.tsx

## 0. 前置事实与纪律声明

1. HEAD 关系：审查时 HEAD=2f31d85cf，被审提交在其前 3 个。已核验 git diff 20e6db475..HEAD 对 4 个被审文件为空、git diff 20e6db475 对 4 个被审文件为空 → 后续提交未触碰被审文件、工作区与被审提交一致，结论对当前工作区成立。
2. 方法论检索：search_records 工具在本执行域不可用（get_tool_schema 回执：不在当前可调用集合），未取得任何方法卡，本回执不以记录库作背书。
3. 全部审查动作只读：git show / read_file / grep / 定向 pytest + vitest。

## 1. Verdict

**PASS**（P0=0，P1=0，P2=7）

一句话结论：后端四出口 session_id 投影齐全、locator 形状校验与 fail-open 到位、审计字段全调用点传值正确；前端预填时序、跨区先切换成功后导航、批量去重 ≤3、不自动发送均按设计实现；定向测试后端 15 例、前端 17 例全绿；剩余 7 条均为一致性/测试充分性类非阻断问题。

## 2. 发现清单

### P0（0）

无：未发现越权切换、路径穿越可达、自动发送、旧数据改写或审计字段破坏。

### P1（0）

无：未发现阻断设计书 §6 验收标准或造成既有语义退化的缺陷。

### P2（7）

**P2-1 工作区切换后侧栏状态不同步（跨区主路径，实测约 93%）**
- 位置：webui/src/components/sidebar/EvolutionPanel.tsx:277-291
- 问题：既有切换路径 WorkspaceGroups.switchWs（WorkspaceGroups.tsx:152-170）在成功后还会 setCurrentWsId + reload + onWorkspaceChanged，由 Sidebar.tsx:405-412 触发 refreshSessionsAndCurrent；本实现直接调 switchWorkspace，绕过了这条状态同步链。
- 影响：会话列表可由 SSE sessions_updated（routes.py:4226-4230，轮询 workspace 根指纹，切换本身即触发）在约 3 秒内自愈，但侧栏当前工作区标题与分组归属不会自愈，直到用户再次手动切换或刷新页面；用户看到旧工作区标签而服务端已切走，工具根与文件预览根也随之改变。
- 建议：切换成功后触发共享的工作区已变更通知，复用 Sidebar 的 onWorkspaceChanged 语义。

**P2-2 409 原因文案硬编码，丢失后端真实原因**
- 位置：EvolutionPanel.tsx:281-289
- 问题：sw.status 等于 409 一律显示「当前会话运行中」，但后端 409 有两种：workspace_busy（routes.py:5057）与 workspace_path_unavailable（routes.py:5067-5071）；switchWorkspace（core/api.ts:898-917）返回的 error 与 detail 被丢弃。
- 影响：工作区路径被删或移动时给出错误归因，用户无法判断真实原因。
- 建议：优先展示 sw.error / sw.detail，状态码仅作兜底。

**P2-3 单条审批响应 session_id 未按设计做 cur_after or cur 兜底**
- 位置：src/llm_loop/web/routes.py:3232-3237
- 问题：设计书 §4.2.3 要求 (cur_after or cur) 取值，实现只用 cur_after。
- 影响：并发下若审批后再次读取建议短暂失败，响应 session_id 变空串，前端误显示「来源会话未记录」；正常路径无影响（approve/reject 不修改 session_id）。
- 建议：session_id 取 (cur_after or cur or 空字典) 的 session_id 再 or 空串。

**P2-4 identity_only 归因可能不准确**
- 位置：routes.py:3415-3418；文案 EvolutionPanel.tsx:244-245
- 问题：.identity 是全局身份命名空间存根目录（实测 data/sessions/.identity 下有 2479 个 90 字节级 json 存根，不是会话正文），对所有已知 sid 留痕；因此「只存在于 .identity」的真实语义是「已注册工作区目录里没有正文文件」（如来源工作区已注销或未注册），而非「属于身份会话」。
- 影响：结论（打不开）正确，但文案把用户引向错误排查方向。
- 建议：文案改为「未在已注册工作区找到会话正文（来源工作区可能已注销或会话已删除）」。

**P2-5 后端未钉住「当前工作区优先」的排序语义**
- 位置：routes.py:3393-3414；测试 tests/web/test_evolution_review_batch.py:221-254
- 问题：实现顺序正确（candidates 首项为 current），但无用例让同一 sid 同时存在于 current 与其他工作区目录并断言返回 current。
- 影响：实现正确但无回归防护，未来重构易退化为先命中任意工作区。
- 建议：补一条同 sid 双目录用例，断言 workspace_id 为 current 的 id 且 current 为 true。

**P2-6 前端缺 403 与定位器网络失败用例；草稿追加只断言文案未断言行为**
- 位置：webui/src/evolution-panel.test.tsx:401-429（仅 409）、:418-429（草稿）
- 问题：(1) 设计书 §6.5 要求 409 与 403 都给原因且不导航，现仅 409；(2) fetchLocator 的 catch 分支（EvolutionPanel.tsx:218-222，reason 为 locator_failed，按钮保持可点以允许重试）无用例；(3) 草稿用例断言的是 evo-origin-note 文案（由 localStorage 推导，EvolutionPanel.tsx:292-300），未断言 Composer 最终文本 = 原草稿 + 换行 + 回执，属断言应用自述而非行为。
- 影响：验收标准 §6.4 与 §6.5 的 403 分支缺证据；追加语义无端到端证据（真实逻辑在未改动的 Composer.tsx:224-229）。
- 建议：补 403 与 locator 失败两例；草稿例改为断言 Composer 实际文本。

**P2-7 投影未做字符串归一 + 批量多来源共用一个提示槽位**
- 位置：routes.py:3029、3070（d.get 取 session_id，未做 str 归一）；EvolutionPanel.tsx:194（originNote 为单一状态）
- 问题：(1) 历史记录若含 session_id 为 null，投影返回 JSON null，与前端 session_id 可选字符串的声明不一致（前端用 String(x 或 空串) 兜底，运行时不炸）；(2) 批量多来源时一个来源的提示覆盖另一个来源的提示。
- 影响：均为低风险契约与体验问题。
- 建议：统一做 str(d.get(session_id) 或 空串)；提示改为按 sid 存字典或带上 sid 前 8 位。

## 3. 关键核对结论

### 3.1 后端（routes.py）

- 四出口投影齐全：list（:3029）、detail（:3070）、review（:3232-3248）、review-batch（:3298/:3303/:3310/:3315/:3334/:3338/:3360 七个分支全部带 session_id 键，失败分支给空串）；旧记录缺字段即空串，不报错。
- locator 形状校验：_SESSION_ID_SHAPE 为 ^[0-9a-fA-F-]{8,64}$（:3368），字符集不含点号与斜杠，先挡穿越再拼路径；非法形状返回 400 invalid_params（:3378-3383）。
- 定位顺序：current 优先（:3391-3399）；identity_only（:3415）、not_found（:3419）、整体 try/except fail-open 不 500（:3384-3425，settings 或 workspace_store 缺失亦被同一 except 兜住）。
- 审计：_log_web_review（:3087-3096）新增 keyword-only 且带默认值的 suggestion_session_id，签名向后兼容，原有 ts/source/action/id/decision/ok/reason/note 字段全部保留；4 个调用点（:3218 异常、:3238 正常、:3339 批量成功、:3351 批量异常）均已传值；全仓无其他调用点、无其他 evolution_review_log.jsonl 读取方，无解析破坏面。

### 3.2 前端（EvolutionPanel.tsx）

- origins 构造：buildOrigins（:315-323）按 sid 聚合 evoIds；单条取响应 session_id（:369）；批量按 ok 过滤后去重（:408-415）；渲染上限 3 个并显示「等 N 个」（:532、:563-565）。
- 时序：setCurrentSession（:298）先于 prefillComposer（:299）。已核实竞态：conversation.ts:152-222 的会话切换订阅者在 setCurrentSession 时同步把 composerPrefill 重置为 null（:180），而 sessionStore.setCurrentSession 是 zustand 同步 setState（core/stores.ts:115-130），故先重置后写入不会被清空；Composer.tsx:203-210 草稿恢复 effect 声明在前、:219-250 预填 effect 在后，最终文本 = 草稿 + 换行 + 回执，符合设计 §4.4。
- 跨区：await switchWorkspace 成功后才切会话（:278-291），失败即 return 不导航；不可达（:273-276）直接 return 并给原因；409 与 403 分支均不切会话。
- 不自动发送：全流程只调 session-locator 与 workspaces/switch，无发送调用（前端用例断言无 /api/v1/chat 请求）。
### 3.3 安全面

- 路径穿越：sid 先过正则再拼 sessions_dir/ws_id/sid.json；ws_id 取自经 _validate_workspace_id 校验的工作区注册表（workspace/store.py:223-228）；前端从不以 sid 拼路径，只用于 localStorage key 与展示文本（React 转义，无 XSS 面）。
- 跨工作区越权：locator 只回读注册表里的 workspace_id；切换仍走 POST /api/v1/workspaces/switch，越界条目由后端 403 workspace_not_allowed 拦截（routes.py:5077-5083），前端如实提示且不导航。
- 低风险信息面：locator 回传已注册工作区绝对路径供按钮标注目标工作区（设计书 §4.2.5 明确要求），该端点与其它 evolution 端点同属本地 web 受保护面。

### 3.4 回归面

- 新增字段全部可选：前端 session_id 为可选字符串（后端恒在，缺字段即空串）；locator 为新增端点，旧前端不受影响。
- 旧 jsonl 未被改写：本次提交未触碰 evolution_suggestions.jsonl 的写入路径；新增写入仅在既有 evolution_review_log.jsonl 追加行。
- 未改动 prefillComposer 既有 append 语义与撤销编辑路径（core/conversation.ts、components/conversation/Composer.tsx、Sidebar.tsx、WorkspaceGroups.tsx 均不在本次 4 文件变更清单内，见 git show --stat）。
- 既有语义未变：copy 回执文案生成与复制逻辑原样保留；既有前端 9 例与后端 5 例全绿。
- 与设计书的一处文字差异（不影响行为）：设计 §4.2.4 说 review-batch 取审批后条目的 session_id，实现取审批前 cur（:3308）；approve/reject 不修改 session_id，行为等价，建议回填设计书或统一实现。

### 3.5 测试充分性（对照设计书 §7）

已覆盖并有真实断言：list/detail 的 session_id 有值与空串两态（后端用例 :155-177）；review 与 review-batch 响应含 session_id（:180-218）；locator 命中当前区（:221-238，含全字段等值断言）、命中第 45 个工作区即不截断扫描（:240-254）、not_found 与 identity_only（:257-269）、非法形状含 ../ 与 a/b 与 空串均 400（:272-279）、异常 fail-open（:282-298）；审计行 suggestion_session_id 有值与空值（:180-203）。

前端已覆盖：渲染按钮且位于复制按钮下方（:329-340）、无 session_id 时不渲染（:342-349）、点击后会话切换加预填加未发送（:351-362）、不可达则 disabled 加原因加不切换（:364-374）、跨区先 switch 再开会话且请求体为工作区 id（:376-399）、409 不导航（:401-416）、批量去重且按钮上限 3 与等 N 个（:431-457）。

假绿排查：既有 9 条与新增 8 条前端断言、既有 5 条与新增 10 条后端断言中，未发现恒真空转用例；唯一「断言了应用自述而非行为」的是草稿追加提示（见 P2-6 第 3 点），已如实标注。

## 4. 测试执行回执

| # | 命令 | 退出码 | 结果摘要 |
|---|---|---|---|
| 1 | cd <repo> && .venv/bin/python3 -m pytest tests/web/test_evolution_review_batch.py -q | 0 | 15 passed in 0.87s（输出中 52 处 provider base_url 提示为既有非失败信息） |
| 2 | cd webui && TMPDIR=<repo>/.tmp-test npx vitest run src/evolution-panel.test.tsx | 0 | Test Files 1 passed (1) / Tests 17 passed (17) / Duration 847ms（vitest v2.1.9） |

两条命令均真实执行、真实退出码 0，无「未能执行」项。

## 5. 未覆盖项 / 未执行项（如实记录）

1. 未跑全量回归：npm --prefix webui run test、npx tsc --noEmit、python -m pytest tests/web -q（设计书 §7 回归段）本次未运行（委派限定定向测试）；类型检查未跑，故 TS 编译通过未获证据，人工复核见 P2-7。
2. 未做浏览器端到端验证：Composer 最终文本与焦点落位（Composer.tsx:249）由代码路径推断与既有逻辑保证，本特性测试未渲染 Composer 做断言。
3. 未在真实数据集上跑 locator：仅用 tmp 会话目录构造用例；真实 data/sessions 布局（54 个工作区目录、.identity 2479 个存根）仅作静态核验。
4. 未覆盖用例：403 不导航、locator 网络失败、current 优先排序（同 sid 双目录）。
5. search_records 方法论检索未执行（工具不可用，见 §0 第 2 条）。
6. 被审提交与 HEAD 的关系见 §0 第 1 条。
7. 沙箱限制：写回本回执时 heredoc 与 shell 重定向被写侧护栏拒绝（unmodeled_shell_construct / write_target_not_in_allow_list），最终以工作区内绝对路径的 python 写入完成；未改动任何被审文件。

补充（来源：父代理独立执行的真实回执，本代理未复跑）：npx tsc --noEmit → exit=0；npm run build → exit=0，binding=ebd564da132db6c9（143 tracked files）。据此 §5 第 1 条中的类型检查一项已有外部证据，TS 编译面无阻塞。

## 6. 建议的最小修订（可选，不阻断合入）

1. EvolutionPanel.tsx:281-289 改用 sw.error / sw.detail 给真实原因（P2-2）。
2. EvolutionPanel.tsx:277-291 切换成功后触发工作区状态同步（P2-1）。
3. routes.py:3232-3237 用 cur_after or cur 兜底（P2-3）。
4. 补 3 条用例：403 不导航、locator 网络失败、current 优先（P2-5、P2-6）。
5. 文案与归一：identity_only 文案、originNote 按 sid 分槽、session_id 投影做 str 归一（P2-4、P2-7）。

## 7. 交付核对

- 回执文件 reports/review-20261030-evolution-origin-session-link.md 已落盘，且含被审 SHA 20e6db475。
- 三态 verdict：PASS；P0=0、P1=0、P2=7，每条均含文件与行号、问题、影响、建议。
- 后端与前端定向测试本代理真实执行并给出退出码（均 0）；tsc 与 build 采用父代理回执并已标注来源。
- 未修改任何 src/tests/webui 代码（git status 中 4 个被审文件无改动）。
