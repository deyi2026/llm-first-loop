# R8.5 Resolved Episode Retirement — implementation report

状态：**PASS（new/proven episodes） / legacy migration NOT STARTED / behavior canary NOT STARTED**

基线：`88db821 docs(injection): audit prompt eligibility lifecycle`

日期：2026-08-30

## 1. 目标

落实 owner 冻结原则：

> **Resolved is retrievable, not injectable.**

已经得到完整回答的 user episode 不再默认占用未来 provider working context；如果模型后续需要回看原问题、答案或工具证据，通过稳定索引主动检索/hydrate。

本阶段严格遵守顺序：

```text
durable retrieval proof
  -> stable episode ref
  -> session metadata marks resolved
  -> provider-view retirement
```

禁止先过滤、后补索引。

## 2. Durable truth：EpisodeStore

新增 `src/llm_loop/memory/episode.py`：

- 存储：`<data_dir>/episodes/<session_id>.jsonl`；
- append-only，不依赖 ArchiveStore 的 TTL/max-entry GC；
- stable ref：`episode:<session_id>:<user_seq>:<digest>`；
- 同 ref 重放幂等；同 ref 不同 transcript fail-closed；
- write 后 `flush + fsync`，只有成功返回后才允许 session message 获得 `resolved_episode_ref`；
- search 默认只返回 compact Q/A/tool-name 索引；
- hydrate 明确调用、固定上限 6000 chars，超长返回 `next_query=<ref>#offset=N` 分页。

EpisodeStore 保存的是**可见任务事实**：

- genuine user 原文；
- assistant 可见回答与 tool-call declaration；
- tool result。

明确不重复保存：

- `reasoning_content`；
- program-only user/system injection；
- observability/status prompt 噪声。

所以“历史可恢复”不等于“把过去的 prompt control 重新做成第二套 archive”。

## 3. 什么才算可以退休

R8.5 不把 `run_end_reason=completed` 当作 resolved 的充分条件。

原因：provider 截断回答也可能正常退出循环。

`engine.py` 现在只在以下条件全部成立时写：

```text
episode_resolution_candidate=true
```

条件：

1. `answer_origin == model`；
2. `run_end_reason == completed`；
3. final answer 非空；
4. 有真实 provider response；
5. `resp.truncated == false`。

`episode_history.py` 只接受这个显式 proof。旧 session 没有该字段时**不猜**，继续留在 provider view。

因此本阶段不宣称自动完成历史大迁移；legacy migration 必须后续另做证据化映射。

## 4. 生命周期接线

### 4.1 当前 run 完成

最终 assistant message 写入后：

1. `index_current_completed_episode()` 尝试 durable write；
2. durable write 成功后，才给本 episode 范围内消息加：
   - `resolved_episode_ref`；
   - `episode_state=resolved`；
3. session save 持久化 metadata。

如果 EpisodeStore 写失败：

```text
no durable ref
-> no resolved metadata
-> no provider retirement
```

这是 fail-open / information-preserving 路径。

### 4.2 下一 human run

新 user message 进入前会执行 conservative backfill，但只认 R8.5 的显式 candidate proof。

随后 `build.py` 的 provider projection 在 history/budget/profile 之前过滤带 durable resolved ref 的消息。

storage/event truth 不删除。

## 5. Provider view 与 Cognitive packet 同一生命周期

只过滤 flat history 不够。

R8.4 已发现未来 Cognitive behavior applied 时，`_packet_parts` 会直接扫描 persisted `memory_snapshot`，可能把已经 retired 的 memory 从第二条路径复活。

R8.5 因此同时执行：

```text
flat history:
  resolved_episode_ref -> hidden

Cognitive packet memory scan:
  resolved_episode_ref -> skip
```

这闭合了**新/proven resolved episode** 的 flat/packet 双路径。

legacy/unresolved `memory_snapshot` 仍保留现有 R3 语义，因此矩阵 E07 仍是 PARTIAL，不伪装成全部 DONE。

## 6. 历史 anchor 映射

provider view 删除历史消息后，不能继续直接使用原 `sess.history_anchors` 数字。

R8.5 新增双向边界映射：

```text
original session anchor
  -> filtered provider anchor
  -> build_history_messages
  -> filtered anchor_out
  -> original session anchor
```

否则旧 anchor 可能在当前 tool-followup 中落到：

```text
assistant(tool_calls) / tool result
```

之间，形成 orphan tool result 或丢 user query。

专项 E2E 已构造：旧 episode 退休后故意保存 original anchor=旧 episode 尾边界；新 turn 再执行 tool call。最终 followup payload 同时保留：

- current user；
- assistant tool declaration；
- matching tool result；
- 旧问题为 0。

## 7. Durable standing instruction 保护

“这一轮回答结束”不能推出用户写下的长期规则也失效。

因此 R8.5 对明确 cross-turn wording 使用保守 lexical guard，例如：

```text
以后 / 今后 / 从现在开始 / 始终 / 永远 / 不要再
from now on / going forward / always use / never use
```

命中时：

- 整个 episode 仍被 durable index；
- assistant/tool/program 内容退休；
- **exact genuine user message** 标记 `resolved_episode_keep_provider=true`，继续 provider-visible。

这只是 P0-protect，不是完整 effective-constraint store。supersession / canonical current-value 仍是后续工作，所以 E06 保持 PARTIAL。

## 8. Retrieval UX：不新增工具，不扩参数 schema

复用既有 `search_records`，只增加 `kind=episode`：

```text
search_records(kind="episode", query="")
  -> 最近 episode refs

search_records(kind="episode", query="缓存")
  -> 关键词搜索

search_records(kind="episode", query="episode:<...>")
  -> exact bounded hydrate

search_records(kind="episode", query="episode:<...>#offset=6000")
  -> 下一页
```

没有新增 `ref/offset/max_chars` tool 参数，也没有新增第二个 tool。

`search_records` description 从基线 399 chars 变为 415 chars，仅 +16 chars；避免为了历史减负反而显著膨胀稳定 tool schema。

## 9. 因果验证

### 9.1 专项单元/E2E

`tests/unit/test_resolved_episode.py`：**13/13 PASS**。

覆盖：

- stable ref + idempotent durable write；
- search + exact bounded hydration；
- program prompt material 不进入 hydration；
- `reasoning_content` 不进入 hydration；
- durable write 成功后才 mark/retire；
- write failure 不 mark、不 retire；
- unresolved/错误结束不 retire；
- truncated answer 不产生 candidate/ref；
- legacy `completed` 但无 candidate 不猜 resolved；
- standing user constraint 保持 exact provider-visible；
- original ↔ filtered anchor 映射；
- query-only hydration paging；
- 两轮 engine 因果：旧 Q/A/tool 未来 payload=0，但 ref hydrate 可恢复；
- old anchor + 新 tool-followup protocol 不破坏。

关键两轮 fixture：

```text
run 1:
  FIRST-QUESTION-SECRET
  FIRST-TOOL-SECRET
  FIRST-ANSWER-SECRET

run 2 provider payload:
  FIRST-QUESTION-SECRET = absent
  FIRST-TOOL-SECRET     = absent
  FIRST-ANSWER-SECRET   = absent
  SECOND-QUESTION       = present

EpisodeStore hydrate(run1-ref):
  question = present
  tool     = present
  answer   = present
```

这证明是 working-context retirement，而不是信息删除。

### 9.2 相邻回归

history/cache/tool-round/1210/R1-R8/introspection/factory 组合 suite：**420/420 PASS**。

覆盖重点：

- R2 injection budget；
- R3 reference policy；
- R4 program recovery；
- R5 identity summary；
- R6 user truth；
- R8 shadow attribution/soak；
- history layering / projection guard；
- cache anchor/breaker/window；
- tool-round pairing；
- err1210 retry/recovery/session isolation；
- factory / introspection schema。

已知 21 条 `audit_test_side_effects` provider-base-url warning 仍是既有 non-blocking warning。

### 9.3 Static

changed production + new tests：

```text
pyright: 0 errors / 0 warnings
py_compile: PASS
```

### 9.4 R0 frozen

canonical replay：

```text
R0 = PASS
R0-1 = PASS
R0-2 = PASS
R0-3 = PASS
R0-4 = PASS

r0 directory hash before = b54d47a31109a03d9f926f65b7a3d9f6caf3f24c0d42b1bff26fe338ee74b02a
r0 directory hash after  = b54d47a31109a03d9f926f65b7a3d9f6caf3f24c0d42b1bff26fe338ee74b02a
```

### 9.5 Detached clean checkout

首个提交候选 `a9fc88f feat(injection): retire resolved episodes from prompt` 在 detached clean worktree 复跑：

```text
status before = clean
resolved episode focused = 13/13 PASS
adjacent regression = 420/420 PASS
pyright = 0 errors / 0 warnings
py_compile = PASS
eligibility matrix = PASS
R0-1..R0-4 = PASS
R0 directory hash before/after = identical
status after = clean
```

R0 数据只在 analyzer 执行窗口临时挂载 Git-ignored canonical `data`，执行后移除；不把验证辅助路径计入 checkout 内容。

## 10. 明确没有完成的事

R8.5 不是“Eligibility 全部完成”。以下仍保持 blocker/open：

1. pre-R8.5 legacy resolved history 没有显式 resolution proof，未迁移；
2. `model_switch_notice` 当前 run 仍复制最近 user/assistant；
3. Evidence Recovery Manifest 仍自动注入且旁路 R2；
4. legacy/unresolved memory snapshot 仍可能进入 Cognitive packet；
5. local 每轮 behavior hint 仍是动态 command-shaped prompt；
6. unknown program slot 仍 prompt fail-open 为 STATUS；
7. round-exhaustion consumed predicate 仍受 R1 wrapper 破坏。

因此：

```text
R8.5 resolved episode retirement = PASS（new/proven episodes）
legacy migration = NOT STARTED
behavior canary = NOT STARTED
R9 = NOT STARTED
```

下一阶段应继续按 `eligibility/matrix.json` 的剩余 blocker 顺序推进，而不是直接启用 profile behavior。
