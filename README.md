# LLM-First Core Loop

> **License**: [Apache-2.0](LICENSE) ｜ **Version**: 0.6.8 ｜ **状态**: 开源框架化（B 路线）进行中 ｜ **English**: [README.en.md](README.en.md)

大模型是核心，所有动作围绕大模型展开。架构核心 = **消息进 → 理解 → 行动 → 真诚回答 → 记住**。

程序是辅助大模型使用（及时反馈、如实反馈），不是约束大模型使用。大模型做对和出错都如实反馈；大模型可随时了解架构运行情况并自主修正。

**定位**：一个"AI 优先"（LLM-first）的 Agent 运行时（Harness）——程序最小化 + 文档规则驱动 + AI 自主演进闭环（自我评估 → 演进建议 → 人工审阅 → 分级执行 → 全链路审计）。三端接入（CLI / Web / 飞书桥），内置记忆、检索、事件溯源、评测体系。

## 架构原则（AI 视角）

- **程序最小化**：能由 AI 自主 + 文档规则（`docs/ai_rules.md`）实现的判断，尽量不用程序。程序只保留 AI 无法自完成的部分（工具真实执行、存储、灾难性安全硬边界）。
- **程序是便利与补充，不是约束**：工具成功/失败/异常如实构造（`[状态: xxx]` 标注），错误完整透传，不静默降级。
- **容错优先**：程序组件故障 → `[程序异常]` 如实告知 AI → 循环继续，不影响大模型发挥。
- **AI 自主规则**：诚实自查 / 参数自主规范 / 停滞自主调整 / 程序故障处理（见 `docs/ai_rules.md`，唯一规则真相源，内嵌于 system prompt）。

## AI 视角速读（T4，spec.md 5.3.1/5.5.1）

> 程序/文档规则/架构三者角色声明（AI 优先视角）：

- **程序 = 感官 + 手脚**：提供信息（`architecture_status` 感知上下文/模型/异常/待办）+ 执行通道（`adjust_strategy`/`retry_tool`/`switch_model` 等工具）+ 硬边界（灾难性安全/协议约束/存储）；不替 AI 思考、不替 AI 选择。
- **文档规则 = 大脑约束**：`docs/ai_rules.md` 为唯一规则真相源（SoT），RULE-AI-00~07 内嵌 system prompt，AI 自主遵守；程序不重复实现规则。
- **架构 = 服务于 AI 执行力发挥**：程序最小化（能 AI 自主 + 规则完成的不用程序），程序是便利与补充非约束，避免程序错误影响大模型。
- **硬约束不移交**：C1-C6 协议（tool_call_id 绑定等）/ FR-SAFE-01 灾难性安全 / 数据完整性仍由程序硬执行（AI 无法自完成），仅决策类判断移交 AI + 规则。

## 快速开始

```bash
# 1. 初始化
cd llm-first-loop
python3.13 -m venv .venv && .venv/bin/pip install -e ".[dev]"

# 2. 配置密钥（LLM_MODEL 缺省默认 deepseek-v4-flash，可不设）
export LLM_API_KEY=sk-xxx
export LLM_BASE_URL=https://api.deepseek.com/v1
# export LLM_MODEL=deepseek-v4-flash   # 可选: deepseek-v4-flash（默认）/ deepseek-v4-pro
# export LLM_THINKING_MODE=enabled     # DeepSeek V4 思考模式（默认开启）
# export LLM_REASONING_EFFORT=high     # 推理强度 low/high/max（默认 high）

# 3. 最小闭环：单条消息
.venv/bin/python -m llm_loop.cli "请读取 data/notes.txt 并总结内容"

# 4. 交互模式（--session 复用既有会话）
.venv/bin/python -m llm_loop.cli --interactive
.venv/bin/python -m llm_loop.cli --session <id> "继续对话"

# 5. 测试
.venv/bin/python -m pytest tests/ -q
```

## 功能

- **核心循环**：LoopEngine 五阶段状态机（消息进→理解→行动→真诚回答→记住）
- **严格 function calling**：tool_call_id 由程序统一管理，绝不产无 id 的 tool 消息（兼容 DeepSeek/OpenAI 严格 API）
- **架构自省**：LLM 可调用 `architecture_status` 查询架构运行状态，异常主动 `[架构上报]`，可用修正工具（adjust_strategy / retry_tool / refresh_config）自主修正
- **演进建议自动落地执行**（M12 深化 + M16/M17 审计）：AI 可 `submit_evolution` 提交架构演进建议（纯建议通道，回执含"等待 evolve-review 审阅"引导）；`EVOLVE_LOCAL_EXEC` 三级权限（0=仅建议 / 1=白名单局部执行 / 2=全面执行），人工 `evolve-review <id> accepted` 后按权限分级自动执行（状态推进 + 审计 + 执行引导）；**执行动作/验证/回滚由 AI 自主完成**（经修正工具 `adjust_strategy`/`retry_tool`/`refresh_config`，RULE-AI-06 子规则承载，程序不代 AI 执行/验证/回滚，verify_result=unverified 如实标注）；执行完成后 AI 经 `evolution_complete` 工具登记"已完成 + 验证结论"（executing→executed），涉边界演进经 CLI `evolve-complete` 人工登记（executor=human）；循环内存在 executing 演进时自动注入 `[演进执行提醒]`；全链路审计 `evolution_exec_log` 可检索
- **AI 自我评估与改进**（M12 深化 + M16 审计）：AI 可 `self_evaluate` 主动发起五维自我评估（成功率/工具效率/诚实性/停滞率/异常率，来源可溯，样本不足如实标注）；定期/里程碑触发仅提示不强制（异常触发时机交 AI 自主，RULE-AI-06）；评估结果落盘 `self_eval_log` 可检索；评估→建议双向溯源（`evidence="eval:SE-..."`），改进执行走同一权限分级，`SelfEvalComparison` 支持改进前后对比
- **信息不丢失**：上下文超长时另存压缩档案（`search_archive` 检索找回）；`search_records` 统一检索历史记录/记忆/档案（可查可检索）
- **记忆智能**：LLM 语义摘要（`SUMMARY_MODE`）、语义检索（`EMBEDDING_PROVIDER`）、独立记忆提取（会话结束/定期/手动）
- **多会话管理**：CLI 子命令 `list / delete / archive / unarchive / search / extract` + `--session` 复用
- **模型体系**（M47-M50）：`model_catalog` 查目录 / `switch_model` 自主切换（带 reason 审计落盘，AI 决策权）；Provider 注册表 + `MODEL_FALLBACKS` 应急降级链（仅默认装配模型失败时自动应急降级并如实标注，用户显式选择的模型不降级）；模型窗口自适应历史预算（按当前模型 context 收紧/放宽）
- **双端接入**（Web + 飞书桥）：Web 管理界面（FastAPI :8902）+ 飞书长连接桥；配置 `FEISHU_OWNER_OPEN_ID` 后两端共享同一会话（一端说话另一端可续聊同一上下文）；飞书桥内置假死防护（SDK 锁泄漏运行时修补 + 看门狗心跳 + 健康检查按心跳新鲜度判定）
- **蒸馏数据集导出**（export_distill，纯读只读薄壳）：`export-distill` 子命令把 `data/sessions/*.json` 会话轨迹导出为带思考链的 ReAct JSONL 蒸馏集 + 结构化统计报告——user 边界切分任务段 → `status=success` + 闭环完整性段级过滤（过滤原因分类计数）→ ReAct 三元组样本（thought/action/observation 与源逐字节一致，缺失思考链如实置 null）→ JSONL（`ensure_ascii=False` 超长不截断）+ 报告（通过+过滤=段总数闭环对账）；只产数据不训练、不切分/增强/脱敏；损坏文件 fail-open 如实标注跳过，输出已存在默认拒绝（`--force` 覆盖），源 session 文件只读零修改
- **事件源化单一真相源**（D1 事件日志）：`data/event_logs/<session_id>.jsonl` 事件日志作为轨迹单一真相源（5 类事件：session.created / message.appended / context.compressed / session.meta_changed / session.forked），运行期经 fail-open 钩子追加事件，`event-replay` 回放重建派生视图；`event-inventory` 只读盘点（哈希+mtime 零修改）→ `event-migrate` 从存量 session JSON 迁移生成事件日志（迁移前自动备份 `event_logs/_backup/<ts>/`，v3 旧会话缺省字段自动补默认，幂等二次迁移 0 迁移）→ `event-verify` 重放视图与源逐字段对账（差异如实标注）→ `event-rollback` 备份区逐字节恢复（`--remove-events` 还原事件日志）；`EVENT_LOG_ENABLED=0` 时事件写入零行为，三套存量存储保留双轨可对账
- **D1 后续批次**（d1_es_followup）：**D3 会话 fork**——`session-fork` / `POST /api/v1/sessions/{id}/fork` 触发事件日志物理复制继承（保留 type/ts/payload 重分配 seq/event_id/session_id）+ session.forked 事件承载 fork 元信息 + 源会话逐字节不变 + 新会话事件独立可 replay；**三套存储退役**——`event-retire` 编排（备份→双轨对账→归档 action_trace/session JSON→切读路径 `READ_PATH_SOURCE=event_log`）+ `event-retire-rollback` 逐字节恢复，对账全量通过方可切换（不一致不切换不退役）；**事件日志滚动**——多段目录 `<sid>/<segment_seq>.jsonl`（大小/天数/会话结束三触发条件）+ `event-rotate-status` 段清单 + 跨段 replay 逐字节一致 + 归档段只读；**D4 过滤钩子**——`EventStore.append` 入口 HookChain（filter 丢弃 / desensitize 脱敏 / transform 转换，按 priority 升序）+ 审计落盘 `_hook_audit.jsonl`（不含原始 payload 敏感内容）+ fail-open 异常不阻断 + `event-hooks` CLI（list/test）+ 钩子链默认空零行为零回归
- **灾难性安全**：唯一硬边界 = 不可逆删除/系统破坏，其余一切反馈放行；**已知灾难模式硬阻断 + 全量阻断审计**（`data/audit/safety_blocks.jsonl`）——判定前做 `$VAR`/`~` 展开 + 复合命令切分 + shell/python `-c` 载荷递归检查（拦截 rm -rf 根/主目录/系统目录、mkfs、dd 写块设备、fork bomb、curl 管道执行、写系统关键区、find -delete/-exec rm）；如实标注：非完备沙箱，更强隔离叠加 EXEC_MODE 分级与系统级沙箱
- **数据治理**（T3）：压缩档案分片（`ARCHIVE_SEGMENT_BYTES` 默认 100MB，超阈值开 `<sid>-N.jsonl` 新段，检索按段倒序 + sidecar 索引快速通道 + 全文补齐，limit 截断语义等价；存量无索引段全文扫描兜底）；飞书心跳历史轮转（`FEISHU_HEARTBEAT_HISTORY_MAX_MB`，超阈值 `.1` 保留 1 份）
- **人工审批流**（T5a）：EXEC_MODE 拦截项在 CLI 交互模式可经终端确认放行（`_cli_approval_prompt`，无终端 fail-closed 拒绝）；审批审计落盘 `data/audit/approval_audit.jsonl`（decision/tool/参数摘要，不含密钥）；灾难性安全硬阻断不可审批
- **symlink 写防护**（T5b）：edit_file 写路径含符号链接（自身/父目录）拒绝写入防越界（fail-closed + realpath 引导）；read_file 读 symlink 如实标注不拒绝
- **评测体系**（T4）：固定评测集 `tests/eval_sets/scenarios_v1.json`（6 场景，判定口径源自内部实证基线）+ 运行器 `scripts/run_eval.py`（真实 LLM / `--dry` 管道验证，判定 + Wilson CI + 报告落盘 `docs/metrics/`）+ CI nightly 自动运行
- **CI + 版本**（T7/B11）：GitHub Actions 三件套门禁（pytest/ruff/pyright）+ nightly 真实评测；语义化版本 v0.6.8；Release Drafter（PR 标题自动归类 changelog）+ tag 触发门禁复核 + Release 草稿（发布节奏制度化）
- **插件化 Skill**（B3）：`skills/<name>/SKILL.md` 目录自动扫描（`SKILLS_DIR`，默认 ./skills），AI 经 `skill_list`/`skill_load` 发现并加载外部技能执行——外部开发者零代码扩展框架能力；损坏/缺失文件 fail-open 跳过；仓库自带示例技能（`skills/`：notebook-session/incident-report）可直接 `skill_list` 发现体验
- **web_fetch SSRF 内网拦截**（HARNESS-03 + P0-2/P0-3 深化）：`WEB_FETCH_BLOCK_PRIVATE`（默认开）拦截私网/环回/链路本地/保留段地址（IP 字面量 + DNS 解析双路径），防云元数据等内网探测；命中返回 BLOCKED `[内网拦截]`；**重定向逐跳校验**（httpx/curl 均关闭自动跟随，手动循环上限 5 跳，每跳重新校验——公开 URL 302 跳内网不再泄漏）；**DNS rebinding 收窄**（curl `--resolve` 钉已校验 IP 预连接钉扎；httpx 连接后复核实际对端 IP，命中即丢弃——如实标注：httpx 通道 GET 已发出，防数据回读，更强隔离走 curl 钉扎通道）
- **上下文预算预警**（HARNESS-04）：上下文占用率 ≥80% 预算时注入一次 `[预算预警]`（含占用率/字符数），"压缩/收尾"决策归 AI——程序不自动压缩
- **孤儿 tool_calls 合成回执**（HARNESS-01）：`run_stream` 客户端中断时自动写「已取消」回执并立即保存，不产生「有声明无回执」的孤儿声明（严格 FC 协议 400 根源）
- **`request.meta` 事件**（HARNESS-02）：每轮 LLM 请求快照入事件日志（round/model/tools_count/history_chars/budget），回放可确知"当时用的哪个模型/挂了哪些工具"
- **Headless 服务模式**（B5）：无 UI 纯 API 嵌入——`examples/04_headless_service.py`（`build_engine` 单实例 + 同步/流式对话端点约 20 行）；公共 API 签名快照测试锁定（防语义漂移）
- **多 provider 成本路由增强**（B6）：`switch_model` 成功回执注入目标模型成本档（cost_tier）+ 能力语义（thinking/reasoning/long_context/multimodal）+ 上下文窗口（元数据缺失如实标注，判断归 AI）
- **评测集贡献指南**（B7）：`docs/eval_scenarios.md`——外部贡献者按 schema 新增场景约 30 分钟（判定注册 + dry 验证 + PR 验收清单）

## CLI 子命令

```bash
.venv/bin/python -m llm_loop.cli list                  # 列出会话（--archived 含归档）
.venv/bin/python -m llm_loop.cli delete <id> [--yes]   # 删除会话（须确认）
.venv/bin/python -m llm_loop.cli archive <id>          # 归档会话
.venv/bin/python -m llm_loop.cli unarchive <id>        # 取消归档
.venv/bin/python -m llm_loop.cli search <query>        # 检索会话
.venv/bin/python -m llm_loop.cli extract <id>          # 手动触发独立记忆提取
.venv/bin/python -m llm_loop.cli evolve-list [status]  # 列出演进建议（人工审阅入口）
.venv/bin/python -m llm_loop.cli evolve-review <id> <accepted|rejected>  # 审阅演进建议（accepted 且权限允许 → 自动执行）
.venv/bin/python -m llm_loop.cli evolve-complete <id> "<结果说明>"  # 人工完成登记（涉边界演进 → executed, executor=human）
.venv/bin/python -m llm_loop.cli export-distill [--input-dir DIR] [--output FILE] [--report FILE] [--force]  # 导出蒸馏数据集（薄壳只读，ReAct JSONL + 统计报告）
.venv/bin/python -m llm_loop.cli event-inventory [--event-logs-dir DIR]  # 事件日志盘点（只读，规模数字+割裂点，文件零修改）
.venv/bin/python -m llm_loop.cli event-migrate [--event-logs-dir DIR] [--force]  # 存量 session 迁移为事件日志（先备份 _backup/<ts>/，幂等）
.venv/bin/python -m llm_loop.cli event-verify [--all|--session ID] [--event-logs-dir DIR]  # 重放视图与源逐字段对账
.venv/bin/python -m llm_loop.cli event-rollback [--session ID] [--remove-events]  # 从备份区恢复源文件（可选移除事件日志）
.venv/bin/python -m llm_loop.cli session-fork --session <id> [--fork-point N] [--summary ...]  # 会话 fork（事件日志物理复制继承 + session.forked 事件）
.venv/bin/python -m llm_loop.cli event-retire [--data-dir DIR] [--force]  # 三套存储退役（备份→对账→归档→切读路径）
.venv/bin/python -m llm_loop.cli event-retire-rollback --data-dir DIR --backup-dir <dir>  # 退役回滚（逐字节恢复 + 读路径切回）
.venv/bin/python -m llm_loop.cli event-rotate-status [--data-dir DIR] [--session <id>]  # 事件日志滚动段清单
.venv/bin/python -m llm_loop.cli event-hooks [--data-dir DIR] {list,test}  # 过滤钩子管理（list 已注册 / test 示例事件）
.venv/bin/python -m llm_loop.cli --session <id> "消息"  # 复用会话继续对话
```

## 配置（.env.example 完整模板）

| 变量 | 默认 | 说明 |
|:---|:---|:---|
| `LLM_API_KEY` / `LLM_BASE_URL` | — | 必填 |
| `LLM_MODEL` | deepseek-v4-flash | 模型（缺省链: 显式 > OPENSYGAI_DEEPSEEK_DEFAULT_MODEL > 内置） |
| `LLM_THINKING_MODE` | enabled | DeepSeek V4 思考模式开关（非 DeepSeek 自动不发） |
| `LLM_REASONING_EFFORT` | high | 推理强度 low/high/max |
| `LLM_MAX_ITERATIONS` | 40 | 单次 run 最大循环轮数（工具密集任务可调大；达 80% 时注入 [轮数预警]，AI 可经 adjust_strategy 调大，硬上限 500） |
| `SUMMARY_MODE` | off | LLM 摘要: off/sync/async |
| `EMBEDDING_PROVIDER` | none | 语义检索: none/hash/api |
| `EXTRACT_ENABLED` | 1 | 独立记忆提取开关 |
| `VALIDATE_SEMANTIC` | 0 | 声明-回执语义匹配（默认关） |
| `EVOLVE_LOCAL_EXEC` | 0 | 演进执行权限三级: 0=仅建议/1=白名单局部执行/2=全面执行（旧布尔兼容） |
| `EVOLVE_EXEC_WHITELIST` | 空 | 执行白名单（级别 1 时，逗号分隔影响范围/模块/动作类型；空=未配置则不自动执行） |
| `SELF_EVAL_ENABLED` | 1 | 自我评估能力开关（self_evaluate 工具） |
| `SELF_EVAL_REMIND_ENABLED` | 1 | 触发提醒开关（仅提示不强制） |
| `SELF_EVAL_INTERVAL_ROUNDS` / `SELF_EVAL_MIN_SAMPLES` / `SELF_EVAL_SPAN` | 50/5/50 | 定期触发间隔/样本不足阈值/聚合窗口 |
| `SYSTEM_PROMPT_EXTRA` | — | 叠加自定义 AI 规则（程序最小化，无需改代码） |
| `HISTORY_MAX_CHARS` | 100000 | 提交给 LLM 的历史上下文预算（字符），默认 100K（≈50K tokens），可按模型窗口调整（1M 窗口模型可调大，小窗模型调小）；预算过高会撑爆窗口导致所有模型调用失败/超时 |
| `MODEL_FALLBACKS` | 空 | 降级链（逗号分隔 `provider/model`，如 `deepseek/deepseek-v4-flash,local/qwen3.6-27b-fable-fusion-711-uncensored-heretic-nm-dau-neo-max-mtp`）；空=不启用降级 |
| `EVENT_LOG_ENABLED` | 1 | 事件源化单一真相源开关（`data/event_logs/<session_id>.jsonl` 追加写；0=事件写入零行为） |
| `EVENT_LOGS_DIR` | 空 | 事件日志目录覆盖（空=从 data_dir 派生 `data/event_logs`） |
| `READ_PATH_SOURCE` | session_json | 读路径分派（session_json 既有 / event_log replay 重建） |
| `EVENT_LOG_ROTATE_BYTES` | 10485760 | 事件日志滚动大小阈值字节（0=禁用） |
| `EVENT_LOG_ROTATE_DAYS` | 30 | 事件日志滚动天数阈值（0=禁用） |
| `EVENT_LOG_ROTATE_ON_SESSION_END` | 1 | 会话结束时触发滚动 |
| `EVENT_HOOKS_CONFIG` | 空 | 过滤钩子配置文件路径（空=钩子链默认空零行为） |
| `ARCHIVE_SEGMENT_BYTES` | 104857600 | 压缩档案单文件分片阈值（默认 100MB；0=不分片；超阈值开 `<sid>-N.jsonl` 新段，检索按段倒序 + sidecar 索引快速通道） |
| `FEISHU_HEARTBEAT_HISTORY_MAX_MB` | 空 | 飞书心跳历史轮转阈值（MB；空=不限制；超阈值当前文件轮转为 `.1` 保留 1 份） |

> **配置加载（M63）**：CLI / Web / 飞书 三端统一从项目 `.env` 加载（环境变量优先）。
> 修改 `.env` 后：CLI 直接生效；web/feishu 执行 `bash scripts/restart_system.sh restart` 一键重启。

## 参与贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)（项目哲学/门禁/PR 流程）与 [CHANGELOG.md](CHANGELOG.md)（公开变更记录）。

## 文档

- 快速上手：`examples/`（01 最小 CLI 循环 / 02 Web 嵌入 / 03 自定义工具注册）
- 公共 API 参考：`docs/api.md`（装配/引擎/会话/工具/Web/CLI/扩展点）
- 配置参考：`docs/configuration.md`（分组配置表 + 常见坑速查）
- 事件溯源设计：`docs/event_sourcing.md`（单一真相源 + 迁移/回滚指南）
- 飞书渲染支持矩阵：`docs/feishu_render_matrix.md`（markdown 特性支持范围）
- 开发方法论：`docs/development_methodology.md`（SoT 先行/如实记录/零回归纪律）
- 评测集扩展指南：`tests/eval_sets/README.md`（场景 schema + 贡献步骤）
- 文档导航：`docs/INDEX.md`
- AI 自主规则（唯一规则真相源）：`docs/ai_rules.md`
- 开源框架化路线图：`docs/ROADMAP-B-20260814.md`
- 开发过程规格（spec/design/tasks）为本地 CodeArts 工作流文档，不随开源仓库分发
