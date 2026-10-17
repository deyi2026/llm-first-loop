# 让方法进入执行回路：需求实现设计方案

- 状态：draft v1（2026-10-18 部分实施：§9 所列检索/可见性/排序改动已落地，规则 29/31 的强制 `record_use` 已撤销；其余章节仍待评审）
- 日期：2026-10-17
- 目标：方法库**必须被使用**；使用后**减少错误复发**、**缩短达到结论的路径**
- 事实口径：全部数字为 2026-10-17 对 `data/methods` 与源码的实测，非估算

---

## 0. 结论先行

方法库不缺生成，缺**在正确的时刻出现**。

系统已经有一个"你在重复同一个错误"的识别点（`tool_fault_repeat`，阈值 3 次），它的提醒**确实送达模型**，但建议内容指向异常台账（`search_records(kind=exception_log)`），**不指向方法库**。

把这一根线接上，是让 1156 张卡变成可用能力的最高杠杆单点：同一错误第 3 次发生时，模型看到的应当是"上次你是怎么解决这个的"，而不是"你错了 3 次"。

---

## 1. 已核实事实

| 事实 | 数值 | 核验方式 |
|---|---|---|
| 卡片总数 | 1156 | 逐卡 METHOD.md 计数 |
| 状态分布 | candidate 1123 / hold 28 / retired 2 / active 2 / qualified 1 | 逐卡 frontmatter |
| parent_ref 非空 | 5 张 | grep frontmatter |
| 使用台账 usage.jsonl | 39 条：applied 33 / adapted 5 / not_applicable 1 | 直接统计 |
| qualification 记录 | 73 条，覆盖 68 张卡 | 逐卡 qualification.jsonl |
| promotion=pass | 60 条，覆盖 58 张卡 | 同上 |
| 其中仍挂 candidate | 51 张 | 同上 |
| verdict 分布 | not_evaluated 53 / pass 7 | 同上 |
| task_type | None 59 / unknown 1 | 同上 |
| promotion=pass 时间分布 | 2026-09 共 59 条，2026-10 共 1 条 | 同上 |
| 零信号 candidate | 1063 张，629 张 age>7 天，衰减中位 -34、最大 -46 | 按 (age-7)*2 复算 |
| 检索耗时 | 91-93 ms / 1156 张（线性，1 万张约 0.8 s） | 实测 MethodStore.list |
| 命中面 | edit_file snapshot 冲突 → 429 张；失败 重试 → 658 张 | 实测 |
| 故障台账 | 4866 条，其中 tool_fault_repeat 379 条 | data/audit/exception_log.jsonl |

---

## 2. 被证伪的两个判断（先纠正，再设计）

### 2.1 「58 张 promotion=pass 齐备、只差一次 refine」——门通过，但证据不合格

上一轮据此建议批量补转。实测该批记录：

```
verdict: not_evaluated  53/60
task_type: None         59/60
三项全 pass             7/60
时间：59 条集中在 2026-09（且多为同一 episode 连续评估）
```

update_status 转向 qualified 只校验 promotion=pass + provenance 存在，所以这 51 张**在机械意义上都能转**。但 verdict=not_evaluated 意味着"机制未评估"，把它们批量升进 qualified，等于用弱证据填满**唯一合法的信任层**（qualified 权重 25，且免于零信号衰减）。

**结论：不批量补转。** 这是本设计明确的不做项。

### 2.2 「零信号卡衰减到不可见」——衰减不是主因，命中面过宽才是

打分是 identifier_bonus + lexical*10 + coverage*50 + life。lexical 与 coverage 主导，life 只是加数。实测 top-5 在英文技能名上高度相关：

- browser click element not found → 5 条全部是 not-found/enumerate 类方法
- edit_file snapshot 冲突 过期 → 5 条全部是 CAS/serial-edit 类方法

但中文多词 query 明显漂移：

- 飞书 发送 失败 → top5 为 silent-failure、diff-class、prove-non-delivery 等泛化卡，无一飞书专用
- pytest 失败 重试 → top5 仅 1 条相关

真实缺陷是**命中面 429-658 张、截断到 5 张全凭打分**，同一问题换个措辞结果就换一批。所以"更高效"的关键不是加权重，是**收敛候选面 + 给可信度标记**。

---

## 3. 四个断裂（按杠杆排序）

| 编号 | 断裂 | 证据 |
|---|---|---|
| D1 | 重复故障的提醒指向台账，不指向方法 | status.py:391-397，suggestion 为 search_records(kind=exception_log) |
| D2 | 评估与晋级语义割裂，模型以为说完了 | 样本 note 写「…qualify。」但卡仍 candidate；record_qualification 明确不改 lifecycle |
| D3 | 改进即清零，几乎无人修订 | parent_ref 5/1156；save_candidate 对 parent_ref 只写 frontmatter |
| D4 | 生成无准入，18 天 555→1156 | 同期 qualification 66→68 |

---

## 4. 对抗性拷问（自我评审，结论已并入方案）

| 拷问 | 结论 |
|---|---|
| Q1 在故障通道里塞方法，会不会重蹈"开场常驻注入"被否决的覆辙？ | 形态不同：条件触发（第 3 次同形态故障）、有界（≤2 条）、可关、可忽略。但弱模型照抄的风险同源 → 必须给开关 + 前后错误复发率对比才能上线。 |
| Q2 凭什么说"减少错误"？没有基线就是空话 | 用**同签名复发率**：(phase, error_type) 在会话内出现 ≥2 次的比例。可从 exception_log.jsonl 直接算，不依赖自评。必须先算基线。 |
| Q3 qualified 只有 3 张，按状态加权会不会让 top5 全是这 3 张无关卡？ | 会。所以 status 只作**同 lexical 命中下的破平手**，不作主导项；且必须先过 lexical 门槛才参与排名。 |
| Q4 1123 张 candidate 怎么办？ | 承认它们是"素材库"而非"方法论库"。不要试图全部转正；目标是让**每月新增少量 verified**，而不是清理积压。设计上区分检索面（全部可搜，标注未验证）与信任面（仅 qualified+）。 |
| Q5 改进继承会不会被刷资格？ | 会。继承不给全状态：子卡继承的是**免疫零信号衰减**与父卡 provenance，status 上限为 qualified 的一半权重；且父卡本身已有 parent 时不再继承（链深 ≤2）。 |
| Q6 1156 张每次全量读盘，规模化了会崩吗？ | 会。实测 91 ms 线性 → 1 万张约 0.8 s。必须加 mtime 索引。 |
| Q7 方法卡太长，模型读了反而慢？ | 检索结果只返回 summary + 前三步（已有 summary），全文按需 hydrate。保持"先摘后详"。 |
| Q8 会不会"方法"本身就不该由模型自产这么多？ | 这是根问题。准入即成本：新建卡必须附一条已发生的证据 + 同 episode 限流。 |

---

## 5. 方案

### P0-1【主线】故障重复时接入方法库

**改动点**：src/llm_loop/introspection/status.py 中 tool_fault_repeat 分支。

现状（status.py:391-397）建议内容只指向台账。改为：在该事件首次达阈值时，用 (tool 名, error_type) 做一次有界方法检索，把结果并入 suggestion（仍走既有 report_event → build_report_message → 模型消息，**不新增注入路径**）：

```
suggestion = (
  f"同形态故障第 {count} 次。可先查台账：search_records(kind=exception_log)；"
  f"库中同类处置方法（未验证，仅供参考，不适用请说明理由）：\n"
  f"- {name}：{first_3_steps}\n"
  f"仍适用于本次请 method_manage record_use decision=applied|adapted"
)
```

**边界**：
- 每 (phase, error_type) 签名只发一次（沿用 _tool_fault_alerted 去重）
- 方法候选 ≤2 条，且必须命中 ≥2 个 query token 才入选（复用 P1-1 门槛）
- 检索异常一律 fail-open：拿不到方法不影响原提醒
- 环境开关 METHOD_ON_FAULT_REPEAT_ENABLED，默认 true，可单点回退
- 不改 RU-31 三层计分；此处只提供参考，不改变任何卡的状态或分数

**验收**：
1. 构造同形态故障 3 次，第 3 次回执含方法候选且真实存在（非幻觉名）
2. 开关关闭时不出现方法段
3. 检索超时/异常时原提醒仍完整

---

### P0-2 评估与晋级的显式耦合

**改动点**：registry_experience._run_record_method_qualification 回执。

现状回执只有一行 verdict/promotion，模型在 note 里写「qualify」以为完成，实际 record_qualification 明确不改 lifecycle → 51 张卡卡住。

改为：回执追加**当前可达动作与差距**（陈述事实，不代裁）：

```
status 未改变（record_qualification 只记证据）。
本卡距 qualified：已满足（promotion=pass 且 provenance 独立）
  → 如需晋级：method_manage refine method_ref=<id> transition=qualify
本卡距 active：缺 1 个不同 task_type 的 verdict=pass（当前 task_type=None）
  → 评估时请显式传 task_type
```

**边界**：只输出可达性判断，不自动流转；是否晋级仍由模型裁决。新增参数校验：record_qualification 缺 task_type 时回执提示"该卡将无法满足 →active 的跨域条件"。

**验收**：对一张已满足前置的卡调用后，回执同时含"未改变"与"如何晋级"。

---

### P1-1 检索面收敛

**改动点**：methods/store.py 打分与过滤。

1. **门槛**：lexical 命中需满足「命中 name」或「≥2 个 token 命中」，否则不进候选。现状只要任一词出现即入池 → 429-658 张候选。
2. **中文 query**：store.list 对 CJK 连续串做二元切分后再匹配（当前整词匹配失效，是 飞书 发送 失败 漂移的直接原因）。
3. **status 只破平手**：排序键改为 (lexical, coverage) 降序，status 作为同分次序；避免 3 张 qualified 挤掉真正相关卡。
4. **索引**：以 dir mtime + METHOD.md 数量为键缓存解析结果，命中即跳过读盘。

**边界**：门槛会减少召回，需保留 shadow 记录（命中数、被门槛丢弃数）以便回调阈值。

**验收**：
- 飞书 发送 失败 top5 中出现飞书相关卡（当前 0/5）
- edit_file snapshot 冲突 命中数从 429 显著下降且 top5 不变差
- 1 万张规模下 list ≤150 ms

---

### P2-1 改进继承（对应 D3）

**改动点**：store._save_candidate_locked。

parent_ref 从"仅写 frontmatter"改为：
- 子卡 status 上限为 qualified，但标记 inherited=true，检索 life 取 15（介于 candidate 0 与 qualified 25）
- 继承父卡 qualification 为 provenance（不复制 verdict，只记来源）
- 父卡本身已有 parent_ref 时不再继承（链深 ≤2），防刷

**验收**：基于一张 qualified 卡修订，新卡不再从 0 分起，且无法通过连续修订获得 active。

---

### P2-2 生成准入（对应 D4）

**改动点**：save_candidate 前置校验。

- 必须附 evidence_refs（≥1，指向本会话真实 episode/工具回执）
- 同一 source_episode_ref 最多新建 3 张卡（超出需 parent_ref 修订）
- 新建前对同 trigger 做一次 list，若已有 name 高度重合则回执提示优先修订

**验收**：单会话产出卡数上限生效；重复 trigger 时回执引导修订而非新建。

---

## 6. 度量（上线前后各取一次）

| 指标 | 口径 | 当前值 |
|---|---|---|
| M1 同签名复发率 | 会话内 (phase,error_type) 出现 ≥2 次的比例 | 待算（exception_log.jsonl 4866 条可算） |
| M2 复发时方法采用率 | tool_fault_repeat 发生后同会话内是否出现对应 record_use | 0（通道未接） |
| M3 使用密度 | usage.jsonl 条数 / 有工具调用的 episode 数 | 39 / 待算 |
| M4 信任层厚度 | qualified+ 卡数 | 3 |
| M5 检索准确率 | 人工标注 20 条真实 query 的 top5 相关率 | 待测（英文好、中文漂移） |

M1/M2 是"减少错误"的唯一可机械验证口径；M3/M5 对应"更高效"。
**没有 M1/M2 前后对比，不得宣称"减少错误"。**

---

## 7. 明确不做

- 不批量补转 51 张 promotion=pass 卡（证据 verdict=not_evaluated）
- 不恢复会话开场常驻注入（已因弱模型干扰被否决）
- 不改 RU-31 三层计分口径，不让自评改变资格
- 不重写存量 1156 张卡的内容
- 不以"检索加权"替代触发时机改造（D1 优先级高于排序调优）

---

## 8. 落地顺序

1. **先测基线**（零风险）：算 M1、M3 分母，落 data/audit/method_baseline.json。
2. **P0-2 回执衔接**（改动最小，纯文案 + 校验）：立刻让 51 张卡从"卡住"变为"可推进"。
3. **P0-1 故障接入**（主线）：带开关上线，跑 2 周看 M2 是否非零。
4. **P1-1 检索收敛**：有 P0-1 后才有真实 query 分布可调门槛。
5. **P2-1 / P2-2**：结构性治理，最后做。

每步独立可回退；P0-1 与 P1-1 需按 RULE-AI-28 走独立审查后合并。

---

## 9. 2026-10-17 追加裁决：方法与经验同一套使用口径

### 9.1 用户裁决

> 「经验和规则都能用，方法反而不能用，就是做方法使用设计过多障碍了，对齐经验怎么使用，方法就怎么使用应该是合理的，没必要的限制一定要舍却，只要不会限制干扰大模型智力、能力、执行力不利的，就可以大胆使用。」

据此否决本文档 §5 原先的"分级治理"取向：**问题不在方法卡内容，而在方法多了一套经验没有的使用前提**。

### 9.2 经验侧的基准（为什么说方法多了一套）

| 环节 | 经验 | 方法（改前） |
|---|---|---|
| 检索 | 全量返回，`verification_state` 只展示 | `candidate` 排序权重 0、零信号按 `(age-7)*2` 衰减（上限 -80） |
| 提示注入 | 卡片状态标注 | `hold`/`invalidated`/`teacher` 直接**不出现**在 advisor 提示中 |
| 使用 | 读到即用，无前置 | 读到即用，但 status 暗示"未验证不可信" |
| 标记可信 | `refine_experience(record_use)` 一条调用，模型自declare | `record_qualification` → `qualify` → 再攒 ≥2 个跨 `task_type` 的 pass → `activate`（三步，程序校验） |
| 破坏性动作 | invalidate 需依据 | invalidate/retire 需依据（**保留**） |

### 9.3 已实施改动（6 文件，+92/-164）

1. `methods/store.py`
   - 删除 `life` 状态权重（active +35 / qualified +25 / candidate 0 / hold -10）与零信号年龄衰减；检索只按 `identifier_bonus + lexical*10 + coverage*50` 排序，状态不参与。
   - 正文命中权重 `1 → 5`：正文包含查询词比一行 description 的偶然提及更能代表内容相关。这是替代原先"用状态权重压过词法噪声"的正确做法。
   - 删除 `candidate → active` 禁止、`qualified` 需 `promotion=pass`、`active` 需 ≥2 个跨域 `task_type` 三道转换门。**保留** teacher 不可变、invalidate/retire 需独立事实依据（资产保护，不限制使用）。
2. `introspection/knowledge_advisor.py`：`_METHOD_ELIGIBLE` 由 3 态扩到全部 6 态（hold/invalidated/teacher 不再被隐藏）。
3. `introspection/registry_experience.py`、`registry_introspection.py`、`tools/registry.py`：工具描述明示"候选卡与 active 同等可用、status 只是质量标注、读到即可照做、`record_use` 可选"。
4. `tests/unit/test_method_learning.py`：删/改 6 处依赖旧门的断言；新增"状态不改变检索可见度"测试。

### 9.4 实测：改动前后 top5 对比（`data/methods`，1157 张）

状态分布：candidate 1124 / hold 28 / retired 2 / active 2 / qualified 1（97.1% 是 candidate）。

| query | old/new top5 重叠 | 说明 |
|---|---|---|
| `failure retry` | 5 / 5 | 头部靠 identifier bonus（250）与 lexical，状态权重影响不到 |
| `飞书 发送 失败` | **2 / 5** | 正文权重修正后，真正含中文词的方法（resolve-recipient…、resolve-conversation-anchored…）才上来 |
| `browser click element not found` | 4 / 5 | 均匀小幅变化 |
| `edit_file snapshot 冲突` | 4 / 5 | 同上 |

**诚实修正上一轮推断**：状态权重不是"方法不能用"的主因——库里 97% 的卡都是 candidate，彼此之间没有状态差，所以压低效果有限。真正被修好的是两件别的：一是**中英文正文检索**（`飞书` 那条 2/5 的重叠就是证据），二是**"要用就得先走三步证明"的流程负担**（这是设计障碍，不是排序问题）。

### 9.5 未做（需用户单独裁决）

- **RULE-AI-29 第 2 条 / RULE-AI-31 第 2 条**原规定"所有实际使用必须落 `record_use`"。这条对经验与方法**同等**适用，不是方法独有障碍。**2026-10-18 用户授权后已撤销该强制义务**：`record_use` 改为可选，不记录不构成违规；负反馈（卡片有错/过期）的修/弃义务保留。见 `docs/ai_rules.md` 规则二十九、三十一条目注记。
- 运行中的进程加载旧模块，**改动需重启服务才生效**。2026-10-18 已提交 restart（`svc-65a9a8ab009142d2948abb4cfd6677b4`），状态 `waiting_for_requester_exit`——当前会话退出后执行，届时新进程加载新模块。
- 全量测试未跑（按 RULE-AI-28 需独立审查准入）。本次仅跑局部：`test_method_learning.py` 35 passed，`-k "method or experience or knowledge or introspection"` 494 passed，ruff clean。

### 9.6 回退

改动集中在 6 个文件、无数据结构变更、无迁移；`git checkout -- src tests` 即完全回退。旧行为对应的 4 个测试已随实现同步移除，回退时需一并回退测试。

