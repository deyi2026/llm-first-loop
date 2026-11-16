# DESIGN-20261116：审查循环的可度量与可收敛 v1.1

- **状态**：设计修订候选（M0；未实现、未取得独立 Reviewer PASS）
- **性质**：需求、数据契约、实现路径与验收标准；不是功能完成报告
- **来源**：原稿 `docs/design/DESIGN-20261116-review-loop-measurement-and-convergence-v1.md`；2026-11-16 只读源码交叉核验
- **隔离基线**：`origin/main` = `96098972f9edc25080d836d08cc9bd7b3c9dd676`；独立分支 `docs/review-loop-design-v11-20261116`
- **范围**：先完成 M0 文档修订；D1/D2/D3/D4/D5 均为待实现设计。保留脏 `main`、现有发布 Goal、其他工作树与生产服务
- **证据口径**：原稿所列 124 份历史回执及其 110/14、33/18 分布是**一次历史只读快照**，不是当前全量审查分母；任何未实测阈值标记 `PROVISIONAL`

> **核心裁决**：保留“先测量，再讨论收敛”的方向，但将原稿七项 P1 修正为可执行契约。**度量永远不能替代独立 Reviewer、原版 R9 或 GitHub CI，也不得降低现有合并与发布门禁。**

## 0. 本轮拷问结论与修订追踪

| 优先级 | 原稿问题 | v1.1 决策 | 章节 |
|---|---|---|---|
| P1-1 | `parent_digest + kind` 混淆不同任务 | 显式 `review_series_id`、`previous_child_id`，区分逻辑任务/child/Provider 尝试 | §3 |
| P1-2 | 文件名含资格，终态可重复、并发覆盖 | 每 child 唯一终态文件；排除轮询与缓存重复；冲突留痕但不覆写 | §4 |
| P1-3 | `_finding_digest` 是拼接字符串，不能当结构化 finding 集 | 只从已验证的结构化解析结果产生指纹；不回退正文；未知就输出 null | §5 |
| P1-4 | 124 个历史样本全部非 PASS；写失败无法自我记录 | 分开历史快照、观测通过率、捕获覆盖率和真实总体未知；失败在回执上报 | §4、§6 |
| P1-5 | 按时间/文件名/插入序各说各话 | 仅用显式前驱链排序；无法验证前驱则不计算相邻轮次 | §3、§5 |
| P1-6 | 把自动合并 S1 误施加到人工合并 | 人工 RULE-AI-34 与 S1 自动合并资格分离；不改变合法 ff-only | §8 |
| P1-7 | 只有 evidence hash，没有可信来源与独立采集 | 独立证据采集器、可信引用、配置快照、时效与执行前复核 | §8 |

P2 同步处理：隐私摘要改为带版本的 HMAC；历史数字进入冻结样例而非生产断言；捕获失败在当前回执暴露；限制单文件体积与扫描窗口，不增设常驻扫描服务。

原稿 R1/R2 的失败模式、事实核验与“曾尝试但未完成的独立子代理审查”记录仍保留在 v1；**不能把原稿的审查尝试或本轮自检当作独立 PASS**。

## 1. 问题、目标和非目标

已有 `review_admission` 独立审查和 `lane_gate.evaluate_s1_gate`，但审查循环的终态捕获、任务归属、跨进程相邻轮次、结构化 finding 覆盖率仍不完整。目标是回答：

1. 在**可观测且去重的**终态样本中，PASS / REVISE / UNAVAILABLE 各占多少？覆盖率是否足以解释？
2. 同一个明确的审查任务，修订后又经历多少独立 child？是否有新问题、旧问题延续、还是证据不足？
3. 什么时候给非阻断的“停止重复打磨、重审方案/切分候选”建议？
4. 自动合并资格是否可以用可信的 S1 证据**独立验证**，同时不破坏人工合并？

**非目标**：自动合并、自动降低 P0/P1 要求、自动放宽测试、无证据的“重复率 KPI”、替代原版 R9、全量重跑每次 poll、新数据库/守护进程、伪造历史 PASS。

### 1.1 事实底座（以代码而非旧行号为准）

- `src/llm_loop/tools/review_report.py`：`persist_report` 只在非 PASS 的回执链使用；`parse_counts` 返回可能含 None 的计数；`extract_findings` 每级最多 8 条并报告丢弃数。
- `src/llm_loop/tools/review_host_admission.py`：`start` 已接受 `previous_child_id`；`_Frozen` 有 `previous_child_id`、`attempts`、`live_child_id`、`cached_pass`；`poll` 会返回 running、失败、REVISE、PASS 和已签发资格的缓存响应。
- 同文件 `_finding_digest(answer)` 返回最长 4000 字符的**文本字符串**，可能退回正文前 1000 字符；不是可用于集合运算的结构化发现项。
- `src/llm_loop/introspection/lane_gate.py`：`GateConfig.auto_merge_allowlist=()`；S1 第 5 条检查自动合并路径白名单，第 10 条要求 `no_ff=True`；`evaluate_s1_gate` 的 verdict 只有 `pass|fail`，每个 check 使用 `check_id`。
- `skills/merge-review-gate/SKILL.md`：人工受控合并允许 `ff-only`；`skills/code-review-gate/SKILL.md`：独立审查仍由 RULE-AI-28 管理。

原稿记录的历史 124 个 md 回执（110 REVISE、14 UNAVAILABLE、0 PASS）、33 个 findings 解析空、18 个 counts 为 None，只用于冻结历史兼容性测试。**0 个 PASS 文件不等于真实 PASS 率为零**。

## 2. 不变量与权限边界

| ID | 必须满足的不变量 |
|---|---|
| N1 | D1 度量写失败、D2 收敛计算失败，不得改变 `qualification`、Host 授权、PASS 缓存、资格消费或审查结论 |
| N2 | 一次 Host child 只对应一个权威终态；Provider 自动重试与重复 poll 不能制造新的审查轮次 |
| N3 | 不同逻辑审查任务不可仅因同 parent/kind 被合并；候选 SHA 变化仍可属于同一任务，但必须有显式前驱 |
| N4 | 任何统计必须披露分母、缺失/解析状态、缓存与重复数；证据不足输出 `null/unknown`，不能填零 |
| N5 | 独立 Reviewer PASS、P0/P1=0、冻结 SHA、原版 R9、GitHub PR/CI 与人工受管发布门禁保持原状 |
| N6 | D3 的 S1 只描述**自动合并资格**；当前自动执行器禁用，人工合并仍走 RULE-AI-34 |
| N7 | 审查文本、命令原文、session 原始 ID 不进入指标文件；隐私键与证据来源必须有版本与可信边界 |
| N8 | 观测与报表为有界、尽力而为、只读分析；无后台全量扫描、无新持久数据库、无隐式发布 |

## 3. D1 身份与轮次链（先解决“谁的第几轮”）

### 3.1 四种不同对象

| 对象 | 身份/计数 | 不应混淆 |
|---|---|---|
| 逻辑审查任务 | `review_series_id`：Host 首次接受 start 时生成随机不透明 ID | 同会话同 kind 的两个任务不应合并 |
| 审查 child | `child_id`：一次 Host `start` 返回的稳定句柄 | 独立 Reviewer 的一次审查轮次 |
| Provider 尝试 | `attempt_count` / `auto_retry_count` / `live_child_id` | 超时后自动 respawn 仍属同一个 child |
| 观察/复用 | `poll_count` 不持久化；`cached_pass`、`reused_from_child_id` | 重复 status/poll 或 PASS 复用不产生新轮次 |

**链的建立**：

1. 第一次有效 `start` 由 Host 生成 `review_series_id` 并随 start 回执返回；该字段仅作观测，不参与准入判据。
2. 后续窄复审沿用现有 `previous_child_id` 参数；Host 必须从可信的当前记录或已持久化的前驱指标解析其 `review_series_id`，并核对 kind、parent 归属。不能只相信父代理传入的 series ID。
3. 前驱缺失、跨 parent、跨 kind、形成环或同一 child 被多条不一致链引用：标记 `lineage_status="unknown|conflict"`；**不猜测、不按时间补链**。允许本次审查继续，但该对样本不参与轮次/收敛统计。
4. 同一 series 可以跨候选 SHA 变更；保留每 child 的精确候选 SHA。跨进程重启只依赖持久前驱链；若历史没有前驱证据，不反填伪造关系。
5. 如果现有 `start`/`_Frozen` 的字段不足以返回/保留 series ID，M1 可增加**纯观测字段**；不得改变 `_same_admission`、`_consume` 等载权比较。

### 3.2 顺序的唯一真值

轮次顺序为 `previous_child_id` 指向的有向链，且链内 child 不重复。`started_at`/`terminal_at` 仅用于延迟、审计与时效，不用于推断前驱；文件名、目录扫描顺序、系统时钟和内存 OrderedDict 插入顺序都不是可跨重启证明的轮次真值。

统计器遇到断链、环、重复前驱、跨 series、时钟回退时分别记录 `pairs_skipped_reason`；有完整前驱才比较相邻轮次。并行分叉（两个 child 指向同一前驱）分别统计为两个分支，不假装有唯一“下一轮”。

## 4. D1 记录契约、写入与去重

### 4.1 文件布局与最小 schema

只新增一个目录 `<data>/review_metrics/YYYY-MM/`，每个 child 最多一份 start 标记和一份权威 terminal 记录：

- `<child_id>.start.json`：Host 接受 start 后尽力写入，供离线估算捕获覆盖率。
- `<child_id>.terminal.json`：终态只创建一次，不含 qualification 的文件名；重复 poll 不生成新记录。
- 使用安全化的 Host child ID（固定长度、路径穿越拒绝）、目录 `0700`、文件 `0600`、原子 staging + **不覆盖**的原子发布。已有 `_write_atomic` 的 `replace` 语义不能直接用于终态：它会让后到者覆盖先到者。
- 建议实现：唯一 staging 文件写入并 fsync，使用同目录原子 exclusive link/create-if-absent 发布终态，清理 staging；目标已存在时核对 canonical digest：相同视为幂等，不同报 `metric_conflict` 并保留首个终态。不得以竞争获胜者的观测结果覆盖 Host 权威状态。
- 允许 start 标记缺失但 terminal 存在；此时计入 `terminal_without_start`，不伪造 start。

示例（所有字符串为**格式示例，不是实测记录**）：

~~~json
{
  "schema": "review_metric.v1.1",
  "metric_id": "host-child-derived-id",
  "review_series_id": "opaque-series-id",
  "child_id": "opaque-child-id",
  "previous_child_id": null,
  "lineage_status": "root",
  "parent_key": "hmac-v1:hex",
  "kind": "full_test",
  "target_key": "hmac-v1:hex",
  "candidate_sha256": "full-content-sha256",
  "started_at": "ISO8601-with-offset",
  "terminal_at": "ISO8601-with-offset",
  "terminal_source": "host-attested",
  "qualification": "PASS",
  "cached_pass": false,
  "reused_from_child_id": null,
  "attempt_count": 1,
  "auto_retry_count": 0,
  "counts": {"P0": 0, "P1": 0, "P2": 0},
  "counts_parse_status": "valid",
  "findings_extract_status": "not_applicable",
  "findings_fingerprints": [],
  "findings_dropped": 0
}
~~~

`metric_id` 为 child 的稳定去重键（可由 Host child ID 规范化生成），**不是**另一次审查；`attempt_count` 为同 child 的 Provider 尝试数，不能与逻辑轮次相加。`qualification` 只保存 Host 实际终态资格（例如 PASS / REVISE / UNAVAILABLE）；不把运行中 PENDING、错误归属 DENIED 的轮询当终态。具体 Host 分支的 terminal 映射须在 M1 列表化、逐分支测试，不能只接 PASS/REVISE 两条 happy path。

### 4.2 唯一终态写入点

- 在 Host **终态转换处**统一尝试持久化，而非每次 `poll` 写入；覆盖 `_mint_pass`、REVISE、deadline、runner failure、NOT_COMPLETED 等真实终态。
- 已 `granted` 的重复 poll 返回缓存响应，不重新写终态；`cached_pass` 复用记为同 child 的属性，报表单列 `cached_pass_count`，不得额外增加 PASS 样本。
- 同 child 自动 respawn 只增加尝试数；如果新 `start` 产生新的 child 且显式链接前驱，才算新轮次。
- 持久化是全函数异常隔离。磁盘满、权限、序列化、符号链接、竞争失败时，**只在本次返回回执附 `metric_error`（不含原始敏感路径/正文）并增加进程内失败计数**；不能声称错误已写进失败的文件。
- 同一个终态文件内容不同视为一致性异常：保留原文件、暴露 `metric_conflict`、等待人工诊断；不能用 last-write-wins 静默吞掉。
- 度量的成功与否不得成为 `review_admission` 的放行条件，亦不得让失败路径无限重试。

### 4.3 可信分母与缺失率

离线 `scripts/review_metrics.py` 只读扫描 start/terminal 文件，并在可用时对账 Host 已有的可信持久执行事件/回执（具体数据源需在 M1 验证可访问性；不得假定存在）。

**至少输出**：

| 字段 | 定义 |
|---|---|
| `start_markers` | 成功写入的 start 文件数 |
| `terminal_metrics` | 唯一、有效的终态文件数 |
| `terminal_without_start` | 终态存在但 start 缺失的 child 数 |
| `started_missing_terminal` | start 存在但没有有效终态的 child 数（含仍运行、丢失、未捕获；不能直接当失败） |
| `invalid_metrics` / `conflict_metrics` | 损坏、schema 不合规、同 child 冲突 |
| `cached_pass_count` / `provider_retry_count` | 缓存 PASS、同 child 自动尝试数，均不增加 child 分母 |
| `observed_pass_rate` | 有效、去重、已知终态中的 PASS / 有效已知终态；明确标为**观测样本率** |
| `capture_coverage` | 有可信的全体终态来源时才计算：有效终态指标数 / Host 真实终态数；否则 `null` |
| `true_pass_rate` | 在总体覆盖无法证明时固定 `null`，不从历史非 PASS 文件推断 |
| `counts_parse_coverage` / `findings_parse_coverage` | 各自分母为适用且有答案的终态样本，不以空值充零 |

历史 124 份 md 回执是**偏向失败结果的独立旧集合**，仅在 `legacy_snapshot` 下展示；与新指标文件不可简单相加形成 PASS 率。若可信 Host 全量事件源不可用，输出 `denominator_status="incomplete"` 和缺失上下界，而非宣称 100% 覆盖。

## 5. D1 发现项解析与重复率

### 5.1 输入只来自有效结构化发现项

- `_finding_digest` 是用于窄复审上下文的有界**字符串**，不是 findings 数组；禁止对其拆行后冒充结构化问题，也禁止在提取失败时回退答案正文计算相似度。
- 优先复用 `review_report.extract_findings` 的明确 `P0/P1/P2` 行解析结果；它每级最多 8 条、每条最多 280 字符，必须保留 `finding_lines_dropped` 和解析状态。若后续引入更好的结构化输出，先用独立样例验证再替换。
- `findings_extract_status`：`valid`（存在可信问题行）、`empty_valid`（明确无问题且计数支持）、`unparsed`（无法判断）、`truncated`（已截断，不完整）、`not_applicable`（PASS 等不适用）。
- REVISE 且解析不到问题不能视为“零问题”；PASS 的 P2 文本默认不采集，P2 数量若能解析可保留在 `counts`，不伪称有 P2 文本指纹。
- 只有 `valid`、未截断且来源明确的单条 finding 才产生 `findings_fingerprints`（规范化后的行做 HMAC 或固定版本指纹；不存原文）。`unparsed`、`truncated`、`not_applicable` 对配对指标均按缺失处理，不把空集合当有效样本。

### 5.2 三个指标不能混称“重复率”

对同 series、同 kind、显式前驱相连、两轮均有有效结构化 findings 的集合 A（前轮）和 B（后轮）：

- **逐字相同问题重合度（Jaccard）**：`|A∩B| / |A∪B|`。
- **旧问题持续率**：`|A∩B| / |A|`；回答“上轮问题还剩多少”。
- **新问题占比**：`|B\A| / |B|`；回答“本轮报出多少新问题”。

任一分母为空，输出 `null` 并给 `undefined_reason`。三者只衡量**同一规范化字符串的精确重合**，不应宣称“语义重复率的严格下界”：问题拆分、合并、严重度重分配和解析遗漏都可能改变分母。输出名称为 `exact_finding_overlap`，附 `semantic_equivalence="not_evaluated"`。

文本 token Jaccard 暂不进入 M1 主路径。未来若要引入，须有带来源、正负样本、独立复核的人工标注集与 precision/recall；“5 对样本 + 阈值 0.6”只能探索，**不足以声称校准完成**。不把该数值作为 Reviewer 排名或门禁 KPI。

### 5.3 只读报表示意

~~~json
{
  "schema": "review_metrics_report.v1.1",
  "legacy_snapshot": {"receipts_total": 124, "revise": 110, "unavailable": 14, "pass_files": 0, "biased_sample": true},
  "capture": {"start_markers": null, "terminal_metrics": null, "capture_coverage": null, "denominator_status": "incomplete"},
  "outcomes": {"observed_pass_rate": null, "true_pass_rate": null, "cached_pass_count": 0},
  "lineage": {"valid_series": 0, "pairs_compared": 0, "pairs_skipped": 0, "order_basis": "previous_child_id"},
  "repeat": {"exact_finding_overlap": null, "old_issue_persistence": null, "new_issue_fraction": null, "semantic_equivalence": "not_evaluated"},
  "quality": {"counts_parse_coverage": null, "findings_parse_coverage": null, "invalid_metrics": 0}
}
~~~

以上是**结构示例**；所有 `null`、零值均非当前实测。命令默认只扫描最近有限月份，支持显式历史窗口；单文件设大小上限，损坏跳过并计数；不接受任意外部文件路径作为数据根，不修改数据目录，也不在 `poll()` 扫描整个目录。

## 6. D1 采集质量与误差披露

1. `capture_coverage` 必须有**独立于指标文件的可信分母**才可报告；start 标记只能形成“已见 start 的终态覆盖”，不能证明所有 start 都被写入。
2. `metric_error` 是**当次响应字段**；如果响应也丢失，离线统计无法看到这次失败，必须写 `coverage_unknown_reason`。禁止“写失败后在同一失败文件里写 write_error”的循环假设。
3. 历史解析失败（33 findings 空、18 counts None）与新 schema 的解析失败分开统计；历史常量放在固定 fixture 中，生产报表不 assert 当前文件数恰为 124。
4. 若系统时钟回拨，保留原始带时区时间，统计 `clock_anomaly`，不改变 §3 前驱顺序。
5. 统计分母拆为：accepted start、已知终态、有效指标、有效解析、可比较相邻对；每层给绝对数和缺失原因。
6. 对有界缓存、自动重试、进程重启的丢样率做独立测试；不能用“看起来趋势稳定”替代覆盖率证据。

## 7. D2 非阻断收敛提示

### 7.1 启用条件

只有 D1 已有真实、可归因、去重的轮次分布，才考虑启用。阈值 `4` 仍是 `PROVISIONAL`，由配置控制且默认关闭；绝不写入资格判据。

- `improving`：同一 series 的有效前驱链中，旧问题持续率下降且没有明显新问题（仅作提示，不下硬结论）。
- `stagnant`：有至少两次可比较的 REVISE，候选 SHA 未变化或精确问题高度重复；建议核对是否重复审查同一产物。
- `insufficient_evidence`：断链、解析失败、UNAVAILABLE 中断、时钟/终态缺失；只提示补证据，不判断“不收敛”。

**连续 REVISE**：沿前驱链向前计数，遇 PASS 结束；遇 UNAVAILABLE/未知终态/断链则标记“不足以判连续”，不跨缺口硬凑第 4 轮。Provider 自动重试不计轮次。并行分叉分别计算。

### 7.2 运行成本与输出

不在每次 `poll` 全量扫盘。可在新终态产生时更新该 series 的有界进程内摘要，或离线报告提供建议；摘要不可用/重启后无法恢复时返回空提示，不能阻断 Host。若确需跨重启提示，只读取当前 series 的**显式前驱链、限定最大跳数**，不扫全库。

~~~json
{
  "review_round_advice": {
    "review_series_id": "opaque-series-id",
    "classification": "stagnant",
    "consecutive_revise": 4,
    "basis": "verified_lineage",
    "threshold": 4,
    "threshold_provisional": true,
    "suggestion": "建议先核对重复问题与候选范围，再决定是否继续窄复审；此提示不影响准入。"
  }
}
~~~

资格、PASS 复用次数、artifact_reviewed 与 Host 权威回执在启用前后必须一致。任何 D2 异常只删除 advice 字段或输出 `insufficient_evidence`。

## 8. D3：S1 自动合并资格诊断与独立核验

### 8.1 先划清适用范围

**人工受控合并**仍按 `skills/merge-review-gate/SKILL.md` 的 RULE-AI-34 独立 Reviewer 回执执行：可 `ff-only`，也可受控 merge commit；**不要求 S1 十项全绿**。不允许把 S1 的默认空自动白名单或 `no_ff` 条件强加给人工合并。

**自动合并**目前由 `MergeNotSupportedError` 禁用；S1 的 `evaluate_s1_gate` 只用于自动合并资格的诊断/未来自动执行前门禁。即使诊断全绿，也不授权执行自动合并。将来如恢复自动执行器，必须另行设计并独立审查执行临界区。

### 8.2 独立证据采集，而不是“只验一个 hash”

新增**只读诊断器** `scripts/check_merge_receipt.py` 的输入为受信任的仓库根、lane ID、受审候选 SHA、现有回执引用；不允许任意回执自称的 `repo_root` 直接决定读取范围。

采集器从受信任源重新构造 `S1Evidence`：lane 账本及当前 claim/help 状态、git 当前 main/head/merge-tree、verify receipt 与其 patch digest、独立 reviewer 绑定 SHA/时间、实际改动文件、merge_plan、GateConfig 开关/白名单、当前时刻。**每个字段**要么附来源与采集时刻，要么显式 `unavailable`；不能以缺失值代替 pass。

诊断回执（只用于 `mode="auto_merge_diagnostic"`）包含：

~~~json
{
  "s1": {
    "mode": "auto_merge_diagnostic",
    "lane_id": "opaque-lane-id",
    "main_head": "exact-main-sha",
    "candidate_sha": "exact-candidate-sha",
    "evidence_ref": "trusted-local-receipt-reference",
    "evidence_sha256": "sha256-of-canonical-evidence-bytes",
    "config_sha256": "sha256-of-canonical-GateConfig",
    "source_refs": ["lane-ledger-ref", "verify-ref", "review-ref", "git-precheck-ref"],
    "evaluated_at": "ISO8601-with-offset",
    "result": {
      "verdict": "fail",
      "checks": [{"check_id": "s1_01", "verdict": "skip", "reason_code": "missing_input"}],
      "auto_merge_allowed": false
    },
    "validation_status": "insufficient"
  }
}
~~~

注意：`evaluate_s1_gate` 的顶层 verdict 只能 `pass|fail`；`insufficient` 是**诊断器的证据充分性状态**，不是 S1 verdict。每个 check 的字段名是 `check_id`，不是 `id`。示例中的 `reason_code` 只是占位，不得声称它对应当前实现的某条真实 skip 代码。

`evidence_sha256` 仅证明**被引用的实际 evidence 字节**与摘要一致，不证明来源可信。诊断器必须重读可信源、比对 SHA/配置/TTL、重新调用 `evaluate_s1_gate`，再核对回执内 `result`。只有输入完整、来源可信、结果一致、main 未漂移才可报“诊断有效”。

### 8.3 退出码与边界

| code | 诊断结果 | 判据 |
|---|---|---|
| 0 | `s1_diagnostic_pass` | 独立采集、完整来源、SHA/配置/时效一致，十项 pass |
| 2 | `missing_s1` | 自动诊断回执无 S1 |
| 3 | `s1_not_pass` | 实际 S1 `verdict=fail`，包括任一 fail/skip |
| 4 | `s1_evidence_tampered` | 可信引用的证据字节与 hash 不符 |
| 5 | `s1_stale` | main/candidate/verify/review 时效不匹配 |
| 6 | `s1_evaluation_error` | 采集或求值异常，保守拒绝诊断通过 |
| 7 | `s1_mismatch` | 独立重算的 checks/结果与回执不一致 |
| 8 | `s1_provenance_insufficient` | 来源缺失、不可独立采集或配置未知 |

诊断返回 0 **不代表自动合并已启用或允许人工合并免审**。执行前必须再次读取 main SHA、lane/claim/help、verify、review 及 GateConfig；TOCTOU 时停止。此文不实现合并执行器，不自动写 main。

## 9. D4：UI 变更的真实页面证据

在 `skills/code-review-gate/SKILL.md` 增加界面实证条目（待 M3 修改）：

- **产出者**负责提供变更后真实页面的可追溯证据：route、viewport、代码/构建版本、操作步骤、截图/浏览器观测引用、采集时刻。
- **独立 Reviewer**验证证据是否覆盖实际改动和声称的交互；必要时用独立浏览器观测复现，不接受仅单测截图或旧版本页面。
- 浏览器不可用时标注 `ui_evidence_status="unavailable"`，不得宣称“已完成真实 UI 验收”；由现有审查与发布门禁判断是否阻断，**不得由度量层自动放行或替代判定**。
- 不依赖单一路径正则判断是否 UI 改动；清单适用范围包括用户可见页面与交互，保留人工语义判定。

最小回执字段：`ui_evidence={route,viewport,build_sha,steps,refs,captured_at,reviewer_verification}`，不在指标文件保存截图内容。

## 10. D5：真实事故形成可复查样例

`evals/review_regression/cases.jsonl` 仅收录可追溯的真实 PR、提交或 Experience；每例有来源、候选 patch 引用、人工预期、证据与复核人。最小 schema：

~~~json
{
  "id": "rr-example",
  "source_ref": "real-incident-or-commit-ref",
  "patch_ref": "relative-fixture-path",
  "expect": "flag",
  "expected_kind": "P1",
  "evidence_ref": "real-observation-ref",
  "review_status": "pending_manual"
}
~~~

干净负例允许 `expect="clean"`、`expected_kind=null`，**不能强迫负例报 P0**。无真实来源时不伪造 5 个案例充数；先收集 1 个可信正例 + 1 个可信负例，再逐步扩展到至少 5 个。

初期工具只打印 case、证据和人工核验清单；**不宣称已接入自动回归 CI**。待结构化 finding 覆盖率和人工一致性足够时另议自动评分。

## 11. 安全、隐私、容量

| 面 | 最小要求 |
|---|---|
| 低熵标识 | `sha256[:16]` 不是匿名化；parent/target 使用带版本的 `HMAC-SHA256`、稳定的受保护本地密钥；不保存原文。密钥不可用则键为 null，降低可归因覆盖率，不回退裸 hash |
| 密钥轮换 | 写 `key_version`；跨版本不默认等值连接。密钥不得进入 Git、回执或日志；只读报表无需密钥即可按既有匿名键聚合 |
| 数据最小化 | 指标文件不保存 reviewer 正文、命令、绝对路径、密钥、用户内容；只保存经结构化验证的指纹与状态 |
| 文件系统 | 目录 0700、文件 0600；限制文件名、拒绝路径穿越/符号链接；staging 原子写、终态 exclusive publish |
| 留存 | 默认按月分片，设可配置保留窗口与删除前预检；本设计不自动清理历史回执或生产数据 |
| 容量 | 单 JSON 例如上限 64 KiB（PROVISIONAL，M1 实测后定）；每次报表限制月份/文件数/总读取字节；按 series 只保留有界聚合 |
| 权限 | D1/D2 不参与准入；D3 只读诊断；所有自动合并与部署执行权限保持禁用/独立授权 |

## 12. 失败模式与可验证行为

| 情况 | 必须表现 |
|---|---|
| 磁盘满、权限拒绝 | 审查原 verdict 不变；本次回执带 `metric_error`，离线覆盖率可能未知 |
| 同 child 两次 poll / 并发写 | 只有一个 terminal；相同幂等、不同冲突留痕，绝不静默覆盖 |
| Provider 自动重试、缓存 PASS | 同 child 仍只算一次；尝试与复用另列 |
| 两个同 parent/kind 的任务 | series 不同，不得误配对 |
| 缺前驱/环/跨 series/分叉 | 只对可信链计数；异常原因单列 |
| REVISE 解析失败或 finding 截断 | 不产生“零问题”或重复率 0；输出 null/跳过原因 |
| 时间回拨/进程重启 | 不用时间排序；链可读则恢复，不能读则 unknown |
| 指标损坏、超大、目录不存在 | 报表跳过并计数；Host 不异常 |
| HMAC 密钥丢失/轮换 | 降低可归因覆盖，不泄露或降级为裸 hash |
| S1 只有 hash、没有可信 evidence | 退出 8，不伪称独立重算 |
| S1 主线漂移/配置漂移 | 诊断拒绝或标记 stale；人工合法 ff-only 不受影响 |
| UI 只提供旧截图 | 不能宣称真实新版本页面已验收 |
| 事故 case 无真实来源 | 不计入有效回归样本 |

## 13. 验收矩阵（M1/M2/M3 开发时执行，不是已通过）

| ID | 对应问题 | 通过条件 |
|---|---|---|
| AC01 | P1-1 | 同 parent/kind 两个独立任务得到不同 series；同一任务跨 SHA 通过前驱正确链接 |
| AC02 | P1-1/P1-5 | 缺前驱、跨 parent、环、分叉、时钟回退不错误排序；重启后有效链仍可恢复 |
| AC03 | P1-2 | 同 child 重复 poll、缓存 PASS、并发终态写只保留一个终态；冲突可观察 |
| AC04 | P1-2 | 自动 Provider 重试计入 attempts，不额外增加轮次 |
| AC05 | P1-3 | `_finding_digest` 回退正文时不生成结构化指纹；解析失败返回 null |
| AC06 | P1-3 | 已解析 findings 的相邻样例计算 Jaccard、旧问题持续率、新问题占比；空分母为 null |
| AC07 | P1-3 | 超过每级 8 条时标记 truncated，不能将部分样本冒充完整重复率 |
| AC08 | P1-4 | 冻结历史 fixture 124/110/14/33/18 兼容通过；生产统计不硬编码这些数字 |
| AC09 | P1-4 | 只有非 PASS 历史 md 时 true_pass_rate=null；不能输出“真实通过率 0%” |
| AC10 | P1-4 | 磁盘满/权限拒绝不改变资格；响应有 metric_error，离线 coverage 不能假称完整 |
| AC11 | P1-4 | 缺独立全体终态分母时 capture_coverage=null；有可信分母时按公式计算 |
| AC12 | P1-6 | 合法人工 ff-only 按现有 RULE-AI-34 不被 S1 `no_ff`/空 allowlist 阻断 |
| AC13 | P1-6 | 自动诊断遇任一 skip/fail 不输出 S1 pass；默认自动执行仍禁用 |
| AC14 | P1-7 | hash 正确但来源缺失 → 退出 8；hash 篡改 → 4；独立重算不一致 → 7 |
| AC15 | P1-7 | main 漂移/过期 → 5；异常 → 6；完整可信正例 → 0（但不执行 merge） |
| AC16 | D2 | 第 3 次不提示、第 4 次仅非阻断建议；UNAVAILABLE/断链不能拼接“连续” |
| AC17 | D2 | 开关前后 Host 资格、PASS 缓存计数、artifact_reviewed 逐字段一致 |
| AC18 | D4 | 实际 UI 变更有新构建版本、route、viewport、步骤、独立核验引用；旧截图拒作实证 |
| AC19 | D5 | 真实可追溯正负样例；clean 样例 expected_kind=null；无自动判定虚假声明 |
| AC20 | N1/N8 | 只读报表运行前后数据字节不变；损坏 JSON/超大文件跳过，运行有界 |
| AC21 | 隐私 | 低熵 target 无法从裸 sha 猜测；无密钥不回退不安全摘要；目录权限正确 |

**验收纪律**：每项标注 fixture、命令、真实 exit code、候选 SHA 和输出回执。AC12–AC15 必须同时有“应拦”与“应放行”样例，防止实现成“全拒门”。不能把本矩阵视为测试已运行。

## 14. 分阶段实施与独立门禁

| 阶段 | 交付 | 收口条件 |
|---|---|---|
| **M0（本次）** | 本 v1.1 文档，消除 7 项 P1，定义最小 schema/测试；不改业务代码 | 文档结构/事实/边界自检；保留原稿；独立审查尚未发生则明确标记 |
| **M1** | D1：可信终态捕获、series 链、幂等、解析状态、只读报表 | AC01–AC11、AC20–AC21；真实 PASS/REVISE/UNAVAILABLE 样本；无准入变化 |
| **M2** | D2：可配置、默认关闭的非阻断建议 | AC16–AC17；基于 M1 真实直方图再定阈值 |
| **M3** | D3/D4/D5 分别推进，不互相阻塞 | AC12–AC15、AC18–AC19；D3 仅诊断、D4 实证、D5 真实种子 |
| **M4** | 冻结候选 SHA、独立 GLM-5.3 Reviewer、原版完整 R9、GitHub PR/CI、受控 main/发布 | **独立 PASS 且 P0/P1=0 → 原版完整 R9 exit 0 → 精确 SHA 远端 CI → 受控合并与按需发布**；任一失败停止，禁止以重试或旧 PASS 冒充 |

开发由单一问题族的一个实现代理负责，最多三个只读调查代理并行；主代理协调、交叉核验、最终收口。必须先确认 Lane/Goal 归属、冻结受审输入与并行工作树，避免覆盖其他会话。**当前 Mac 四服务发布 Goal 不属于本设计，不得借用。**

### 14.1 本次 M0 的实际边界

本文件是独立工作树里的**设计修订**；未启动 Reviewer、未跑 R9、未合并、未部署、未重启。文档分支是否已提交/推送以实际 Git 回执为准，不能把分支 push 当作设计审查 PASS。下一步先核实设计文件无矛盾、完成必要的独立设计审查，再决定 M1 的实现授权与受控工作区。

## 15. 未决项与默认处置

1. **series ID 的跨重启来源**：优先通过现有 `previous_child_id` + 可信终态记录解析；无法证明前驱时标 unknown，不强行引入全局任务注册服务。
2. **Host 全体终态分母**：M1 先调查现有 runner/journal 是否有可信、可枚举的终态事件；没有就如实输出覆盖率未知，不为一个指标新建数据库。
3. **HMAC 密钥来源与留存**：复用现有受管本地密钥设施（如确有）；否则先定义最小安全存储并取得安全审查，不将密钥提交 Git。
4. **D3 独立采集的可信引用**：先复用现有 lane/verify/review 回执和 git 只读证据；未接线字段返回 unavailable，不做假 pass。
5. **D5 真实事故种子**：从已有可核实的 P0/P1 修复 PR/Experience 选取；未找到不伪造。
6. **是否采集 PASS 的 P2 文本**：默认不采集，仅统计可靠的 P2 计数；未来有明确用途再单独审查。

## 附录 A：M0 自检与后续核验命令

~~~bash
# 设计基线（在隔离 worktree 执行）
git rev-parse HEAD
git status --short
rg -n 'review_series_id|previous_child_id|capture_coverage|auto_merge_diagnostic|HMAC|AC21' docs/design/DESIGN-20261116-review-loop-measurement-and-convergence-v1.1.md

# 实现前先确认当前源码契约，不以旧行号作为真值
rg -n 'def start|def poll|def _finding_digest|def extract_findings|def evaluate_s1_gate' src/llm_loop
rg -n 'auto_merge_allowlist|no_ff|ff-only' src/llm_loop/introspection/lane_gate.py skills/merge-review-gate/SKILL.md

# M1 以后才有的命令（此时不得冒称已运行）
# python3 scripts/review_metrics.py --json
# python3 scripts/check_merge_receipt.py <trusted-receipt>
~~~

## 附录 B：审查状态

- **原稿**：v1 未跟踪文件仍保留在原工作区，未覆盖。
- **本稿**：v1.1 设计修订；七项 P1 已在设计层提出对应契约，**代码层尚未修复**。
- **独立 Reviewer**：未启动，未取得 PASS/P0/P1=0。
- **原版完整 R9、远端 CI、main 集成、生产部署**：均未因本次文档修订执行。
