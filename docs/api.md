# llm_loop 公共 API 参考

> 本文档面向集成者：把 LLM-First Core Loop 嵌入自有应用/脚本。  
> 完整配置项见 `.env.example` 与 `docs/configuration.md`；示例代码见 `examples/`。  
> **稳定 API 声明（B5）**：下表列出的符号（§1–§8）为公共稳定接口，语义变更需版本号  
> 升级（0.x 内小版本可增补，不破坏）；未列出的内部符号（`_` 前缀、mixin、registry\_*）  
> 视为私有，勿在外部依赖。

---

## 1. 快速装配（两行起步）

```python
from llm_loop.config import load_env_file, load_settings
from llm_loop.factory import build_engine

load_env_file()              # 从项目根 .env 加载配置（环境变量优先）
engine = build_engine(load_settings())

# 一次性对话（自动创建会话）：最简路径
result = engine.run_single("请读取 data/notes.txt 并总结")
print(result.final_answer)
```

## 2. 配置层（`llm_loop.config`）

| 符号                            | 说明                                                                                                   |
| :---------------------------- | :--------------------------------------------------------------------------------------------------- |
| `load_settings() -> Settings` | 从环境变量装配全部配置；缺少 `LLM_API_KEY`/`LLM_BASE_URL` 抛带指引的 `ValueError`                                       |
| `load_env_file(path=None)`    | 从 `.env` 加载到环境变量（已设置的环境变量优先；文件缺失 fail-open）                                                          |
| `Settings`                    | 全部配置的 dataclass（只读惯用）；关键字段：`llm_model`/`max_iterations`/`history_max_chars`/`exec_mode`/`data_dir` 等 |

## 3. 引擎（`llm_loop.factory` / `llm_loop.core.loop.engine`）

### `build_engine(settings: Settings) -> LoopEngine`

装配全部组件（LLM client、记忆、检索、工具注册表、事件日志、审批审计）——**唯一生产装配点**。

### `LoopEngine`

| 方法                                                                       | 说明                                                              |
| :----------------------------------------------------------------------- | :-------------------------------------------------------------- |
| `run(session_id: str, user_text: str, model=None) -> LoopResult`         | 同步执行完整循环（工具循环内部阻塞）                                              |
| `run_single(user_text: str, model=None) -> LoopResult`                   | **一次性便捷入口**：自动创建新会话并执行（等价 `run(create(), text)`）                |
| `run_stream(session_id, user_text, model=None) -> Iterator[StreamDelta]` | 流式版本：逐 content delta yield，结束抛出 `StopIteration` 携带 `LoopResult` |
| `session`                                                                | 已装配的 `SessionStore`（会话 CRUD）                                    |
| `registry`                                                               | 已装配的 `ToolRegistry`（工具注册/执行）                                    |

### 注入自定义工具（B5）

```python
engine.registry.register(MyTool())   # 实现 name/description/parameters/execute（见 §5）
# 注册后 AI 在下一轮循环即可自主调用（schema 自动注入）
```

### `LoopResult` 关键字段

`session_id` / `final_answer` / `rounds` / `tool_calls`（工具声明轨迹）/ `model_used`（如实标注实际模型）/ `tokens_in` / `tokens_out` / `truncated` / `reasoning_content`

## 4. 会话（`llm_loop.core.session`）

| 方法                                                                              | 说明                   |
| :------------------------------------------------------------------------------ | :------------------- |
| `SessionStore(sessions_dir, event_store=None, read_path_source="session_json")` | 会话存储（JSONL + 可选事件溯源） |
| `create() -> str`                                                               | 新建会话，返回 session_id   |
| `load(session_id) -> Session`                                                   | 加载会话（损坏 fail-open）   |
| `save(session)` / `append(session_id, message)` / `delete(id, confirm)`         | 落盘/追加/删除（原子写）        |
| `list_sessions()` / `get_meta(session_id)`                                      | 会话列表/元数据             |
| `fork(session_id, ...)`                                                         | 会话 fork（事件日志物理复制继承）  |

**删除语义**：`SessionStore.delete()` 删除的是 session-owned 会话状态及其明确 sidecar；它不级联删除当前工作区的 `artifact://v1/...` immutable artifact。Workspace artifact 属于 workspace-owned durable execution record，记录中的 `owner_session_id` 只表示 producer provenance，不授予 session 级联删除权。因此 producer session 被物理删除后，后续 session 只要仍在同一 workspace 且持有已知 artifact ref，仍可按 SHA256/immutable snapshot 契约精确读取。未来若清理 artifact，必须走独立、显式的 workspace/artifact retention 或 GC 契约，不能从 session delete 隐式推导。

## 5. 工具系统（`llm_loop.tools`）

### 工具协议（注册新工具只需实现 4 项）

```python
from llm_loop.core.message import ToolResult, ToolResultStatus

class MyTool:
    name = "my_tool"
    description = "何时用/何时不用/失败对策"
    parameters = {"type": "object", "properties": {...}, "required": [...]}  # JSON Schema

    def execute(self, **kwargs) -> ToolResult:
        # 返回五态之一：SUCCESS / FAILURE / ERROR / TIMEOUT / BLOCKED（禁止伪装成功）
        return ToolResult(status=ToolResultStatus.SUCCESS, content="结果文本",
                          tool_call_id="", tool_name=self.name)
```

### `ToolRegistry`

| 方法                                              | 说明                                           |
| :---------------------------------------------- | :------------------------------------------- |
| `register(tool)`                                | 注册工具（重名覆盖 + warning）                         |
| `unregister(name) -> bool` / `dispose() -> int` | 注销/清空（热更新/演进回滚基础）                            |
| `execute(call: ToolCall) -> ToolResult`         | 统一执行包裹：参数校验→灾难性安全→EXEC_MODE 分级→审批→瀑布→超时→五态回执 |
| `execute_many(calls) -> list[ToolResult]`       | 批量执行（只读并行/修改串行）                              |
| `schemas(lazy=False) -> list[dict]`             | 工具 schema 清单（lazy=索引模式省 token）               |
| `set_approval_callback(fn)`                     | 注入人工审批回调（EXEC_MODE 拦截项可终端确认）                 |

## 6. 消息模型（`llm_loop.core.message`）

- `Message(role, content, source, tool_call_id=None, tool_name=None, status=None, ...)`
- `MessageSource`：`USER` / `SYSTEM` / `TOOL`（如实标注来源）
- `ToolCall(id, name, arguments)`：工具声明（`tool_call_id` 由程序统一管理）
- `ToolResult` + `ToolResultStatus`（五态，见上）

## 7. Web 嵌入（`llm_loop.web`）

```python
from llm_loop.config import load_env_file, load_settings
from llm_loop.web import build_app

load_env_file()
app = build_app(settings=load_settings())   # FastAPI 应用（含鉴权/上传/SSE 全部端点）
# uvicorn.run(app, host="127.0.0.1", port=8902)
```

`build_app(settings=None, engine=None)`：双参数装配；`app.state.engine` 单实例。  
端点速览：`POST /api/v1/chat`（body: `{message, session_id?, model?}`）、  
`POST /api/v1/chat/stream`、`GET /api/v1/sessions`、`POST /api/v1/upload`、`GET /health`  
（鉴权：回环豁免 + `WEB_API_KEY` 远程强制）。Web 设置页的 Provider/模型控制面使用  
`GET/POST /api/v1/providers`、`PUT/PATCH/DELETE /api/v1/providers/{provider_id}`、  
`POST/PUT/DELETE /api/v1/providers/{provider_id}/models[/{model_id}]`、  
`PUT /api/v1/providers/{provider_id}/credential`、`POST /api/v1/providers/default-model`、  
`POST /api/v1/providers/discover-models`（短别名 `/discover`）、  
`POST /api/v1/providers/{provider_id}/test` 与 `POST /api/v1/providers/reload`；会话级模型  
覆盖走 `POST /api/v1/sessions/{session_id}/model`（body `{model: "provider/model" | null}`，  
`null` 清除覆盖回到默认）。Web 修改写入  
git-ignored `data/providers.local.json` 完整本机快照，不改 tracked `data/providers.json`；API Key  
只写本机 `.env`/进程环境且 API 永不回显明文。动态 Provider/模型可热重载并立即被会话选择；  
`POST /api/v1/providers/default-model` 现在**live 生效**：先原子写 `.env` 的 `LLM_MODEL`，再热切换  
`ModelClientPool` 运行态默认（先构造后提交；失败回滚 `.env`），下一次无会话覆盖的请求即使用新默认，  
`restart_required=false`；若 `LLM_MODEL` 由外部环境拥有则 runtime-only（`default.persistence="process"`，  
不写 `.env`，重启后由外部环境决定）。`PATCH /api/v1/providers/{id}` 接受  
`expected_version` + `enabled/default_model/display_name/timeout_s/...` 标量子集，不要求整包 body；  
409 冲突错误体附 `current_version`。模型输入接受配置事实 `name/note/input_modalities`（与 `multimodal`  
同步），运行时事实（`effective/credential_*`）仍被 422 拒绝（detail 数组含字段路径）。编辑/替换保留  
schema 外的未知字段（疑似密钥的未知键除外）；删除/停用承载配置默认或运行默认的 Provider/模型返回  
409（`default_provider_cannot_*` / `default_model_cannot_*`，先切换默认后可删）。写配置后 Registry  
重载失败时文件与内存 Registry 原子回滚到修改前。模型发现只返回候选不写配置（仅 `openai`/`anthropic`  
协议；10s 超时、2MB 响应上限、2000 候选上限、拒绝跨 host 重定向；错误只含类型/HTTP 状态/timeout  
类别，不反射密钥与响应体）。  
若 `MODEL_PROVIDERS` 环境变量存在，它保持最高优先级，Web 设置页只读且拒绝被遮蔽的写入。  
`GET /api/v1/models` 返回 `models`（当前有效 Registry 的可选模型）、`default`（当前 live 默认  
引用）、`current`（当前会话真实选择：会话覆盖优先，否则 live 默认）、`current_source`  
（`session`/`default`）、`current_available` 与机械 `catalog`（含 `display_name`/`provider_name`/  
`input_modalities` 等配置元数据）。Provider 被热停用/删除后不会改写会话选择；若 `current` 已不在  
有效 Registry，API 返回 `current_available=false` 且不把它伪装回 `models`，前端以“当前不可用”的  
禁用项显示。新会话只在上一共享会话的覆盖来源为真人显式选择（`model_override_source="user"`）时  
继承其模型覆盖；否则回落 live 默认。跨标签目录刷新：`GET /api/v1/events` SSE 在 Provider 配置  
指纹（配置版本 + live 默认 + registry 代数）变化时推送 `providers_updated` 事件。Provider 连接测试  
只返回连接成功/延迟，或安全的异常类型与可机械取得的 HTTP 状态/  
timeout 类别；provider/library 原始异常正文、URL 凭证、响应体不会回显。Provider JSON 与 `.env` 管理  
写操作使用同一 compare-and-write 锁，避免并发设置请求丢失更新。

**Headless 服务模式（B5）**：无 UI 纯 API 嵌入——示例 `examples/04_headless_service.py`  
（装配 + 同步/流式对话端点，约 20 行），核心是 `build_engine(load_settings())` 单实例 +  
`engine.run_single` / `engine.run_stream` 两个入口（签名快照测试锁定）。

## 8. CLI（`python -m llm_loop.cli`）

- 单条消息：`python -m llm_loop.cli "消息"`
- 交互模式：`python -m llm_loop.cli --interactive`
- 会话管理：`list` / `delete` / `archive` / `unarchive` / `search` / `extract`
- 演进审阅：`evolve-list` / `evolve-review` / `evolve-complete`
- 数据工具：`export-distill` / `event-*`（盘点/迁移/回放/对账/回滚/退役）

## 9. 扩展点速查（B 路线规划）

| 扩展面            | 入口                                                                                        |
| :------------- | :---------------------------------------------------------------------------------------- |
| 新 LLM Provider | Web 设置 `/api/v1/providers`（完整本机快照）或 `MODEL_PROVIDERS` 注册表 JSON + `llm_loop.llm.providers` |
| 新工具            | `ToolRegistry.register`（协议见 §5）                                                           |
| 语义检索           | `EMBEDDING_PROVIDER`（none/hash/api）+ `memory.retriever`                                   |
| 事件溯源           | `EVENT_LOG_ENABLED` + `event_log` 包                                                       |
| 人工审批           | `set_approval_callback`（CLI 交互模式已接线）                                                      |
| Skill 经验       | `EXPERIENCES_DIR` + `tools_skills`（SKILL.md 机制）                                           |
