# SMC AI-Native Control Plane v0.2 — 跨桌面与移动系统语义操控架构

> 日期：2026-09-19
> 状态：**DESIGN FREEZE CANDIDATE / DOCS-ONLY**
> 基线：**lfl/main@c9f33b4c3d2cbe92c7865d1aba1a6b9c8b165ed7**
> 性质：架构与合同设计；**不修改生产代码、不授予新的执行权限、不改变 P4-FCR v0.1 冻结结果、不进入 P4-LIVE。**
> 上游：SMC-CONTRACT-v0.1、DESIGN-20260911-semantic-manipulation-framework.md、Browser SMC Phase 1、Semantic Logic P0-P4D、P4-FCR v0.1 负结果。

---

## 0. 一句话定义

**SMC 是连接 AI 语义推理与现实计算环境的统一控制协议：模型选择语义对象、动作与参数；程序把已经确定的语义动作机械绑定到当前平台上可验证、已授权且语义等价的物理执行通道，并用版本、边界事实、差分与回执诚实结算。**

SMC 不是 Browser Automation 的另一个封装，也不是新的鼠标键盘模拟器。

它长期服务于 Browser、Windows、macOS、Linux、Android、iOS/iPadOS、文件/Shell、原生应用、Web 应用，以及主动为 AI 暴露语义能力的应用。

UI、快捷键、命令行、Accessibility API、App Intent、应用 API、键鼠、手势和视觉都只是 **Execution Binding**，不是模型的主要思维介质。

---

## 1. 本版为什么需要重做

### 1.1 Browser 已证明“语义面”有价值，但也暴露了 transport 泄漏

P4-FCR v0.1 已完整执行 40/40 declaration-only A/B：

- Arm B structural：20/20；
- Arm B mechanical：16/20；
- 四个失败全部集中于 select 路径；
- exact opaque grounding 引用被模型从 grounding:// 转录成 ground://；
- 原矩阵因此正式 NOT_QUALIFIED，P4-LIVE 被 Gate 阻止。

这个结果不支持“教模型更认真复制长引用”作为长期方向。

它暴露的是更一般的问题：

> **LLM 应负责“选择哪个语义对象”，不应负责重新生成 transport identity 的每一个字节。**

### 1.2 Browser 不是终点

现有 SMC 合同本来就把 Browser / OS / Shell / FS 放在统一跨域方向里，但现有设计对以下问题仍不充分：

- Desktop 的前台 App / Window / Focus / Selection；
- 快捷键依赖 ambient context 的风险；
- Android 与 iOS 完全不同的控制权限模型；
- App 主动暴露复杂 AI 动作时如何避免 Tool 爆炸；
- UI 做不到时，是否应该开发 AI-native Semantic Control；
- Execution Binding 自动选择是否会偷偷拿走模型决策权。

本版专门回答这些问题。

---

## 2. 不变的六对象核心

v0.2 **不新增第七核心对象**。

继续保持：

1. SemanticObject
2. WorldSnapshot
3. SemanticDiff
4. SemanticAction
5. ActionReceipt
6. Predicate

原因：

- 六对象已经能表达对象、世界状态、变化、动作、动作事实与条件；
- Window / Focus / Selection / Gesture / AppIntent 等首先应由 domain profile 表达；
- 只有未来真实反例证明六对象无法无歧义表达，才允许扩 core schema；
- 禁止“每遇到一个平台概念就新增一个核心对象”导致合同失去跨域稳定性。

---

## 3. 三轮架构拷问后的正式裁决

### Grill-1：Semantic Control 会不会变成另一种 Tool Explosion？

#### 问题

如果每个 App 暴露 save、export、share、archive、resize、generate、upload、publish 等能力，最终模型是不是又面对几百、几千个工具？

#### 裁决

**Capability 不能直接等于 provider-visible tool。**

模型面应尽量保持一小组稳定操作面：

~~~text
observe
hydrate
diff
act
wait
assert
~~~

act 的动作种类来自 **CapabilityManifest 中的数据化 typed verb contract**，不是每发现一个 capability 就永久新增一个全局工具定义。

允许实现为少量 typed family tools，但必须满足：

- tool 数量不随安装 App 数量线性增长；
- capability discovery 是数据，不是动态注入海量函数；
- 模型可以按 scope/domain 显式查询 capability；
- provider 不得把所有底层 API 原样倾倒成模型工具；
- capability projection 必须标完整性，不能静默省略。

**裁决：SMC 的扩展单位是 capability declaration，不是 tool。**

---

### Grill-2：Execution Binding 自动选择会不会夺走模型决策权？

#### 问题

模型说 save(document_17)，下面可能有 native API、App Intent、UIA/AX/AT-SPI action、menu command、shortcut、keyboard input。程序自动选哪条，会不会已经在替模型做策略？

#### 裁决

程序只能在一个 **Frozen Equivalence Class** 内机械选 binding。

两个 binding 只有同时满足以下条件，才可被程序视为自动可替换：

1. 同一 semantic verb；
2. 同一 target scope；
3. 同一 semantic argument contract；
4. 同一 authorization class；
5. 同一 effect class；
6. 同一 idempotency / atomicity 语义；
7. 同一用户确认要求；
8. 能产生等价的 receipt / post-observation obligations；
9. 不需要根据任务目的判断哪个“更好”；
10. equivalence 由 adapter profile 预声明并经 deterministic conformance 验证。

例如 document.save 若 App native save command 与 Cmd+S 被证明在该 App / document state 下语义等价，可以机械选择。

但 save、save_as、export、overwrite、publish 不是一个 equivalence class，必须由模型选择。

#### 禁止项

程序不得：

- 因“成功率更高”偷偷改 semantic verb；
- 因“用户可能想要”自动选 Save As；
- 因某 binding 失败就自动换一个语义不完全等价的路径；
- 用 fuzzy target 替换模型选择的对象；
- 把 recovery strategy 藏进 binding resolver。

**裁决：Binding selection 是 compiler dispatch，不是 planner routing。**

---

### Grill-3：iOS / Android 权限差异会不会让跨平台统一合同名存实亡？

#### 问题

桌面 OS 可以有较强的跨 App Accessibility client。Android 在用户授权 AccessibilityService 后，可以操作节点、执行 global action，并在声明 capability 后发 gesture。

iOS 的公开 Accessibility 模型主要让 App 向系统暴露自身可访问语义；不能假设普通第三方 App 拥有 macOS 式通用跨 App AX client 权限。

如果物理能力如此不同，统一合同还有意义吗？

#### 裁决

统一的是：

- 对象模型；
- action / predicate 语义；
- scope / version / provenance；
- permission / capability honesty；
- receipt / diff；
- unsupported / human_required 的表达。

**不是统一“任何设备都能执行同样的动作”。**

所以 CapabilityManifest 必须显式声明控制等级：

~~~text
DIRECT_SEMANTIC
ACCESSIBILITY_CONTROL
SYSTEM_COMMAND
SHORTCUT
STRUCTURED_INPUT
VISION_GROUNDED_INPUT
OBSERVE_ONLY
UNSUPPORTED
HUMAN_REQUIRED
~~~

一个 iOS App 若没有合作式语义入口，就可以诚实返回 UNSUPPORTED 或 HUMAN_REQUIRED。

这不代表 SMC 失败，反而说明 SMC 没有把平台限制伪装成模型能力问题。

**裁决：SMC 是跨平台统一语义协议，不是跨平台权限绕过层。**

---

## 4. 模型面对“语义”，程序承担“精确性”

传统 Computer Use 常见路径：

~~~text
intent
→ screenshot
→ visual locate
→ coordinate
→ mouse / keyboard
→ screenshot
~~~

命令式自动化常见路径：

~~~text
intent
→ exact command
→ exact path / exact args
→ execute
~~~

两者分别把不同弱项压给模型：

- UI 路线要求空间定位、焦点追踪、布局适应；
- command 路线要求字节级路径/参数准确。

SMC 目标：

~~~text
intent
→ SemanticObject
→ SemanticAction
→ exact mechanical binding
→ ActionReceipt + SemanticDiff
~~~

模型负责选择对象、选择 verb、提供 semantic args、解释异常、选择恢复策略、判断任务是否完成。

程序负责 exact identity lookup、version fencing、context prerequisite、permission/lock/reservation、deterministic compilation、physical dispatch、side-effect observation 和 durable receipt。

---

## 5. ActionRef：消除长 GroundingRef 转录负担

### 5.1 目的

模型不应反复复制长 grounding URI，而应操作短、opaque、session-scoped 的 ActionRef，例如 ar_7k2m。

### 5.2 机械绑定

ActionRef 不是第七核心对象；它是 Runtime 发放的短期机械 handle。

内部绑定至少包括：

~~~text
session_id
device_id
domain
scope_ref
semantic_object_id
observation_ref
grounding_ref
observed_version
permission_scope
issued_at
expires_at
integrity
~~~

### 5.3 硬约束

ActionRef：

- MUST opaque；
- MUST session / authority scoped；
- MUST integrity-bound；
- MUST expiry-bound；
- MUST exact resolve；
- MUST NOT fuzzy；
- MUST NOT silently refresh；
- MUST NOT silently rebind；
- MUST NOT itself mint permission。

过期就是 expired；跨 session 就是 unauthorized；identity 不再成立就是 stale / unresolved。

### 5.4 与 SemanticObject.id 的关系

SemanticObject.id 表示语义对象身份。

ActionRef 表示：

> 在当前授权、版本、scope 与 retention 条件下，对该对象执行动作的精确机械引用。

两者不能混为一谈。

---

## 6. ExecutionBinding：统一 API / Accessibility / Shortcut / Input

ExecutionBinding 不是模型-facing 核心对象。

它是 adapter 内部或 capability manifest 中可审计的机械声明：

~~~text
SemanticAction
    ↓
ExecutionBinding
    ↓
physical mechanism
~~~

第一版至少区分：

~~~text
native_semantic
app_intent
native_api
accessibility_action
system_command
application_command
keyboard_shortcut
structured_keyboard
structured_pointer
structured_gesture
vision_grounded_input
~~~

### 6.1 快捷键的正确位置

模型不应主要说 press(Cmd+S)，而应说 save(document_17)。

macOS adapter 可以把它编译到 Cmd+S；Windows adapter 可以编译到 Ctrl+S；若 App 有 native command，则可能根本不发按键。

快捷键是执行后端，不是 AI 的操作语言。

---

## 7. Interaction Context：快捷键与桌面操作的正确性前提

OS 操作最大的风险不是坐标，而是 ambient context。

因此各 OS Domain Profile 的 WorldSnapshot 必须能表达当前可观察的：

~~~text
active_application
active_window
focused_object
selection
input_method
keyboard_layout
modifier_state
foreground_scene
orientation
virtual_keyboard
system_overlay
lock_state
~~~

第一版把这些放在 WorldSnapshot.extensions.interaction_context，而不是增加新的 core object。

### 7.1 Context version

必须有可比较的 context_version 或等价版本事实。

需要快捷键或 input binding 的动作，应携带 mechanical preconditions：

~~~text
expected_app
expected_window
expected_focus
expected_context_version
~~~

任何一项变化，均在 dispatch 前拒绝。

### 7.2 Context preparation

若模型已明确选择 save(document_17)，程序可以机械完成：

~~~text
activate exact owning window
focus exact document
execute equivalent save binding
~~~

前提：

- preparation 是该 binding 预声明的 mechanical prerequisite；
- 不包含目标/verb 重新选择；
- 每一步 observable effect 写入 receipt；
- 用户并发操作导致 context 改变时 fail closed。

---

## 8. Semantic Control Provider：UI 之外的 AI-native 能力

### 8.1 为什么需要 Provider

Accessibility / UI 擅长表达 button invoke、expand/collapse、selection、text、scroll、value、focus。

复杂应用能力却往往是：

~~~text
export(document, format, destination)
archive(message)
share(asset, recipient)
create_workspace(template)
apply_filter(dataset, expression)
render(project, preset)
~~~

逼 AI 用 UI 一步步模拟这些操作，会重新引入 navigation noise、focus risk、selector churn、token/round 消耗和 transport 参数错误。

因此允许应用主动暴露 **Semantic Control Provider (SCP)**。

### 8.2 SCP 不是视觉 Widget

Semantic Control：

- 可以有 UI 对应物；
- 也可以没有独立 UI；
- 但必须是用户授权范围内真实存在的应用能力；
- 不能因为“给 AI 用”而拥有更高权限。

### 8.3 Semantic Control Descriptor

示例：

~~~yaml
control_id: document.export
target_kind: document
verb: export
parameters:
  format:
    type: enum
    values: [pdf, docx, txt]
  destination:
    type: semantic_ref
    target_kind: folder
effects:
  class: create_artifact
idempotency_class: unknown
atomicity_class: single_dispatch
authorization:
  - document.read
  - destination.write
result:
  artifact_ref: semantic_ref
~~~

### 8.4 禁止 generic execute

SCP MUST NOT 退化成 execute(script)、execute(command_string)、call(method, arbitrary_json)。

复杂能力必须 typed、closed、可发现、可版本化。

---

## 9. Semantic Control 不能成为隐藏超级 API

### 9.1 权限不增原则

SCP 可以减少 UI 步骤，但不能绕过：

- authentication；
- authorization；
- consent；
- biometric；
- protected confirmation；
- enterprise policy；
- OS permission；
- audit obligation。

### 9.2 UI 不存在不等于权限可以更大

允许没有一一对应视觉按钮的 export(document_17, format=pdf)，前提是 App 本身拥有并愿意公开此能力、用户当前权限允许、effect/confirmation/audit 与 App 正常安全模型一致。

不允许因为“AI 接口方便”而新增 grant_admin、bypass_payment_confirmation、read_protected_secret、disable_security_policy 等隐藏高权限能力。

### 9.3 Protected Interaction

以下 interaction 应有显式硬边界：

~~~text
device_unlock
biometric_auth
password_secure_entry
payment_confirmation
OS_permission_grant
security_policy_change
~~~

默认结果为 protected_interaction / human_required，除非平台提供明确、合法、用户已授权的机器接口。

---

## 10. CapabilityManifest：能力发现而非工具爆炸

每个 adapter / App Provider 应提供版本化 CapabilityManifest，至少包含：

~~~text
domain
provider_id
provider_version
smc_contract_version
supported_object_kinds
supported_verbs
parameter_schemas
control_capability_class
binding_equivalence_classes
permission_requirements
effect_classes
idempotency_classes
atomicity_classes
context_preconditions
receipt_obligations
known_blind_spots
~~~

模型可以显式请求 capabilities(scope=app_7) 或 capabilities(target=document_17)。

返回可以分页/过滤，但必须说明 projection.complete、full_ref 与 count。

禁止程序按“任务相关性”偷偷删能力。

---

## 11. Control Capability Class

### DIRECT_SEMANTIC

应用主动提供 typed semantic action。

### ACCESSIBILITY_CONTROL

通过 UIA / AX / AT-SPI / Android AccessibilityNode 等结构化能力。

### SYSTEM_COMMAND

系统级 Back / Home / open / share 等正式 command。

### SHORTCUT

预声明快捷键 binding。

### STRUCTURED_INPUT

确定性的 keyboard / pointer / gesture。

### VISION_GROUNDED_INPUT

需要视觉接地后再使用低层输入。

### OBSERVE_ONLY

可观察但不能控制。

### UNSUPPORTED

平台或 App 没有允许的控制路径。

### HUMAN_REQUIRED

已知只能由用户完成或政策要求用户在环。

这个字段是事实，不是能力评分。

---

## 12. 统一执行梯

~~~text
Tier 0  Native Semantic Provider
        SCP / App Intent / native typed API

Tier 1  Structured Accessibility
        UIA / AX / AT-SPI / Android AccessibilityNode

Tier 2  System / Application Command
        menu command / command palette / shortcut

Tier 3  Structured Input
        keyboard / pointer / gesture

Tier 4  Vision-Grounded Input
        screenshot / visual grounding / coordinate action
~~~

**Tier 号不是策略优先级。**

Runtime 不得因为“Tier 更低数字”就自动改变 semantic action。

它只可在已冻结的 equivalent binding set 内按机械条件选择可用实现。

---

## 13. Desktop Domain Profile

### 13.1 Windows

优先可利用：

- Microsoft UI Automation client/provider；
- standard / custom control patterns；
- application command；
- shortcut；
- structured input；
- vision fallback。

Windows UIA 的 provider/client 模型允许外部 client 跨进程读取并操作 UI elements；custom controls 可以实现 provider/control pattern，因此适合作为 SMC Desktop Adapter 的重要 grounding/control 层。

### 13.2 macOS

优先可利用：

- cooperative semantic provider / App Intent（支持时）；
- AXUIElement / Accessibility；
- App command / menu command；
- shortcut；
- structured input；
- vision fallback。

macOS 与 iOS 不应因为同属 Apple 平台而使用相同跨 App 控制假设。

### 13.3 Linux

优先可利用：

- AT-SPI；
- D-Bus / App-native command；
- shortcut；
- approved input backend；
- vision fallback。

AT-SPI Action 已能让 Accessible object 暴露 action name、description、key binding 并 invoke action，这与 SMC structured action model 高度同构。

---

## 14. Android Domain Profile

Android 是移动端里更接近“系统级结构化操控”的平台。

AccessibilityService 可以查询可访问节点、对节点执行 action、执行 system global action，并在声明 gesture capability 后 dispatch gesture。

因此 Android binding ladder 可为：

~~~text
DIRECT_SEMANTIC
→ ACCESSIBILITY_CONTROL
→ SYSTEM_COMMAND
→ STRUCTURED_GESTURE
→ VISION_GROUNDED_INPUT
~~~

### 14.1 Android 必须显式的移动状态

WorldSnapshot extension 至少考虑：

~~~text
foreground_app
active_window
input_focus
accessibility_focus
orientation
virtual_keyboard
system_overlay
notification_shade
lock_state
app_suspended
app_terminated
~~~

### 14.2 Gesture 是 fallback，不是主语义

模型应说 activate(item_17)。

只有 node action 不可用、且该 domain profile 明确允许 gesture fallback 时，程序才可在同一等价动作语义下使用 gesture。

是否允许 fallback 必须预声明且 receipt 可见。

---

## 15. iOS / iPadOS Domain Profile

### 15.1 不复制 macOS 的权限假设

UIKit Accessibility 的公开核心用途是 App 把自身 UI 语义暴露给系统辅助功能。

XCUITest / XCUIAutomation 是 UI testing 能力，不应直接被假设成普通生产 Agent 的通用跨 App control plane。

所以 iOS 第一阶段应采用：

~~~text
App Intent / App Entity
→ cooperative Semantic Control Provider
→ system-exposed action / Shortcut
→ OBSERVE_ONLY / HUMAN_REQUIRED / UNSUPPORTED
~~~

### 15.2 iOS 的“能力不足”必须是一等事实

若第三方 App 没有 App Intent、没有合作式 SMC Provider、平台没有合法通用控制面，则不能偷偷切换为“视觉点击一切”并声称同等能力。

应该直接暴露 UNSUPPORTED 或 HUMAN_REQUIRED。

### 15.3 iOS 的 SMC 价值

SMC 在 iOS 上最有潜力的路线不是“做更聪明的坐标自动化”，而是推动应用提供 App Intents、App Entities、Shortcuts actions 与 typed Semantic Control Provider，即合作式 AI-native interface。

---

## 16. 移动端 identity：View Node 不能等于业务对象

RecyclerView、Compose、SwiftUI、UITableView 等可能 recycle view、rebuild node、offscreen detach、lazy materialize、reorder。

所以 Accessibility node identity 不能自动等于 SemanticObject identity。

最佳情况下，合作式 provider 应暴露业务对象身份，例如：

~~~text
email_message_5238
photo_asset_819
note_222
song_318
~~~

UI node 只是它在当前 observation 的一个 grounding。

无法机械证明 continuity 时：

- 旧 object 不静默继承；
- 分配新对象或标 identity unresolved；
- 相似 name / position 不作为 identity proof。

---

## 17. Mobile Lifecycle 与 Boundary Events

移动 App 的 foreground、background、suspended、terminated、scene replacement、orientation、system sheet、permission prompt、virtual keyboard 都会改变动作含义和可执行性。

因此 ActionReceipt 的 boundary events 应能表达：

~~~text
app_backgrounded
app_foregrounded
scene_changed
system_sheet_presented
permission_prompt_presented
keyboard_presented
orientation_changed
app_suspended
app_terminated
~~~

但只有有机械 detector 时才能声明发生/未发生。

检测不全必须暴露 completeness。

---

## 18. 并发用户操作

AI 和用户可能同时操作设备。

SMC 不能假设控制期间用户不动鼠标、不切窗口、不碰手机。

### 18.1 User interaction invalidation

任何动作 dispatch 前都要重新验证其声明的 target identity、expected version、interaction context、permission、lease/ownership（如适用）。

### 18.2 不抢焦点原则

若 binding 需要改变 active window / focus：

- 该变化必须是已声明 mechanical prerequisite；
- receipt 必须显示；
- 如果用户在 preparation 后重新改变 context，动作必须拒绝；
- 不得和用户持续“抢焦点”形成循环。

### 18.3 Human takeover

用户开始直接操作时，可以产生 human_interaction_observed。

是否继续、暂停或换策略由模型 / runtime policy 的明确合同决定，不能由 adapter 猜任务意图。

---

## 19. Receipt：跨所有 binding 的统一事实面

无论动作底层使用 App Intent、UIA、AX、AT-SPI、shortcut、gesture、coordinate，都必须结算成统一 ActionReceipt。

至少包含：

~~~text
action_id
semantic_verb
target_id
binding_id
binding_class
attempt
precondition_result
dispatch_status
observed_effects
boundary_events
before_version
after_version
context_before
context_after
completeness
~~~

binding_id 的存在非常重要：

模型不需要在动作前选择物理实现，但动作后必须能知道究竟发生了什么。

---

## 20. Transport Ambiguity 与 non-idempotent 动作

跨平台必须继承 Browser 已验证的原则：

> stable identity 不等于动作幂等。

send、submit、purchase、share、delete 等动作，即使 target 完全稳定，transport acknowledgement 丢失后也不能自动 replay。

只有 read_only、mechanically idempotent，或有正式 idempotency key / exactly-once mechanism，才允许协议级 retry。

retry 事实必须进入 receipt。

---

## 21. Tool Surface 最终形态

长期目标不是 browser tools x30、windows tools x30、mac tools x30、android tools x30、ios tools x20。

而是稳定的语义操作面：

~~~text
observe
hydrate
diff
act
wait
assert
~~~

Domain differences 进入 SemanticObject.kind、CapabilityManifest、typed verb schema、Domain Profile 和 ExecutionBinding。

这使模型学习的是一种世界操作语言，而不是五套操作系统 API。

---

## 22. 分层架构 v0.2

~~~text
┌────────────────────────────────────────────┐
│ L5 Agent / Model                           │
│ goal / reasoning / planning / completion   │
├────────────────────────────────────────────┤
│ L4 SMC Semantic Control Plane              │
│ Object / Action / Predicate / Diff         │
│ ActionRef / Capability projection          │
├────────────────────────────────────────────┤
│ L3 Semantic Provider & Binding             │
│ SCP / App Intent / UIA / AX / AT-SPI       │
│ Accessibility / Command / Shortcut         │
├────────────────────────────────────────────┤
│ L2 Context & Grounding                     │
│ identity / scope / version / focus         │
│ lifecycle / completeness / provenance      │
├────────────────────────────────────────────┤
│ L1 Physical Execution                      │
│ API / IPC / DOM / key / pointer / touch    │
│ gesture / vision-grounded input            │
├────────────────────────────────────────────┤
│ L0 Runtime Authority                       │
│ permission / consent / locks / leases      │
│ idempotency / durable receipt / audit      │
└────────────────────────────────────────────┘
~~~

权责：

~~~text
L5 决定语义目标与策略
L4 表达语义
L3 只在等价集合内机械绑定
L2 维护事实、identity 与前置条件
L1 执行
L0 掌握硬权限与效果权威
~~~

---

## 23. 跨平台 Capability Matrix（设计目标，不是当前实现声明）

| 平台 | 合作式语义 Provider | Accessibility 控制 | System action | Shortcut | Input/gesture | Vision fallback | 关键限制 |
|---|---|---|---|---|---|---|---|
| Windows | 可设计 | 强：UIA | 有 | 强 | 有 | 可选 | integrity/UIPI/secure desktop 等边界 |
| macOS | 可设计 | 强：AX | 有 | 强 | 有 | 可选 | Accessibility permission / secure UI |
| Linux | 可设计 | AT-SPI | 视桌面 | 有 | 后端相关 | 可选 | compositor/Wayland/desktop 差异 |
| Android | 可设计 | 强：AccessibilityService | 强：global actions | 外接键盘非核心 | gesture | 可选 | 用户授权、节点盲区、系统/安全 UI |
| iOS/iPadOS | 应优先 App Intent / cooperative provider | 不能假设通用跨 App AX client | 系统开放能力有限 | Shortcuts/App Intent | 不作为通用产品假设 | 受平台权限约束 | sandbox / cross-app control model |

此表只描述架构适配方向。

实际实现必须用每个平台当前公开 API 和政策重新 qualification。

---

## 24. Developer SDK：让应用原生适合 AI

长期可以提供 SMC SDK。

开发者只需声明：

~~~text
SemanticObject type
stable domain identity
observable state
available semantic actions
typed parameters
permissions
effects
result schema
~~~

而不用专门设计一套“AI 点按钮路径”。

SDK 设计目标：

- 少于 UI automation 的接入成本；
- 不要求开发者写自然语言 prompt；
- contract 可生成 conformance test；
- 能映射现有 Accessibility / App Intent；
- 不制造第二套权限体系；
- 同一 semantic action 可以同时服务 AI、Accessibility、Automation 和 Shortcuts。

---

## 25. 反模式

1. **把 App 每个方法都暴露成 Tool**：导致 Tool Explosion 和安全边界崩溃。
2. **一个万能 execute(any_json)**：等同把 API surface 原样甩给模型。
3. **自动从一个不等价 binding 切到另一个**：例如 export 失败后偷偷 save-as。
4. **ActionRef 过期后自动找相似对象**：破坏 identity authority。
5. **把 iOS 当成 Android/macOS 一样的全局 Accessibility client**：制造错误平台假设。
6. **因为 Vision 能点击就宣称 capability supported**：平台/安全政策不允许的控制仍应 unsupported/human_required。
7. **Semantic Control 绕过 App 原有权限与确认**：AI-native 不等于 privileged backdoor。
8. **用“Tier 更高”作为自动策略优先级**：Tier 是 capability 分类，不是任务策略。

---

## 26. 资格验证框架

未来不能只测 task success。

### 26.1 共同指标

至少记录：

~~~text
task_success
pass_at_1
semantic_action_count
physical_dispatch_count
tool_calls
tokens
wall_time
recovery_turns
stale_rejections
context_rejections
unsupported_count
human_required_count
unexpected_side_effects
duplicate_effects
vision_fallback_rate
exact_string_transcription_errors
~~~

### 26.2 三臂实验

可比较场景优先：

~~~text
A = vision / coordinate human-UI emulation
B = low-level command / traditional automation
C = SMC semantic control
~~~

固定 model、task、permissions、initial state、success oracle。

### 26.3 错误分类

必须区分：

~~~text
MODEL_DECISION_ERROR
SEMANTIC_CONTRACT_ERROR
BINDING_ERROR
GROUNDING_ERROR
CONTEXT_RACE
PERMISSION_DENIED
PLATFORM_UNSUPPORTED
TASK_ORACLE_ERROR
TRANSPORT_AMBIGUITY
~~~

SMC 的安全拒绝不能机械计为“模型失败”而丢失原因。

---

## 27. 实施路线

### Phase A — Browser 当前链先收口

保持因果隔离：

~~~text
P4-FCR v0.1 immutable negative result
→ ActionRef / exact-ref architecture experiment
→ fresh P4-FCR v0.2
→ P4-LIVE
~~~

**本 v0.2 Control Plane 文档不得直接成为 P4-FCR treatment patch。**

P4-FCR 是否采用 ActionRef，要在其独立协议里重新冻结并验证。

### Phase B — Execution Binding Contract

docs + deterministic conformance only：

- CapabilityManifest；
- ExecutionBinding；
- equivalence class；
- Interaction Context；
- ActionRef；
- receipt parity。

### Phase C — Desktop Read-Only

分别验证 Windows UIA、macOS AX、Linux AT-SPI，只做 application、window、focus、menu、controls、selection、state。

### Phase D — Desktop 小动作集

优先：

~~~text
activate
focus
open
close
copy
paste
save
undo
redo
find
switch_window
switch_tab
~~~

验证 native / accessibility / shortcut binding equivalence。

### Phase E — Android

验证 AccessibilityNode、node action、system global action、gesture fallback、focus/window、lifecycle/boundary events。

### Phase F — iOS Cooperative SMC

优先 App Intents、App Entities、Shortcuts、cooperative SMC Provider SDK。

不把 XCUIAutomation 当正式产品控制面的默认假设。

### Phase G — Semantic Control SDK

让第三方 App 原生暴露 typed semantic actions。

### Phase H — Cross-device workflow

最终验证：

~~~text
Browser → OS → App → Mobile / cloud handoff
~~~

模型全程保持 SMC 语义，不直接管理坐标、快捷键和物理路径。

---

## 28. 阶段 Gate

### G0：Contract stability

- 六对象不因平台扩展发生含义漂移；
- Domain extension 不覆盖 core semantics。

### G1：No tool explosion

- 安装 App 数量增长不导致 provider-visible tool count 线性增长；
- capability 作为数据发现。

### G2：Binding authority

- 自动 binding 只发生在 frozen equivalence class；
- semantic target / verb / args 零自动替换。

### G3：Context safety

- focus/window/context stale 在 dispatch 前机械拒绝；
- 无持续抢焦点。

### G4：Permission parity

- Semantic Provider 不扩大 App/用户已有权限；
- protected interaction 保持 protected。

### G5：Identity

- virtualized/recycled UI 不靠 name/position 静默续 ID；
- domain identity 可用时优先绑定 domain identity。

### G6：Receipt parity

- 不同 binding 的相同 semantic action 均产出统一可审计 receipt；
- observed side effects 不因 transport 不同被隐藏。

### G7：Platform honesty

- unsupported / observe-only / human-required 被真实表达；
- 不用 vision 假装绕过平台权限。

---

## 29. 本轮拷问后已经关闭的问题

### Q1：SMC 是否依赖快捷键？

否。快捷键只是 binding。

### Q2：没有快捷键的手机是否破坏架构？

否。手机可使用 semantic provider、accessibility action、system action、gesture；iOS 能力不足时诚实降为 unsupported/human_required。

### Q3：需要专门适合 AI 的控件吗？

需要，但应提升为 **Semantic Control Provider / typed capability**，而不是只做新的视觉 Widget。

### Q4：Semantic Control 会不会变成隐藏 API？

只有严格执行 permission parity、typed closed schema、receipt/audit、禁止 generic execute 才能避免。

### Q5：App 暴露一百个 action 会不会让模型面对一百个 tool？

不应。CapabilityManifest 是数据；模型工具面保持稳定。

### Q6：程序是否可以自动选择快捷键/API/AX？

只允许在预先冻结且机械证明语义等价的 binding set 内。

### Q7：ActionRef 是否允许恢复旧 target？

不允许。ActionRef 只减少转录负担，不改变 stale/expiry/identity fail-closed。

---

## 30. 仍未关闭、必须由实验回答的问题

1. 一个稳定 act + capability schema 对不同模型是否比多个窄 typed tools 更 First-Call-Ready？
2. CapabilityManifest 多大时需要怎样的分页/投影，才能既不爆 token 又不做任务相关裁剪？
3. ActionRef 的最佳生命周期是 observation-bound、context-bound 还是短 TTL + version-bound？
4. Desktop context preparation（activate/focus）多大程度会干扰用户并发操作？
5. Linux Wayland / compositor 差异下哪些 structured input 能被稳定资格化？
6. Android gesture fallback 在真实 App 中有多少是 AccessibilityNode action 缺失，而非 adapter 缺陷？
7. iOS 第三方 App 对 App Intents / Shortcuts 的现实覆盖率是否足够支持通用 Agent workflow？
8. Semantic Provider SDK 的最小 schema 能否同时映射 UIA/AX/AT-SPI/App Intent，而不成为最低公分母？
9. 跨设备对象 identity（例如同一云端 document 在电脑和手机）是否属于 SMC core，还是更高层 entity layer？
10. 哪些 protected interaction 必须永久 human-required，哪些可由正式平台授权机制机器化？

这些问题不得靠纸面继续扩合同，应由分阶段 prototype / benchmark 回答。

---

## 31. 外部平台事实锚（2026-09-19 重新核验）

本设计只引用各平台公开官方文档来约束平台能力假设。

### Windows

- Microsoft UI Automation fundamentals:
  https://learn.microsoft.com/en-us/windows/win32/winauto/entry-uiautocore-overview
- UI Automation Providers:
  https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-providersoverview
- Custom properties/events/control patterns:
  https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-designingcustompropseventpatterns

### Apple

- App Intents / AppIntent:
  https://developer.apple.com/documentation/appintents/appintent
- macOS AXUIElement:
  https://developer.apple.com/documentation/applicationservices/axuielement
- UIKit Accessibility:
  https://developer.apple.com/documentation/uikit/accessibility-for-uikit
- XCUIApplication（测试/自动化参考，不作为本设计的生产跨 App 权限假设）:
  https://developer.apple.com/documentation/xcuiautomation/xcuiapplication

### Android

- AccessibilityService:
  https://developer.android.com/reference/android/accessibilityservice/AccessibilityService
- AccessibilityNodeInfo.AccessibilityAction:
  https://developer.android.com/reference/android/view/accessibility/AccessibilityNodeInfo.AccessibilityAction

### Linux

- AT-SPI Action:
  https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/iface.Action.html

平台 API、商店政策和系统权限会变化；进入任何 production adapter 前必须按当时版本重新 qualification。

---

## 32. 最终裁决

SMC 的最终目标不是：

> “让 AI 更像人一样使用电脑。”

而是：

> **给 AI 一套比人类 UI 更贴近语言模型认知结构、又比裸 API/命令更安全和可泛化的计算机接口。**

传统：

~~~text
Application
→ UI
→ Human
~~~

Computer Use：

~~~text
Application
→ UI
→ Vision
→ AI
~~~

SMC：

~~~text
                 ┌─ UI / Accessibility ─┐
                 ├─ App Intent / Command │
Application ─────┼─ Semantic Provider    ├─ SMC ─ AI
                 ├─ Native API           │
                 └─ Input / Vision ──────┘
~~~

UI 不再是 AI 与应用之间唯一的桥。

核心边界始终不变：

> **模型拥有“做什么、对谁做”的语义决策权；程序拥有“怎样把已决定的动作精确、安全、可审计地执行”的机械能力。**

只要这条边界守住，SMC 就可以同时吸收 UI、Accessibility、快捷键、命令、API、触控和视觉的优点，而不继承它们作为模型主接口时的主要弱点。
