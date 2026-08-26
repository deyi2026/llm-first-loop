# Program-Induced Drift Root Cause v1

> Status: ROOT-CAUSE AUDIT COMPLETE — DESIGN RECOMMENDATION ONLY
> Date: 2026-08-26
> Scope: long-task context projection, tool-output truncation, archive/retrieval, provider switching, repeated tool use
> A3 status: STOPPED. 64 raw generations + 24 partial judge artifacts are development evidence only; no A3 Gate interpretation.

## 1. Executive conclusion

当前大量“模型反复调用工具 / 压缩后重新查文件 / plan drift”不能简单归因于模型不服从停止条件。

更上游的程序根因是：

> **程序在缩减 Context Projection 时，没有维护一个跨轮、跨 provider、可精确水合的 Evidence Identity / Recoverability Contract。**

因此系统多处满足“原始 bytes 还在磁盘”，却不满足更重要的不变量：

> **模型在下一轮 context rebuild 后，仍然知道自己曾获得过什么证据、证据现在在哪里，并能不重新执行 source action 就精确恢复它。**

这是一种 **Program-Induced Epistemic Amnesia（程序诱发的认知失忆）**。

它违反当前架构已经写明的目标：Context Projection 只是 Semantic AI State 的派生视图；COLD 原始证据应保留 reference 并按需 retrieval，而不是随着 prompt 压缩一起失去身份。`ARCHITECTURE-ai-state-model-v1.md` 明确把 `raw_logs/full_tool_outputs/large_source_files` 放在 `cold_refs`；`ARCHITECTURE-ai-operating-v1.md` 的 Compression Invariants 明确要求 `Critical evidence refs preserved`。

## 2. Root cause chain

### RC-1 — Evidence capture occurs after some tools have already destroyed the canonical observation view

`read_file`、`web_search` 与 `execute_command` 存在工具内部截断。

- `src/llm_loop/tools/builtin/read_file.py:100-105`：默认在 ToolRegistry 看到结果前调用 `truncate_output()`。
- `src/llm_loop/tools/trim.py:66-101`：完整输出写入 `data/audit/tool_outputs/<hash>...log`，返回给 Registry 的已经是首尾截断表示。
- `src/llm_loop/tools/builtin/execute_command.py:72-116`：使用独立 `_truncate_output()`，完整输出写 `data/audit/cmd_outputs/`。

ToolRegistry 的 `_archive_oversize_output()` 只有在 Registry 自己仍拿到 full content 时才能保存原文；默认工具内 3K 截断早于当前 `TOOL_SUMMARY_THRESHOLD=6000`，因此 Registry 经常只看到截断后的 3K 左右内容。

离线端到端复现：

```text
原始 read_file observation      28,873 chars
工具内截断后 Registry 可见       3,289 chars
sidecar                         28,873 chars
ToolRegistry 后 ArchiveStore         0 entries
后续 history compression 入档       3,289 chars
原始中段                           不在 ArchiveStore
```

因此“history archive 保存完整原文”在这种路径上只对 **Message.content 的完整原文** 成立，不对最初 tool observation 成立。

### RC-2 — Storage is split, but no layer owns durable evidence identity

目前至少有两套事实存储：

```text
ArchiveStore
  data/archives/<session>.jsonl

ad-hoc sidecars
  data/audit/tool_outputs/*.log
  data/audit/cmd_outputs/*.log
```

当前存量：

```text
tool_outputs sidecars = 273
cmd_outputs sidecars  = 277
```

sidecar 路径仅存在于截断回执文本中；没有 canonical content_ref、session evidence ledger、source snapshot record 或 recovery manifest。

`cleanup_audit_logs()` 只清理 audit 根目录 `*.jsonl`，不会管理这些子目录 sidecar；因此当前问题不是 TTL 太短，而是相反：**bytes 长期存在，但没有 ownership / indexing / durable recovery identity。**

这正是“保存了，但模型后来不知道去哪里拿”的状态。

### RC-3 — Compression recovery map is transient, not semantic state

`history.py` 只在当前 build 确实发生 `archived` 时临时生成：

- `[压缩关键事实]`
- `[压缩档案目录]`
- `[上下文压缩]`
- `[上下文归档摘要] ... search_archive`

这些不是 Session durable state，而是 build-time projection。

主循环每个 tool round 都重新 `_build_llm_messages()`。当前 provider-scoped compaction 会在后续 build 过滤已标记消息，因此上一轮刚生成的 recovery map 可以下一轮消失。

当前代码两次连续 build 的机械复现：

```text
build #1:
  archive summary      yes
  archive directory    yes
  compression notice   yes
  search_archive hint  yes

build #2:
  archive summary      no
  archive directory    no
  compression notice   no
  search_archive hint  no
```

被折叠的消息仍然不可见。

所以程序实际上执行了：

```text
remove observation
+ temporarily explain how to recover it
+ next round remove the explanation too
```

### RC-4 — Intended persistent summary state exists, but is not wired into production projection

`Session` 已经有：

```text
fixed_summary
summary_chain
```

注释宣称它们用于追加式压缩、跨轮保持任务语义。

但生产代码 grep 证明，这两个字段目前只参与：

- serialization
- replay
- migration
- tests that manually assign values

实际 compression 没有生产它们，build 也没有消费它们。

也就是说，代码结构里已经存在“durable compression state”的形状，但当前生效的是另一套 transient `_archive_summary_dict` 路径。

### RC-5 — `search_archive` conflates discovery with hydration

工具描述宣称：

> 上下文压缩后需要找回早期信息、工具结果被截断需要看完整内容时使用。

但真实接口只做 discovery：

`ArchiveStore.search()` 返回 `_hit_dict`：

```text
id
tool_call_id
summary
key_facts
key_paths
content_preview = content[:800]
```

随后 `run_search_archive()` 又只向模型显示 summary 和最多约 400 chars 的 preview，并没有输出可直接使用的 archive id / tool_call_id / content_ref hydration route。

完整读取 primitive 事实上已经存在：

```text
ArchiveStore.get_by_tool_call_id(...)
```

Web 的“展开原文”已经使用它；AI 没有等价工具。

结果是：**人类 UI 能展开完整 archive，模型自己不能。**

### RC-6 — Archive search semantics and model mental model do not match

当前匹配核心是整串 substring：

```python
q = query.lower()
return q in hay
```

模型则自然地把 `query` 当搜索关键词集合使用。

历史 event log 中：

```text
search_archive results = 63
MISS                   = 57
HIT                    = 5
MISS rate              = 90.5%

multi-word query       = 54 / 63
>=4-word query         = 36 / 63
```

直接例子：

```text
"prepare_method b'GET' 400"  -> MISS
"prepare_method"             -> HIT

"test_2317 bytes method"     -> MISS
"pytest 结果 2317 通过"       -> MISS
"2317"                       -> HIT
```

12 个 run 出现同一 run 内 2 次以上 `search_archive`；其中 9 个 run 全部 MISS。

因此 retrieval 工具自身就会制造“换几个词再试一次”的循环。

### RC-7 — Even a HIT can be epistemically useless

`ArchiveStore.search` 在全文判断是否匹配，但返回永远是内容开头 preview，而不是 match-centered snippet。

因此 query 可能命中内容中段，但 AI 得到的展示片段里根本没有 query，也没有匹配上下文。

实测历史 HIT `prepare_method` 就存在 `query_visible=False`。

当前 `run_search_archive` 还丢弃内部已有的 `key_paths`, `id`, `tool_call_id` 等定位信息，进一步降低 HIT 的可操作性。

### RC-8 — Provider-specific Context Projection is now semantically asymmetric

当前未提交 `cache_compacted_for` 是对旧“重复归档风暴”的重要修复；它使被 DeepSeek 折叠的消息后续对 DeepSeek 隐藏，但可继续对 MiniMax 可见。

机械复现：

```text
30 observations
DeepSeek compaction 后标记 25 条

下一轮 DeepSeek visible = 5 / 30
切 MiniMax visible       = 30 / 30

两边 persistent recovery map = none
```

这作为 cache/transport optimization 本身可以成立，但它必须建立在 provider-neutral Semantic AI State 之上。

当前没有 durable evidence refs/decisions 作为语义 SoT，因此 model/provider switch 会同时改变模型能看到的历史证据集合：旧 observation 可能“复活”，也可能“失忆”。

这会诱发 closed decision reopen、重新调查、不同模型计划分叉。

## 3. Historical baseline vs current uncommitted changes

### Historical baseline defects — 已在 HEAD 存在

1. 工具内先截断、full bytes 只进 sidecar。
2. sidecar 与 ArchiveStore 分裂，无 canonical evidence ref。
3. `search_archive` preview-only，没有 AI full hydration。
4. `search_archive` 整串 substring 语义。
5. compression recovery hint 只在发生压缩的 build 当轮生成。
6. `fixed_summary/summary_chain` 是未接线的 durable state。
7. `architecture_status` >8K 直接截断且不持久化；这是另一种 observation continuity gap。
8. 历史上曾启用过 `TOOL_ROUND_ZERO_HISTORY`，项目自己的 `.env` 注释已经明确记录它导致“工具轮失忆→只读查询停滞循环”；当前已关闭。

这些说明核心问题不是本轮新 patch 引入，而是长期以“prompt/cache 局部优化”替代“semantic evidence continuity”的设计债。

### Current uncommitted improvements

1. provider-scoped `cache_compacted_for` 明显修复了同一批中段反复归档。
2. 当前 `.env` 已关闭 `TOOL_ROUND_ZERO_HISTORY`。
3. docs/ai_rules 后来增加“search_archive 用短关键词”的补救 SOP。
4. sidecar 路径改为 content hash，消除时间戳导致的 cache drift。

### Current uncommitted risk

`cache_compacted_for` 把历史可见性变成 provider-specific persistent projection。没有 provider-neutral evidence state 时，这会把 cache optimization 的实现细节泄漏成 semantic behavior 差异。

所以这项改动不应回滚；应在它上面补齐 Evidence State，而不是重新暴露所有 raw history。

## 4. Historical telemetry: correlation with program-induced loops

所有 event logs 的初步只读统计：

```text
tool calls                               5,419
same-run exact tool+args repeats           226
repeat with context.compressed between     120
  prior result truncated/summary            43
repeat without compression between         106
  prior result truncated/summary             3
```

按工具：

```text
read_file:
  after compression 58, prior truncated 35
  without compression 31, prior truncated 2

architecture_status:
  after compression 35, prior truncated 21
  without compression 11, prior truncated 1

execute_command:
  after compression 26
  without compression 10
```

其中一部分数据来自显式 long-session / pressure stress tests，不能把全部重复都归因于程序故障。

排除 19 个明显压测/强制 full=true/持续读取会话后：

```text
tool calls                               4,092
repeat after compression                    82
  prior truncated                           22
repeat without compression                 100
  prior truncated                            3
```

这仍然显示明显方向性关联，尤其是 `architecture_status`。

更重要的是存在可读的真实链路：

```text
read_file / architecture_status
  -> truncated observation
  -> repeated context compression
  -> search_archive query
  -> MISS / preview-only HIT
  -> exact same source action executed again
```

因此 telemetry 用作支持证据；真正的 causal proof 来自代码路径和离线 end-to-end reproduction，而不是单靠相关性。

## 5. Historical compression storm: amplifier, not current root cause

旧 event logs 中存在非常严重的程序重复归档：

```text
one session:
  context.compressed events 19,573
  same archive_ref max repeat 64
  same msg_seq max repeat    1,170

another:
  2,391 compressed events
  same archive_ref repeat 37
```

当前 `cache_compacted_for` 正在修复这一层放大器；较新的样本已观察到 archive refs 1:1 唯一。

所以需要区分：

```text
old bug:
  same history repeatedly archived
  -> compression storm

remaining root cause:
  once evidence is projected out,
  model cannot reliably identify + hydrate it later
```

前者会放大后者，但修掉前者不会自动恢复证据连续性。

## 6. Why Action Guard is not the root fix

Duplicate suppression / budget terminal 可以：

- 少执行一次外部动作；
- 防止 SOURCE_LIMIT 后继续打工具；
- 降低 provider/API 成本。

但如果模型重复调用的原因是：

```text
I no longer have the evidence
+ I cannot hydrate the archived evidence
```

那么 guard 只会把模型置于：

```text
still missing evidence
+ action blocked
```

这会把“重复工具”指标变好，却可能降低任务成功率或让模型基于缺失信息硬答。

所以 Action Guard 应是 **P2 execution insurance**，不是 P0 root fix。

## 7. Recommended architecture: Evidence Recoverability Contract

### 7.1 Core invariant

任何程序主动减少 AI-visible information 的操作：

```text
truncation
summarization
history compression
provider fold
reasoning slimming
tool-result projection
```

必须同时满足：

```text
1. Original observation snapshot is persisted before projection.
2. Snapshot gets immutable stable evidence_ref.
3. evidence_ref survives every later context rebuild.
4. AI can hydrate exact content/range by ref without re-running source action.
5. Provenance + freshness + source identity survive with the ref.
6. Provider/model switching changes projection, not semantic evidence identity.
```

“磁盘上还在”不算 recoverable。

### 7.2 Capture before projection

工具层不要各自决定“先截断再返回”。

推荐 pipeline：

```text
Tool executes
    ↓
Raw Observation
    ↓
Evidence Capture  <-- persist first
    ↓
EvidenceRef
    ↓
Projection Policy
    ├─ inline full
    ├─ deterministic summary
    ├─ head/tail
    └─ ref only
    ↓
LLM Context
```

即：**capture 与 projection 必须解耦；capture 永远先发生。**

### 7.3 Canonical content-addressed Evidence/Artifact Store

不建议继续让 ArchiveStore 和两个 audit sidecar 目录各自承担部分语义。

推荐一个 content-addressed observation store：

```yaml
ref: evidence://sha256/<digest>
session_id:
tool_call_id:
tool_name:
source_identity:
  kind: file|command|web|runtime_snapshot|...
  locator:
  version_fingerprint:
acquired_at:
content_sha256:
original_chars:
content_complete: true
representation_in_prompt: full|summary|head_tail|ref
provenance:
freshness:
```

Blob 可以复用当前 content-hash sidecar 思路；关键是 metadata/index 成为一等公民。

ArchiveStore 应存/索引 evidence_ref，而不是成为唯一 blob storage；历史消息归档和大型 tool output 可以共享同一 immutable blob，避免复制。

### 7.4 Structured ToolResult completeness

不要再只靠正文里的 `[输出已截断]` 文案表达完整性。

`ToolResult` / Message metadata 应至少有：

```yaml
content_complete: false
original_chars: 28873
content_sha256: ...
evidence_ref: evidence://sha256/...
representation: head_tail
source_fingerprint: ...
```

这样即使文本摘要本身后来又被压缩，恢复信息仍可进入 Semantic AI State / Evidence Ledger。

### 7.5 Separate discovery from hydration

推荐两个明确动作：

```text
search_evidence(query / filters)
  -> returns refs + match-centered snippets + provenance

read_evidence(ref, offset/range)
  -> deterministic exact hydration
```

`search_archive` 可以兼容保留为 discovery alias，但不应继续暗示自己“返回完整原文”。

已有 `ArchiveStore.get_by_tool_call_id()` 可以作为最小实现的第一步，先暴露 AI-safe exact retrieval，再演进到 canonical evidence ref。

### 7.6 Durable Recovery Manifest / Evidence Ledger

Session / Semantic AI State 维护一个小型 provider-neutral ledger，而不是保存所有 raw text：

```yaml
evidence_refs:
  - ref: evidence://...
    source: read_file
    locator: src/foo.py
    acquired_at: ...
    source_fingerprint: mtime+size/hash
    supports:
      - fact-X
      - decision-Y
    state: current|stale|historical
```

Context Projection 决定：

```text
HOT  -> inline critical evidence + ref
WARM -> summary + ref
COLD -> ref only
```

但 ref 不随 prompt compression 消失。

### 7.7 Preserve observation vs current-source distinction

Recoverability 不能变成“永远复用旧数据”。

例如 `read_file`：

```text
old evidence_ref = exact snapshot acquired at T1
current file      = source at T2
```

如果 `mtime/size/hash` 未变，模型可以直接 hydrate T1，没必要重新 read source。

如果 source fingerprint 变化：

- T1 evidence 仍是历史事实；
- 当前决策需要 fresh source 时允许重新读取；
- 系统明确告诉模型 old evidence is stale，不把“有 archive”误当“无需刷新”。

同理，`architecture_status`、web、command observation 都必须把 freshness 作为一等字段。

这样才能区分：

```text
bad repeat:
  same immutable source, old evidence lost -> rerun

good re-verification:
  source may have changed / current state needed -> rerun
```

## 8. Search/retrieval repair

`search_archive` / future `search_evidence` 至少要修：

1. 多词 query 默认 token AND/OR，而不是整串 contiguous substring。
2. 支持 quoted exact phrase。
3. 返回 match-centered snippet。
4. 返回 `evidence_ref/archive_id/tool_call_id/key_paths/chars/acquired_at`。
5. exact ref hydration 不再走 search。
6. no-hit 时给出可解释原因：no candidate / terms too restrictive / scope mismatch。

这会直接消除当前 90.5% miss 下的大量 query reformulation loop。

## 9. Provider projection rule

`cache_compacted_for` 应保留作为 transport optimization，但只能影响：

```text
what raw bytes this provider receives
```

不能影响：

```text
what the agent semantically knows exists
which evidence supports current decisions
which questions are already closed
```

这些必须来自 provider-neutral Semantic AI State / Evidence Ledger。

模型切换时：

```text
same mission
same constraints
same decisions
same evidence refs
same open questions

+ provider-specific projection
```

而不是重新从该 provider “碰巧还能看到的 raw history”推导一次世界状态。

## 10. Test strategy before any new real-provider benchmark

先离线修测量链，不调用真实模型。

### R0 — Recoverability Contract tests

必须新增 end-to-end tests：

#### R0-1 large file

```text
read_file large file
-> default projection truncates
-> exact full observation persisted with stable ref
-> context compression
-> unrelated tool round
-> second/third context rebuild
-> ref still discoverable
-> hydrate middle lines exactly
-> no source re-execution needed
```

#### R0-2 source freshness

```text
capture file snapshot
-> source unchanged
-> reuse evidence
-> mutate file
-> old ref becomes historical/stale
-> current read allowed and creates new ref
```

#### R0-3 command output

完整 stdout/stderr observation 可恢复；旧 command output 与“当前环境状态”明确区分。

#### R0-4 archive search

- multi-term query
- middle-of-content match
- match-centered snippet
- exact ref fetch
- no query reformulation required for hydration

#### R0-5 multiple rebuilds

recovery manifest 跨连续 10+ build 不消失。

#### R0-6 provider switch

DeepSeek compact -> MiniMax -> DeepSeek：

```text
raw projection may differ
semantic evidence refs must remain identical
```

#### R0-7 compression invariants

直接机械验证架构文档已有 invariant：

```text
objective preserved
constraints preserved
closed decisions preserved
critical evidence refs preserved
open questions preserved
```

### R1 — Historical trace replay

使用已有 event logs 做 deterministic replay，不让模型参与：

- 标记原先 exact repeat 链；
- 在新 recoverability layer 下确认对应 evidence ref 在重复动作前仍可取回；
- 估算多少 repeat 属于“程序失忆可避免”，多少是 freshness/用户显式要求/真实模型策略。

### R2 — Fresh real-provider confirmation

只有 R0/R1 通过后，才设计全新 fixture family 做 MiniMax + DeepSeek real confirmation。

不得复用 A3 作为 confirmatory，因为 A3 treatment 没控制 recoverability 这个上游 confound。

## 11. Metrics

建议新增真正能解释漂移的 program metrics：

```text
evidence_capture_success_rate
recoverable_projection_rate
hydration_success_rate
lost_evidence_ref_count
recovery_manifest_survival_across_builds
search_hit_rate
search_hit_with_visible_match_rate
same_source_repeat_without_freshness_change
source_refresh_due_to_fingerprint_change
provider_switch_evidence_set_delta
```

其中 North Star 之一应该是：

```text
Recoverable Projection Rate
=
programmatically hidden observations with valid stable hydration path
/
all programmatically hidden observations
```

目标应接近 100%。

## 12. Recommended implementation order

### P0 — Root fix

1. 定义 `EvidenceRef` / Recoverability Contract。
2. 建 Observation Capture 层，保证 truncation 前先 persist。
3. 给 AI 暴露 exact `read_evidence/read_archive` hydration。
4. 将 evidence refs 接入 durable Session/Semantic State。
5. compression 输出 decision structure + evidence refs，不只输出临时自然语言提示。

### P1 — Retrieval and cross-provider correctness

6. 重做 search semantics + match-centered snippets。
7. provider switch invariance：semantic refs 不随 provider projection 变化。
8. 处理 `fixed_summary/summary_chain`：要么真正接入，要么废弃，避免 dead-state 假象。
9. 给 sidecar 建 ownership/index/GC；迁移为 EvidenceStore blob 或兼容 backend。

### P2 — Secondary action insurance

10. 再评估 Duplicate Suppression / Budget Terminal。
11. 保留 `attempt_count` 与 `execution_count` 分离，不能让 guard 隐藏模型仍在 loop。
12. 用 fresh fixtures 做新的 Action Guard confirmation，而不是复活 A3。

## 13. Final decision

当前不建议继续 A3，也不建议先给 runtime 打“重复调用禁止”补丁。

推荐路线：

```text
A3 STOP / DEVELOPMENT ONLY
        ↓
R0 Recoverability Contract
        ↓
Evidence Capture + Stable Ref + Exact Hydration
        ↓
Persistent Evidence Ledger
        ↓
Search semantics repair
        ↓
Provider projection invariance
        ↓
Offline historical replay
        ↓
Fresh MiniMax + DeepSeek confirmation
        ↓
再判断 Action Guard 是否仍需要
```

核心修复原则：

> **不要阻止模型重新找证据；先确保程序没有把它已经拿到的证据变成“存在但不可恢复”。**

> **Context 可以压缩，Evidence Identity 不能压没。**
