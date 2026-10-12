# P6 Legacy Shared Fallback Retirement Qualification

日期：2026-09-14
分支：`fix/active-run-ingress-1214-20260914`
基线：`1e854429`（P5 Exact Provider-Visible Context Integrity）
阶段：State Ownership / Run Ownership / Context Integrity — P6

## 1. 裁决

P6 不做“删除所有 fallback”。只退休已经证明**没有合法 authority consumer**、且会把缺失上下文错误解释为授权的 shared / latest / last-writer fallback。

保留三类机制：

1. **显式产品语义**：`shared_current_session` 是 Web / 飞书共享当前会话的产品契约，不是隐式 authority fallback；
2. **diagnostic-only**：RunState `last_active_sid` 只用于诊断桶，不给 mutation / routing / Goal / Evidence authority；
3. **显式恢复 API**：`GoalStore.get()` 的 relaxed 模式仍允许显式恢复/CLI 场景使用，但任何已知 session-owned 调用必须 `strict_session=True`。

P6 的机械原则：缺少 exact session / store / getter+setter binding 时，mutation authority = unknown，必须 fail closed；不能借最近 session、最后写入 callback、历史测试挂载或全局 active/latest 代替当前 owner。

## 2. Ownership Map

| Surface | P6 裁决 | 原因 |
|---|---|---|
| `shared_current_session` | 保留 | 明确跨端产品语义 |
| RunState `last_active_sid` | 保留 | diagnostic-only，不参与 mutation |
| `CorrectionContext.session_id` | 保留 | read-only search/archive/introspection compatibility；authority 路径另有 exact binding |
| `GoalStore.get()` relaxed API | 保留 API | 显式恢复仍有价值；session-owned consumer 必须 strict |
| Feishu Resume preferred Goal lookup | **收紧** | 原先 session A 无 Goal 时可借 session B active/latest；现 `strict_session=True` |
| Web / Feishu Evolution approval `engine.evolution_store` | **删除** | production SoT 唯一装配在 `correction_ctx.evolution_store`；历史 side mount 不应获得审批写 authority |
| ToolRegistry `_session_id_explicit/_session_id/set_session_id` | **删除** | production mutation 已由 `current_session_id` ContextVar exact binding；shared last-writer 无生产 reader |
| Active run 写 `CorrectionContext.session_model_override/session_set_override` | **删除** | model-facing switch 已由 per-session resolver exact binding；shared 字段形成跨 session last-writer 污染面 |
| `CorrectionContext.session_model_override/session_set_override` dataclass fields | **删除** | 两个正式入口均已有 exact local binding，无合法 authority consumer |
| CLI/飞书 `/model` 临时把 Session callback 发布到 shared context | **删除** | deterministic interleaving 复现 TOCTOU：A 可调用 B setter，却回执成功 |
| `run_switch_model()` shared override fallback | **删除** | 有效 model mutation 必须同时持有同一 Session 的 exact getter + setter；缺任一 fail closed |

## 3. RED → GREEN 证据

### 3.1 Feishu Resume 跨会话 Goal 借用

RED：请求 session A，无 Goal；session B 有 active Goal。`ResumeAnchorReader` 因 `GoalStore.get(prefer_session_id=A)` 默认 relaxed fallback 返回了 B 的 checkpoint。

GREEN：调用改为 `strict_session=True`；A 无 Goal 时返回 `None`，不会借 B。

### 3.2 Evolution approval 历史 side mount 获得写 authority

RED：`correction_ctx.evolution_store=None`，但测试/历史对象 `engine.evolution_store` 存在时，Web / 飞书审批仍可 mutate suggestion。

GREEN：两个写入口只解析 factory-owned `correction_ctx.evolution_store`；legacy engine mount 被忽略，pending 状态不变。

### 3.3 ToolRegistry shared last-session fallback

RED/审计事实：registry 维护 `_session_id_explicit`，Engine 每 run 写 `set_session_id()`；历史设计允许缺 ContextVar 时回退最后 session。

GREEN：删除字段/property/setter 及 Engine 写入；archive/evidence/tool direct tests 改用 exact `current_session_id` ContextVar。无 ContextVar 时 owner unknown，mutation 不借 stale session。

### 3.4 Active-run shared model override 污染

RED：Engine run 与 `_set_session_override()` 会把当前 Session 的 override / setter 镜像到共享 `CorrectionContext`，并发 session 可互相覆盖 last-writer 状态。

GREEN：active run 只注册 exact `_run_sessions[session_id]` binding；`_set_session_override()` 只改绑定 Session。`CorrectionContext` 两 shared model authority 字段已从 dataclass 删除。

### 3.5 CLI / 飞书 model command TOCTOU

独立 deterministic race 真实复现：线程 A 将自己的 setter 写入 shared context 后暂停；B 覆盖 shared setter 并完成；A 恢复后读取 shared setter，调用了 B 的 Session setter。A 回执“切换成功”，但 A durable Session 未改变。

GREEN：`model_command._switch_reply()` 的 getter/setter 都是本次显式 `Session` 的函数局部闭包，不发布到 shared context；`session=None` 直接 fail closed。三条专用 ownership 测试覆盖并发交错、missing Session、shared residue pollution。

### 3.6 `run_switch_model()` 最后一层 shared fallback

RED/审计事实：即使正式入口都已有 exact getter/setter，helper 仍在 getter 缺失时读取 `ctx.session_model_override`，未来调用方可能重新获得 shared authority。

GREEN：任何有效 model mutation 必须同时传 exact getter + setter；缺任一在 resolve/client construction 前失败。旧 shared 字段不再属于 `CorrectionContext` 类型契约。

## 4. Source Invariant Scan

- ToolRegistry `_session_id_explicit` / `_session_id` / `set_session_id`：production consumer **0**；
- source 中所有 session-owned `prefer_session_id=` GoalStore 调用：均 `strict_session=True`；
- Web / 飞书 Evolution approval：legacy `engine.evolution_store` authority **0**；
- `CorrectionContext` dataclass：`session_model_override` / `session_set_override` 字段 **0**；
- model-facing registry：通过 `session_binding_resolver + current_session_id` 解析 exact Session getter/setter；
- CLI / 飞书 model command：getter/setter 为本次显式 Session 的局部闭包；
- `run_switch_model()`：缺 exact getter 或 setter 即 fail closed。

## 5. Qualification Results

- P6 focused authority / model / Feishu / Web / Registry / Evidence / SubAgent：**223/223 PASS**；
- P6 broad adjacency：**112 files / 1189 tests PASS**，覆盖全 `tests/feishu`、全 `tests/web`、Goal/Task/Factory/Model/SubAgent/Evidence/Continuity 邻接面；
- changed + untracked Python Ruff：PASS；
- changed + untracked Python `py_compile`：PASS；
- changed production source + P6 ownership tests Pyright：**0 errors / 0 warnings / 0 informations**；
- `git diff --check`：PASS。

老测试文件本身存在既有动态 `Settings(**dict)` / stub typing 债务，因此没有把“所有 touched historical tests Pyright 0”作为 P6 门，也没有为追求数字顺手重构与 P6 无关的 fixture 类型系统。P6 新增/修改的 authority 逻辑由 production-source + dedicated ownership Pyright 0/0/0 和真实 pytest matrix 验证。

现有 pytest side-effect audit、Starlette/httpx 与 lark SDK deprecation warning 为既有非阻断诊断；P6 未隐藏 warning 取得 PASS。

## 6. 明确未做

- 未删除 `shared_current_session`；
- 未删除 RunState diagnostic `last_active_sid`；
- 未删除 `CorrectionContext.session_id` 的 read-only compatibility；
- 未删除 GoalStore relaxed API 本身；
- 未改变模型选择语义、fallback 策略或 prompt / Rule / Experience / Method；
- 未重启 Web / Feishu / 8901 / 8903；
- 未启动第二个本地模型；
- 未 push / deploy / tag；
- 未进入 P7 live qualification。
