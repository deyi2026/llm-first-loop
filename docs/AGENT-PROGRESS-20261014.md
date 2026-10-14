# Agent 进展总结（2026-10-14）

> 会话背景：从 `data/compressed_archive/handoff_20261013-232333/handoff.md` 交接恢复。
> 上会话已闭合 Phase3-6 Goal（git HEAD 0072fbc0c；99069aae6 = phase6 M5 交付；web/learning = gen254）。
> 本轮用户决策（2026-10-13T23:22 批准）：**候选 1（真机 web 通道验收）优先，候选 3（可观测性 M0）其次**。
> 本文严格区分「已执行（有工具回执）」与「计划中（未执行）」。

## 一、已执行（均有本会话工具回执）

### 1. 交接上下文恢复 ✅
- 读取 `handoff.md` 全文 72 行：决策、环境探针快照、代码锚点、七条语义红线、新会话第一步清单。

### 2. 真机环境再验（满足交接「勿仅信快照」要求）✅
- CDP 端点 `127.0.0.1:9229` 实测存活：`PUT /json/new` 成功（Chrome/154 系）。
- 登录态探针（只读 DOM）：`textarea_count=1`、无登录按钮 → **LOGGED_IN**。
- 附带动作：手动开过一个 deepseek 标签（target `8696C29D…`，现已不在 deepseek URL 列表，疑被用户关闭/导航）。

### 3. 生产栈代码侦察（候选 1 实施前置）✅
- `src/llm_loop/llm/deepseek_web.py`：
  - 组装入口 `build_deepseek_web_model_client()` L375（endpoint/root_url/profile/timeout/reasoning_effort 均来自 settings）。
  - M2 协作取消链三层：`DeepSeekWebModelClient.cancel()` → `_ThreadBoundTransport.cancel()`（Event.set，线程安全）→ `_SurfaceOwnedTransport.cancel()` → 页面 transport 早退。
- `src/llm_loop/llm/deepseek_surface.py`（全文 229 行）：
  - `open()` 走 **lease 恢复优先**：lease 存在 → 按 target_id 找页面 → URL 对齐 conversation_url → 稳定返回；仅页面丢失才 `_create_owned_page()`（该分支要求**恰好一个 browser context**）。
- 配置来源 `config.py`：`DEEPSEEK_WEB_CDP_ENDPOINT` 默认 `http://127.0.0.1:9229`。

### 4. 今日外部状态核对（RULE-AI-12）✅
- `data/deepseek-web-provider/surface-lease.json` 存在：target_id `7A0E489A…`，conversation `bc0310ea…`，**updated_at = 2026-10-14T09:57:55（非本会话所为）**。
- 该 lease 页面在浏览器中存活，URL 与 lease 完全一致，标题 **「LFL生产通道验证就绪 - DeepSeek」** → 用户侧已为验收备好会话页面。
- 当前浏览器共 8 个 page target。

## 二、进行中 / 未开始（2026-10-14T10:1x 修订）

| 项 | 状态 |
|---|---|
| 候选 1 真机验收 | **已收口**（carveout 会话顺路完成，回填 docs/phase6-delivery-report.md §5.2；非本会话所为） |
| `get_goal`/`task_frontier` 确认无活动 Goal | 已执行（2026-10-13 23:24 本会话开场：无活动目标） |
| 候选 3：可观测性 M0 立项 | 未开始（当前唯一后续计划） |

## 三、待验点 / 风险 —— 已全部解开（2026-10-14）

1. **09:57 lease 更新来源已确认**：carveout 会话 G4 真机往返（web-carveout-delivery-report.md §5.2，7.7s 回显 `OK-G4`）+ 候选 1 收口抽查（§5.2 t_effect n=3）——非引擎生产占用，争抢风险不存在。
2. **单 context 契约**：lease 恢复分支实测可用（G4 往返即走此路径）。
3. **真实资源消耗**：不再适用（§四用户裁决 deepseek 通道退役）。

## 四、用户裁决与后续计划（2026-10-14T10:10 新指令，替代原计划）

**用户裁决（原话要点）：「不要用这个 deepseek，如果是受相关文档影响就修改文档，也不要用本地模型，太慢了，用 glm」**

配置落地（已执行，注记内含回滚方法）：
- `lfl-web-providers/.env`：`DEEPSEEK_WEB_ENABLED=0`（deepseek-web 通道退役；chatgpt-web 未提及不动）；
- 本仓库 `.env`：`LLM_MODEL` cognilocal/qwen3.8-flash-next → **glm/glm-5.3-flash**；
- 本仓库 `.env`：`MODEL_FALLBACKS` 移除 `deepseek/deepseek-flash` 档（剩 glm-flash → minimax-M3）；
- 文档修订：本节 + web-carveout-delivery-report.md §5.3 + phase6-delivery-report.md §5.2 尾注。

后续计划（按序）：
1. ~~候选 1 真机验收~~ → **已收口**（carveout 会话，§5.2）。
2. ~~deepseek-web 生产核验往返（carveout §5.3）~~ → **撤销**（用户裁决通道退役）。
3. restart 终态核验（action_id：web=svc-e9c583dfca3f4dcdbfda9aef6c68cf26、
   feishu=svc-b42c894856d24868ab20e8b74d3c383e；两阶段等待 requester 退出后
   异步执行——本会话退出后生效，下会话用 service_control(status) 核对）：
   引擎默认模型 = glm/glm-5.3-flash；`/api/v1/providers` 无 deepseek-web 条目；
   降级链无 deepseek 档。离线预验已过（settings 解析回显 + registration
   specs=[] 无 deepseek-web，2026-10-14T10:2x）。
4. **候选 3 立项**：`create_goal`（可观测性 M0：五桶 t_effect 运行时看板，hq `interject_pressure` 雏形在 `src/llm_loop/web/human_turn_queue.py:514`）→ 现状调查 → `grill_me` 设计评审 → 定验收门 → 实施。

## 五、语义红线（交接继承，实施中不得破坏，均有单测锁定）

chat_stream 通道零行为变化；Stop 四态不变；打断轮不进下一轮 provider 投影（P1-6）；
provider_call 单次结算；guard 无死锁；peek 失败 fail-open 不收割（§4.4）；
配置门 `sync_chat_interject_checkpoint` 关闭 = 回退窗口形态（逃生舱）。
