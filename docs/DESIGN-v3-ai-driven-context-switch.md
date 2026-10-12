# 方案 v3：AI 主导上下文选择（AI-Driven Context Switch）——切换模型的任务接续 + 缓存成本双优

> 状态: **方案 v3（待审）** | 2026-08-20 | 关联: `docs/DESIGN-v2-slim-first-model-switch-cache-cost.md`（v2 锚点瘦身，v3 的兜底分支）、`docs/ARCHITECTURE-cache-stable-rules.md`（缓存稳定总纲）
> 触发: 用户拷问"让大模型自己组装上下文，如何组合式——既方便任务接续执行，又考虑缓存命中"
> 演进路径: v1（无方案，首轮全量 miss）→ v2（程序硬算尾部锚点 slim-first）→ **v3（AI 声明 + 程序执行）**

## 0. 时序真相（一切设计的前提，含 v2 修正）

代码时序（engine.py 循环）：`417 build（用旧锚点）→ 444 routing → 452 切换检测`。

**452 在 build 之后** → 无论 v2 还是 v3，切换**首轮**必然用旧锚点（全量/旧尾部）build：

| 轮次 | 锚点来源 | 发送内容 | 成本 |
|---|---|---|---|
| **首轮** | 旧 provider 锚点（build 时新锚点未写） | 全量/旧尾部 + 切换通知（尾部注入） | **全量 miss（物理事实，无法避免）** |
| **第二轮** | 452 写的 slim-first 默认 N（生效） | system + 尾部 N 轮 + 通知 | 尾部 miss（省 ~80%） |
| **第三轮起** | AI `declare_context` 声明（若有） | system + AI 选窗口 + 任务帧 | AI 精准窗口（任务接续最优） |

**首轮全量 miss 是架构顺序决定**（routing 依赖 build 产物，前移需重构 routing 解耦，改动大不推荐）。
**必须修正 v2 §1.2 承诺**："首轮就省 80%" 不成立，实为"首轮贵一次（物理事实），第二轮起省 ~80%"。

### 0.1 时序硬伤解法（拷问：是否重构 routing 让首轮就瘦身？）

| 解法 | 改动 | 代价 | 结论 |
|---|---|---|---|
| A. 重构 routing 前移到 build 前（预 routing 确定 model_used → 检测切换写锚点 → build） | 大（routing 依赖 messages/tools_param，需解耦） | 高，解耦可能引入新问题 | ❌ 不推荐 |
| **B. 接受首轮全量 miss 是物理事实**，瘦身第二轮起、AI 声明第三轮起 | 小（只改文档承诺 + 注入通知） | 低，诚实反映时序真相 | ✅ **采纳** |

选 B：首轮全量 miss 是 build→routing→452 时序决定的物理事实，非方案缺陷。重构 routing 为"让首轮就瘦身"是过度工程——省一轮 miss 不值得解耦 routing 的风险。

## 0.2 判断权归属架构审视（拷问：哪些程序判断该交 AI）

基于 build.py / history.py / engine.py 逐项审视，**不是全盘重构，是"判断权交 AI，执行权留程序"**——
对齐 ARCHITECTURE §1"程序最小化：能由 AI 自主 + 文档规则实现的判断，尽量不用程序"。

| 程序当前做的事 | 适合谁 | 依据 | 动作 |
|---|---|---|---|
| system prompt 静态构建（L0 硬约束/安全） | 程序 | AI 无法自完成（身份/灾难性安全） | 保留 |
| 工具 schema 注入 | 程序 | API 协议要求 | 保留 |
| interop 协调通道注入（DSH→LFL） | 程序 | 外部系统消息，AI 不感知 | 保留 |
| 分层降级 / reasoning_tail 瘦身 | 程序 | 机械规则（age/threshold）+ 字节级确定性（裁错改变前缀/协议 400） | 保留 |
| 切换检测（model_used 变化） | 程序 | 程序才知道 model_used | 保留 |
| 检索/归档/存储执行 | 程序 | 存储隔离，AI 不直接写 | 保留 |
| cache_guard 拦截判定 | 程序 | 安全硬边界，fail-closed（ai_rules 程序硬执行） | 保留 |
| **历史窗口锚点起点（slim-first 硬算 N）** | **该交 AI** | AI 知道任务进度在哪几轮，程序不知道 | → declare_context（本方案） |
| **压缩保留哪些帧（程序机械归档）** | **该交 AI** | AI 知道哪些是关键决策/事实，程序只按 age 归档 | → v4：AI 主动 compact(keep=[...]) |
| **memory 召回哪些（程序 top_k）** | **该交 AI** | AI 知道任务需要哪些历史决策，程序按 query 相似度召回可能漏 | → v4：AI 主动 recall_memory(query, filter) |
| 会话状态快照注入 | 组合式 | 程序兜底按间隔注入，AI 可主动 get_status | 程序兜底 + AI 主动 |

**红线（必须留程序，AI 无法/不应自完成）**：
1. 字节级确定性：reasoning_tail / 锚点写入 / system 前缀组装——裁错/变序改变前缀 → 缓存全断
2. 安全硬边界：cache_guard BLOCK——灾难性安全，fail-closed
3. 真实执行/存储：归档落盘、工具执行、API 调用

**统一模式（判断权交 AI，执行权留程序）**：
```
程序（执行）: 检测 → 注入通知/提供工具 → 解析 AI 声明 → 按声明执行（锚点/裁剪/检索）
AI（判断）:   看到通知 → 声明所需（窗口/帧/记忆）→ 经工具（declare_context / search_archive）
```

## 1. 三方分工（程序最小化）

| 角色 | 职责 | 实现 |
|---|---|---|
| **程序（最小）** | ① 切换检测 ② 注入切换通知 ③ 解析 `declare_context` 工具参数并写锚点 ④ 兜底（AI 未声明 → slim-first 默认 N） | engine.py:452 + build.py 注入点 |
| **AI（主导）** | 看到切换通知后，调 `declare_context(recent=N, anchors=[轮号])` 声明所需窗口；或调 `search_archive` 拉特定帧 | 工具调用（结构化参数，非自然语言） |
| **规则（大脑约束）** | ai_rules.md 加一条："切换模型时，AI 应调 declare_context 声明所需上下文窗口；或经 search_archive 拉回关键帧" | docs/ai_rules.md |

## 2. 工具定义：declare_context

结构化工具（**不用自然语言解析**——AI 声明夹在长回答里程序解析必然出错，工具参数可靠可审计）：

```json
{
  "name": "declare_context",
  "description": "切换模型后声明本轮所需上下文窗口。切换通知注入后调用；recent=保留最近几轮，anchors=需常驻的关键轮号（任务定义/决策依据）。未调用则程序用默认兜底。",
  "parameters": {
    "type": "object",
    "properties": {
      "recent": {"type": "integer", "minimum": 1, "description": "保留最近 N 轮对话"},
      "anchors": {"type": "array", "items": {"type": "integer"}, "description": "需常驻的历史轮号（0 基）"}
    },
    "required": ["recent"]
  }
}
```

## 3. 执行流程（时序对齐）

```
切换检测（452，本轮 build 后）
  ↓
① 首轮：slim-first 默认 N 兜底（v2 行为）+ 注入切换通知（尾部 user，不破前缀）
   通知内容: "刚从 X 切到 Y，新缓存池无前缀，首轮全量 miss 成本已发生。
             历史窗口自第 {N} 轮起（更早已归档，可 search_archive 检索）。
             请声明所需上下文: 调 declare_context(recent=N, anchors=[关键轮号])；
             或经 search_archive 拉回关键帧。"
  ↓
② AI 首轮决策（看到通知后）：
   - 需要早期历史 → 调 search_archive 拉回关键帧（尾部追加，本轮可见）
   - 需要稳定窗口 → 调 declare_context(recent=N, anchors=[轮号])
   - 不需要 → 不调（程序维持 slim-first 默认 N）
  ↓
③ 程序第二轮起执行：
   - declare_context 已调 → 解析工具参数写锚点（recent N 轮起点 + anchors 轮抽为常驻任务帧）
   - 未调 → 维持 slim-first 默认 N（兜底）
   - **锚点写定后不再改**（防前缀反复断）；扩展上下文走 search_archive（尾部追加不破前缀）
  ↓
④ 切回（任意 provider）→ 同样流程（AI 声明 → 重写锚点，旧前缀让位）
```

## 4. 缓存命中分析（修正后，三轮渐进）

| 轮次 | 发送内容 | 命中 | 成本 |
|---|---|---|---|
| 首轮 | system + 旧锚点窗口 + 切换通知 | **全 miss**（新缓存池无此前缀） | 全量（物理事实） |
| 第二轮 | system + 尾部 N 轮 + 通知 | 部分命中（前缀=首轮尾部段） | 增量 miss（省 ~80% vs 首轮） |
| 第三轮起 | system + AI 选窗口 + 任务帧（常驻） | 前缀渐长 | AI 精准窗口（任务接续 + 成本双优） |

**关键**：
- 切换通知 = 尾部注入（GATE_NOTE 机制），不占前缀 → system+历史前缀字节稳定
- 任务帧（anchors 轮）抽为 **system 尾部固定字节** → 后续轮不破前缀（对齐 ARCHITECTURE L0 尾部追加）
- AI 拉回的 archive = 尾部追加 → 前缀零影响
- **锚点写定后不变**：AI 想扩展 → search_archive（不重写锚点，防前缀反复断）

## 5. 任务接续分析（根治反例1）

| 场景 | v2（程序硬算 N=10） | **v3（AI 声明）** |
|---|---|---|
| 42→52→52 三步任务中途切 | N=10 可能不含第1步定义 → 断 | **AI 声明 anchors=[1] → 第1步常驻任务帧** |
| 长任务依赖早期决策 | 程序不知道哪轮关键 → 可能丢 | **AI 知道 → 主动声明 anchors** |
| 简单问答切换 | N=10 浪费（只需最近1轮） | **AI 声明 recent=1 → 更省** |
| 切回对称 | 旧锚点窗口膨胀（上轮拷问场景B） | **AI 声明 → 重写锚点按需最小化** |

## 6. 风险与兜底

| 风险 | 兜底 |
|---|---|
| AI 忘声明 | 程序兜底 slim-first 默认 N=10（v2 行为，零回归） |
| AI 声明不准（recent=3 实际需 5） | 下轮可 search_archive 补拉（不重写锚点，不破前缀） |
| 锚点轮注入破前缀 | 进 system 尾部（GATE_NOTE 转 user），对齐 memory/interop 现有机制 |
| 工具循环内多次切换 | 锚点写入仅当"该 provider 无锚点或久远"时发生（防重复写/覆盖） |
| 切回旧前缀让位 | 写明：切回=重写锚点+旧前缀作废（AI 声明让 miss 按需最小化） |
| AI 不主动调 declare_context | 先落 v2 通知（AI 感知），观察 AI 是否自然声明；不声明则 v2 已够用 |

## 7. 与 v2 的关系

**v3 = v2 的 AI 主导版**：
- v2 slim-first = 程序硬写尾部锚点（N 固定）→ v3 的**兜底分支**
- v3 = AI 声明 + 程序执行 → v2 是 AI 未声明时的 fallback

**渐进落地（对齐 ARCHITECTURE 程序最小化）**：

```
v1（现状）: 切换首轮全量 miss（无方案）
v2（已设计）: 程序硬写尾部锚点 slim-first + 切换通知（AI 感知）——零行为风险，先落地
v3（本方案）: + declare_context 工具（AI 结构化声明窗口）——简单格式先行
v4（可选）: + anchors 轮抽为常驻任务帧（AI 声明关键轮）——完整组合式
```

**v1-v4 完整路径（判断权渐次交 AI，执行权恒留程序）**：

| 阶段 | 程序 | AI | 风险 |
|---|---|---|---|
| v1（现状） | 硬算锚点 N=10 | 不参与 | 反例1（丢任务起点） |
| **v2（先落）** | + 注入切换通知（尾部，零行为风险） | 感知切换，可主动 search_archive 补 | 低（只多一条 user 消息） |
| v3 | 解析 declare_context 写锚点 | 主动声明 recent=N, anchors=[轮号] | 中（需新工具 + 规则） |
| v4 | 压缩/memory 执行权留程序 | 主动 compact(keep=[...]) / recall_memory(query) | 中（AI 主导判断） |

> **落地原则**：v2 先落——零行为风险，观察 AI 是否会主动声明/调 archive。
> 若 AI 自然声明 → v3 顺势接；若 AI 不声明 → 说明程序硬算更稳，v2 已够用。
> 先让 AI 证明它能主导，再把主导权交它（程序最小化但不过度让权）。

## 8. 落地路径（MIRROR 协议）

```
镜像实施（engine 452 注入通知 + declare_context 工具注册 + 锚点写入规则）
→ 镜像验证（时序三轮行为 / AI 声明触发率 / 命中率曲线 / 任务接续 / 成本）
→ 提交审批 → 主区同步 + 全量回归 → 重启生效
```

### 验证方法（修正后）
1. **时序验证**：抓首轮/第二轮/第三轮 payload 前缀（确认"首轮全量→二轮尾部→三轮 AI 窗口"）
2. **成本核算**：三轮累计 miss token vs 无方案（确认"首轮贵一次+后续省"净收益）
3. **任务接续**：三步任务中途切换 + AI 声明 anchors（复用 42→52→52）
4. **回归**：AI 不声明时 = v2 行为（兜底），既有测试通过

### 回退
- `declare_context` 工具下架即回 v2（锚点逻辑不变，只少 AI 声明通道）
- 切换通知保留（无害，AI 感知有益）
- 无新增持久化状态（锚点机制复用），回退干净

> 注：首轮全量 miss 是架构时序决定的物理事实（build→routing→452），**不是方案缺陷**；
> v3 的目标是"首轮之后"的窗口由 AI 精准控制，把任务接续和成本都交给最懂任务的 AI。
