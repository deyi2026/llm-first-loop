# SMC 下一步需求设计规划书 v1.0

Date: 2026-09-17
Status: 草案（供评审）
性质：规划文档。事实基础全部来自仓库已提交文档（§1 逐条引用）；标注 [先验] 的条目为训练先验，落地前需另行核验，不作为本规划的依赖前提。

## 1. 已确立事实（规划的事实基础）

### 1.1 Shell 域（SMX）

- 契约冻结：`docs/SMC-CONTRACT-v0.1.md`（N1–N9 禁令、P0–P8 机械探针）。
- SMX 适配：基线 8 PASS / 6 GAP / 0 FAIL（`docs/SMC-CONFORMANCE-v0.1-20260912.md`）→ `docs/SMC-ADAPT-SMX-v0.1-RESULT-20260913.md` 后逐项收口 GAP（diff field completeness、snapshot content integrity、scope comparability guard、canonical projection）。
- Focused A/B v1.2（`evals/pilot/SMX-FOCUSED-RESULT-v1.2.md`）：30/30 PASS + 独立复判 30/30；adoption gate 5/9 压线通过；两处 governance 偏差（Q1 manifest 捕获、Q2 外部 executor）已如实记录。
- **Diff 采用空窗**：3 次 diff-ON run 中模型 0 次真实采用 `smx_perceive` 的 diff 能力；效率收益 mixed。Stage2 方向性证据（-56% ~ -15% 重感知，`docs/SMX-STAGE2-RESULT-v1.md`）文档自身已声明非因果验证。→ P5"效率来自增量"原则至今没有真实采用数据支撑。

### 1.2 Browser 域

- 机械面整体 QUALIFIED：`docs/SMC-BROWSER-PHASE1-BQUAL-RESULT-20260913.md`（B0–B14 全 PASS，30/30 非 DEFERRED R3 场景，全套 repo gates 绿）。B-QUAL 明确非声明：不含模型 A/B 质量，"真实模型 A/B 可作为独立下一阶段"。
- B-LIVE-SEMDIFF：live 20/20 PASS。身份不稳对象（snapshot-local AX id）降级为 `identity_unstable_objects` + `completeness.complete=false`，不做 name/role 自动重绑——这条纪律是 Browser 侧对身份危机的既成解法。
- semantic-execute 模型线：
  - v0.3 A/B → v0.4 FCR-AB：3/3 PASS，能力已证明；
  - **confirmatory v0.5：Gate FAIL**（`docs/SMC-BROWSER-SEMANTIC-EXECUTE-CONFIRMATORY-v0.5-RESULT-20260913.md`）：三任务各恰好 1/2，重复稳定性 NOT_QUALIFIED，默认启用 NOT_QUALIFIED，cloud canary NOT_RUN_BY_GATE；
  - 三个未解 FCR 缺口：① invalid `target_ref` 6/6（先于 exact GroundingRef 调用，工具 fail-closed 无 dispatch）；② wait contract 失败累计 7 次（失败行占 6）；③ 12-round 预算被不必要/不完整 perception 耗尽（失败行均值 12.0 rounds / 12.3 tools，成功行 10.0 / 9.0；关联证据，非因果）；
  - FC2C v0.2（`docs/SMC-BROWSER-BOUNDED-SEMANTIC-OPERATION-FC2C-FCR-v0.2-RESULT-20260913.md`）：required-set 机械派生的 schema guidance 使冻结声明矩阵 4/6 → 6/6，QUALIFIED_FCR_ONLY（不含 live 执行/task 完成/云端兼容）。
- 明确 DEFERRED（不进本规划）：R3-14 vision-only actionability（Phase 2）、R3-29 native chrome / OS UI（Phase 3）、root-level scroll、event-driven wait、wait cancellation surface。

### 1.3 契约文本

- `docs/SMC-CONTRACT-v0.1.md` 全文无 RDF / JSON-LD / Notation3 引用（已 grep 核验）：跨域身份与词汇为独立推导，尚未与既有标准做映射。Browser 元素跨重渲染的稳定 ID 问题与 RDF blank node 身份纪律同构 [先验]。

## 2. 目标与非目标

**目标**（下一阶段，三轨并行）：

- G1 关闭 Browser semantic-execute 重复稳定性缺口：从 confirmatory 3/6 回到预注册 2/2 × 3 任务。
- G2 补上 Shell diff 采用证据空窗：0/3 → 有真实采用数据的新冻结 A/B。
- G3 跨域身份/词汇对齐为可交换格式：Contract v0.2 normative 附录（SMC↔RDF 映射 + JSON-LD @context），纯文本轨，不动 runtime。

**非目标**：

- 不改 Browser Phase 1 已冻结的 stale / version / single-dispatch / append-only receipt 安全边界；
- 不撤销 semantic executor 架构，不放宽 confirmatory gate，不为过 gate 重跑失败行；
- 默认启用 NOT_QUALIFIED 期间不开 cloud canary；
- 不启动 Phase 2 vision / Phase 3 OS；
- 不引入 N3 规则层、triple store、推理机作为运行时依赖。

## 3. 需求清单

### R1（P0 · A 轨）Browser 首调纪律只读诊断

- 动机：v0.5 三个 FCR 缺口无归因；报告裁决明确要求"只读研究为什么模型稳定忽略先 snapshot / wait closed contract"。
- 内容：对已冻结的 6 行 `results.jsonl`（SHA 见 v0.5 文档）做只读轨迹分析：① 每次 invalid `target_ref` 调用发生时模型实际持有的证据面（有无已落盘 exact GroundingRef、是否被 hydrate 失败挡住）；② 7 次 wait contract 失败的具体违例字段分布；③ 轮次消耗分布（navigate/hydrate/snapshot/wait 各占多少）。产出诊断报告，零生产 diff。
- 验收：诊断报告落 `docs/`，每条结论标注行号/轮次级证据；`git diff` 证明 `src/` 无改动。

### R2（P0 · A 轨，依赖 R1）首调接口 v0.3 + confirmatory v0.6

- 动机：FC2C v0.2 已证明"required-set 机械派生 guidance"这一杠杆有效且零语义放宽；v0.5 要求"比堆 universal prompt 更局部、更机械、可泛化的首调接口"。
- 内容：把同一原则推广到两个缺口——① grounding 前置：semantic execute 的 `target_ref` 在 schema/错误面上表达"必须来自已落盘 exact GroundingRef"（机械约束或 fail-fast 文案，不含自动选择）；② wait contract：`kind,target,property,operator,value,timeout_ms,interval_ms` 的 required-set 与违例即返字段名。随后预注册 confirmatory v0.6：同三任务 × 2 repeat，gate 与 v0.5 完全一致。
- 验收：v0.6 预注册 gate 三任务 2/2；invalid `target_ref` 行占比相对 6/6 下降且逐行记录；全程不新增自动 target selection / auto retry / rebind / 程序侧完成裁决 / universal prompt 扩张。
- 出口条件：gate PASS → 进入默认启用评审与 cloud canary 预注册；gate FAIL → 停留在研究态，不放宽。

### R3（P1 · B 轨）Shell diff-forcing focused v1.3

- 动机：0/3 采用空窗使 SemanticDiff 的旗舰收益主张（增量效率）处于零真实使用证据状态；这不是 SMX 的问题，是实验设计没给 diff 路径留出可行且必要的场景。
- 内容：新冻结协议 v1.3。场景设计三要素：长时任务（多轮观察间隔大）、两次观察间目录高频变化（重感知成本高）、任务措辞显式要求增量确认（"只报告自上次观察以来的变化"）。对照组保持 v1.2 场景。预注册度量：diff 真实采用率（逐 run）、重感知调用量、wall time、任务成功率。
- 验收：diff-ON 组真实采用率 > 0 且逐 run 记录；产出与全量感知的效率对比表；adoption gate 规则与 v1.2 完全一致（不因新场景放宽或收紧）。

### R4（P1 · C 轨，纯文档）Contract v0.2 附录：SMC↔RDF 映射 + JSON-LD @context

- 动机：契约独立推导已重造 RDF 学科的一半（三元组式 relations、稳定 ID、图差、谓词查询、溯源）；做一次显式映射可精确划分"重造 / 创新"，并让 Browser 对象从第一天起获得 IRI 级身份方案，避免事后回改。[先验：RDF 1.1 skolemization、RDFC-1.0 规范化哈希、JSON-LD 1.1、PROV-O 均为 W3C 稳定标准；细节落地前核验。]
- 内容（normative 附录，不改 runtime 与 wire 格式）：
  1. 六对象映射表：`relations` ↔ 三元组；稳定 Semantic ID ↔ IRI / skolem IRI；WorldSnapshot ↔ named graph（版本化）；SemanticDiff ↔ 三元组集合差 + RDFC-1.0 规范化哈希（同图异序列化 → 同哈希，正对 DOM 快照序列化歧义）；Predicate ↔ SPARQL ASK 编译目标；ActionReceipt + grounding_refs + observed_version ↔ PROV-O / RDF-star 溯源形态。
  2. 契约对象 JSON-LD `@context`：快照 / diff / 回执零依赖序列化。
  3. 跨域 kind/verb 词汇表：namespace + `subClassOf` + disjointness 声明（Shell `:File`、Browser `:Button` 共享上位类型），服务 Phase 0"三域共用词汇"要求。
  4. 显式标注 SMC 超出现有标准的部分：completeness / blind_spots 契约、expected_version 乐观并发（后者属 HTTP ETag/If-Match 语义，不在 RDF 中找对应物）——这两条是契约的真创新点，映射表中单列。
  5. 不采纳清单并入（见 R6）。
- 验收：附录并入 Contract v0.2；一份真实 snapshot + diff + receipt 的 JSON-LD 序列化示例可被独立 JSON-LD 解析器 round-trip（不改生产代码）；映射表中每行标注"重造 / 对齐 / SMC 特有"。

### R5（P2 · C 轨）adoption gate 与治理收口

- 动机：5/9 压线通过后无后续规则；Q1/Q2 偏差未闭环。
- 内容：GOVERNANCE 文档增补：gate 阈值语义明确化（≥5 通过 / 4 复评 / ≤3 拒绝，或维持现状并记录理由）；Q1 manifest 捕获偏差整改项；Q2 外部 executor 边界声明模板。
- 验收：GOVERNANCE v2 文档 + Q1/Q2 处置记录落 `evals/pilot/GOVERNANCE.*`。

### R6（P2 · C 轨）明确不做清单固化

- 把分散的"明确不采用"合并为契约附录 normative Non-adoption 节：自动 target selection、自动 latest/snapshot、auto retry/replay、rebind、程序侧 task completion、universal prompt 扩张、为过 gate 重跑失败行、N3 规则层（`{前件} => {后件}` 前向链 = 程序侧生成事实，贴 N2/N3 禁令边界；派生事实要么禁、要么显式标 noncanonical）、triple store / 推理机运行时依赖。
- 验收：并入 Contract v0.2 附录；后续 PR 引用该节即可拒绝越界提案。

## 4. 排序与里程碑

三轨并行，A 轨为关键路径：

- **A 轨（Browser 稳定性）**：R1 → R2。M-B1：R1 诊断报告；M-B2：R2 v0.6 gate 结果（PASS → 默认启用评审；FAIL → 研究态续行）。
- **B 轨（Shell 证据）**：R3 独立推进。M-S1：v1.3 结果报告。
- **C 轨（契约文本）**：R4 → R6 → R5，纯文档随时可做。M-C1：Contract v0.2 发布。

优先级理由：v0.5 FAIL 是当前唯一挡住"能力→可用"转化的缺口（A 轨 P0）；diff 空窗是唯一挡住旗舰主张举证的缺口（B 轨 P1，协议层面成本低）；R4 不阻塞任何运行时工作，但应在 Browser 对象身份继续扩张前完成（避免回改）。

## 5. 风险与护栏

1. 全部 gate 预注册 + 身份冻结（protocol commit / plan SHA / surface SHA），失败不重跑失败行、不放宽 gate（延续 v0.5 裁决纪律）。
2. R2 的 schema guidance 只允许从 required-set 机械派生（延续 FC2C 纪律）；禁止以 prompt 语义教化方式扩张。
3. R3 场景设计不得诱导程序侧替模型判断"哪些变化重要"（diff 保持纯机械，语义解释权在模型）。
4. R4 不得引入运行时依赖、不得改变任何 wire 格式（仅新增附录与序列化示例）。
5. R1–R2 期间不得顺手"修复"v0.5 失败行之外的东西：每轨只动自己声明的内容。

## 6. 验收总表

| 需求 | 机械判据 | 依赖 |
|---|---|---|
| R1 | 诊断报告落 docs/ + 每结论带行/轮次证据 + src/ 零 diff | — |
| R2 | v0.6 预注册 gate 2/2×3 + invalid target_ref 占比下降 + 禁令零违反 | R1 |
| R3 | diff-ON 采用率>0 逐 run 记录 + 效率对比表 + gate 规则与 v1.2 一致 | — |
| R4 | Contract v0.2 附录 + JSON-LD round-trip 示例 + 映射表逐行分类 | — |
| R5 | GOVERNANCE v2 + Q1/Q2 处置记录 | — |
| R6 | Non-adoption 节并入 v0.2 | R4 |
