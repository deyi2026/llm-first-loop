# Injection Governance R5 — Identity Q&A Summary Stripping

状态：**PASS（mirror verification）**
日期：2026-08-30
范围：**R5 / L2-3 only**

## 1. 目标

R5 解决的不是“禁止用户询问模型身份”，也不是删除对话原文，而是防止短暂的身份/能力问答在 compact 之后被长期摘要不断重放，继续吸引模型偏离后续主体任务。

硬边界：

- 用户/assistant/tool 原始消息保持可逆、可检索；
- 只治理**派生的长期 summary/index projection**；
- identity episode 只折叠身份/能力自述，不得吞掉混合真实任务；
- 不激活 dormant `fixed_summary/summary_chain`；
- 不改变 R2 budget、R4 recovery、R6 user-truth wire；
- 不进入 R7/R8/R9。

## 2. 根因审查：原设计的落点已漂移

最初设计写的是“run.compact summary 输入 + fixed_summary”。当前代码实证显示这一路已经不是 active runtime path：

- `Session.fixed_summary` / `summary_chain` 仍是兼容持久字段；
- 主 `core/loop` 不生成也不消费它们；
- 既有测试明确冻结其 inert 语义；
- R3 已把 compact prompt 自动回灌改成 `ref=archive:search_archive` 指针，不再把旧 `[压缩关键事实]` / 摘要正文自动塞回 prompt。

真正仍会形成**长期摘要细节**的 active surface 有两个：

1. `ArchiveStore.archive` / `_ArchiveMixin._archive_sink`
   - 原文完整进入 archive JSONL；
   - 同时派生 `summary/key_facts/key_paths`；
   - `SUMMARY_MODE != off` 时还会由 `summarize_archive()` 用 LLM 覆盖持久 summary。
2. `SessionStore._trim_session_unleased`
   - 原始 session backup 完整保存；
   - 另写 `*_summary.jsonl`，旧行为直接保留早期 user/assistant 的前 200 字。

因此 R5 没有给 dormant 字段打补丁，而是在这两个 active summary boundary 上治理派生信息。

## 3. 单一策略：sequence-aware identity episode

新增：`src/llm_loop/core/identity_summary.py`。

### 3.1 Identity-only classifier

确定性、无 LLM、保守匹配，覆盖：

- `你是谁`
- `你是什么大模型 / 你现在用的是什么模型`
- `介绍一下你自己`
- `你能做什么 / 你有哪些能力`
- `Who are you? / What model are you running? / What can you do?`
- 身份核验附属句，例如“由谁开发/创建”“先核验真实模型身份再作答”。

关键规则：**整条 human turn 都必须是 identity/self-description 语义**。第一子句命中身份后，后续每个子句仍必须是身份问题或窄身份核验附属句，否则整条消息保留。

实际发现并修复的 false-positive：

```text
你现在是什么模型？上一轮我让你记了什么？
```

第一句是身份询问，第二句是独立记忆任务，因此 R5 必须判为 **non-identity**，不能折叠。

同理以下均保留：

```text
你是什么模型？顺便修复 src/app.py 里的缓存 bug
你能做什么？帮我分析这个仓库
审查 runtime/identity.py 的模型身份校验逻辑
把“你是什么模型？”这句字符串加入单元测试
```

### 3.2 Episode boundary

identity episode 从一个 genuine human identity-only turn 开始，持续覆盖其回答链中的：

- program-user appendix；
- assistant tool-call；
- tool result（例如 `model_catalog`）；
- assistant identity/capability answer。

遇到下一条 genuine human turn 立即结束。

不新增第二份 session 状态；每次从 canonical message sequence 派生。

### 3.3 Legacy program-user 兼容

pre-R1 会话可能存在无 metadata 的 user-role program appendix。R5 不能把它误识别为下一条真人消息，否则 identity episode 会过早结束。

兼容识别：

- `[上下文注入·非新指令]`
- `[上下文注入]`
- R1 已知 program semantic labels / legacy status/reference prefixes

同时 current R1 metadata 优先：`origin_layer=user_instruction` 是权威来源。即使真人字面输入 `[声明提醒] ...`，也仍是 human boundary，不会被 visible label 反向污染。

## 4. Archive 长期 summary/index 治理

`ArchiveStore.archive()` 新增可选的 derived-index overrides；只影响：

- `summary`
- `key_facts`
- `key_paths`
- `summary_source`

**不改变**：

- `content`
- `reasoning_content`
- tool metadata
- archive JSONL 的可恢复原文

identity episode 写入规则：

- identity human 起点：`summary = [身份问答 x 1 轮，已略——本会话主体任务见下]`
- 同 episode 的 program/tool/assistant：`summary = ""`
- 整个 episode：`key_facts=[]`, `key_paths=[]`
- `summary_source=identity_filtered`
- 自动 `summarize_archive()` 跳过，防 LLM backfill 再写回身份细节。
- `ArchiveStore.update_summary()` 对 `identity_filtered` 为 sticky guard：generic backfill 可返回已处理，但不得覆盖净化 summary/source；未来若需改写必须走显式可逆 migration。

Archive sidecar 同时保存净化后的 summary/index，但 `content_head` 仍保留 raw，保证精确恢复能力不丢失。

### 4.1 `with_summary=true` 二次回灌缺口

审查中发现：即使持久 summary 已净化，`search_archive(with_summary=true)` 旧路径仍会把 raw `content_preview` 再送给 Summarizer，重新生成身份细节。

R5 增加闭环：

- `summary_source=identity_filtered` 的 hit 不再调用 Summarizer；
- 只返回已保存 placeholder，或 `[身份问答详情已略]`；
- 不在 `with_summary=true` 输出 raw identity preview；
- `with_summary=false` 仍是明确 raw retrieval 路径，原文可按用户/模型明确检索意图恢复。

## 5. Legacy Session trim summary

`SessionStore._trim_session_unleased` 保持完整 backup 不变，只改变派生 `*_summary.jsonl`：

- 多个 identity episode 聚合为一条：

```text
[身份问答 x N 轮，已略——本会话主体任务见下]
```

- episode 中 user/tool/program/assistant 细节均不写进 summary JSONL；
- 非身份 user/assistant/tool 摘要保持旧规则；
- session backup 仍包含 identity Q&A 原文字节。

## 6. 冻结真实会话审查

对 R0 四个 frozen event log 用 R5 的 genuine-human boundary + classifier 离线扫描：

```text
68fed5f5: human=43  identity=1  → 你是什么大模型
09c44093: human=11  identity=1  → 你什么大模型
996e7e52: human=17  identity=1  → 你是什么大模型
69715765: human=102 identity=0
```

关键点：clean-control `69715765` 中存在：

```text
你现在是什么模型？上一轮我让你记了什么？
```

R5 正确保留为 mixed real task；未产生 identity hit。

## 7. 验收

### 7.1 Focused

**97/97 PASS**，覆盖：

- identity classifier / episode / legacy boundary / visible-label poisoning
- archive raw + sanitized summary/index/sidecar
- mixed identity + real task preservation
- `search_archive(with_summary=true)` no-resummarize
- archive search/index/segments / generic update_summary sticky guard
- summarizer / archive semantic backfill
- SessionStore trim / read-path compatibility
- validator semantic / async-sync archive summary backfill compatibility

### 7.2 Expanded

**542/542 PASS**，45 个测试文件，覆盖：

- core loop / Cognitive integration
- history / layering / summary backfill
- archive / search / summarizer
- R1/R2/R3 injection/reference
- R4 recovery
- R6 user-truth wire
- err1210 / Direction-C
- event/read-path
- memory / focus / model-switch

pytest 仍报告 21 条既有 provider URL 人工复核 warning；非 R5 新增且不阻断。

### 7.3 Static

Touched production：

- `/opt/homebrew/bin/pyright`: **0 errors / 0 warnings**
- `py_compile`: PASS
- `git diff --check`: PASS

### 7.4 R2 × R4 × R5 × R6 matrix

`off/shadow/enforce × 512/700/900/2000/8000` 共 15 点全部满足：

```text
recovery_count == 1
tail_user_run == 1
exact user suffix == true
recovery slot consumed == true
generated_program_chars <= R2 used_chars <= budget
```

**15/15 PASS**。R5 不改变 prompt assembly/budget/wire。

### 7.5 R0 frozen gate

```text
R0=PASS
turns=170
origin=100.0%
attribution=100.0%
post_user=41.76%
dup=51.05%
imperative=3.45%
wire_tail_viol=18.81%
```

`docs/injection-governance/r0` pre/post diff：**0 bytes**。

## 8. 兼容与剩余边界

- **不迁移/改写 pre-R5 archive**：历史 archive 是证据真相，不在 R5 中做破坏性数据迁移。
- pre-R5 archive 可能仍含旧 derived summary；R3 已停止其自动 prompt 回灌，因此只在显式 archive 检索时可见。若未来要批量重建旧 summary，应独立立项并做可逆 migration，不在 R5 静默修改存量证据。
- 新写入的 identity archive 已带 `summary_source=identity_filtered`，其 `with_summary=true` 二次摘要路径被封闭。
- per-message ArchiveStore 的存储拓扑是一条 message 一个 entry，因此每个 identity episode 起点保存 `x 1` placeholder；legacy Session trim 对一个批次内多个 identity episode 才聚合成全局 `x N`。两者都不保留 identity detail。
- `fixed_summary/summary_chain` 保持 inert；R5 没有重新启用该状态机。

## 9. Scope exclusion

R5 未实施：

- R7 L3 A/B；
- R8 model capability tiering；
- R9 主区应用；
- memory 检索算法调整；
- Cognitive Runtime 语义策略调整；
- pre-R5 archive destructive migration。
