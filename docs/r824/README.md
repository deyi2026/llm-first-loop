# R8.24 设计包索引 — 模型发挥阻碍审计拆分

> 日期：2026-08-31 | 状态：**索引文档 —— ANALYSIS ONLY，五包均为纯设计文档，未修改任何生产代码/配置**
> 上位审计：`docs/ANALYSIS-20260831-model-agency-obstruction-audit.md`（1169 行，下称"总审计"）
> 前序审查：`docs/ANALYSIS-20260831-rules-procedure-review.md`（126 行，下称"r-p-r"）
> 冻结来源：`.codeartsdoer/specs/tool_eligibility_unblock/tasks.md`（2026-08-31 执行冻结标注，下称"tasks.md"）
> 核心原则：**用户和模型拥有语义决策权；程序负责确定性机械控制。**

---

## 1. 五包一览表

| 包 | 文件 | 范围一句话 | 主要动作分类（总审计 §0.3） | 状态 |
|---|---|---|---|---|
| A 模型契约瘦身 | `R8.24-A-model-contract-slimming.md` | 规则从"运维手册"降回"最小语义契约"：删强制读、lite 降级 playbook、删元任务与平台手册条款 | DELETE-GLOBAL / MOVE-SKILL | 待审批 |
| B 运行时控制面闭环 | `R8.24-B-runtime-control-plane-closure.md` | E12/E15/E16/E17/E18 零 prompt、current_turn 不再 grant、E19 通知不进 sess.messages、熔断文案取消（计数保留） | MOVE-CONTROL / REDESIGN | 待审批 |
| C 工具结果事实化 | `R8.24-C-tool-result-factualization.md` | 回执只留事实：guidance/胶囊/提炼指令退出、capsule metadata-only、read_file 短路、可见性走按需 | FACTUALIZE / MOVE-METADATA | 待审批 |
| D 来源/缓存/降级加固 | `R8.24-D-provenance-cache-fallback-hardening.md` | trace-leak quarantine+fail-closed、性能 BLOCK 退出（安全 BLOCK 保留）、fallback 能力下限 | REDESIGN / KEEP-HARD | 待审批 |
| E 潜在语义通道收口 | `R8.24-E-latent-semantic-channels.md` | E07/E08/E35 退出、Cognitive 冻结、task_active 授权化、CORE9 与词法路由 A/B | RETRIEVAL-ONLY / EXPERIMENT | 待审批 |

## 2. 依赖图

```text
                    ┌──────────── A（规则文本层，独立）────────────┐
                    │        （与 B 建议同批发布，无代码耦合）      │
                    ▼                                              │
   B（grant 机制 + 控制面闭环）◄──────────────┐                    │
   ├──► C（回执事实化；B 的 failure_class      │ A-D6/A-D13 与     │
   │     metadata 接口对齐）                   │ D-D6 表里衔接 ────┤
   ├──► D（trace 批次强依赖 B 验收：E19/E12   │                   │
   │     收口后 quarantine 才不复活；cache/    ▼                   │
   │     fallback 面可并行）              D（floor/budget）        │
   │                                          │                   │
   └──► E（producer 退役在 B 的 grant 闭合    ▼                   │
         之后：prompt_eligibility 同文件              E ◄── C（capsule 退出定局
         B 先 E 后；E18"等用户继续"是                    影响 CORE/词法路由 A/B
         E 授权 resolver 触发源）                        的评估前提）
```

关键依赖边（详见各包 §5）：

1. **D-trace ← B**（强）：D 包批 D3/D4 排 B 包验收之后；
2. **E ← B**（强）：grant 机制先闭、通道后删；E-D5 resolver 触发源是 B-D6；
3. **E ← C**（强）：CORE9/词法路由 A/B 以 capsule chars=0 为前提；
4. **C ← D2 放行项**：失败不 capture 先行落地是 C 包批 C3 联合验收前置；
5. **A ↔ B/C**：发布节奏建议同批（A 删规则、B/C 上机制），无代码依赖；
6. **A-D6 ↔ D-D6**：模型切换手册下沉（A）与 capability floor（D）互为表里。

## 3. 审批顺序建议

```text
第 1 批：A ∥ B（A 独立可先行；B 是 C/D/E 的共同前置）
第 2 批：C（依赖 B + D2 放行项）；D 的 cache/fallback 面可并行审批
         （D 的 trace 批次批准即挂 B 验收 gating）
第 3 批：D-trace 批次（B 验收后解锁实施）
第 4 批：E（依赖 B grant 闭合 + C capsule 定局；含 CORE 三态终判提交用户）
```

全局收尾条件（总审计 §12）：五包 fixed-point 达成前 behavior canary 继续 BLOCKED、R9 不启动；E 包批 E5⑪ 核验解除条件。

---

## 4. 条目映射全表

### 4.1 总审计 P0 条目（§3，7 条）

| 条目 | 主题 | 归包 | 备注 |
|---|---|---|---|
| P0-1 | current_turn 仍被当成 prompt 权限 | **B**（grant 机制）+ **E**（task_active 部分，P1-7 联动） | B 断 `program_recovery` 自动权限；memory/tip producer 退役归 E |
| P0-2 | 工具结果夹带程序建议 | **C** | MOVE-CONTROL + FACTUALIZE |
| P0-3 | evidence capsule 上下文税 | **C** | MOVE-METADATA；complete=true chars=0 |
| P0-4 | cache 性能 BLOCK 阻止模型 | **D** | 性能 BLOCK 退出；安全 BLOCK 保留 |
| P0-5 | trace-leak observe + downgrade reinject | **D** | quarantine + fail-closed 两修订 |
| P0-6 | E12/E15/E16/E17/E18 | **B** | MOVE-CONTROL |
| P0-7 | E07 自动 memory | **E** | DELETE AUTO MEMORY |

### 4.2 总审计 P1 规则层条目（§4，10 条）

| 条目 | 主题 | 归包 | 备注 |
|---|---|---|---|
| P1-1 | ai_rules.lite 强制读 | **A** | DELETE MANDATORY READ |
| P1-2 | RULE-AI-00 重写 | **A** | 语义/机械二分 |
| P1-3 | 方法层①~⑥ | **A** | MOVE-SKILL |
| P1-4 | Rule 5 `[[memory]]` | **A**（规则面）+ **E**（通道面 E07） | 表里两层 |
| P1-5 | Rule 6/10 自评/演进/每轮自查 | **A** | MOVE-MAINTENANCE |
| P1-6 | Rule 8 动作链/提工具名 | **A** | 保留 OFFLINE METRIC |
| P1-7 | task_active | **E** | USER_AUTHORIZED_STATE |
| P1-8 | Rule 9 模型切换手册 | **A**（下沉）+ **D**（floor） | 表里衔接 |
| P1-9 | Rule 11 截断 SOP | **A**（规则文本）+ **C**（回执事实化） | blanket 禁令删除 |
| P1-10 | Rule 13/14/15/17/18/19/20/21 | **A**（全部）+ B/C/E 联动 | Rule 21 过渡期保留 |

### 4.3 总审计 P1 程序机制条目（§5，4 条）

| 条目 | 主题 | 归包 | 备注 |
|---|---|---|---|
| P1-11 | Cognitive enforce | **E** | FREEZE/REDESIGN |
| P1-12 | Compression 元工作 | **A**（规则面）+ **B**（机制面 E17） | KEEP MECHANICS |
| P1-13 | history budget 硬上限 | **D** | budget=optimizer（收编 r-p-r P3-1） |
| P1-14 | fallback capability floor | **D** | 收编 r-p-r P1-4 |

### 4.4 总审计 P2 条目（§6，4 条）

| 条目 | 主题 | 归包 | 备注 |
|---|---|---|---|
| P2-1 | CORE9 | **E** | A/B FIRST（并入 tasks.md E1 三态评估） |
| P2-2 | PROGRAM_FINAL 边界 prose | **B** | KEEP SHAPE, MINIMIZE CONTENT |
| P2-3 | TOOL_ROUND_ZERO_HISTORY | **E** | EXPERIMENT ONLY |
| P2-4 | SYSTEM_PROMPT_EXTRA | **A** | REMOVE/GOVERN |

### 4.5 总审计 §7 规则逐项表 / §11 撤销修订项 / §12 框架

| 来源 | 条目 | 归包 | 备注 |
|---|---|---|---|
| §7 | 方法层①~⑥ + 规则 1~21 全表 | **A** 为主清单 | 规则 3/4/19 机械面联动 B；规则 5 联动 E；规则 9 联动 D；规则 11 联动 C；规则 21 删除条件挂 B/C 验收 |
| §11.1 | 熔断三要素建议 → 修订 | **B** | 原因/错误码保留，建议文案取消 |
| §11.2 | 程序指标直接注入 → **撤销** | — | 即 r-p-r P1-7 撤销（见 4.7 表标注） |
| §11.3 | 停滞提醒升级 → **撤销** | **B** | 更强提示不实施 |
| §11.4 | Rule 20/21 长期保留 → 修订 | **A**（Rule 20）+ **E**（Goal 机制）+ **B/C**（Rule 21 删除条件） | |
| §12-A~E | 五包框架原文 | A/B/C/D/E 一一对应 | 本索引即其落地 |

### 4.6 r-p-r 条目（12 条）

| 条目 | 主题 | 归包 | 备注 |
|---|---|---|---|
| P1-1 | evidence:// 误读 + 误导提示 | **C** | D5 短路并入；(a)/(b) 两案不采纳（沿 tasks.md 判定） |
| P1-2 | read_file 复用吞正文 | **C** | 内联或标 failure（C-D9） |
| P1-3 | 停滞提醒软约束 | **B** | 计数/熔断保留；提醒与"第 2 次即拒"激进案均不采纳 |
| P1-4 | failover 无能力下限 | **D** | D-D6 capability floor |
| P1-5 | 提示推荐不存在工具 | **C** | 存在性校验 + T8 式扫描（C-D10） |
| P1-6 | 截断元状态注入 | **B** | 残余面完整性原则（B-D9） |
| P1-7 | 程序自答型任务直供指标 | — | **已撤销**（总审计 §11.2：程序指标属 observability；用户问健康状态时模型可主动调 architecture_status，普通任务不自动注入指标表） |
| P2-1 | Rule 18 Web 面板手册 | **A** | 并入平台手册下沉 |
| P2-2 | Rule 24 截断 SOP 重复 | **A** + **C** | 规则删（A）+ 回执模板事实化（C） |
| P2-3 | Rule 33 三主题合一 | **A** | 拆分判定被"删除/下沉"覆盖 |
| P2-4 | 历史实证 ID 占上下文 | **A** | 脚注化建议被"整条下沉"覆盖 |
| P2-5 | 必读触发条件收敛 | **A** | **被更彻底方案覆盖**：直接删除必读义务 |
| P2-6 | 应保留规则清单 | **A** | 规则 21 保留判定被 §11.4 修订为"过渡期保留"；方法层"降为建议"被 P1-3 升级为 MOVE-SKILL |
| P3-1 | 30K 预算过小 | **D** | optimizer 化（P1-13），非一刀切提额 |
| P3-2 | evidence 块噪音 | **C** | =总审计 P0-3 |

### 4.7 tool_eligibility_unblock（tasks.md，冻结后去向）

| 组 | 内容 | 去向 | 备注 |
|---|---|---|---|
| 组 1（P0-A） | 胶囊驱动解锁 + 路由输入面扩展 | **C**（替代路线 C-D8）+ **E**（A/B 评估 E-D7） | 胶囊锚扫描方案**弃案**（capsule 退出后失效） |
| 组 2（P0-B） | 失败不 capture（D2）+ read_file 短路（D5） | D2：**例外放行独立实施**（走 EVO 审批，不属五包）；D5：**C**（C-D7 重审文案后纳入） | C 包批 C3 与 D2 联合验收 |
| 组 3（P1） | 恢复类计数熔断 + 提醒/替代文案 | **B**（B-D3） | 计数/阈值/BLOCKED 保留；提醒与 C4 两文案函数**取消**（§11.1/§11.3） |
| 组 4（P2） | 关键词「健康」/E1 CORE 评估/E2 词法复审/E3 胶囊复审/E4 阈值审视 | **E**（4.1、E1、E2 主体）；E3 由 **C** 消解；E4 数据回填 **B** | 三态终判归用户（门 E 纪律） |
| 组 5 | T5-T8 测试资产 + A/B 对照 | 分解归包：T2 归 D2 放行项（联合 C）；T3/T6-T8 断言口径归 **C**；T6"熔断收敛"断言归 **B**；T5 shadow 口径归各包 §6 | 实施期按新设计重写脱敏场景 |

### 4.8 覆盖率自检

- 总审计 §3 P0：7/7 归包；§4 P1：10/10；§5 P1：4/4；§6 P2：4/4；§7 规则表：整表归 A 执行（联动标注齐）；§11：4/4（1 项撤销 + 3 项修订落实）；§14 优先级总表 23 行：全部含于上述条目，无孤儿项；
- r-p-r：12 条全部处置（1 撤销 / 2 被覆盖 / 9 归包）；
- tasks.md：组 1-5 全部处置（D2 例外放行 + 其余并入 B/C/E 或分解为测试资产）；
- 未归包遗留：无。凡"仅作记录不采纳"的备选案（r-p-r P1-1(a)/(b)、P1-3 激进案）均已在对应包"被弃方案"表中留档。

---

## 5. 阅读指引

- 只关心"模型该知道什么"：读 A；
- 只关心"运行时故障谁处理"：读 B；
- 只关心"工具回执长什么样"：读 C；
- 只关心"安全边界与模型选择"：读 D；
- 只关心"记忆/Goal/工具可见性"：读 E；
- 查某条旧建议（r-p-r 或 tasks.md 编号）落在哪：查 §4 映射表。