# SMX × Semantic Manipulation Framework 分析与发展建议

**日期：2026-09-12**  
**项目：LFL / Semantic Manipulation Framework / SMX**  
**设计依据：** `docs/DESIGN-20260911-semantic-manipulation-framework.md`

---

## 一、核心结论

重新以 `docs/DESIGN-20260911-semantic-manipulation-framework.md` 为最高设计依据后，SMX 的定位应当明确调整为：

> **Semantic Manipulation Framework 是主项目；SMX 是 Domain-0（Shell / FS / Process）的第一个参考实现与实验场。**

因此，SMX 不应被理解为一个终点，也不只是一个“更好的语义 Shell”。

它真正承担的是更大的验证任务：

> **验证大模型能否通过“语义对象 + 状态版本 + 增量变化 + 谓词等待 + 可回验回执”的统一接口操控外部世界，同时保持模型拥有理解、策略和完成判断权。**

SMX 当前最重要的成果，不是增加了 `wait / diff / receipt` 几个工具能力，而是已经在低风险、强确定性的 Shell / 文件系统环境里验证了 Semantic Manipulation Framework 的若干核心原则：

- 程序提供事实，不提供策略；
- 模型仍然负责判断下一步；
- 世界状态可以版本化；
- 状态变化可以用 diff 而不是全量重述；
- 等待可以变成机械谓词，而不是模型反复 `sleep → read → sleep → read`；
- 不完整观察必须显式表达，不允许“没看到 = 不存在”；
- 任何语义解释都必须能够回到原始接地事实。

从这个角度看，SMX 应被视为：

> **Semantic Manipulation Framework 的 Domain-0 Proof / Wind Tunnel。**

---

## 二、为什么 SMX 与 LFL 的架构哲学高度一致

LFL 的核心原则是：

> **程序是 AI 的感官和手脚，不是大脑。**

映射到 Semantic Manipulation Framework：

- 程序负责：感知、状态采集、版本维护、diff、等待、原子执行、安全边界、回执、可恢复性、完整性声明。
- 模型负责：理解任务、选择关注对象、决定动作、判断异常含义、决定恢复策略、判断任务是否完成。

SMX 当前正式接入形态 `smx_perceive` 已经很好地遵守这一边界：

- 暴露 `wait / snapshot / diff / receipt`；
- 不直接向 Agent 暴露 SMX 自身的 `exec / bg / collect` 执行面；
- 真正执行命令仍经 `execute_command`；
- 不替模型做工具选择；
- 不自动重试；
- 不自动纠偏；
- 不自动判断任务完成。

这正是 Semantic Manipulation Framework 应当长期保持的权力结构。

---

## 三、SMX 已经验证了设计文档的哪些核心原则

### 3.1 P1：语义是 LLM 的原生介质

当前 SMX 已经把一部分 Shell 原始世界状态提升成了结构化事实：

- 目录前后差异；
- created / deleted / modified；
- wait predicate；
- process / file readiness；
- receipt；
- pipeline exit chain；
- snapshot completeness。

但目前仍然主要是“状态语义化”，还没有进入真正完整的“世界对象语义化”。

因此 P1 当前属于“部分验证”。

### 3.2 P2：模型是大脑，程序是感官与手脚

这一点当前 SMX 已经验证得比较充分。

SMX 可以告诉模型“某文件出现了”“目录发生了哪些机械变化”“这个等待条件是否满足”，但不会告诉模型“下一步应该修改哪个文件”“哪个变化最重要”“现在任务已经完成”。

这非常符合 LFL-First / LLM-First 的边界。

### 3.3 P3：语义层只给事实，不给策略

当前 `smx_perceive` 没有：

- recommended_action；
- best_candidate；
- semantic priority；
- automatic next step；
- completion decision。

未来扩展到 Browser / OS，也必须保持这条边界。

### 3.4 P4：语义解释必须可回验

这一点是 SMX 当前最成熟的部分之一。

已有机制包括：

- `snapshot_id`
- `run_id`
- `receipt.json`
- stdout / stderr 原始路径
- snapshot store
- `smx_sha`
- `diff_complete`
- truncation 明示
- unknown / null 而不是假定值

特别是最近修复后的完整性纪律：当任一侧 snapshot 被 budget 截断或出现遍历异常时，不再把缺失条目误报为 `deleted`，而是明确返回：

```text
diff_complete = false
created = null
deleted = null
```

并抑制不可信的 `+/-` 差异行。

这代表一个非常重要的框架原则：

> **程序不知道 ≠ 世界中不存在。**

这个原则以后应推广到 Browser、OS、Memory、Evidence 等所有结构化感知层。

### 3.5 P5：效率来自增量，而不是压缩

Stage2 A/B 已经给出方向性证据。

有效对中，重复感知下降：

| 任务 | Control | SMX | 变化 |
|---|---:|---:|---:|
| T1 | 18 | 8 | -56% |
| T5 | 18 | 12 | -33% |
| T6 | 13 | 11 | -15% |
| T3 | 20 | 20 | 持平 |

这说明：

> **语义 diff 和结构化回执确实可以减少模型重新观察世界。**

更重要的潜在二阶收益是：

```text
更少重感知
→ 更少工具输出
→ 更少新 token
→ 更慢的 context 增长
→ 更少 fold 压力
→ 更稳定的 working set
→ 更好的长 Agent 连续性
```

不过这一整条链目前还只是合理推论，不能声称已经完成因果验证。

---

## 四、当前 SMX 还不是完整的 Semantic Manipulation Framework

设计文档定义的核心其实是“四契约”：

1. 感知契约
2. 标识契约
3. 动作契约
4. 反馈契约

当前 SMX 只完整覆盖其中一部分。

---

## 五、四契约当前完成度

### 5.1 感知契约：已经比较成熟

当前已有：

```text
wait
snapshot
diff
receipt
```

并且有：

- scope；
- depth；
- budget；
- truncation；
- completeness；
- raw receipt；
- snapshot version；
- grounding path。

这一部分已经非常接近可抽象为通用协议。

### 5.2 标识契约：目前只有雏形

当前有：

- `snapshot_id`
- `run_id`
- 文件路径
- receipt path

但设计文档要求的是 **Stable Semantic Object ID**。

例如 Browser 应引用：

```text
el_a3f2
```

而不是每一轮重新匹配：

```text
button[name="提交订单"]
```

Shell / FS 最终也应该能够表达：

```text
fs_721
proc_338
job_82
```

因此当前 SMX 有的是“状态 ID / 回执 ID”，还不是完整的“世界对象 ID”。

### 5.3 动作契约：目前尚未真正实现

当前 Shell 动作主路径仍然是：

```text
模型
→ execute_command("...")
```

SMX 负责观察：

```text
wait
snapshot
diff
receipt
```

这是当前阶段正确的安全裁决。

但完整 Semantic Manipulation Framework 最终希望做到：

```text
action(
  verb,
  semantic_object,
  expected_version
)
```

例如 Browser：

```text
click(
  id = "el_a3f2",
  expected_version = "snap_021"
)
```

而不是：

```text
page.locator("...").click()
```

更不是：

```text
click(x=387, y=612)
```

因此当前 SMX 更准确的定位是 **Semantic Perception 的成熟原型**，而不是完整的 Semantic Manipulation runtime。

### 5.4 反馈契约：当前最成熟

SMX 已经非常接近跨域通用反馈模型：

```text
before_version
after_version
created
deleted
modified
completeness
grounding
receipt
```

这一层以后不应该重新设计，而应该直接上提成框架契约。

---

## 六、建议抽象出的跨域最小内核

下一阶段不建议直接进入大规模 Browser 编码。

更重要的是先从 SMX 已验证事实中抽出一个：

> **Semantic Manipulation Contract v0.1**

建议最小包含以下六个跨域对象。

---

## 七、SemanticObject

```text
{
  id,
  domain,
  kind,
  attributes,
  state,
  relations,
  grounding_ref,
  observed_version
}
```

### Browser 示例

```text
{
  id: "el_a31",
  domain: "browser",
  kind: "button",
  attributes: {
    name: "提交订单"
  },
  state: {
    enabled: true,
    visible: true
  }
}
```

### OS 示例

```text
{
  id: "ui_f17",
  domain: "os",
  kind: "text_field",
  attributes: {
    name: "Password"
  },
  state: {
    focused: false
  }
}
```

### Shell / FS 示例

```text
{
  id: "fs_721",
  domain: "filesystem",
  kind: "file",
  attributes: {
    path: "src/app.py"
  },
  state: {
    size: 12344
  }
}
```

关键要求：

> **SemanticObject 只能承载事实，不能出现 recommended_action。**

---

## 八、WorldSnapshot

```text
{
  snapshot_id,
  domain,
  scope,
  observed_at,
  objects,
  completeness,
  blind_spots,
  grounding_version
}
```

SMX 当前 snapshot 已经是这个对象的非常好的 Domain-0 雏形。

---

## 九、SemanticDiff

```text
{
  from_version,
  to_version,
  created,
  removed,
  changed,
  completeness
}
```

这是 SMX 当前最值得直接推广到 Browser / OS 的部分。

它对应 Semantic Manipulation Framework 的核心原则：

> **世界状态不重述，只报告变化。**

---

## 十、SemanticAction

```text
{
  action_id,
  verb,
  target_id,
  args,
  expected_version
}
```

模型负责：

- 选哪个对象；
- 做什么动作；
- 何时执行。

程序负责：

- 把 Semantic ID 映射到底层真实对象；
- 验证版本；
- 执行动作；
- 返回机械事实。

---

## 十一、ActionReceipt

```text
{
  action_id,
  status,
  target_id,
  before_version,
  after_version,
  effects,
  side_effects,
  grounding_refs,
  completeness
}
```

SMX receipt 已经是这一对象非常有价值的前身。

未来 Browser / OS 也应该遵循同一结构。

---

## 十二、Predicate

建议把 SMX `wait` 真正上提为跨域 Predicate，而不是继续扩展 shell-specific wait。

统一形式：

```text
{
  target,
  property,
  operator,
  value
}
```

例如：

```text
file.exists == true
port.open == true
process.state == exited
element.visible == true
element.enabled == true
window.title contains "..."
```

这样统一的不是 shell wait，而是：

> **Predicate Wait**

这才是可跨域推广的真正抽象。

---

## 十三、三个域最终应当共享同一认知接口

### Shell / FS

```text
observe()
snapshot()
diff()
wait(predicate)
execute_command()
```

### Browser

```text
observe(scope)
hydrate(id)
click(id)
fill(id)
wait(predicate)
diff()
```

### OS

```text
observe(window)
hydrate(id)
click(id)
set_value(id)
wait(predicate)
diff()
```

模型面对的统一结构是：

> **对象 + 动作 + 状态变化**

而不是：

- bash
- CSS
- XPath
- Playwright script
- AX selector
- UIA selector
- pixel coordinate

底层技术介质不同，但模型认知接口保持一致。

---

## 十四、现有 Playwright 工具不能直接视为 Browser Phase 1

当前 LFL 中已有：

```text
src/llm_loop/introspection/tools_playwright_exec.py
```

其基本范式仍然是：

```text
模型写 Python
→ helper
→ Playwright
→ Browser
```

它没有：

- persistent semantic object ID；
- snapshot lineage；
- object hydration；
- semantic diff；
- expected_version；
- cross-turn element tracking；
- blind-spot coverage；
- incremental observation。

所以它不能直接算作 Semantic Manipulation Browser Adapter。

但是它仍然有价值。

正确关系应该是：

```text
Semantic Browser Adapter
        ↓
Grounding / Execution backend
        ↓
Playwright / CDP
```

也就是说：

> **Playwright 应成为底层驱动，而不是模型接口。**

这和 SMX 当前已经做出的架构裁决同构：

```text
Semantic perception
        ↓
execute_command
        ↓
shell
```

---

## 十五、为什么 Shell 是非常好的 Domain-0

Shell / FS 世界特别适合作为 Semantic Manipulation Framework 的第一验证域，因为：

- 世界状态真值容易获取；
- diff 可以精确验证；
- judge 容易机械化；
- side effect 容易观察；
- wait 可以客观验证；
- snapshot 成本低；
- 基本不存在视觉歧义；
- 很容易检查程序有没有偷偷做策略。

因此 SMX 更像是：

> **Semantic Manipulation Framework 的 wind tunnel。**

它负责先验证基本空气动力学。

Browser 才是下一阶段真正复杂的飞行环境。

---

## 十六、建议的总体项目结构

```text
Semantic Manipulation Framework
│
├── Phase 0   Cross-domain Contract
│      SemanticObject
│      WorldSnapshot
│      SemanticDiff
│      Predicate
│      SemanticAction
│      ActionReceipt
│      GroundingRef
│
├── Domain-0  Shell / FS / Process
│      SMX
│
├── Phase 1   Browser
│      DOM + AX grounding
│      stable semantic ID
│      semantic observe
│      hydrate
│      click / fill / select
│      predicate wait
│      semantic diff
│
├── Phase 2   Vision blind-spot
│      canvas
│      WebGL
│      inaccessible UI
│      model-requested vision only
│
└── Phase 3   OS
       macOS AX
       Windows UIA
       Linux AT-SPI
```

Browser 应继续放在 OS 前面。

原因是 Browser 具有更完整的 grounding：

```text
DOM
+ Accessibility Tree
+ Screenshot
+ URL / network / document state
```

因此更适合先解决 stable ID、grounding fidelity、snapshot lineage、semantic diff、stale action rejection。

---

## 十七、研究目标也应该升级

以后真正要验证的核心问题，不再只是：

> SMX 是否让 Shell 少几个工具调用？

而应该升级为：

> **LLM 是否能够通过统一的“语义状态—动作—反馈”接口，比 raw shell / raw DOM / raw Accessibility Tree / screenshot / coordinate 更可靠、更省认知成本地操控世界？**

建议核心指标升级为：

- Semantic ID stability
- Grounding round-trip fidelity
- stale-action rejection accuracy
- diff precision
- diff completeness
- blind-spot honesty
- redundant re-observation
- model tool rounds
- new-prefill tokens
- context growth
- cache working-set impact
- recovery after world-state change
- task success
- human intervention rate

wall time 仍然可以保留，但不应成为主要指标。

---

## 十八、SMX 当前工程成熟度与证据成熟度应分开评价

当前状态呈现出一个明显结构：

> **SMX 的工程实现成熟度高于 Agent 效果证据成熟度。**

当前已有：

- 安全边界审查；
- S1–S6 闭环；
- opt-in 感知层；
- 13/13 glue tests；
- 18/18 lab selftest；
- diff completeness；
- truncation honesty；
- Stage2 A/B。

但正式 AgentPilot v1 中：

- 108 runs；
- SMX 使用次数 = 0。

因此 AgentPilot v1 的 LFL 优势不能归因于 SMX。

这反而是一个好条件。未来可以非常干净地做：

```text
同一个 LFL
同一个 Ornith
同一个 8901
同一任务
只改变 SMX OFF / ON
```

用于验证 SMX 的真实增量价值。

---

## 十九、当前不建议继续做大的 SMX 功能扩张

如果总目标是 Semantic Manipulation Framework，则当前最不应该做的是把 SMX 本身继续扩展成一个庞大的 Shell runtime。

暂时不建议优先增加：

- 大量新 predicate；
- process ontology；
- 自动 wait 选择；
- 自动 diff 路由；
- 自动判断下一步；
- 复杂 shell semantic planner；
- 第二执行通道；
- 自动 replay / retry。

否则很容易演化成：

> **复杂 Shell Agent Framework**

而不是：

> **跨 Browser / OS / Shell 的 Semantic Manipulation Framework**

---

## 二十、下一阶段最高优先级

### Phase 0：Semantic Manipulation Contract v0.1

建议先写合同，不急着写 Browser 实现。

合同至少定义：

1. **SemanticObject**：对象是什么。
2. **GroundingRef**：对象如何回到物理真值。
3. **WorldSnapshot**：世界状态如何版本化。
4. **SemanticDiff**：状态变化如何表达。
5. **Predicate**：等待 / 条件如何统一表达。
6. **SemanticAction**：模型动作如何绑定目标和 expected_version。
7. **ActionReceipt**：程序如何返回动作后的机械事实。
8. **Completeness Contract**：什么时候可以说完整，什么时候必须返回 unknown。
9. **Blind-spot Contract**：无法观察的区域必须如何显式表达。
10. **Authority Boundary**：程序永远不得推荐最佳对象、自动决定下一步、自动重试、自动纠偏、判断任务完成。

---

## 二十一、建议先让 SMX 实现这个合同

这是非常关键的一步。

不要先拿 Browser 来证明合同。

先要求现有 SMX：

> **在不显著改变行为的前提下，适配 Semantic Manipulation Contract v0.1。**

如果能够做到：

```text
现有 SMX
→ 只增加统一 schema adapter
→ 行为基本不变
→ Stage2 事实仍成立
```

说明我们提炼出来的可能是真正的跨域合同。

如果为了适配合同必须大量扭曲 SMX，则说明抽象仍然太 Browser-centric 或理论化。

---

## 二十二、然后再进入 Browser Phase 1

Browser Phase 1 应尽量小，只验证四件最核心的事：

### 1. Stable Semantic ID

同一个物理元素跨轮次是否保持 ID。

### 2. Grounding

任意 Semantic ID 是否可以回验到：

- DOM；
- AX；
- screenshot region。

### 3. Semantic Action

模型能否：

```text
click(id)
fill(id)
select(id)
```

而不是操作 CSS/XPath/坐标。

### 4. Semantic Diff

操作后只返回变化，而不是重新倾倒整页。

如果这四点成立，Semantic Manipulation Framework 才真正从 Shell Domain-0 走向跨域。

---

## 二十三、项目级评价

如果 SMX 只是一个“语义 Shell”，那么它是一个不错的 Agent 工具创新。

但如果 SMX 被正确定位为：

> **`DESIGN-20260911` 的 Domain-0 Proof**

那么项目层级明显更高。

它真正尝试解决的是：

> **定义 LLM 与可操作世界之间的统一语义 I/O 层。**

如果这一层成立，LFL 的技术差异化将不再只来自：

- context management；
- continuity；
- cache；
- evidence；
- tool harness；
- recoverability。

还会多出一个非常重要的新层：

> **模型不直接面对机器原语，而面对可回验、版本化、增量、可水合的世界语义。**

同时保持：

> **程序不替模型思考。**

这实际上是 LFL 架构哲学向“外部世界操控”方向最自然的一次延伸。

---

## 二十四、最终建议

当前主线建议调整为：

```text
第一步：
冻结 SMX 功能扩张

第二步：
编写 Semantic Manipulation Contract v0.1

第三步：
让 SMX 成为第一个 contract-conformant Domain Adapter

第四步：
补 SMX focused OFF / ON 实验，验证 Domain-0 的真实增量收益

第五步：
进入 Browser Phase 1

第六步：
验证 stable ID / grounding / semantic action / semantic diff

第七步：
再引入 vision blind-spot

第八步：
最后进入 OS adapter
```

总体原则：

> **先统一认知契约，再扩展物理介质。**

而不是：

> 为每个介质分别发明一套 Agent 工具。

如果这一方向坚持住，SMX 最终的价值将不在于它自己有多强，而在于：

> **它帮助 LFL 找到了“模型如何与世界交互”的统一架构语言。**
