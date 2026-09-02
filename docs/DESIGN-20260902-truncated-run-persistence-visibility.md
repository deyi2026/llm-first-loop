# DESIGN-20260902：中断 run 半截产物落盘 + 截断 run 的 episode 可见性（EVO 提案 B1+B2）

- 状态：已实现（2026-09-02 executing→implemented，工作区待提交）
- 实施落点：events.py（`_event_append` 回传 Event + `_on_llm_interrupted`）/ engine.py（取消分支+两处 llm_error 收口挂点、reasoning 增量累积、`_llm_error_digest`、per-run 重置）/ run_finalizer.py（非 completed 终态 → `_index_truncated_run`）/ memory/episode.py（truncated.jsonl 存储与检索/水合）/ introspection/search.py（合并列表 + compact 水合分发）
- 测试：tests/unit/test_interrupted_run_persistence.py（8 例：流式取消端到端、限量与如实标注、env=0 关闭、零产物不加行、fail-open、幂等、行<2KB、检索合并与水合分发）
- P2 存量回填未实施：待运行时窗口协商后另行执行（使 a100a752 的 04:34/04:40 两案可检索）
- 发起：2026-09-02，源起会话 `a100a752`（r9_arch_refactor）中断恢复失灵的根因调查
- 关联调查结论：04:34 llm_error / 04:40 user_stop 两次 run 结构性不可检索；round 17 流式推理中断零落盘
- 范围：本提案只含 **B1（取消/出错路径落盘半截产物）+ B2（truncated episode 索引）**；B3（reasoning_trace 读通道）/ B4（"继续"入口注入提示）/ B5（1214 归因）另列后续

---

## 一、动机与现场证据

用户在会话中断后说"继续"，AI 找不到被截断当时的现场。根因调查（2026-09-02）实锤三个缺口，本提案修其中可程序化的两个：

### 证据 1：取消路径零落盘（B1 靶点）

`src/llm_loop/core/loop/engine.py:698-729` 流式循环：

- `partial_parts` 只累积可见文本 delta（L717 `if getattr(d, "text", "")`）；
  推理 delta（`StreamDelta(text="", reasoning=...)`，见 `llm/client.py:883/887/903/1043/1205`）从头不在捕获范围。
- 取消分支（L701-711）：`_cancelled_during_llm = True` → 关流 → `break`，**不落任何盘**。
- GeneratorExit（客户端断连）是唯一落盘路径：`_on_stream_disconnect`（`events.py:399-420`）——`[对话已中断]` 标注 + 双轨事件 + 立即保存（fail-open）。
- 随后 L945-949：`final_answer = _CANCELLED_ANSWER`（L88"（已停止——…）"），经 run_finalizer 走 program-final 路径；按 R8.24-B E19/B-D7，存储面只留 `[program-final]` role-shape 占位（`prompt_eligibility.py:28`），半截产物彻底消失。
- LLMError 路径（L766+ → `_e1210_llm_error_finalize`）同理：报错轮的 error 摘要只进程序反馈，不进可检索面。

事件日志实证：round 17 的 request.meta（04:40:08）之后直接是 program.final，中间零记录。

### 证据 2：截断 run 被 episode 索引结构性排除（B2 靶点）

- `run_finalizer.py:153-157`：`_episode_resolution_candidate` 要求 `completed + resp 非空 + 未截断`（防伪装完成，本意正确）。
- `episode_history.py:131-146` `_completed_model_answer`：再要求 `answer_origin == "model"`。
- 因此 `run_end_reason ∈ {cancelled, llm_error, …}` 的 run **永远不会**进入 episode 索引。实测 `a100a752` 最后一条 episode 停在 04:20（B5-W3-01 收口），04:34/04:40 两次中断均无索引行——"继续"后即便调 search_records 也只能看到 04:20。

### 证据 3（非目标佐证）：已有思维链只写不可读

会话存储含 1659 条非空 reasoning_content（242.9 万字符），但 `REASONING_TAIL` 未配置=0 → 投影为 0 条；`_render_transcript`（`memory/episode.py:135`）剥掉 reasoning；无工具可读原始事件日志。此为 B3 范围，本提案不展开，但 B1 的落盘设计会为 B3 预留兼容。

---

## 二、目标 / 非目标

**目标**
1. 用户取消（user_stop）与 LLM 错误（llm_error）中断时，当轮已产出的半截可见文本与推理尾部**限量、如实标注**落盘（会话 + 事件日志双轨），不再无声丢失。
2. 上述两类中断 run 在 episode 检索面**可见**：search_records 能回答"何时被打断、为何、最后到哪、半截内容尾段是什么"。
3. wire 投影零变化（不新增 1214/1210 面），resolved episode 退休语义零回归。

**非目标**
- 不改变 completed run 的任何行为；不改变退休判定（truncated 行永不参与退休）。
- 不做 B3 全量思维链检索通道；不做 B4 注入提示；不归因 1214（B5）。
- 同步 chat 路径（FakeLLM 测试专用）不挂 B1（P2 备注）。

---

## 三、设计

### B1：`_on_llm_interrupted`（events.py，仿 `_on_stream_disconnect`）

```python
def _on_llm_interrupted(self, sess, *, text_parts, reasoning_parts,
                        reason: str, error_digest: str = "") -> None
```

行为：

1. 尾部截断保存（限量防爆炸）：
   - 可见文本尾 `INTERRUPT_TEXT_TAIL_CHARS`（默认 4000）；
   - 推理尾 `INTERRUPT_REASONING_TAIL_CHARS`（默认 8000）；设 0 = 关闭该项（env 可关）。
   - 超限时内容前缀如实标注"（截断保存：仅尾部 N/M 字符）"，不伪装完整（P1-6 精神）。
2. 落盘为一行独立 SYSTEM assistant 消息（在 run_finalizer 占位行**之前**，同一 run 至多一行）：
   - `content = 尾段 + "\n[截断标注] reason=cancelled|llm_error; 保存尾 N/M 字符; error=<digest 头部>"`；
   - `reasoning_content = 推理尾段`（Message 已支持该字段，会话存储本就持久化它）；
   - `source = MessageSource.SYSTEM`；
   - `metadata = {"answer_origin": "program", "run_end_reason": <reason>, "llm_interrupted": true, "partial_chars": n, "partial_sha256": digest}`。
3. 双轨同步：`_append_message_event` + `session.save`，全程 fail-open（与 P1-6 相同纪律；事件日志为主锚）。
4. 新事件类型 `llm.interrupted`：`{round, reason, error_digest(≤200 chars), text_tail_chars, reasoning_tail_chars}`——审计与 B2 索引共用数据源。

engine.py 挂点（两处）：

- **流式取消**（L701-711）：`break` 前调用，`reason="cancelled"`。同时在 delta 循环补一行 `if getattr(d, "reasoning", ""): reasoning_parts.append(d.reasoning)`。
- **LLMError**（L766+ 异常入口处）：调用，`reason="llm_error"`，`error_digest` = 状态码 + provider code + 消息头（≤200 chars）。

**wire 安全（关键设计约束）**：`answer_origin=="program"` 的 assistant 消息在投影层被现有谓词（`base_assembly.py:196-203`）自动替换为字节稳定的 `[program-final]` 占位且 `reasoning_content=None`——**零新增 provider 面**。双重保险：`REASONING_TAIL=0` 现状下推理本就不进投影。

### B2：truncated episode 索引（独立 JSONL，非退休型）

1. `memory/episode.py` `EpisodeStore` 新增：

```python
def index_truncated_run(self, session_id, *, ts, run_end_reason, error_digest,
                        last_round, last_event_seq, text_tail, reasoning_tail,
                        partial_chars, partial_sha256) -> None
```

   - 写同目录**独立文件** `truncated.jsonl`（不与 resolved 索引混文件，schema 独立演进；append + flush + fsync 同纪律）；
   - `entry_kind="truncated"`；每行 <2KB；
   - 幂等：以 `(session_id, run_end 事件 seq)` 为去重键，重复收口不重复写。
2. 挂点：`run_finalizer.py` 收口处——`_answer_origin == "program"`（即一切非 completed 终态：cancelled / llm_error / stagnation / overflow / guard_blocked / breaker_context_pressure …）时写一行；completed 不写。
3. 检索面（`introspection/search.py`）：
   - `search_records(kind=episode)` 空查询列表：resolved + truncated 合并按时间倒序；truncated 行带 `state:"truncated"` + `run_end_reason`，一眼可见"04:40 有一次被打断"；
   - hydrate：truncated ref 返回**compact 记录**（摘要字段 + 两个尾段），不跑 `_render_transcript`；
   - **永不参与退休**：不写 RESOLVED_EPISODE_REF、不动 provider 可见性、不进 resolved 判定。
4. 存量回填（P2 可选）：从事件日志扫历史 user_stop/llm_error run 边界补写 truncated 行（使 a100a752 的 04:34/04:40 两案可检索）。

---

## 四、测试计划（红→绿）

**B1 单测**（FakeLLM stream 注入后触发取消 / 抛 LLMError）：
- 断言 sess.messages 出现截断行：content 含 `[截断标注]`、reasoning_content 为推理尾段、metadata 三标记齐全；
- 事件日志存在 `llm.interrupted` 且字段完整；session.save 被调用；
- 超长流：只存尾部且标注字符数如实；
- 环境变量置 0：reasoning 尾不落、文本尾不落（开关有效）。

**wire 投影单测**：build 后该行 content == `[program-final]`、reasoning_content 为 None（复用 m25/fault_isolation 断言风格）。

**B2 单测**：
- cancel/llm_error run 收口 → `truncated.jsonl` 增一行；同 run 重复收口幂等（不重复写）；
- completed run → 不写；
- search 空查询列出 truncated 行、hydrate 返回 compact 记录；
- resolved 流程零回归：episode_history 现有测试套全绿。

**回归**：fault_isolation / m22-m25 / episode 相关套件全绿；`err1210_locating` 现场复放无新增 provider 报错。

---

## 五、风险与对策

| 风险 | 对策 |
|---|---|
| 中断路径再添写盘步骤，可能拖慢/失败 | fail-open + 尾部限量（默认 12K chars 总量）；写失败仅 warning，事件日志为主锚 |
| reasoning 尾落盘扩大敏感面 | reasoning 本就全量在事件日志/会话存储（242.9 万字实证），此处仅"可检索化"，无新增暴露 |
| 上下文膨胀（hydrate 拖回大尾段） | 行级 <2KB；尾段合计 ≤12K chars 硬顶；env 可关 |
| 与 R9 施工（a100a752 会话 B5-W4）在 engine.py / run_finalizer.py 热点冲突 | 落地前与该会话对齐窗口（对应调查建议 A-1"先对齐再放行"） |

## 六、验收标准（用户视角）

1. 中断后（停止/报错），同会话"继续"或新会话 search_records 可见：何时被打断、run_end_reason、最后轮次、半截文本与推理尾段。
2. 被截断轮产物不再无声丢失（限量内如实可取）。
3. wire 投影字节稳定不变，1214 不复发；resolved episode 退休行为零回归。

## 七、工作量与优先级

- B1：M（engine 挂点 2 处 + events 新方法 + 投影断言，约 1 天含测试）
- B2：S-M（EpisodeStore 新方法 + finalizer 挂点 + search 两条路径，约 0.5-1 天）
- 建议同分支一批落地（共享 run_finalizer 触点与测试基建）；整体优先级 **high**（直击"中断即失忆"这一可靠性缺口）。
