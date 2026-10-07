# DESIGN-20261007 浏览器语义守卫与观测开销削减 — 需求设计

Date: 2026-10-07
Status: **CONVERGED — 设计已收敛（2026-10-07 三轮拷问自主收敛，用户授权"不待用户决裁"）；本文不含实现，实施待触发**
上游: 2026-10-07 jev-ultrafast（browser-use/jev-ultrafast，MIT，22,198 star）全库核实 + 三轮 grill_me 拷问
方法: 证据基线全部来自本会话实测（对方仓库克隆通读 + 我方源码 grep/AST），未经核实处显式标注"待实测"

## 0. 证据基线

### 0.1 外部项目（jev-ultrafast，已克隆核实）

| 事实 | 数值/结论 | 来源 |
|---|---|---|
| 核心代码量 | ~850 行（agent 174 / model 198 / questions 157 / browser 155 / snapshot.js 170）；依赖仅 browser-harness==0.1.13 + httpx | 仓库实测 |
| 端到端效果 | 中位 9.45s → 7.09s（-25%）；**浏览器协议调用 1092 → 101（≈11x）**；决策输出 28 token；n=3、符号检验 p=0.25（作者自曝不显著） | docs/performance.md + 原始 JSON |
| 五头投机作答 | 一次请求答操作选择 + 各操作目标头，schema 限制目标为该操作合法元素索引，执行时只消费被选分支 | model.py:119 / questions.py 实测 |
| 局部语义守卫 | 执行前校验比对语义指纹：document、URL、viewport、表单值、目标元素、目标邻近 form/dialog/row；不做 mutation 计数失效 | browser.py + design.md:17 |
| 交互后等待 | 2 animation frame 或 50ms；combobox 等可见选项出现，200ms 封顶 | browser.py 实测 |
| 自曝盲区 | shadow DOM、iframe、canvas、上传、弹窗；纯视觉变化不触发指纹 | design.md |
| 硬上限 | 60 动作 / 120 决策 / 250 候选截断 | design.md |

### 0.2 我方现状（本会话源码实测）

| 事实 | 数值/结论 | 来源 |
|---|---|---|
| snapshot 协议成本 | 每次 = DOMSnapshot.captureSnapshot + Accessibility.getFullAXTree 双全量；128MiB 帧上限；10.4MB HTML/~100k 节点实测 ~1.4s/帧、AX 全树曾撞 1009 | cdp_host.py:41-46,77-78 |
| 执行前校验现状 | compile_request 机械编译 + grounding_ref 全等 + 同 action_id 幂等拒绝；version 单调机制存在，无局部指纹概念 | browser_semantic_execute.py:86,102,144 |
| 只读会话 evaluate 可用 | read_document_ready_state 已走 Runtime.evaluate → 守卫脚本通道无需新权限 | cdp_host.py:211-214 |
| 等待现状 | 轮询引擎（timeout_ms 上限约束），无 rAF/可见性语义粒度 | browser_wait.py:63-115 |
| 权限/通道 | channel_binding、profile_policy（189 行）、loopback 校验既有；mutation single-dispatch、no-retry/rebind 为硬原则 | browser_*.py 工具描述实测 |
| 消费端回执现状 | dispatch 后无条件再全量双取+计算 diff；回执仅含 diff_ref 引用，observed_effects.provisional=True，completeness.complete 恒 False（boundary_detector_non_exhaustive 兜底） | action.py:448-449,599-664 实测（2026-10-07 二轮） |
| 差量消费原语已存在 | hydrate 支持 diff/&lt;from_version&gt; ref 并返回 canonical_diff；diff 粒度=字段名（attributes./state./coverage./relations），**不含字段值** | perception.py:646-673,259-282 实测（2026-10-07 二轮） |
| 消费契约现状 | 方法卡已有 receipt ok != task complete、rejection 恢复规则、object 谓词优先；但 Verify 未规定 diff-first，"Re-observe/Verify" 默认退化为再全量 snapshot | method_card.py 全文实测（2026-10-07 二轮） |
| 记录链现状 | exception_log/self_correction_log 无浏览器相关条目；拒绝/验证失败→经验/方法蒸馏无自动管线 | search_records 实测（2026-10-07 二轮） |
| snapshot 无基线摘要 | snapshot 段（smc.world_snapshot.v0.1）仅 content_sha256 全量哈希 + scope/observed_at/budget，**无独立 document 结构摘要**；FR-1 基线指纹需新增字段，落点=canonicalize 一次生成随 bundle 持久化 | perception.py:1527-1652 实测（2026-10-07 三轮，闭合 Q1） |
| value_text 明文落盘 | persist() 将 bundle 原样落盘（TTL 86400s）；objects[].attributes.value_text **无敏感排除**（DOM 路径 2378-2381、AX 路径 2444-2452 均不区分 password/PII）；attestation.py 本身仅进程/端口级核查、不落页面内容 | perception.py:440-469,2369-2452 + attestation.py 全文实测（2026-10-07 三轮，闭合 Q2，证实泄露面→FR-6） |

## 1. 背景、问题诊断

外部证据表明：jev 端到端 -25% 中真正的大头不是模型，而是**观测/协议开销削减（11x）**——砍掉重复读全树与 mutation 计数式假失效。我方架构不同（CDP host + semantic object + grounding/version + attestation，非 Playwright page 驱动），但病理同源：

1. **全树双取是 scale 瓶颈**：100k 节点页面单帧 ~1.4s + AX 全树帧风险，执行前校验若依赖重取全树，开销随页面规模线性恶化。
2. **假失效机制**：version 单调 + 全量 snapshot 语义下，动画/广告类无关变化同样迫使重新观测；Jev 已验证语义指纹 + 局部守卫可消除这类损耗。
3. **等待粒度粗**：固定间隔轮询无法区分"渲染完成"与"选项已出现"，首个有效观测被系统性推迟。

诊断结论：优先级应为 **FR-1（守卫）> FR-2（等待）**，二者均为 CDP Runtime.evaluate 级改动、零新依赖、不动权限模型；FR-3/FR-4 经拷问后**不适合直接移植**（见 §3 与 §8）。

## 2. 目标 / 非目标

**目标**

- G1 执行前置校验从 O(DOM) 降为 O(目标局部)：单次固定只读 evaluate 返回指纹 bundle + 遮挡检查。
- G2 动画/无关变化导致的假失效可被语义分层判定（document / viewport / 目标局部三层）。
- G3 交互后等待获得语义粒度（rAF 基线 + 可见选项谓词）。
- G4 每个验收项可机械重放（对齐仓库 eval 口径）。

**非目标（红线）**

- 不引入 browser-harness / Jev 模型 / Typesafe API 任何依赖。
- 不做视觉理解：grounding/version 保持 DOM+AX only（vision 仍停留 evidence 层，与决策解耦）。
- 不改 mutation 通道原则：single-dispatch、no-retry/rebind/fuzzy 不动摇；守卫只新增"拒绝理由"，不新增"自动重试"。
- 不替换现有 version 机制——守卫是其前置增量，默认关闭可回滚（配置开关）。
- FR-3 不进主循环（架构不适配，见 §8 Q3）。

## 3. 需求分解

### FR-6（P0，三轮拷问新增，先于/同批 FR-1）落盘敏感值修复

- 需求：canonicalize 侧统一敏感字段排除——`type=password` 与标记敏感（AX sensitive 属性）的 value 不进 `value_text`（DOM/AX 双路径共用**单一白名单函数**，与 FR-1 指纹的表单摘要白名单同一事实源，防规则漂移）；下游消费（hydrate、wait object_text）遇排除字段返回"策略排除"哨兵而非空串，防模型误判为空值。diff 落盘为字段名粒度不含值，无需处理。
- 存量清理：修复落地时一次性清理 store 的 snapshots/ 目录既有 bundle（diffs/ 不含值可保留）；此后靠排除规则源头阻断。
- 验收：构造含 password/PII 输入页 capture→persist→grep 落盘文件零敏感明文；hydrate/wait 对排除字段返回哨兵语义。
- 依据：Q2 实测证实（§0.2 末行）——原"推断可能落盘"升级为事实，此项从 FR-1 子项拆出独立立项，因它修复**现存**泄露面而非新增功能的附带约束。

### FR-1（P0）局部语义守卫

- 需求：browser_operate dispatch 前插入一次固定只读 Runtime.evaluate，返回指纹 bundle：(a) document 指纹（URL + 结构摘要）；(b) viewport 状态；(c) 目标元素身份（由服务端从 grounding_ref 解析 backend elementId，模型不可传任意表达式）；(d) 目标邻近 form/dialog/row 上下文摘要；(e) document.elementFromPoint 遮挡检查。
- 分层判定：document 指纹不变而 viewport 变 → 仅空间失效（scroll 后重找元素语义）；目标元素 detach/身份不符 → 分类型拒绝；被遮挡（elementFromPoint ≠ 目标及其祖先）→ 分类型拒绝。
- **敏感字段**：type=password 及标记敏感字段不进指纹（哈希亦不用，直接排除），与 FR-6 共用同一白名单函数；普通表单值进摘要前先经字段白名单。（三轮更新：泄露面已实测证实，修复主责移至 FR-6，本条仅约束指纹输入。）
- 失败策略 **fail-closed**：evaluate 异常/超时 → 拒绝 dispatch + 分类型错误（guard_detach / guard_document_changed / guard_occluded / guard_timeout），不静默降级旧机制、不自动重试。
- 可观测：guard_verdict + 指纹命中层级进 ToolResult（沿 attestation 链路）。
- 基线来源：基线指纹在上次 snapshot 时同源生成并随 version 绑定（改动面：snapshot 路径需落基线；**Q1 已实测闭合**——现状无 document 级摘要，仅 content_sha256 全量哈希，需新增字段，见 §7）。
- 验收：动画页面假失效率下降（用例：含 CSS 动画页连续操作）；遮挡场景拦截率 100%（用例：cookie-banner 覆盖按钮）；敏感字段零明文/零哈希落盘（grep 日志回归）；守卫异常路径全部 fail-closed（故障注入）。

### FR-2（P1）交互后细粒度等待

- 需求：dispatch 成功后默认等 2 animation frame 或 50ms（先到先止）；combobox/autocomplete 类操作等待"可见选项出现"谓词，200ms 封顶；超时如实返回 wait_verdict，不重试。
- 实现通道：同 Runtime.evaluate（rAF 计数 + 可见性谓词），零新依赖。
- 验收：交互后首个有效观测提前 ≥ 1 个现行轮询周期；combobox 用例（autocomplete 渲染完成前不消费预测）通过。

### FR-3（P2，探索项）受限候选集 + 投机多头作答

- 结论：**不适用于 LFL 主循环**。该模式为"无上下文单步决策模型"设计（一次请求并行答 5 个分支问题）；LFL 主循环是带完整上下文的通用 agent，一次决策 = 一次工具往返，不存在多分支并行作答需求，移植无收益且增加 schema 复杂度。
- 保留范围：仅当未来出现专用高频子循环（如 form-filling skill、批量表格填充）时，作为该子循环的决策契约候选，先实测收益再立项。
- 验收：本轮仅本节结论，无代码。

### FR-4（重定位）独立 DONE 裁决 → eval 规范

- 结论：与 LFL 既有原则（"未获成功回执不得声称完成"）同构，不是浏览器工具缺口；落地形态为 eval 基建中 checker 独立裁决 DONE 的书写约定（benchmark 用例的终态判定不得引用被测模型自报）。
- 验收：新增 eval 模板含 checker 字段时引用本节；无浏览器侧代码。

## 4. 非功能需求

- NFR-1 性能：守卫单次 CDP 往返（一个 evaluate 返回全部指纹+遮挡），目标局部计算 O(子树)，禁止多次往返探测。
- NFR-2 安全：守卫脚本为固定只读 JS 常量，参数面仅服务端解析的 elementId；脚本本身进版本管理并做代码评审（注入面 = 0）。
- NFR-3 兼容：默认关闭（配置开关），开启前行为与现状逐字节一致；回滚 = 关开关。
- NFR-4 可观测：guard_verdict / wait_verdict 结构化字段，可进 action_trace 机械重放。
- NFR-5 诚实性：残余盲区（canvas 内容变化、纯 CSS transform 位移、TOCTOU 窗口）在工具描述中如实声明，不宣称已解决。

## 5. 里程碑与依赖

| 阶段 | 内容 | 依赖 |
|---|---|---|
| M1 | ~~§7 Q1/Q2 基线实测~~ **已完成（三轮）**：Q1 无独立 document 摘要（需新增字段）、Q2 attestation 不落页面内容但 persist 落 value_text 明文 | 无 |
| M0 | ~~FR-6 敏感值修复 + 存量清理 + 验收回归~~ **已完成（2026-10-07 实施触发）**：单点白名单 `SENSITIVE_VALUE_SENTINEL`/`_redact_value_text` 落 perception.py（DOM 路径 + AX 路径 + sensor 层防御三层接入同一函数，归一化匹配覆盖 "verification code"/"verification_code" 变体）；hydrate/diff/bundle content_sha256 全链路实测零明文（密码变更 produce 零 delta）；存量 414 bundle/551MB 清零；附带修复：TTL 过期 bundle 惰性删除（原只报错不删，累积根因），availability=expired 对外契约保持；验收测试 `tests/unit/test_browser_perception_sensitive_redaction.py` 8 用例 | M1 ✅ |
| M2 | ~~FR-1 守卫实现 + 故障注入测试~~ **已完成（2026-10-07 实施触发）**：基线指纹随 snapshot 落 bundle `guard_baseline`（分层 hash：document=url-only / target=语义属性+脱敏 value / neighborhood=form·dialog·tr·li 邻域结构；两采集口径钉死同构——name=aria-label‖name、text=直接文本子聚合、value=attribute 口径、id/viewport/几何不入指纹）；守卫探针为 cdp_host 固定只读 JS 常量（DOM.resolveNode + Runtime.callFunctionOn，resolve 失败→guard_detach、evaluate 失败→guard_timeout、遮挡/零尺寸→guard_occluded、分层失配→guard_document_changed:layer）；执行序=守卫先于 before-capture（拒绝零捕获成本）+ guard pass 豁免"可比但不等"的 version mismatch（availability 类失败不可豁免，守卫基线不可读时退回 version 单闸门=fail 到旧行为）；verdict 沿回执链路落 receipt["guard"]；配置 `LFL_BROWSER_SEMANTIC_GUARD_ENABLED` 默认 off；实现口径修正：readyState 不入 doc 指纹（sensor 通道不持久化该字段，入则必假失配）。测试 `tests/unit/test_browser_semantic_guard_v01.py` 14 用例（基线落盘/哨兵进指纹/全拒绝分类/豁免放行/快速失败/off 回归/无 collector 惰性） | M1 ✅, M0 ✅ |
| M3 | ~~FR-1 用例验收（动画/遮挡/敏感字段回归；真实 CDP 浏览器端到端）~~ **已完成（2026-10-07）**：`tests/integration/test_browser_semantic_guard_e2e.py` 5 用例真实 Chromium 端到端全绿——E1 guard pass 豁免 version stale（focus 态翻转+邻域外轮播+无关输入变化）；E2 form 邻域插入被拒零执行；E3 全屏 overlay 拦截（真 elementFromPoint）；E4 detach 拒绝；E5 password 零明文落盘。E2E 首调即暴露并修复 3 个真实缺陷：① `DOM.resolveNode` 响应键 `node`→`object`（M2 fake 层无覆盖、协议建模错误）；② 已删节点悬垂 objectId 零尺寸几何被误分类 occlusion → 探针 JS 增 `connected:el.isConnected`，detach 精确分类；③ 豁免不可观测 → receipt 的 guard verdict 显式落 `exempted`/`exemption_reason` | M2 ✅ |
| M4 | ~~FR-2 等待粒度~~ **已完成（2026-10-07）**：dispatch acknowledged 与 post-capture 之间插入单次往返 settle（`Runtime.callFunctionOn`+awaitPromise，浏览器侧 `Promise.race` 先到先止）——基线 2 rAF/50ms；combobox 类 click（服务端判定 kind=select/combobox 或 role∈{combobox,listbox}，combobox 语义经 `_kind_for` 归一化为 select 是判据真值面）等"可见 option 出现"200ms 封顶。verdict 落 receipt `wait` 键（settled/timeout/unavailable 如实，不重试不失败）；`LFL_BROWSER_DISPATCH_SETTLE_ENABLED` 默认 off=逐字节等同现状（NFR-3）。真 Chromium E2E 4 用例（`test_browser_dispatch_settle_e2e.py`）：E6 基线 race（raf 与 cap 两分支均实测出现）；E7 对照实验证"首个有效观测提前 ≥1 轮询周期"（off 臂 capture 抢跑 120ms 弹层→combobox 未展开，on 臂 settle 后 after bundle 已含展开态）；E8 240ms 迟现选项→timeout 如实单次 dispatch；E9 off 无 wait 键。E2E 再抓 2 个真实缺陷：④ document 根节点宿主 `ownerDocument===null` 使谓词 raise（防御式 view 解析修复）；⑤ **真实 CDP capture 投影层 `state.visible` 缺席**（fixture 层有、真层无，state 仅剩 exists）——E2E 改用投影真值 `state.expanded` 断言，该缺口记录在案留给 capture 层，不在 M4 内偷修 | 独立，可与 M2 并行 |
| M5 | FR-3/FR-4 结论归档（本文即归档） | 无 |
| M6 | FR-5a 消费协议进方法卡 + eval 重放基线（每步全取次数 / verdict 分布 / diff 可比率）；含 Q6 兜底报表口径。**方法卡部分已完成（2026-10-07）**：method_card.py compact 增 diff-first/空 diff 裁决/哨兵纪律；MethodStore 新卡 `mutation-verify-consumption-protocol`（parent=method-semantic-operation）。eval 重放基线未动 | 无，可先行 |
| M7 | FR-5b 回执内联 diff 摘要（自适应封顶 cap=32 起步，Q5 实测校准） | M1 ✅ |

## 6. 风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| 指纹假阴性（语义变而指纹不变，如 canvas 重绘）导致错点 | 高 | elementFromPoint 遮挡检查兜底 + NFR-5 残余盲区声明；守卫只是拒绝理由的增量，不承诺绝对正确 |
| fail-closed 增加拒绝率，交互摩擦上升 | 中 | 分类型错误信息指导模型下一步（re-snapshot vs 换目标）；上线前用动画用例量化拒绝率增量 |
| 基线指纹与 version 绑定引入 snapshot 路径改动面 | 中 | M1 先实测现状，若已有可复用摘要则改动面收敛 |
| 敏感字段判定不全（非 password 但含 PII） | 中→**已证实存在**（Q2 三轮闭合：value_text 明文落盘） | FR-6 白名单制 + 下游哨兵语义 + 存量清理；不再列为风险而是立项为 FR-6 |
| TOCTOU：守卫通过到 dispatch 落地间页面再变 | 低（与 Jev 同级） | 残余风险声明；消除需 CDP 输入事件原子性，超本文范围 |

## 7. 开放问题（三轮收敛后状态）

- ~~Q1（阻塞 M2）~~ **已闭合**：snapshot 无独立 document 摘要，仅 content_sha256 全量哈希（perception.py:1527-1652 实测）——FR-1 基线指纹确认为新增字段，改动面=canonicalize 单点。
- ~~Q2~~ **已闭合**：attestation.py 不落页面内容（进程/端口级核查）；真正落盘面=persist() 的 bundle，含 value_text 明文、无敏感排除——证实泄露面，立项 FR-6。
- Q3（实现期）：elementFromPoint 对 transform/clip-path 的语义边界——构造用例定界，不阻塞设计。
- Q4（M3 数据决定）：viewport 分层失效时是否保留 document 级缓存——不在本设计承诺。
- Q5（降级为校准项，不阻塞 M7 立项）：大页面 canonical_diff 条目量级——三轮已定**自适应封顶**（min(cap, entries)+truncated 标记+总数），cap=32 起步，Q5 实测后只校准数值不改机制。
- ~~Q6（待裁决）~~ **已闭合（三轮）**：纪律优先+报表兜底——方法卡约定模型遇 guard 拒绝/diff 不可比/验证不符即时落 lesson（FR-5c）；eval 侧（M6）重放统计 verdict 分布/diff 可比率，异常时由模型补记。程序不自动判定（红线不动）。

## 8. 拷问记录（三轮 grill_me，诚实存档）

第一轮暴露并已吸收的盲点：

1. 敏感表单值不得进指纹（落盘泄露风险）→ FR-1 敏感字段排除 + Q2 待实测（历史状态；三轮已闭合并升级为 FR-6，见下）。
2. 守卫脚本必须零模型可控参数（注入面）→ NFR-2。
3. fail-open/fail-closed 未定 → 明确 fail-closed（对齐 no-retry 原则）。
4. FR-3 架构适配性存疑 → 降级 P2 并限定专用子循环。
5. FR-4 与既有原则重复 → 重定位为 eval 规范，不做工具改动。

第二轮针对 v2 的盘问未再产生新结构性盲点（模板问题重复，边际价值归零，主动终止）。

第三轮（2026-10-07，收敛拷问，用户授权自主裁决）在 M1 实测（Q1/Q2 闭合）后进行，暴露并已吸收：

1. **敏感值落盘泄露面从推断变事实**（failure_modes/security 域）→ 拆出 FR-6 独立 P0，含下游消费哨兵语义与存量清理。
2. **排除规则的下游语义**：value_text 被 hydrate/wait object_text 消费，排除后返回哨兵而非空串，防"空值误判"（新盲点）。
3. **单一事实源**：FR-6 白名单与 FR-1 指纹表单摘要共用一个函数，防两处规则漂移（递进层发现）。
4. **空 diff 裁决规则**：diff-first 契约补"空 diff ≠ 效果达成"，期望含视觉变化必须 re-observe（edge_cases 域）→ 并入 FR-5a。
5. **Q5 降级**：自适应封顶（min(cap,entries)+truncated+总数）使量级实测从阻塞项变为校准项。
6. **Q6 定案**：纪律优先+eval 报表兜底，程序不自动判定（红线）。

对前轮分析的修正：初稿曾将"投机多头作答"列为第三优先移植项；拷问后确认其收益绑定于 Jev 的独立小决策模型架构，对通用 agent 主循环为负收益，已降级。

## 9. 决策记录（三轮收敛，替代原"裁决请求"）

用户 2026-10-07 授权："不要我去决裁，遇到问题需要解决时，你通过拷问去获得答案。" 据此撤销裁决请求，以下决策由第三轮 grill_me 自主收敛：

| 裁决点 | 决策 | 依据 |
|---|---|---|
| FR-1 立项 | **采纳 P0**，前置=FR-6 先行/同批 | fail-closed 只增拒绝不增错执行；假阴性有遮挡兜底+盲区声明；架构改动零新依赖 |
| FR-2 并行 | **采纳，与 FR-1 并行** | 独立通道（Runtime.evaluate），M4 无依赖 |
| FR-3/FR-4 归档结论 | **维持** | 二轮已确认架构不适配/原则同构，三轮无新事实反转 |
| FR-5a | **采纳 P1 零代码**，补空 diff 裁决规则 | 见 §10.3（三轮新增第 4 条盲点） |
| FR-5b | **采纳 P1**，阈值=自适应封顶 cap=32 起步，Q5 校准数值不改机制 | 固定阈值在量级未知时两难；自适应+truncated+总数在大页面下信息不丢失 |
| FR-5c / Q6 | **采纳 P2**，纪律优先+eval 报表兜底 | 纯纪律会漏、纯报表滞后；程序不自动判定（红线） |
| FR-6（新增） | **采纳 P0，先于/同批 FR-1** | Q2 实测证实现存泄露面，修复现存问题优先级高于新增功能 |
| 实施触发 | 本设计已收敛可实施；实现排期待用户触发（任务边界：本轮授权=设计收敛，未含实现授权） | 红线：未获授权不动实现 |

## 10. 消费端闭环（2026-10-07 二轮补充）

用户追问："进一步考虑是否可以借鉴优化方法消费端的应用，形成真正闭环。" 本节为答复，证据见 §0.2 新增四行，仍属需求设计、不含实现。

### 10.1 结论先行

Jev 的消费端技巧可归纳为两条，**均不可直接搬**：

1. **分支差量消费**（五头投机作答"执行时只消费被选分支"）——已由 FR-3 拒绝，架构不适配通用 agent 主循环，结论不变。
2. **可消费性等待**（等语义条件成立再消费观测）——我方已存在且更细：browser_wait_object_state/object_text 按 exact grounding_ref 谓词等待，方法卡已规定 object 谓词优先于 scope 谓词。

真正的缺口不在原语而在**契约**：差量消费原语（diff / hydrate / projection 分页 / object 谓词等待）全部已存在，但没有被绑成协议，导致消费端退化路径与生产端病理同构（见 10.2）。可借鉴的增量因此是协议与记录，不是新机制——即 FR-5 三件套。

### 10.2 消费端病理（§1 的镜像诊断）

1. **每步三次全量双取**：模型 snapshot（全量）+ pre-dispatch 全量（action.py:448）+ post-dispatch 全量（action.py:605）；信息需求只是"一个 ground truth + 差量"。FR-1 砍 pre-dispatch 那次，本节管另外两次。
2. **已付费的 diff 只给引用不给内容**：post-dispatch diff 已算出，回执仅 diff_ref；Verify 路径未规定 diff-first，"Re-observe/Verify" 实践中默认再全量。
3. **裁决权在模型但没有最便宜的可裁决事实**：回执 honest-by-construction（provisional=True、complete 恒 False），"程序不判完成"是对的；缺的是把差量事实递到裁决现场。

### 10.3 FR-5 消费端闭环三件套

- **FR-5a（P1，零代码，方法卡层）**：Verify 规定为 diff-first——receipt ok 后先消费差量（内联摘要或 hydrate(diff_ref)）对照模型自持的期望效果裁决；仅 diff 不可比（comparable=False / created=removed=None）或需新 grounding 时才重新 snapshot。**空 diff 裁决规则（三轮新增）**：空 diff ≠ 效果达成——期望效果为"无语义变化"时空 diff 判 match；期望含视觉/canvas 变化时必须 re-observe（diff 盲区，fail-open to observation）。拒绝分类消费表（扩展现有方法卡）：guard_*（FR-1 落地后）按分层失效选局部重找 vs re-snapshot；version_precondition_* → re-observe；target_scope_mismatch / target_identity_* → re-ground；compile FAILURE → 修 ref 同 action_id 重发（既有规则保留）。**期望效果声明留在模型推理内，不进 action schema**——程序不拥有完成判断（红线）。
- **FR-5b（P1，增量 schema）**：ActionReceipt.observed_effects 内联结构化 diff 摘要：created/removed/changed 的 id+字段名，**自适应封顶**（三轮定案）：`min(cap, entries)` + `truncated:true` + 三类总数，cap=32 起步、Q5 实测后仅校准数值——大页面下信息不丢失（可 hydrate 全量），小页面零截断。已核实 diff 为字段名粒度、不含值（perception.py:259-282），内联**不新增值泄露面**；值级消费仍走 hydrate（session+retention 边界既存）。回执 schema frozen v0.1，落地为附加可选字段，旧回执无此字段读取不得报错。
- **FR-5c（P2，记录闭环）**：机械事实（version/diff/verdict）已沿 receipt+attestation 链持久化；闭环最后一段=模型在 guard 拒绝 / diff 不可比 / 验证不符时用既有 save_experience / method_manage 落 lesson；eval 侧用 action_trace 机械重放统计 verdict 分布、diff 可比率、每步全取次数作为 M3/M6 验收口径。**不做程序自动判定记录重要性**（红线）；触发约定见 Q6。

### 10.4 闭环视图

```
[snapshot 全量·ground truth]
   → [模型：意图 + 期望效果（自持，不进 schema）]
   → FR-1 guard（局部指纹）──fail──→ 分类拒绝 → 按 10.3 消费表恢复（局部重找 / re-snapshot）↺
   → dispatch（单次，no-retry）
   → FR-2 settle（rAF / 可见性谓词）
   → post-capture + diff（机械，已付费）
   → [模型：diff-first 验证 vs 期望] ──match──→ 下一步（grounding 未失效则复用）↺
                                    └─mismatch/不可比→ re-observe + 落 lesson（FR-5c）↺
   → 任务收口：DONE 独立裁决，不引用被测自报（FR-4 eval 规范）
```

闭环之所以"真"：每一环产出的都是机械事实（version / diff / verdict），可低成本消费、可持久化重放、可蒸馏为方法/经验并改变后续消费行为——而判断权全程留在模型，程序不新增任何"替模型判定"的面。

### 10.5 诚实边界（继承 + 新增）

1. **diff 是 snapshot-pair net**：两次快照间的净差，不可归因于单次 dispatch（中间动画/脚本都计入）；mismatch 的消费规则是 re-observe + 记录，**不是自动重试**（no-retry 红线不动）。
2. **盲区继承**：canvas/纯视觉变化不进 diff（与 NFR-5 同源）；兜底=重新观测——fail-open to observation，不是 fail-open to claims。
3. **FR-5a 依赖模型纪律**：可靠性由 eval 重放统计兜底，不靠自报。
4. **勿重复建设**：消费端语义等待已存在（object 谓词），FR-2 的增量只剩 dispatch 后 settle 等待。

### 10.6 裁决点（已收敛，并入 §9 决策记录）

原开放裁决点（FR-5 三件套是否同批采纳、FR-5b 是否待 Q5 后定阈值、Q6 触发约定取哪侧）已于三轮拷问全部收敛：FR-5a 采纳并补空 diff 裁决规则、FR-5b 采纳且阈值定自适应封顶（Q5 降级为校准项）、FR-5c 采纳且 Q6 定纪律优先+报表兜底。详见 §9 决策记录表。
