# R8.24 全量落地终验回执 — 结构硬门实测 + 金丝雀/R9 解锁条件评估

> 日期：2026-09-01 ｜ 性质：**验收测量（ANALYSIS ONLY + 补常驻断言测试）**
> 验收依据：`docs/ANALYSIS-20260831-model-agency-obstruction-audit.md` §13（验收标准）、§12 末尾（金丝雀/R9 冻结条款：*完成上述 fixed-point 前 behavior canary 继续 BLOCKED、R9 不启动*）
> 设计包索引：`docs/r824/README.md`（五包一览）｜CORE 相关断言以 `docs/r824/CORE9-final-ruling.md`（已生效终判）为准
> 测量口径：**重启后生产默认态**（无任何 `LFL_*`/`CACHE_GUARD_*` env 的干净进程实测；探针经 `env -u` 七开关逐项清除）
> 本轮改动：新增 `tests/unit/test_r824_final_gates.py`（13 用例）+ `scripts/git_security_scan.sh` `_ALLOWLIST` 登记一行（sk- 虚构样例先例，1ef6e62）；**零生产行为/配置/开关默认值改动，现有测试零改动**

---

## 0. 一句话结论

六门中 **H1/H2/H5 在重启后生产默认态达标（PASS）**；**H3/H4/H6 机制 READY 但三开关默认值仍在 shadow 观测态（on），默认生产态 FAIL**——fixed-point 未完成，**behavior canary 维持 BLOCKED、R9 维持不启动**。解锁不需要任何代码开发，只待三项 shadow→enforce 默认值切换（每项均已有"切换锚点"常驻断言预埋，见 §6）。

---

## 1. 六门实测结果表（终验主回执）

| 硬门 | 实测值（重启生产默认态） | 判定 | 证据 |
|---|---|---|---|
| **H1** run 开始后 program-authored natural-language prompt chars | **= 0**（正常轮 + 五故障场景 wire 全扫描零命中；用户消息原文逐字节保留） | **PASS** | 探针 §3.1；`test_runtime_zero_prompt.py` 9 用例（默认态）；`test_runtime_zero_prompt_static.py` 5 静态断言；新增 `test_r824_final_gates.py::TestH1NormalTurnWireZeroProgramProse` 2 用例（补正常任务轮缺口） |
| **H2** automatic memory / experience / digest / recovery / runtime status chars | **= 0**（`LFL_LATENT_CHANNEL` 默认 off=enforce；producer 注册表仅存 {program_recovery, task_active, memory_authorized} 三个授权语义槽；`LFL_COG_ENFORCE_FREEZE` 默认 on） | **PASS** | 探针 §3.2（slots 实测）；`test_latent_channel_exit.py` 10 用例（E-G1~E-G6，含武装通道零投影、注册表 resurrection=0、冻结断言）；新增组一 2 用例 |
| **H3** tool result advisory-prose chars | **> 0（FAIL）**：默认态 FAILURE 回执实测含"可选项（判断归你）: 检查参数/路径/网络后重试…（RULE-AI-02/07）…"（178 chars 回执内 advisory 在场）；typed recovery `[恢复策略]` render 同样在场。`LFL_TOOL_GUIDANCE` 默认 **on**（四源照旧投影） | **FAIL**（机制 READY：off 态 chars=0 有 8 用例承载 + 终验复核 1 用例） | 探针 §3.3；`src/llm_loop/tools/registry.py:40`（默认 on）、`:1259-1263`（文案本体）、`:1290-1296`（渲染路径）；新增组一 `test_tool_guidance_default_on` + 组三双面用例 |
| **H4** evidence full-result capsule chars | **> 0（FAIL）**：默认态 complete=true 回执实测 426 chars，含 `[evidence]…[/evidence]` 完整 capsule（ref/source/coverage/recover）。`LFL_EVIDENCE_CAPSULE` 默认 **on**（capsule 照旧拼接） | **FAIL**（机制 READY：off 态 capsule chars=0 + metadata 六字段完整有承载 + 终验复核） | 探针 §3.4（同构生产装置实测）；`src/llm_loop/tools/evidence_enforce.py:39`（默认 on）、`:139-160`（off 分支机制）；新增组一 `test_evidence_capsule_default_on` + 组三双面用例 |
| **H5** suspect provenance content provider chars | **= 0**（`LFL_LEAK_QUARANTINE` 默认 **off**=quarantine+provider chars=0 生效；`LFL_LEAK_GUARD_MODE` 默认 **enforce** fail-closed；allowlist 无 leak_downgrade） | **PASS** | 探针 §3.5；`src/llm_loop/core/trace_leak/leak_events.py:60-62`、`user_ingress_guard.py:40`；`test_trace_leak_quarantine.py` 22 用例（含 delenv 默认态断言、无 token 写入 drop、engine 级端到端、allowlist 静态断言） |
| **H6** cache hit/performance alone BLOCK count | **默认态 ≠ 0（FAIL）**：ratio>95% 场景实测 `verdict=BLOCK`（rule=submit_ratio，基线 25 次口径行为保留）。`CACHE_GUARD_PERF_BLOCK` 默认 **on**。后半句不受影响：privacy BLOCK 双态保留实测 `BLOCK/privacy_leak` ✓ | **FAIL**（机制 READY：enforce 态同场景 `WARN/submit_ratio_perf`+`would_block=True` 有承载 + 终验复核） | 探针 §3.6；`src/llm_loop/cache_guard/guard.py:56`（默认 on）；源码自证 `test_cache_block_reclassification.py:186-196`（"enforce 切换留待 D'-1.3 观测达标——回执声明"）；新增组三双面用例（含 privacy 双态保留复核） |

### 1.1 §13.1 其余两条（八条结构硬门完整性对照）

| 条目 | 实测 | 判定 | 证据 |
|---|---|---|---|
| Goal/Cognitive state 无 user authorization 时 prompt chars = 0 | 未授权轮 `task.active: unauthorized_zero_projection` + `goal_read=deferred` 在场、无 `authorized_inject` | **PASS** | `test_latent_channel_exit.py:130-143`（E-G2/E-G5 决策日志断言） |
| legacy TIP/compact anchor resurrection = 0 | memory/tip 槽已退出注册表；7 类幽灵 producer 名（含 anchor/hotcard/gate_note）不获语义层 | **PASS** | `test_latent_channel_exit.py:30-48`（E-G6）+ 探针 slots 实测 |

---

## 2. 环境开关默认值实测（重启后生产默认态，七开关全量）

测量方法：`env -u` 清除七开关后新进程 import 实测（模块级常量与每次现读函数均覆盖）。

| # | 开关 | 读取点 | 实测默认值 | enforce 语义值 | 状态 | 归属硬门 |
|---|---|---|---|---|---|---|
| 1 | `LFL_TOOL_GUIDANCE` | registry.py:40 | **on**（照旧投影） | off | ❌ 未切 | H3 |
| 2 | `LFL_EVIDENCE_CAPSULE` | evidence_enforce.py:39 | **on**（照旧拼接） | off | ❌ 未切 | H4 |
| 3 | `CACHE_GUARD_PERF_BLOCK` | cache_guard/guard.py:56 | **on**（性能 BLOCK 保留） | enforce | ❌ 未切 | H6 |
| 4 | `LFL_LEAK_QUARANTINE` | leak_events.py:60-61 | **off** | off=quarantine 生效 | ✅ 已 enforce | H5 |
| 5 | `LFL_LEAK_GUARD_MODE` | user_ingress_guard.py:40 | **enforce** | enforce | ✅ 已 enforce（fail-closed） | H5 |
| 6 | `LFL_LATENT_CHANNEL` | input_authorization.py:29-30 | **off** | off=通道关闭 | ✅ 已 enforce | H2 |
| 7 | `LFL_COG_ENFORCE_FREEZE` | build.py:243-247 | **1（True）** | 1=冻结 promote | ✅ 已 enforce | H2 |

判定解读：4/7 开关已收尾 enforce（D-trace 与 E 包按"落地即 enforce"收尾）；3/7 停留在灰度设计起点（C 包批 C1①"默认 on；shadow 观测"与 D'-1.1 同口径）。**这不是遗漏，是设计包明文的 shadow→enforce 两步走的中间态**——但按 §13.1 结构硬门的验收语义（生产默认态 chars=0），该中间态不满足 fixed-point。

---

## 3. 典型 run 回放场景实测明细（探针数据）

探针脚本：`env -u` 七开关清除的干净子进程（复现"重启后生产默认态"）；一次性探针不入院，关键断言已固化进 `tests/unit/test_r824_final_gates.py` 常驻。

### 3.1 H1 场景组（正常任务轮 + 工具失败轮 + 压缩触发）

- **正常直接回答轮**（新增）：wire 中 user content == `"真实任务"`（逐字节，程序未改写）；`_PROGRAM_MARKERS` 九类程序通知句式与 `ADVISORY_PATTERNS` 六类建议句式全部零命中。
- **正常工具成功轮**（新增）：工具真实输出（事实层）保留在 wire；程序注入/建议句式零命中。
- **工具失败轮 / 压缩触发（overflow→compact→确定性终止或收缩重发）/ 轮数耗尽 / 停滞 / 空搜索 / 1210 盲重试**：既有承载 `test_runtime_zero_prompt.py` 9 用例默认态全绿（E12/E15/E16/E17/E18 全场景 wire 零程序自然语言；B-G4 轮数硬停恰 N 次调用无第 N+1 轮）。

### 3.2 H2 场景组（通道武装 + 注册表）

- producer 注册表实测：`{memory_authorized, program_recovery, task_active}`——automatic memory（E07）/TIP（E08）/compact anchor（E35）全部不在；
- 武装 memory 参数/tip 尾/anchor 后模型可见 slot chars=0（`test_eg1_eg3_armed_channels_zero_model_chars`）；检索面（retrieval plane）存储不受影响；
- Cognitive：默认冻结下 allowlist 命中也不 promote（effective mode 恒 ∈ {off, shadow}）。

### 3.3 H3 场景组（工具失败轮，默认态）

```text
tool_result_to_message(FAILURE 回执) → content（178 chars）：
  [状态: failure] [文件不存在] …
  可选项（判断归你）: 检查参数/路径/网络后重试；或改用其他更合适的工具（RULE-AI-02/07）。
  不确定调用方式可先 search_records(kind=memory)/search_docs 查证…
```
- advisory 在场 =True、RULE-AI 引用在场 =True；
- typed recovery：`[恢复策略]`/`next=` 在场 =True；`failure_class=url_not_found` metadata 保留 =True（B 包熔断输入面不受影响——符合 C-D1 白名单设计）。

### 3.4 H4 场景组（成功 capture 轮，默认态，生产同构装置）

```text
read_file(small.txt, full=True) → SUCCESS, projection_complete=True, content=426 chars：
  …[evidence]
  ref=evidence://v1/a854ad38…
  source=read_file:…
```
- capsule 在默认 content 在场 =True（对照 C 包 off 态断言：`[evidence]` 不在、metadata 六字段完整、`EvidenceHydration` ref 可取回）。

### 3.5 H5 场景组（泄漏内容注入尝试，默认态）

- 无凭据 user 写入（engine.run 级）→ **drop + quarantine 留痕 + 拒绝事件**（fail-closed；终验会话中组二测试意外触发同款拦截——`[写入被拒] 本次 user 身份写入未通过通道白名单校验（leak.channel_denied 事件已留痕，内容已隔离记录）`，反向实证默认 enforce 真实生效）；
- REFERENCE 降级回喂路径：默认 off 态 chars=0 + quarantine 三件套在场（事件/文件/UI）；allowlist/注册表双重排除 leak_downgrade；
- 有 token 白名单写入放行（合法通道不受损）。

### 3.6 H6 场景组（cache 性能压力，默认态）

- ratio>95%（非 breaker 期）：`verdict=BLOCK, rule=submit_ratio`（默认态性能 BLOCK 保留——FAIL 证据）；
- privacy 泄漏样例（sk- 虚构序列）：双态（on/enforce）均 `BLOCK/privacy_leak`（**硬门后半句"privacy/safety BLOCK 保留不受影响"PASS**）；
- enforce 态复核：同 ratio 场景 `WARN/submit_ratio_perf` + `would_block=True` 观测在场；85%~95% WARN 带语义不变。

---

## 4. 测试 ↔ 硬门映射矩阵（聚合对账）

| 硬门 | 既有承载（文件:用例性质） | 缺口 | 本次新增（`test_r824_final_gates.py`） |
|---|---|---|---|
| H1 | `test_runtime_zero_prompt.py`（动态 9：E15/E16/E17×2/E18×2/E12 + shadow/off）；`test_runtime_zero_prompt_static.py`（静态 5：退役函数无调用点/engine 不再 import/溢出确定性/停滞事件化/PROGRAM_FINAL 协议化）；`test_runtime_zero_prompt*.py` 均默认态 | 正常任务轮（无故障）无独立 wire 断言 | 组二 2 用例（直接回答轮 + 工具成功轮；含用户原文不改写断言） |
| H2 | `test_latent_channel_exit.py`（E-G1~E-G6 共 10）；`test_task_active_prompt_r816.py`/`test_task_active_authorization`（授权化）；`test_cognitive_*`（冻结面）；`test_prompt_eligibility_r88.py` | `LFL_LATENT_CHANNEL` 默认值无直接断言 | 组一 2 用例（latent 默认 off + cog freeze 默认 on） |
| H3 | `test_tool_result_factualization.py`（C-G1/G4/G5：off 态四源 chars=0 共 8 + shadow 观测 + 三态解析 + 变体模板 2） | **默认值断言缺失**（现有用例全 setenv off/shadow，无默认态登记） | 组一 1（默认 on 快照）+ 组三 2（默认态在场登记 + off 态零值复核） |
| H4 | `test_tool_result_factualization.py`（C-G2/G3/G9：off 态 capsule=0/事实行三元组/占比 0% 共 4 + shadow/on 反证 + reuse 内联 C-G8 + 短路 C-G6 + 可达性） | **默认值断言缺失** | 组一 1 + 组三 1（双面：默认在场 + off 零值/metadata 完整） |
| H5 | `test_trace_leak_quarantine.py`（D-G1~G3 共 22：默认 enforce delenv 断言、无 token drop、有 token 放行、engine 级双态、allowlist/注册表/bypass 门控静态 4、quarantine 权限/留痕）；`test_channel_whitelist_guard.py`；`test_leak_detector_build.py` | 无（覆盖充分） | —（组一 2 用例固化 quarantine/guard 默认值快照） |
| H6 | `test_cache_block_reclassification.py`（D-G4/G5 共 13：enforce 态零值 6 + privacy 双态 3 + 源码默认自证）；`test_cache_guard.py`/`test_cache_breaker*.py`（存量红线） | 行为级"默认态现状登记"缺失（源码 inspect 已有，行为双面无） | 组一 1（源码默认 on）+ 组三 1（行为双面：on 在场 + enforce 零值 + privacy 双保留） |
| §13.1 追加两条 | E-G2/E-G5（决策日志）、E-G6（注册表）于 `test_latent_channel_exit.py` | 无 | — |
| CORE9 终判 | 以 `CORE9-final-ruling.md` 为准：CORE 维持 9 工具、路线 2 逃生门（`get_tool_schema("?keyword")`）已随 R8.24-C 落地（`src/llm_loop/tools/eligibility.py:20,30`）；扩容暂缓 | 无 | —（不重开 A/B，终判已生效） |

**新增断言文件汇总**：`tests/unit/test_r824_final_gates.py`，3 组 13 用例，单跑 13 passed（0.14s）；语义 = ①七开关默认生产态快照（终验锚点）②H1 正常轮 wire 零注入 ③H3/H4/H6"机制 READY + 默认现状在场"双面固化。

---

## 5. 缺口与补断言清单

| # | 缺口 | 处置 | 状态 |
|---|---|---|---|
| 1 | H3/H4/H6 三开关默认值无常驻断言（未来切换无验收锚点） | 组一 3 用例（delenv/inspect 双式） | ✅ 已补 |
| 2 | H1 正常任务轮（非故障场景）wire 无独立断言 | 组二 2 用例 | ✅ 已补 |
| 3 | H3/H4/H6 默认态行为现状无常驻登记（防静默漂移/切换遗漏） | 组三 3 用例（在场断言——**切换提交时须同步翻转**） | ✅ 已补 |
| 4 | latent/cog freeze 默认值断言分散（quarantine/guard/perf 已有） | 组一 2 用例补齐七开关全家福快照 | ✅ 已补 |
| 5 | H5 场景端到端、故障五场景、武装通道等 | 既有覆盖充分 | 无需新增 |
| 6 | 13.2 能力不退化/13.3 应改善指标（census 级） | 属 canary 重跑与 shadow 观测期数据（C 包批 C1② / D'-1.3 观测项），非本终验单测可承载 | 遗留（见 §8） |

---

## 6. 金丝雀解除与 R9 启动条件评估（逐条对照审计条款）

冻结条款（总审计 §12 末尾）：*完成上述 fixed-point 前 behavior canary 继续 BLOCKED、R9 不启动*。逐包对照：

| 条款（§12 包级目标） | 落地提交 | 结构验收（默认生产态） | 判定 |
|---|---|---|---|
| R8.24-A 模型契约瘦身（minimal contract/删必读/删元任务规则） | `7a66d93`（ai_rules.lite v7→v8）；另有工作区未提交规则面变更（主会话管辖） | 规则面属 A 包验收（v8 20 行最小契约已生效；`test_ai_rules_sync.py` 承载同步断言） | **PASS** |
| R8.24-B 控制面闭环（五事件零 prompt/current_turn 不 grant/E19 不进 messages） | `ecef11e` | B-G1~G9：动态 9 + 静态 5 用例默认态全绿；PROGRAM_FINAL 仅协议形状 | **PASS** |
| R8.24-C 回执事实化（guidance 退出/capsule metadata-only） | `c21f42c` | 机制全量落地且 off 态断言完备；**但批 C1③"达标 → enforce off"未执行**（默认 on）→ H3/H4 默认态 FAIL | **FAIL（机制 READY）** |
| R8.24-D provenance/cache/fallback（trace fail-closed/性能 BLOCK 退出/安全 BLOCK 保留/floor） | `f12c83c`（trace）+ `c2dbf09`（cache/fallback） | trace 面：默认 enforce ✅（H5 PASS）；cache 面：**D'-1.3"观测达标后切 enforce"未执行**（默认 on）→ H6 默认态 FAIL；floor/隐私保留有承载 | **FAIL（仅 cache 面；trace 面 PASS）** |
| R8.24-E 潜语义通道收口（E07/E08/E35 退出/冻结/task_active 授权化/CORE9 A/B 后决定） | `04de352` + `CORE9-final-ruling.md`（终判已生效） | E-G1~G6 默认态全绿；CORE9 终判：维持 9 工具 + 路线 2 逃生门（复评触发条件已登记） | **PASS** |
| fixed-point 总判定 | — | 六门 3 PASS / 3 FAIL（默认生产态） | **未达成** |

### 结论

1. **behavior canary：维持 BLOCKED**（审计条款字面满足——fixed-point 未完成）。
2. **R9：维持不启动**（同因）。
3. **解锁路径（无需新特性开发，属生产配置切换 + 各自观测达标回执）**：
   - ① `LFL_TOOL_GUIDANCE` 默认 → `off`（前置：C 包 shadow 期指标达标——duplicate tool call rate / 任务完成率 / ref 恢复使用率）；
   - ② `LFL_EVIDENCE_CAPSULE` 默认 → `off`（前置：CORE9 终判已生效，A/B 前提满足）；
   - ③ `CACHE_GUARD_PERF_BLOCK` 默认 → `enforce`（前置：D'-1.3 观测达标回执）；
   - ④ 每项切换提交须同步翻转 `test_r824_final_gates.py` 组一对应断言与组三"在场登记"断言（**切换锚点已预埋**——不翻转则 CI 红，防止切换被静默遗漏或回滚后无人察觉）；
   - ⑤ 三门翻转后重跑本终验文件 + canary 重跑（E5⑪ 本身即此核验），方可解除 BLOCKED。
4. 风险提示：三开关同为"性能/语义权衡"型灰度（guidance 退出影响失败恢复率、capsule 退出影响恢复工具可发现性、perf 退出改变熔断行为），**建议按 C 包设计顺序分批切换**（先 capsule complete=true 面风险最低 → guidance → perf），不建议一次性三开关同批。

---

## 7. 红线遵守回执

| 红线 | 执行结果 |
|---|---|
| 禁止修改生产行为/配置/开关默认值 | ✅ `src/` 零改动（git status 未新增 src 变更） |
| working 区外部混合层只读 | ✅ 主会话 46 项未提交变更未触碰 |
| 现有测试零改动（只新增） | ✅ 仅新增 `tests/unit/test_r824_final_gates.py`（import 复用现有 helper，无文件改动） |
| 全量 pytest 0 failed | ✅ `tests/`（除 perf）约 4341 用例全绿（exit 0，进度 100% 无 F/E）+ `tests/perf` 全绿（exit 0）；新增 13 用例计入且单跑通过 |
| sk- 虚构样例走 `_ALLOWLIST` 登记先例 | ✅ `scripts/git_security_scan.sh` _ALLOWLIST 新增一行（沿 1ef6e62 先例：文件级豁免 + 全大写字母数字虚构序列）；扫描脚本实跑通过 |
| 禁止 git commit | ✅ 未执行任何 git 写操作 |

---

## 8. 置信度与遗留

**置信度：高（六门判定）／中（解锁路径时序）**

- 高：六门默认态判定全部有"干净进程实测 + 源码行号 + 常驻断言"三重证据；4341 用例全绿排除机制面回归。
- 中：三项 shadow 期的观测数据（duplicate rate/恢复成功率/would_block 计数）在**生产事件流**中积累，本终验无法替代（单测不产生真实观测期数据）；切换时序建议（§6.4）基于设计包风险评估，最终归用户/主会话决策。

**遗留清单：**

1. 三开关 shadow→enforce 切换及其观测达标回执（解锁唯一前置；锚点断言已预埋）；
2. §13.2 能力不退化硬门与 §13.3 应改善指标需 canary 解锁后首轮回跑建立对照（本终验只覆盖结构硬门）；
3. `docs/CHANGELOG.md` 与 R8.24 落地提交失联（REVIEW-2026-09-01 §3 已记录，v0.6.8 条目待补——含本轮五包）；
4. 工作区未提交变更（46 改 + 新增）中 `src/llm_loop/core/prompt.py`、`config.py` 等属主会话混合层，本终验按"只读"处理，其内容未纳入门判定（若其中含规则面 A 包后续变更，以主会话终态为准）。

---

## 9. 证据索引

- 验收标准：`docs/ANALYSIS-20260831-model-agency-obstruction-audit.md:1040-1052`（§13.1 八条）、`:1033-1036`（§12 冻结条款）
- H3 开关与文案：`src/llm_loop/tools/registry.py:30-41`（三态/默认 on）、`:1259-1263`（_FAILURE_GUIDANCE）、`:1266-1296`（渲染路径）、`:1279`（三态注释）
- H4 开关与分支：`src/llm_loop/tools/evidence_enforce.py:29-40`（三态/默认 on）、`:139-160`（off 分支）、`src/llm_loop/core/message.py:144-148`（off 态 metadata 补齐）
- H5 开关：`src/llm_loop/core/trace_leak/leak_events.py:56-72`（默认 off=enforce）、`src/llm_loop/core/trace_leak/user_ingress_guard.py:32-41`（默认 enforce fail-closed）
- H2 开关：`src/llm_loop/core/loop/input_authorization.py:29-31,77-88`（默认 off）、`src/llm_loop/core/loop/build.py:243-247,1671-1675`（freeze 默认 on）
- H6 开关：`src/llm_loop/cache_guard/guard.py:56`（默认 on）、`:226`（enforce 分支）
- C 包灰度设计：`docs/r824/R8.24-C-tool-result-factualization.md:146-160`（C-G1~G9）、`:190-208`（批 C1-C4 shadow→enforce 步骤）
- D 包验收门：`docs/r824/R8.24-D-provenance-cache-fallback-hardening.md:133-146`（D-G1~G8）
- E 包验收门与收尾：`docs/r824/R8.24-E-latent-semantic-channels.md:149-160`（E-G1~G6）、`:209-212`（批 E5⑪ canary 重跑+R9 核验）
- CORE9 终判：`docs/r824/CORE9-final-ruling.md`（2026-09-01 已生效）
- conftest 合法覆盖：`tests/conftest.py:125-135`（guard=observe 测试基建覆盖；生产默认 enforce 由专项 delenv 断言守护）
- 新增常驻断言：`tests/unit/test_r824_final_gates.py`（13 用例）
- sk- 豁免登记：`scripts/git_security_scan.sh:52`（新增行，沿 1ef6e62 先例）
- 落地提交链：`7a66d93`(A) → `ecef11e`(B) → `c21f42c`(C) → `c2dbf09`(D') → `f12c83c`(D-trace) → `04de352`(E)