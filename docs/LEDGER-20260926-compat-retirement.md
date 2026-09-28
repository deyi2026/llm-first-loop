# 兼容层退役总表（Migration / Compat Retirement Ledger）

| 项 | 值 |
|---|---|
| 状态 | draft-for-review（证据已核验；**本文档不含任何代码改动，也未执行任何退役**） |
| 建立日期 | 2026-09-26 |
| 性质 | 只减不增的收敛台账（evidence-only，**不是门禁**） |
| 判据来源 | `AGENTS.md` 准入不对称；`docs/subsystem-disposition-20260909.md` 北极星；`docs/DEVELOPMENT_REPAIR_SAFETY.md` Q1/Q2/Q5 |
| 三层判据 | `docs/DESIGN-20260926-model-variance-containment.md`（A 不变量 / B 稳定器 / C 模型裁决） |
| 代码模板 | `src/llm_loop/runtime/service_control.py:330-382` `CompatRetirement` / `COMPAT_RETIREMENT_CRITERIA` / `compat_retirement_view()` |
| 关联文档 | `docs/event_sourcing.md`、`docs/known-reds-20260909.md`、`docs/ANALYSIS-20260924-authority-map-refusal-audit.md`、`docs/AUDIT-20260926-q5-semantic-authority.md` |
| 证据口径 | 2026-09-26 工作区实测：`main...lfl/main [ahead 120]`，27 tracked 文件 `+2194/-223` |

---

## 0. 目的与判据

本表不是重构计划，是**退役台账**。目标只有一个：让每一处过渡态都具备
「存在原因 + 替代路径 + 可机械观测的退役判据 + 最后期限」，从而使 compat 代码量**净下降**。

三条硬约束：

1. **只减不增**（准入不对称）：退役兼容层属于"删除控制机器"，默认放行；反之，**新增**兼容层必须先登记本表并回答「为什么模型 + 现有工具做不到」，同时给出 model-invokable veto 出口。
2. **判据可机械观测**：退役判据必须是审计 / log 中**可计数**的事实（沿用 `CompatRetirement` docstring 的纪律），不得是主观判断。
3. **唯一权威**：每个状态域最终只允许一个 authority；旧路径在退役前只能以 shadow / projection 存在，**不得作为第二真值源**（`DEVELOPMENT_REPAIR_SAFETY.md` Q1）。
4. **B 层稳定器不是退役对象**（2026-09-26 增）：凡承担"认知失稳检测"（重复、无新增证据、目标漂移、同一错误反复）且输出**事实形态**的机制，属 `DESIGN-20260926` 的 **B 层**，应长期保留并**硬化输出契约**，**不作为退役对象**。退役只针对「纯策略结论 + 无 veto 出口」的条目（`DESIGN` §0：可靠性是系统属性，不能外包给模型自省）。

> 与 `service_control.compat_retirement_view()` 的关系：后者是**服务生命周期域**的局部实例（4 条），本表是**全仓机制级**扩展。二者 schema 一致，方向是本表吸收并继续引用局部表，而不是另起格式。

---

## 1. 字段定义

| 字段 | 含义 |
|---|---|
| `ID` | 稳定编号（主线字母 + 序号），供 commit message / 测试锚点引用 |
| `机制` | 过渡态名称 |
| `证据` | `文件:行`（2026-09-26 实测） |
| `现状` | active / shadow / off / opt-in / 不一致 |
| `分类` | 放大（agency amplifier，默认保留）/ 替代（control machinery，收缩）/ 中性（transport/compat） |
| `层级`（2026-09-26 增） | A 不变量 / B 稳定器 / C 模型裁决（见 `DESIGN-20260926`）。**与 `分类` 正交**：`分类` 管"要不要保留"（agency 视角），`层级` 管"输出什么形态"（authority 视角） |
| `替代路径` | 目标唯一权威 |
| `退役判据` | **可机械观测**的删除条件 |
| `优先级` | P0（立即）/ P1（本收敛周期）/ P2（观察） |

---

## 2. 主表

### A. Session / Event 双权威（D1 event-sourcing 迁移）

| ID | 机制 | 证据 | 现状 | 分类 | 替代路径 | 退役判据 | 优先级 |
|---|---|---|---|---|---|---|---|
| A1 | 读路径分派 `READ_PATH_SOURCE`（默认 `session_json`） | `config.py:354,854`；`factory.py:637`；`session.py:1399-1407` | session_json active；event_log 待切换 | 替代 | `READ_PATH_SOURCE=event_log`（replay 重建） | 全量 `event-verify` 对账通过且连续 N 天无 fail-open 回退（`session.py:1403-1406` 零命中） | P0 |
| A2 | event log 双写 + save 兜底 `_event_backfill` | `session.py:1177-1245,1364`；`events.py:174,190,215` | active（`EVENT_LOG_ENABLED=1` 默认） | 中性 | 事件写入即唯一轨迹源 | `session_json` 退役（A1 完成）后 `_event_backfill` 防御层可删 | P1 |
| A3 | 三套存量存储物理退役编排 `event-retire` | `event_log/retire.py:49,178`；`cli.py:358-359,941-1010` | active（就绪即报，不自动切） | 替代 | 单一事件源 | 对账全过 + 人工设 `READ_PATH_SOURCE=event_log` 后删除旧源 | P1 |
| A4 | 迁移 / 回滚 `event-migrate` / `event-rollback` | `event_log/migrate.py:82,281`；`cli.py:718-746` | active（幂等，源不删） | 中性 | 迁移工具本身可保留为一次性工具 | 全量迁移 + 校验通过，且不再有新增 session JSON 后归档 | P2 |
| A5 | fork 双轨写（事件日志 + session JSON） | `event_log/fork.py:38,132,145` | active | 中性 | 随 A1 收敛 | 同 A1 | P1 |

> **A 线是全表最高优先级的单点**：它同时命中 `README.md:106`「事件日志=单一真相源」与 `config.py:354`「默认读 session_json」的表述冲突，是认知税的最大来源。

### B. Runtime admission authority（RG 权威切换）

| ID | 机制 | 证据 | 现状 | 分类 | 替代路径 | 退役判据 | 优先级 |
|---|---|---|---|---|---|---|---|
| B1 | `local_runtime_admission_authority` legacy 正权威路径 | `config.py:440,904`；`factory.py:1805-1816`；`resources/provider_calls.py:194,273-332` | legacy active 默认；lfrt opt-in | 替代 | lfrt 为唯一正权威 | lfrt 成为默认且连续 N 次运行无 `legacy` 分支命中；`provider_calls.py:297` 已定义 legacy 为 shadow veto | P0 |
| B2 | legacy 静默语义（异常→`state=None`→不产生 admission） | `provider_calls.py:309-319` | active（lfrt 路径保留为影子否决 `:160-184`） | 替代 | lfrt 显式失败（`required_fact_unknown` 即终止） | B1 完成后删除 legacy 正权威分支 | P0 |

### C. Semantic retrieval rollout

| ID | 机制 | 证据 | 现状 | 分类 | 替代路径 | 退役判据 | 优先级 |
|---|---|---|---|---|---|---|---|
| C1 | 5-store semantic 开关（memory/archive/method/docs/experience） | `config.py:481-485,933-937` | **全部 off（opt-in）** | 放大 | 逐 store 经 QUALIFICATION 后晋级 | 每 store 独立：off→shadow→on→retired-old-path；**禁止一次性全开** | P1 |
| C2 | 主嵌入/hash/关键词三级 fallback（T0-B） | `memory/retriever.py:748-826,851-882` | active（降级链） | 中性 | 主嵌入稳定后去掉 hash 回退 | 主嵌入（api）连续 N 次成功且 hash 回退零命中 | P2 |
| C3 | multiquery 融合 shadow | `config.py:259-271,492`；`memory/multiquery_shadow.py:34` | off/shadow | 放大 | 经影子数据 + 评审后 enforce | `config.py:262-263`「enforce 待影子数据 + 接入评审后再议」 | P2 |
| C4 | TOML 迁移前的 `_LEGACY_GOVERNED_KEYS`（含全部 `SEMANTIC_*`） | `runtime/resolver.py:153-174` | active（legacy adapter） | 替代 | runtime.toml 单一配置源 | `resolver.py:150-152` schema migration 完成后移除 legacy adapter | P1 |

### D. Evidence（ERC）三态 rollout

| ID | 机制 | 证据 | 现状 | 分类 | 替代路径 | 退役判据 | 优先级 |
|---|---|---|---|---|---|---|---|
| D1 | Evidence 三态 off/shadow/enforce | `config.py:343-344,244-256`；`factory.py:682-904`；`tools/registry.py:394-400` | off 默认 | 放大 | enforce 稳定后 off 路径退役 | `config.py:247-249`「enforce gated by deterministic ERC rollout phases」 | P1 |
| D2 | legacy sidecar 迁移器 `LegacySidecarMigrator` | `memory/evidence_legacy.py:122` | active | 中性 | 迁移完成后删除 | 无 legacy sidecar 待迁移记录 | P2 |
| D3 | tool_guidance 三态（off=enforce 态抑制建议） | `config.py:47,818-820`；`tools/registry.py:180-204,1427-1440` | 三态 | 替代 | 定态后删除多余态 | 选定终态并连续 N 次无 shadow 观测需求 | P2 |
| D4 | evidence_capsule 三态 | `config.py:46,815-817`；`tools/evidence_enforce.py:207-216` | 三态 | 放大 | 同 D3 | 同 D3 | P2 |

### E. Engine Mixin → Service 委托壳（W4-02）

| ID | 机制 | 证据 | 现状 | 分类 | 替代路径 | 退役判据 | 优先级 |
|---|---|---|---|---|---|---|---|
| E1 | 运行时参数委托壳 `_RuntimeParamsMixin`→Service | `core/loop/engine.py:440-458` | active（签名保真转发） | 替代 | 调用方直连 Service | 委托方法调用计数为 0（含 tests）后删除 | P1 |
| E2 | 模型路由委托壳（12 个 `_pool_registry_snapshot`…） | `engine.py:460-507` | active | 替代 | RoutingService | 同上 | P1 |
| E3 | 降级链 / 压缩另存 / 协调通道委托壳 | `engine.py:509-583` | active（含 `_interop_svc` 惰性兜底） | 替代 | FallbackService / ArchiveService / InteropService | 同上 | P1 |
| E4 | 历史 Mixin 继承与「退役」注释 | `engine.py:283,387-417` | active | 替代 | 纯组合 | 四个 mixin 全部删除后 `class LoopEngine(...)` 收敛 | P1 |

> E 线是**已完成拆分后的兼容转发层**，删除风险最低，是"只减不增"的最佳第一批样本。

### F. LLMClient legacy 兼容

| ID | 机制 | 证据 | 现状 | 分类 | 替代路径 | 退役判据 | 优先级 |
|---|---|---|---|---|---|---|---|
| F1 | legacy guard 字段（`guard_enabled/guard_audit_file`） | `llm/client.py:875-880,1507-1577` | active（仅兼容直接调用方） | 中性 | `GuardRequestContext` | 无 legacy direct-client 调用方 | P1 |
| F2 | `reasoning_control="legacy"` 控制路径 | `client.py:864,1169-1226` | active | 中性 | 显式 reasoning contract | 全部调用方显式声明 reasoning contract | P1 |
| F3 | legacy tool_call flat shape 规范化 | `client.py:1253-1352` | active（provider 边界） | 中性 | canonical `function{name,arguments}` | 无历史 flat shape 调用方 | P2 |
| F4 | LLM pool legacy provider-only cache key + retire | `llm/pool.py:47-50,95-98,243-277` | active | 中性 | 复合 cache key | 观察期后 | P2 |

### G. Runtime config 双轨

| ID | 机制 | 证据 | 现状 | 分类 | 替代路径 | 退役判据 | 优先级 |
|---|---|---|---|---|---|---|---|
| G1 | `runtime.toml > legacy .env > defaults` 三源解析 | `runtime/resolver.py:376-389,495-543` | active | 替代 | runtime.toml 单一源 | `_LEGACY_GOVERNED_KEYS`（`resolver.py:153-174`）清空 | P1 |
| G2 | secret legacy .env fallback | `runtime/resolver.py:446-453` | active | 中性 | secret 统一入口 | 所有 secret 迁出 .env | P2 |

### H. 其他过渡态

| ID | 机制 | 证据 | 现状 | 分类 | 替代路径 | 退役判据 | 优先级 |
|---|---|---|---|---|---|---|---|
| H1 | **COG Runtime shadow/enforce（代码）vs 文档称已退役** | `config.py:413-425,888-894`；`core/loop/build.py:640-677`；`core/history.py:543-547`；`docs/configuration.md:152-158` | **不一致** | 替代 | 二选一：删代码 或 改文档 | **先裁决**：docs 明示 delete-first closure 而代码未删 | P0 |
| H2 | prompt eligibility 观察期计数 `would_have_granted` | `core/prompt_eligibility.py:58-65` | active（注释「一个观察期后移除」） | 替代 | 删除观察计数 | 观察期结束且零命中 | P1 |
| H3 | memory `inject_policy` legacy 字段（自动注入已退役，仅保读） | `memory/store.py:49-50` | 仅保读 | 替代 | 删除字段 | 无读取方 | P2 |
| H4 | archive legacy flat 段兼容 | `memory/archive.py:44,184,196,229,270` | active | 中性 | 统一分段格式 | 无 legacy flat 数据 | P2 |
| H5 | worktree registry legacy 状态（A4 只标记不删除） | `runtime/worktree_registry.py:36` | active | 替代 | 删除 legacy 条目 | 无 legacy 条目 | P2 |
| H6 | experience `verification_state="legacy_unclassified"` | `experiences/document.py:40,107-109` | active | 中性 | 全部重分类 | 零 `legacy_unclassified` | P2 |
| H7 | session_types 双侧 re-export | `event_log/session_types.py:1-7`；`core/session.py:29` | active（历史导入路径） | 中性 | 单侧定义 | 无旧导入路径 | P2 |
| H8 | knowledge injection ledger kill switch | `knowledge/injection_ledger.py:11,26` | active | 中性 | — | 保留（kill switch 属可逆能力） | — |
| H9 | RG-3C provider settlement shadow（RG-1 lease vs 影子账） | `resources/provider_calls.py:84-158`；`resources/ledger_projection.py:297,803` | shadow | 中性 | 单一结算权威 | 影子账与正账连续 N 次零差异 | P2 |
| H10 | `submit_ratio` 性能 BLOCK（`_PERF_BLOCK_MODE=="on"`，A 形态政策代理） | `cache_guard/guard.py:281-289`；依据 `engine.py:1443` 内部 budget | on（部分进程） | **替代** | 仅保留 `would_block` 观测 | `ANALYSIS-20260831` P0-4「DELETE PERFORMANCE BLOCK」+ 全进程切 enforce | P1 |
| H11 | `_PERF_BLOCK_MODE` import-time 冻结模块常量（live 进程不感知默认切换） | `cache_guard/guard.py:48,61` | active | 中性 | 运行期解析 | 改为运行期读取，长驻进程可感知切换（Q4 三层一致） | P1 |
| H12 | 规则 G BLOCK 分支 + `block_streak` escape 死代码 | `cache_guard/guard.py:99,805-818` | 不可达 | 替代 | — | 删除死分支/字段（`block_streak` 恒空） | P2 |
| H13 | `CACHE_GUARD=0` 关闭开关声明未实现 | `llm/client.py:872-873`（仅注释） | 文档漂移 | 中性 | 实现或删注释 | 二选一（避免假开关） | P2 |

---

## 3. 已完成闭环样例（供参照，不再需要动作）

| 机制 | 证据 | 结论 |
|---|---|---|
| Web V1 弃用（V2 默认，缺失 503 不回退） | `web/routes.py:1747-1761`（2026-09-04） | 已闭环 |
| P1-B 退役 R8.7 semantic tool-selection plane | `tools/eligibility.py:1-7` | 已闭环（工具可见性不再由语义裁决） |
| memory 自动注入退役（仅保读） | `memory/store.py:49-50` | 已闭环 |
| `program_recovery` 退役（仅保留识别/清洗） | `core/program_recovery.py:1-6` | 已闭环 |
| prompt `extra` 参数弃用 | `core/prompt.py:13-21` | 已闭环 |

---

## 4. 执行顺序（本收敛周期）

原则：**先删零风险转发壳，再收单点权威，最后收多 store rollout。**

1. **P0-A：裁决 H1（COG Runtime 代码/文档不一致）** —— 纯事实澄清，无行为风险。
2. **P0-B：E 线（engine 委托壳）** —— 先建立委托方法调用计数，零调用者删除。删除即回退，风险最低，可作为"只减不增"的验证样本。
3. **P0-C：B 线（admission legacy→lfrt）** —— 需先确认 lfrt 在目标 runtime 完成 qualification（`DEVELOPMENT_REPAIR_SAFETY.md` Q4）。
4. **P1-A：A 线（session/event 单点权威）** —— 先跑 `event-verify` 全量对账，再切 `READ_PATH_SOURCE`，最后删旧源。此线牵动历史/连续性，需独立 commit + focused gate。
5. **P1-B：F/G 线（LLMClient / config 兼容字段）** —— 逐调用方迁移。
6. **P2：C/D/H 线** —— 按各自 rollout 判据推进，**不合并**。

每一步：一个职责一个 commit；红绿先行（先写"旧路径零命中"的失败不变量）；在 staged/isolated candidate 上跑 gate（Q6）。

---

## 5. 维护约定

- **新增兼容层**必须追加一行，且 `分类=替代` 的条目必须回答「为什么模型 + 现有工具无法自判」并给出 veto 出口。
- **每次退役**更新本表：条目移入 §3 或删除，并在 commit message 引用 `ID`。
- 本表是**证据，不是门禁**：不得据此新增运行时阻断；`retire_criterion` 未满足时**保持现状**，不得为了"表好看"而提前删路径。
- 与 `service_control.compat_retirement_view()` 保持 schema 一致；服务生命周期域以该局部表为准，本表引用而不复制。

---

## 6. 明确不做

- 不把本表当"重构大计划"：不做机械拆文件、不设 LOC 下降目标（`subsystem-disposition` §0 判据）。
- 不新增硬轮次 / 时长上限、不做近似重复的语义相似度计算（`SPEC-20260922` §5 E/F）。
- 不在同一次变更里跨多条主线"顺手收敛"（`DEVELOPMENT_REPAIR_SAFETY.md` 2.15）。