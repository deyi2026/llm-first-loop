# macOS 桌面感知/操作：AX 载荷瘦身、续读分页与等待语义（需求与实现设计）

- 文档状态：**Draft v1（待评审）**；本轮未修改任何源码。
- 日期：2026-11-04
- 参照对象：`/tmp/dsh-vc`（Windows/UIA 后端）源码通读。**PolyForm Noncommercial 1.0.0，仅借鉴契约形态，不引入其代码。**
- 事实基线：本仓库当前工作树；所有行号为本轮实际读取结果。
- 前置约束：RULE-AI-24（先保真再优化，不得以优化为名退化既有安全语义）。

---

## 0. 阅读指引

| 章节 | 内容 |
|---|---|
| §1 | 结论摘要与三处自我推翻 |
| §2 | 实证基线（file:line + 实测/源码/推算 分级） |
| §3 | 范围（In / Out） |
| §4 | 需求条目 FR / NFR |
| §5 | 拷问记录：14 问逐条应答 |
| §6 | 设计（渲染分级、续读、等待、指纹、批量） |
| §7 | 与既有资产的复用表 |
| §8 | 测试计划 |
| §9 | 观测与指标 |
| §10 | 残余逃逸口与未实测清单 |
| §11 | 实施批次与开工条件 |

---

## 1. 结论摘要（TL;DR）

### 1.1 三处对上一轮判断的推翻（本轮新证据）

| # | 上一轮判断 | 本轮证据 | 修正后结论 |
|---|---|---|---|
| ① | 渲染瘦身可省 **74.8%** token | 用真实 `AxNode` + 真实序列化路径实测（`/tmp/ax_render_probe.py`） | **错误**。sparse 保几何省 **38.3%**，丢几何省 **63.2%**。74.8% 对应的形态同时丢了 `pos_pt/size_pt`，而几何是 `point` 寻址的唯一依据 |
| ② | 桌面侧**没有**截断/分页 | `desktop_perceive.py:490` 已有 `truncated` 回执 | **不准确**。已有截断标记，但**没有续读游标**——超过 1500 的节点**永久不可达**，模型只能缩 depth 重来 |
| ③ | 桌面侧**缺** ref 重解析 | `desktop_operate.py:1247` 已有 act-time 重解析（`n.ax_ref == target`） | **不准确**。已有重解析，但锚是不可自证的索引路径。真缺口是"锚点指纹"，且**不建议照搬**（见 Q7） |

### 1.2 优先级重排（相对上一轮）

上一轮把"渲染瘦身"放 P0。本轮实测后重排：

> **渲染只乘 0.4；续读分页是除 N。** 1500 节点即便按最省的 E 方案渲染，仍约 3.0 万 token（估算），单次回执即可摧毁上下文。**因此 FR-01（续读分页）必须排在 FR-02（渲染分级）之前。**

### 1.3 明确不做

- **不照搬 dsh-vc 的 ref 重解析放宽**：那是在放宽安全门控，而我们没有"长流程跑不完"的实测失败率证据（当前屏幕锁定，无法取得）。见 Q7。
- **不照搬遮挡检测**：其启发式会把我方"如实标注残余"降级为"装作知道"。
- **不降低授权模型**：我方已有写总开关 + `EXEC_MODE` + 白名单 + 敏感名单 + dry_run→令牌→apply + world 比对 + 在场检测 + append-only 审计，全面强于参照对象的一键收回。

---

## 2. 实证基线

### 2.1 已核实（源码，file:line）

| 事实 | 证据 |
|---|---|
| `AxNode` 为 8 字段扁平结构，层级靠 `ax_ref` 路径表达（无 children） | `desktop/models.py:180-188` |
| `MAX_AX_DEPTH=6`，`AX_NODE_LIMIT_DEFAULT=1500` | `desktop/models.py:17,19` |
| snapshot 的 `depth` 默认 3，`0..6` 裁剪并回执 `clipped_depth` | `desktop_perceive.py:124,482-483` |
| 回执已含 `truncated` | `desktop_perceive.py:490` |
| 节点序列化为 `jsonable(node)` 全字段 | `desktop_perceive.py:492` |
| 整体 envelope 用 `ensure_ascii=False, sort_keys=True, indent=1` | `desktop_perceive.py:171` |
| `snapshot` 参数白名单严格：`{action, window_id, depth, vision}` | `desktop_perceive.py:46` |
| `world_fingerprint` = 窗口身份 + 前台归属 + **前 200 节点**(`ax_ref` / `role` / `title` / `focused`) + 目标节点行；**不含几何** | `desktop/operate.py:268-310` |
| 指纹对 `ax_ref` 通道**无条件追加**目标行（R1/S9），防深位目标漏检 | `desktop/operate.py:302-309` |
| act-time 重解析 = `n.ax_ref == target_identity["ax_ref"]` 精确字符串匹配 | `desktop_operate.py:1247,911` |
| `desktop_operate` 的 `do` 枚举来自 `_DOS`，为 click/type/press_key/scroll | `desktop_operate.py:236-240` |
| `browser_perceive` 已有 wait 谓词集与 `settle_ms` 抗抖 | `browser_perceive.py:96-190` |
| `browser_perceive` 已有 `projection_kinds` / `projection_cursor` 投影分页 | `browser_perceive.py`（snapshot 分支） |
| 测试仅断言 `ax_ref` 与 `len(nodes)`，不锁字段集 | `tests/unit/test_desktop_perceive_m3_v01.py:363,371,384,1010` |

### 2.2 实测（本轮执行，可复现）

方法：`/tmp/ax_render_probe.py`。导入真实 `llm_loop.desktop.models.AxNode`，用真实序列化参数（`ensure_ascii=False, sort_keys=True`），对 10 个代表性节点（覆盖 window/button/textfield/checkbox/row/group，含 null 与非 null 几何）量字符数。

| 渲染形态 | 字符/节点 | tok/节点（估） | 相对现状 |
|---|---|---|---|
| A 现状 `indent=1` 全字段 | **205.5** | 55.1 | — |
| B 仅改 compact | 161.6 | 44.1 | −19.9% |
| C sparse（**保留几何**） | 121.1 | 34.0 | −38.3% |
| D sparse + 短键名 | 96.6 | 27.9 | −49.4% |
| E sparse（**丢几何**） | **66.2** | 20.3 | **−63.2%** |

字符成本构成（该样本口径）：**几何子块 23.9%**；**`null` + `focused=false` + 缩进合计 41.0%**。

单节点对照（现状）：
```json
{ "ax_ref": "0.2.2", "focused": false,
  "pos_pt": {"x": 412.0, "y": 880.5},
  "role": "AXButton", "size_pt": {"h": 32.0, "w": 120.0},
  "subrole": null, "title": "提交", "value": null }
```
对应 C：
```json
{"ax_ref":"0.2.2","pos_pt":{"x":412.0,"y":880.5},"role":"AXButton","size_pt":{"h":32.0,"w":120.0},"title":"提交"}
```

节点数外推（token，估算）：

| 节点数 | A 现状 | E 最省 |
|---|---|---|
| 150 | ≈8,270 | ≈3,045 |
| 400 | ≈22,050 | ≈8,120 |
| 1500 | ≈82,690 | ≈30,450 |

### 2.3 推算 / 未测（必须带走的限制）

| 项 | 性质 |
|---|---|
| `tok/节点` 全部数值 | **估算**。规则：CJK 字符计 1 token，其余字符 /4。**未使用真实 tokenizer**（本机无 tiktoken；transformers 可用但需拉取模型，本轮未做）。 |
| 样本分布 | **人为构造**的 10 节点。真实 app 若以无 title/value 的 group/row 为主，丢几何收益上升；若长文本为主，收益下降。**故 38.3% / 63.2% 不是普适常数，设计不绑定百分比，只绑定字段可选机制。** |
| 真实树节点数 | **未测**。屏幕锁定（`screen_locked`），`ax_trusted=false`。150/400/1500 为情景，非测量值。 |
| dsh-vc 任何运行时行为 | **未测**。只读源码。 |

---

## 3. 范围

**In scope**：`desktop_perceive` 的载荷形态与续读能力；`desktop_operate` 的等待/滚动语义；`world_fingerprint` 的绑定范围；受限批量。

**Out of scope**：授权模型改造；屏幕采样（watch）；UIA 语义动作全集中与 macOS 无对应者；任何 dsh-vc 代码移植；Web/浏览器侧。

---

## 4. 需求条目

### 功能需求

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-01 | snapshot 支持**续读**：超 `node_limit` 时回执游标，可继续取后续节点；支持按 `kind`（role）过滤 | P0 |
| FR-02 | 渲染分级：`render=full` 或 `sparse`，sparse 丢 `null`、`focused=false`；**几何默认保留**，仅 `geometry=0` 时丢；字段只减不增，`ax_ref`/`role` 恒在 | P0（B-2，后于 FR-01） |
| FR-03 | snapshot 回执附**焦点控件单行摘要**（role · title · value），免二次调用 | P0 |
| FR-04 | 新增 `do=scroll_into_view`（AXScrollToVisible），与位移式 `scroll` 并存、语义不混 | P1 |
| FR-05 | `desktop_perceive` 新增 `action=wait`，复用 browser 谓词形态；轮询在服务端，只在终态产回执 | P1 |
| FR-06 | `world_fingerprint` 绑定范围精确化（见 §6.5，**需 A/B 证据后才可改**） | P1（受闸） |
| FR-07 | snapshot 支持增量：回 `snapshot_id`，后续只回变化节点 | P2 |
| FR-08 | 受限批量：`do=steps[]`，仅限**非破坏性 + 全 identity 寻址**子集 | P2（受闸） |

### 非功能需求

| 编号 | 需求 |
|---|---|
| NFR-01 | 安全语义不回退：任何渲染/分页改动不得削弱令牌绑定、world 比对、dry_run 默认 true |
| NFR-02 | 兼容：现有消费方（测试、审计）不因字段减少而破坏；新增字段均有缺省 |
| NFR-03 | 超限必须**可见**且**可续**：不允许"静默截断后无法取得余下内容" |
| NFR-04 | 所有新参数进 `_ALLOWED_FIELDS` 白名单，未知字段照旧拒绝 |

---

## 5. 拷问记录（14 问）

### Q1 205.5 字符/节点是实测吗？

**半实测**。序列化路径真实（真实 dataclass + 真实 `json.dumps` 参数），但**样本是人为构造的 10 个节点**。真实分布未知。→ **影响**：文档只把"每字段的字符成本占比"（几何 23.9%、null/缩进 41.0%）当结论，不把绝对值当验收基线。

### Q2 降幅百分比可以写进验收标准吗？

**不可以**。降幅取决于 role/title 分布。→ **影响**：验收改测**机制**（sparse 下不出现 `null`/`focused:false`/几何），不测固定百分比。

### Q3 改渲染会破坏谁？

已核：`world_fingerprint`、`desktop_operate` 的 ax_ref 解析全部消费**后端 dataclass**，不经 JSON（`operate.py:297-309`、`desktop_operate.py:1247`）。测试只断言 `ax_ref` 与 `len(nodes)`。→ **影响**：渲染改动是纯输出层，风险确实低——但这恰恰说明**它的收益也有限**（见 Q4）。

### Q4 渲染是最大杠杆吗？

**不是，上一轮判断错了。** 1500 节点按 E 方案仍 ≈3.0 万 token。→ **影响**：FR-01 提前于 FR-02。渲染只解决"每节点贵 3 倍"，分页解决"节点数没上限"。

### Q5 丢几何的代价是什么？

`point` 寻址**完全依赖** `pos_pt/size_pt`。默认丢几何会让所有 `point` 路径需要额外一次带几何的调用。→ **影响**：默认 **sparse 保几何（−38.3%）**；几何仅在显式 `geometry=0` 时丢。不做按 role 分档（需先有 role 分布实测，否则是猜）。

### Q6 短键名（−49.4%）为什么不推荐？

省 11 个百分点，代价是：破坏字段名可读性、与 browser 侧命名不一致、审计/调试可读性下降、模型对 `k/t/v` 的推测成本可能反超。→ **影响**：列为可选项，默认不开。

### Q7 ref 锚定重解析该照搬吗？

**不该，至少现在不该。** 理由三条：
1. 我方已有 act-time 重解析（`desktop_operate.py:1247`），缺的不是重解析，是**锚的不可自证性**。
2. 锚点指纹（祖先路径 + 标识 + 类型 + 位置容差）本质是**放宽**门控：从"世界变了就拒绝"变成"看起来是同一个就放行"。而"位置容差"是**新增**的不确定性源——容差多大算同一个？没有实测就无法定。
3. dsh-vc 的动机是长流程跑不完，而我方**没有该失败率的实测证据**（屏幕锁定，未跑过真实多步任务）。

→ **影响**：FR-06 降级为"受闸"——必须先测出"因 world 漂移导致的令牌作废率"，证实它是主要阻塞，才允许进入放宽设计；且放宽版本必须保留"四要素不全匹配即 STALE"的硬性拒绝。

### Q8 那 world_version 过敏感是真痛点吗？

**是，但解法不是放宽，是精确化。** 现状指纹把"前 200 节点"全部纳入，任何无关节点（自绘动画、无关子控件）变化都作废令牌。而绑定意图（D4）应是"**我要操作的那件事没变**"。
注意：从"前 200 节点"改成"目标路径 + 目标子树"**同样是放宽**——无关节点变化不再打破。若该变化恰好是遮挡性弹窗，会漏检。而指纹**不含 Z 序**（工具描述已自承此残余），没有补偿信号。
→ **影响**：FR-06 同受 Q7 的闸。**不得**在无 A/B 证据下改指纹。

### Q9 `scroll_into_view` 能替代 HID `scroll` 吗？

**不能，二者语义不同。** `AXScrollToVisible` 是目标导向（"让这个元素可见"，精确、无方向歧义）；`scroll` 是位移导向（"滚 N 行"，浏览用）。→ **影响**：FR-04 是**新增**通道，不是替换。文档与工具描述都必须写清这一点，否则模型会误用。

### Q10 `wait` 会烧 token 吗？

不会——只要轮询在服务端、模型只在终态收到一条回执。但会烧**墙钟**（`within_ms` 上限 60s），且与在场检测（HID idle < 60s）冲突：长等待期间若用户离开，等待可能成功而 apply 失败。→ **影响**：`wait` 不得作为 apply 前置；`within_ms` 默认值要小（建议 ≤10s），必须显式放大。

### Q11 批量 B13 的半完成语义怎么收？

第 k 步失败 → 前 k−1 步已生效、不可回滚。且现有令牌绑定"单目标 + world_version"，批量需要新契约（绑定 `steps[]` 的 hash + world）。更要紧的是：批量会**削弱 dry_run 的逐门控价值**——用户看不到中间态就放行了 8 步。
→ **影响**：FR-08 只在"**无破坏性动作 + 全 identity 寻址**"子集开放；破坏性动作（type 覆盖、click 到提交/删除类）**一律不允许**进入批量。

### Q12 续读游标会不会让模型陷入翻页地狱？

会。若无边界，模型可能连翻 10 页 ×1500 节点。→ **影响**：FR-01 必须同时给出**建议宽度**与**单次会话累计上限**；游标回执必须带 `remaining` 与"建议缩 depth 或加 kind 过滤"的提示，而不是无条件鼓励继续翻。

### Q13 这些改动的 License 边界？

dsh-vc 为 PolyForm Noncommercial 1.0.0。→ **影响**：只借鉴**契约形态与字段语义**（如"截断必须可续"、"稀疏渲染分级"），不复制其代码、标识符命名与文档措辞。

### Q14 若屏幕解锁后实测推翻本文数字，怎么办？

预期会推翻 §2.2 的绝对值（样本是构造的）。→ **影响**：所有验收项写成机制断言（字段存在性/可续性/拒绝码），**不写** token 目标值；§2.2 表格标注为"开工前须以真实树复测替换"。

---

## 6. 设计

### 6.1 FR-01 续读分页（P0，先行）

在 `snapshot` 增加三个参数（全部进 `_ALLOWED_FIELDS`）：

| 参数 | 语义 |
|---|---|
| `node_limit` | 单页节点上限，默认沿用 1500 上限但默认页宽建议 200；`0<..<=1500` |
| `node_cursor` | 上页回执给出的续读位置（不透明串，含 depth/budget/树指纹，跨树版本失效即拒） |
| `node_kinds` | 按 role 过滤（如仅 `AXButton` / `AXTextField` / `AXStaticText`），减少噪声 |

回执：

```json
{ "nodes": [...], "truncated": true,
  "page": {"returned": 200, "remaining": 734, "cursor": "<opaque>",
           "hint": "可加 node_kinds 过滤或减小 depth 以降低总量"} }
```

约束：
- 游标绑定树指纹；树变则 `cursor_stale`，**不得**静默重定位（与 Q7 的立场一致：不引入看起来安全的猜测）。
- 保留现有 `truncated`（语义不变），新增 `page` 块，向后兼容。
- 首版**不**做 projection_kinds 的 browser 式枚举复用到底层遍历，只在返回后过滤（实现简单、可逆）。

### 6.2 FR-02 渲染分级（P0，次行）

`render` 参数：`full`（现状，默认保持一个版本周期）| `sparse`。

`sparse` 规则（**只删字段，不改键名、不改结构**）：
1. 省略值为 `null` 的字段（`subrole`/`title`/`value`）；
2. 省略 `focused` 当且仅当为 `false`；
3. 省略 `pos_pt`/`size_pt` 当且仅当 `geometry=0`（默认**保留**，见 Q5）；
4. 分隔符改紧凑（`separators=(",",":")`）；
5. `ax_ref`、`role` **恒在**（寻址与判读的最小公分母）。

明确不开：短键名（Q6）。

### 6.3 FR-03 焦点摘要（P0）

`snapshot` 回执新增 `focused` 块，单行：

```json
"focused": {"ax_ref":"0.2.3","role":"AXTextField","title":"邮箱","value":"user@example.com",
            "editable": true}
```

无焦点控件时为 `null`（sparse 下省略）。目的：去掉"读整树 → 再读输入框"的第二次调用。

### 6.4 FR-04 `scroll_into_view`（P1）

新增 `do` 值。**必须**在工具描述里与 `scroll` 对照说明（Q9）：

| do | 语义 | 实现 |
|---|---|---|
| `scroll` | 位移导向（down/up :n 行），浏览用 | HID 滚轮（方向符号未经 live 验证） |
| `scroll_into_view` | 目标导向（让 ax_ref 可见） | `AXScrollToVisible`，无方向歧义 |

风险分级：`scroll_into_view` 属**非破坏性**，但仍走 dry_run→令牌→apply 全流程（NFR-01）。找不到 `ax_ref` 时拒绝，不降级为滚动猜测。

### 6.5 FR-06 指纹精确化（受闸，先实验）

**不在本轮实现。** 开工前置条件：

1. 屏幕解锁后，跑 ≥20 次真实多步任务，记录每次 `FOREGROUND_CHANGED` 的**具体打破项**（窗口身份 / 前台归属 / 目标子树 / 无关前 200 节点）；
2. 统计"因无关节点打破"的占比。**若 < 30%，本项不做**（改进收益不抵放宽风险）；
3. 若做，采用**收紧而非放宽**的形态：以"目标 ax_ref 的祖先路径 + 自身 role/subrole/title"为绑定单元，**不引入位置容差**；无关节点移出指纹的同时，要求前台归属与窗口身份仍参与（保留遮挡的部分间接信号）；
4. 必须给出"哪些漏检被引入"的显式清单（诚实义务）。

**计量面已就绪（2026-11-04）**：`desktop_operate` 的回执 payload 新增
`stale_breaks` = `{breaks, primary, unrelated}`，四类打破项可直接计数——第 1 步的
"归因"不再依赖事后回忆。审计字典同步携带同一字段（是否落盘取决于 audit sink，
本仓默认 sink 为空，勿假定有审计文件可查）。口径边界写在 `world_drift_breaks`
的 docstring 里：

- 窗口身份破时**不统计**无关节点：身份变（pid/bounds/title）会让 ax_ref 整体重排，
  计入会把真实身份变化虚报成闸的分子，直接污染"无关打破占比"；
- 目标节点自身那一行不计入无关（它归 `target_subtree`），否则一次改动记两次；
- 前台门早退路径（窗口消失/前台不符）只比身份与前台两段，并标
  `unrelated: {"skipped": ...}`——树未加载时不伪装成"树没变"。

**闸仍未开**：分类能力就绪 ≠ 数据已采集。第 1 步的 ≥20 次真实任务尚未执行（当前
`ax_trusted` 与 `screen_capture_granted` 均为 false、屏幕锁定），故"无关打破占比"仍是
未知量，FR-06 继续挂闸，§2.2 的 token 数字仍为未验证估算。

### 6.6 FR-05 `wait`（P1）

`desktop_perceive` 新增 `action=wait`，谓词形态对齐 `browser_perceive`：

| kind | 语义 |
|---|---|
| `window_state` | 等某 window_id 的 title/bounds 变到某值 |
| `object_state` | 等某 `ax_ref` 的 exists/enabled/focused/editable |
| `object_text` | 等某 `ax_ref` 的 title/value 匹配 |
| `object_absent` | 等某 `ax_ref` 消失，带 `settle_ms` 抗抖（沿用 browser 默认 300） |

约束（Q10）：`within_ms` 默认 10_000（上限 60_000）；`wait` **不得**作为 apply 前置依赖；等待期间的树快照**不进** world_fingerprint。

### 6.7 FR-07 增量读（P2）

`snapshot` 回执附 `snapshot_id`；后续可带 `since`，只回变化节点 + `added/removed/changed` 计数。
与 FR-01 的关系：`since` 与 `node_cursor` 互斥（同为分页维度），同传即拒。

### 6.8 FR-08 受限批量（P2，受闸）

```
do=steps[], steps[1..8]
每步: {do, target(仅 identity), text/keys}
```
- 仅允许 `click` / `scroll_into_view` / `scroll`（非破坏性）；
- 令牌绑定 `sha256(steps)` + `world_version`；
- 回执含 `completed_steps`、失败步 index、失败后现场快照；
- **明确不回滚**，并在回执中说明已生效步数；
- 任一步为破坏性类别 → 整批 `review_required` 拒绝。

---

## 7. 复用表

| 能力 | 复用自 | 复用方式 |
|---|---|---|
| 等待谓词形态 | `browser_perceive` wait（`kind/within_ms/settle_ms/match`） | 结构对齐，语义换到 AX |
| 分页投影 | `browser_perceive` `projection_kinds`/`projection_cursor` | 形态借鉴（`node_kinds`/`node_cursor`），实现独立 |
| 抗抖 | `object_absent` 的 `settle_ms` | 直接沿用默认值 300 |
| 门控/令牌/审计 | `desktop_operate` 现有全流程 | **不新增旁路**，新 do 一律走同一流程 |
| 参数白名单 | `desktop_perceive._ALLOWED_FIELDS` | 新参数必须登记，否则被拒 |

---

## 8. 测试计划

| 场景 | 断言 |
|---|---|
| sparse 渲染 | 无 `null` 字段；`focused=false` 不出现；`geometry=0` 时无 `pos_pt/size_pt`；`ax_ref`/`role` 恒在 |
| 渲染兼容 | 现有 `test_desktop_perceive_m3_v01.py` 全绿（`:363,371,384,1010` 只依赖 `ax_ref`/`len`） |
| 续读 | 超页宽 → `truncated=true` 且 `page.cursor` 存在；带 cursor 续取不重不漏；树变 → `cursor_stale` |
| 续读边界 | `node_limit=0` / `>1500` / 非整数 / 负数 → 确定性拒绝 |
| cursor 与 since 同传 | 确定性拒绝 |
| `scroll_into_view` | 无方向参数；`ax_ref` 不存在 → 拒绝且**不**降级为 scroll |
| `scroll_into_view` 门控 | dry_run 签发令牌；apply 前 world 变 → `FOREGROUND_CHANGED` |
| wait | 谓词达成返回 state；超时返回 `present/absent` 实况，不报成功 |
| wait 与在场检测 | `within_ms` 超 60s 被拒；等待不消耗令牌 |
| 批量 | 破坏性步骤混入 → 整批 `review_required`；失败回执含 `completed_steps` 且不回滚 |
| 渲染不回退安全 | sparse + `full` 两种模式下，同一 dry_run/apply 序列的门控判定一致 |

---

## 9. 观测与指标

| 指标 | 用途 |
|---|---|
| `snapshot` 回执字符数/节点数 | 替换 §2.2 的估算基线（真实测量） |
| 每任务 `snapshot` 调用次数 | 衡量 FR-03/FR-05 减少的轮次 |
| `cursor_stale` 率 | 衡量续读在真实树上的可用性 |
| `FOREGROUND_CHANGED` 计数 + 打破项分类 | **FR-06 的开工闸**（见 §6.5） |
| 批量 `completed_steps` 分布 | 衡量部分完成的实际比例 |

---

## 10. 残余逃逸口与未实测清单

1. **token 数值全部为估算**（CJK=1、其余/4），未用真实 tokenizer；不得作为验收值。
2. **§2.2 样本为构造**，真实 role 分布未知；绝对值须在屏幕解锁后复测替换。
3. **`scroll` 方向符号从未 live 验证**（现有工具描述已自承）；`scroll_into_view` 是其**补充**，不能反证 `scroll` 已正确。
4. **指纹不含 Z 序**，遮挡检测能力为零；§6.5 一旦放宽范围，遮挡漏检风险上升（故设闸）。
5. **`point` 通道残余**：全局 HID tap 可能被浮层接收，world 指纹无法感知。
6. **续读可能诱发翻页地狱**（Q12），靠 `remaining` + `hint` 缓解，非硬性阻止。
7. **批量不可回滚**，只保证回执如实。

---

## 11. 实施批次与开工条件

| 批次 | 内容 | 开工条件 |
|---|---|---|
| **B-1** | FR-01 续读分页 + FR-03 焦点摘要 | 无。屏幕解锁后先跑真实树取基线 |
| **B-2** | FR-02 渲染分级（默认先 `full`，开关灰度） | B-1 落地；真实基线证明渲染是次瓶颈 |
| **B-3** | FR-04 `scroll_into_view` + FR-05 `wait` | 无（独立）；须过 RULE-AI-28 独立审查 |
| **B-4** | FR-06 指纹精确化 | **闸**：§6.5 的 ≥20 次实测完成且"无关打破"占比 ≥30% |
| **B-5** | FR-07 增量 + FR-08 受限批量 | B-1 稳定；批量须先确认 Q11 的破坏性排除表 |

每批：先补测试 → 过独立审查 → 合入。B-3 动了 `do` 枚举与寻址语义，**必须**有回归用例证明既有四类 `do` 行为不变。

---

## 12. 实施偏差登记（B-1/B-2/B-3 落地后回填）

本节记录**代码实际落地与上文设计的差异**。上文未改动，差异在此显式登记——描述与代码不一致的文档比没有文档更危险。

| 编号 | 上文原设计 | 实际落地 | 理由 |
|---|---|---|---|
| **D-1** | §6.1 用"单次会话累计上限"做翻页闸 | **无状态绝对值**：`MAX_PAGED_NODES = 2000`，由游标内 `offset` 判定，超限回 `page_budget_exhausted` | 工具实例的跨调用生命周期不可假定（重启/多会话），进程内计数器口径不一致；无状态口径可被单测直接验证 |
| **D-2** | §6.2 渲染档位默认值未定 | 默认 `render=full` + `geometry=full`；`sparse` 与 `none` 均为显式 opt-in；`sparse` 时**连信封一起**改紧凑分隔符 | full 档必须与既有回执逐字一致（零退化）；缩进与空字段是纯格式开销 |
| **D-3** | §6.3 focused 块含 `editable` | 取自新增 `AxNode.editable`（读 `AXEditable`）；**读不到为 `null`**，不用 role 反推 | 由 role 反推可编辑性属冒充已读；`null` 明确表达"未知" |
| **D-4** | FR-05 谓词集合 | 仅 `exists` / `absent` / `focused` / `enabled` / `value_equals` / `value_contains`；**未实现** `checked` / `selected` | `AxNode` 无对应字段，未经验证的属性通道不编 |
| **D-5** | §6.1 过滤参数名 `node_kinds` | 同名，role 比较**大小写不敏感**（内部小写归一） | 让调用方不必精确猜 AX 角色名大小写 |
| **D-6** | §6.1 游标失效原因分码 | `cursor_invalid`（不可解析）/ `cursor_stale`（树/窗口/深度/过滤变了、或越过树尾）/ `page_budget_exhausted` | 三者对调用方是三种不同处置，合并会逼它去猜 |
| **D-7** | §6.1 遍历截断处理 | 额外回 `degraded: ["ax_traversal_truncated"]` + `page.traversal_truncated` | 否则调用方会把 `remaining=0` 误读成"整棵树看完了" |
| **D-8** | B-4 / B-5 | **未实施** | 闸门未满足：`ax_trusted=false`，无法完成 ≥20 次真实多步任务统计；FR-06 的"无关打破比例"无数据 |
| **D-9** | 工具 schema 未提及 | `desktop_perceive` 的 `action` 枚举增 `wait`、参数增 `node_kinds/node_limit/node_cursor/render/geometry/ax_ref/kind/value/expected/within_ms/settle_ms`；`desktop_operate` 的 `do` 增 `scroll_into_view`。同步更新了 `test_tool_schema_contract_fields` 与 `tools/registry.py` 的 compact 描述 | schema 是模型唯一的能力面；不更新 compact 描述等于能力存在但模型不知道 |
| **D-10** | — | `AxNode` 新增 `editable`/`enabled` 两个读取通道，**均不进入** `ax_fingerprint_nodes` 世界指纹，**也不进入** 节点行渲染白名单 `_NODE_ROW_FIELDS` | 指纹纳入会让"改值/改可用态"被误判为世界漂移而打破 act 门；节点行纳入会给每个节点凭空 +1 键，与降体积目标相反 |

### 12.3 全量门禁的既有红灯（与本批无关，如实记录）

`bash scripts/ci_gate.sh` 在本批改动**之前**即已失败 2 项，均为函数长度基线登记与 AST 实测不一致：

| 失败项 | 实测 vs 登记 | 来源 |
|---|---|---|
| `src/llm_loop/core/loop/engine.py::_run_stream_inner` | 2221 vs 2219 | 提交 `eed9004b4`（EVO-20261104-305716fa） |
| `src/llm_loop/core/loop/engine_services/compaction_gate.py::write_compaction_manifest` | 130 vs 121 | 同上 |

核对方式：这两个文件工作树干净（`git status --porcelain` 无输出）、最近提交为 `eed9004b4`，且**不在本批改动文件集合内**。本批在 ruff ratchet 上的读数为 `new=0 / changed_file_diagnostics=0`。

**不做**：不改基线登记去"顺手变绿"——那会把别人未登记的增长掩盖掉。
**待办**：由该提交的负责方重跑 `python scripts/regen_function_size_baseline.py` 并按 `guard(r9)` 前缀提交。

### 12.4 本批新增/修改的测试（可核验）

| 文件 | 用例数 | 覆盖 |
|---|---|---|
| `tests/unit/test_desktop_ax_paging.py` | 13 | 指纹稳定性/敏感性、游标编解码全拒绝分支、切片边界（PageBudget 已按审查意见删除） |
| `tests/unit/test_desktop_perceive_paging_v01.py` | 18 | 续读不重不漏、cursor_stale/invalid/budget、渲染档位语义、focused 摘要、node_limit 越界拒绝、sparse 恒留 role |
| `tests/unit/test_desktop_operate_scroll_into_view.py` | 7 | dry_run→token→act、point 拒绝、risk=act |
| `tests/unit/test_desktop_waiting.py` | 11 | 状态机：立即命中/超时/absent settle/回闪重置/深冻钟撞轮询上限 |
| `tests/unit/test_desktop_perceive_wait_v01.py` | 13 | 工具层接线：超时仍 ok、同一套 privacy/allowlist 门、形状校验 |

桌面相关合计 **275 passed**（含既有 `test_desktop_perceive_m3_v01.py` 与 `test_desktop_operate_m4_v01.py`）。

### 12.5 本批未能满足的开工条件（如实记录）

- **B-1 声明的"屏幕解锁后先跑真实树取基线"未执行**：本机 `desktop_perceive status` 回执 `ax_trusted=false`，读不到真实 AX 树。
- 因此 B-2 的开工条件"真实基线证明渲染是次瓶颈"**同样未满足**——B-2 仍被执行了，理由是：`render=full` 默认值保证零行为变更，新增档位属纯增量能力，不依赖基线数字即可安全落地；但**"渲染省多少"仍无实测**，`§2.2` 的估算未替换。
- 验收策略相应改为**只断言机制**（字段存在性 / 可续性 / 确定性拒绝码 / 档位语义），不写 token 目标值。

### 12.6 与 dsh-vc 的隔离声明

参考项目 dsh-vc 仍为**只读源码、未运行**；其 UIA 后端、25 种语义动作、ddagrab 采集无一行可移植。本批借鉴的仅是其"游标续读 + 渲染档位 + 等待原语"的**契约形态**，不含其代码（PolyForm Noncommercial，不可引入）。

### 12.7 独立审查回合与修复（RULE-AI-28，如实记录）

第一轮 `git_push` 审查结论 **REVISE（P0=0 / P1=1 / P2=4）**，逐条处置：

| 编号 | 审查意见 | 处置 | 证据 |
|---|---|---|---|
| **P1** | 推送一个 `ci_gate` 红的树，只在文档里"免责声明" | 不接受"免责"式交付。查明 `ci_gate` 的两条红**在我改前即存在**，且**我无权为它放宽基线**——`test_baseline_ratchet_not_raised` 明确禁止任何登记值上调（含我自己函数）。最终做法：**基线文件零改动**，把本批新增逻辑全部落到新函数，使 `_snapshot_action` 105 行（登记 121）、`_validate` 104 行（<120 门槛），本批在棘轮上**零增长**。剩余 2 条红保持原状并如实上报 | `test_arch_guards.py`：50 passed / 2 failed，两条失败项均为 `engine.py` 与 `compaction_gate.py`；`git diff tests/guards/function_size_baseline.json` 为空 |
| **P2-1** | `PageBudget` 无生产调用点，且 `MAX_PAGED_NODES=2000` 因遍历上限 1500 而永不可达 | **删除 `PageBudget` 及其 3 个测试**；`MAX_PAGED_NODES` 改为 **600**（≈ 默认页宽 3 页，低于遍历上限故**可达**），并在代码注释里写明"上限必须 < 1500 否则是死逻辑" | `test_..._page_budget_exhausted_after_offset_cap` 用 1200 节点真实触发 |
| **P2-2** | `node_limit` 静默限幅，与 §8"确定性拒绝"矛盾 | 改为**越界即拒绝**（`invalid_args`，不做 max/min），且拒绝发生在任何 AX 调用之前 | `test_node_limit_out_of_range_is_rejected_not_silently_clamped` 断言 `backend.ax_calls == []` |
| **P2-3** | sparse 下 `role=None` 的节点会整条丢键，违反"`ax_ref`、`role` 恒在" | `_node_row` 在 sparse 分支 `row.setdefault("role", None)`，并注明"字段消失"与"读到未知"语义不同 | `test_sparse_keeps_role_even_when_unreadable` |
| **P2-4** | 工作区有遗留的 CDP 脚本 `_d56_closetabs.py` / `_d56_pages.py` | 非本批产物、未被提交（untracked）。**不动他人文件**；已在上报中列为待清理项 | `git status` 中仍为 untracked |

**修复过程中由护栏抓出的真实退化**（不是靠人工 review，是工具抓的）：

1. 抽取 `_bind_window` 时，内部三处 `return self._envelope(...)` 仍直接返回 `ToolResult`，与三元组约定不符 → 运行期 `AttributeError: 'ToolResult' object has no attribute 'get'`，19 例红。
2. 抽取 `_build_ax_payload` 时丢失末尾 `return`，`payload["ax"]` 变 `None`。
3. 脚本化去缩进把两个方法的函数体缩到类级（语法合法、导入期 `NameError`），`py_compile` 不报、`ruff` 不报，是**测试收集期**才暴露。

三条都说明：这类机械重构必须靠"跑测试"收口，不能靠"看起来对"。最终 `_validate` 从 152 → 104 行、`_snapshot_action` 178 → 105 行。
