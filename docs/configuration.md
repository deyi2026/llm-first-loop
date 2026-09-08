# 配置参考（Configuration）

> 全量模板见 `.env.example`（190 行，含逐项注释）。本文档按功能分组整理：
> 默认值 / 说明 / 常见坑。**配置加载规则（M63）**：CLI / Web / 飞书三端统一从项目
> 根 `.env` 加载，**环境变量优先**（`.env` 不覆盖已设置的 env）；修改 `.env` 后
> CLI 直接生效，web/feishu 执行 `bash scripts/restart_system.sh restart`。

---

## 一、必填（3 项）

| 变量 | 默认 | 说明 |
|:---|:---|:---|
| `LLM_API_KEY` | — | 模型 API Key（密钥仅 env，不入库/日志/审计） |
| `LLM_BASE_URL` | — | API 端点，如 `https://api.deepseek.com/v1` |
| `LLM_MODEL` | deepseek-v4-flash | 缺省链: 显式 > `OPENSYGAI_DEEPSEEK_DEFAULT_MODEL` > 内置 |

## 二、循环控制

| 变量 | 默认 | 说明 / 坑 |
|:---|:---|:---|
| `LLM_MAX_ITERATIONS` | 40 | 单次 run 最大循环轮数。**坑**：工具密集任务（读→改→验证）20 轮常触顶（2026-08-14 已 20→40）；达 80% 时程序注入 `[轮数预警]`，AI 可经 adjust_strategy 调大（白名单，硬上限 500） |
| `EXEC_SANDBOX` | none | bash 沙箱（P3-3）：`bwrap`=bubblewrap 隔离 execute_command（只读系统目录/独立命名空间/工作区可写，回执如实标注）；显式开启而 bwrap 缺失 → fail-closed 命令不执行；空=none 不启用 |
| `LLM_WIRE_PROTOCOL` | openai | 默认 client 线协议（P3-5）：openai / anthropic / google；provider 模型条目可用 `wire_protocol` 元数据逐模型覆盖 |
| `MCP_SERVERS` | — | MCP stdio 服务器 JSON 数组（P3-1）：`[{"name": "fs", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"]}]`；工具以 `mcp.<server>.<tool>` 名注册（schema 透传、五态包装、超时/审计复用；单服务器失败 fail-open） |
| `WEB_VISION_BACKEND` | provider | 图片识别后端：provider（默认，注册表 multimodal 模型，如 Kimi k3）/ arkcli（团队多模态工具，需 `arkcli auth` 登录）/ minimax（旧路径，仅显式 opt-in） |
| `WEB_VISION_MODEL` | — | 视觉模型指定：`provider/model`（如 `kimi/k3`）；缺省扫描注册表首个 multimodal 模型 |
| `LLM_MAX_TOKENS` | 8192 | 单次 LLM 输出预算（token）。思考链模型思考也占此预算——默认 4096 时思考占大半、最终分析被截断（2026-08-15 现场）。**provider 级覆盖**：`data/providers.json` 条目加 `"max_tokens": 16384`（长分析模型放大） |
| `LLM_TIMEOUT_S` | 120 | 单次 LLM 调用超时。**坑**：量化/大上下文模型生成慢，120s 可能不够（调大或用轻模型）。**provider 级覆盖**：在 `data/providers.json` 的 provider 条目加 `"timeout_s": 600`（本地慢模型专用，云端不放大）；未配置时用全局值 |
| `LLM_THINKING_MODE` | enabled | 思考模式（非 DeepSeek 自动不发） |
| `LLM_REASONING_EFFORT` | high | 推理强度 low/high/max |

## 三、上下文与历史

| 变量 | 默认 | 说明 / 坑 |
|:---|:---|:---|
| `HISTORY_MAX_CHARS` | 100000 | 提交给 LLM 的历史预算（字符 ≈ 50K tokens）。**坑**：1M 会撑爆窗口导致所有调用失败（已收敛 100K）；1M 窗口模型可调大，小窗模型调小。**provider 级覆盖**：在 `data/providers.json` 的 provider 条目加 `"history_budget_chars"`——本地慢模型用 `12000`（prefill 成本随上下文线性涨，收紧预算显著缩短首 token 时延）；deepseek 用 **`150000`**（2026-08-24 校准：大上下文流式断连根因修复，见「常见坑速查」第 2 条）；旧历史经压缩归档可检索，信息零丢失；未配置时用全局值 |
| `REASONING_TAIL` | 2 | 提交历史中保留最近 N 轮思考链（更早省略，可 search_records 回溯） |
| `TOOL_TRIM_ENABLED` | 1 | 旧 tool 消息分层降级（超阈值→首尾摘要+归档检索指引） |
| `TOOL_TRIM_THRESHOLD` / `TOOL_TRIM_AGE` | 2000 / 0 | 降级阈值（字符）/ 年龄（距最新消息条数） |
| `TOOL_MAX_OUTPUT_CHARS` | 100000 | 工具输出上限（超出→另存档案+截断标注，信息可检索找回） |
| `TOOL_SUMMARY_THRESHOLD` | 12000 | 工具输出分层阈值（超出→首/尾各 2500 字符摘要注入 + 原文另存可检索 + 提炼要点行动指引；v0.5.0 由 5000 放大） |
| `EVIDENCE_MODE` | off | Evidence Recoverability v1.1 rollout：`off`=旧链路零行为；`shadow`=工具投影前 observation 双写入 `DATA_DIR/evidence/`，**不改变模型可见 prompt/tool result**；`enforce`=Phase3 capture-before-projection + bounded evidence capsule，当前仅用于离线/受控验证；Phase4 `read/search/list_evidence`、Phase5 compression/provider-neutral Recovery Manifest、Phase6 legacy ownership/quarantine/refcount GC 与 Phase7 Full-R0 aggregate gate 均已完成，**Full R0 deterministic PASS**。但当前 `TOOL_PIPELINE_ENABLED=1` 与 enforce 组合仍 fail-closed；按冻结设计继续 R1 historical replay / R2 provider confirmation 后再决定生产 enforce。推荐 rollout 为 `off -> shadow -> enforce`。此外当前 `TOOL_PIPELINE_ENABLED=1` 与 enforce 组合会 fail-closed，需先定义 post-hook/capsule 顺序。shadow/enforce 都未在 `.env` 默认开启 |
| `EVIDENCE_MANIFEST_LIMIT` | 8 | Evidence enforce 每轮从 durable Ledger 再生的 Recovery Manifest 条目上限；运行时钳制 1..20。Manifest 走动态尾部，不进入 system/tools 稳定前缀。 |
| `FALLBACK_NOTICE_COOLDOWN_S` | 86400 | 模型降级提示限频（2026-08-16，EVO-20260816-37633629③）：同一降级对（from→to）的主消息流提示在该间隔内只注入一次（nudge without nagging）；仅抑制消息注入，status/审计/action_trace 每次照常记录；0=关闭限频。stamp 落盘 `<data_dir>/state/fallback_notice_stamps.json` |

## 四、记忆与检索

| 变量 | 默认 | 说明 |
|:---|:---|:---|
| `SUMMARY_MODE` | off | LLM 摘要: off/sync/async（async 仅回填档案 summary，不注入决策上下文） |
| `SUMMARY_MODEL` | 空 | 独立摘要模型（`provider/model`；成本隔离；未配置回退主模型） |
| `SUMMARY_TIMEOUT_S` / `SUMMARY_MAX_INPUT_CHARS` | 30 / 100000 | 摘要超时与输入预算 |
| `EMBEDDING_PROVIDER` | none | 语义检索: none（纯关键词）/ hash（本地 n-gram 向量，零依赖）/ api（OpenAI 兼容端点） |
| `EMBEDDING_BASE_URL` / `EMBEDDING_MODEL` / `EMBEDDING_API_KEY` / `EMBEDDING_DIM` | — / — / — / 128 | api provider 端点与维度 |
| `RETRIEVE_TIMEOUT_S` / `RETRIEVE_SEMANTIC_TOP_K` | 1.0 / 20 | 语义检索超时 / 召回上限 |
| `MEMORY_TOP_K` | 5 | 每轮记忆注入条数（auto-adaptive: 上下文占用 >70%→8 / <30%→3） |
| `EXTRACT_ENABLED` | 1 | 独立记忆提取开关 |
| `EXTRACT_INTERVAL_MSGS` / `EXTRACT_COOLDOWN_S` | 20 / 600 | 提取触发间隔（消息数）/ 冷却 |
| `EXTRACT_MAX_INPUT_CHARS` / `EXTRACT_TIMEOUT_S` | 100000 / 60 | 提取预算 |
| `MEMORY_MAX_ENTRIES` | 0 | 记忆条目上限（0=不限；超限淘汰 decay 最低） |

## 五、压缩档案（数据治理）

| 变量 | 默认 | 说明 |
|:---|:---|:---|
| `ARCHIVE_MAX_ENTRIES` | 0 | 单会话档案条目上限（0=不限；启动 GC） |
| `ARCHIVE_TTL_DAYS` | 0 | 条目存活天数（0=不限） |
| `ARCHIVE_SEGMENT_BYTES` | 104857600 | 单文件分片阈值（100MB；超阈值开 `<sid>-N.jsonl` 新段；检索按段倒序 + sidecar 索引） |
| `AUDIT_TTL_DAYS` | 30 | 审计 JSONL 清理天数 |

## 六、架构自省 / 演进 / 自我评估

| 变量 | 默认 | 说明 |
|:---|:---|:---|
| `SELF_INSPECTION_ENABLED` | 1 | architecture_status 工具开关 |
| `STATUS_REPORT_COOLDOWN_S` | 60 | `[架构上报]` 推送冷却 |
| `EVOLVE_ENABLED` | 1 | 演进建议通道 |
| `EVOLVE_LOCAL_EXEC` | 0 | 演进执行权限: 0=仅建议 / 1=白名单局部执行 / 2=全面执行 |
| `EVOLVE_EXEC_WHITELIST` | 空 | 级别 1 的执行白名单（逗号分隔；空=不自动执行） |
| `SELF_EVAL_ENABLED` / `SELF_EVAL_REMIND_ENABLED` | 1 / 1 | 自我评估开关 / 提醒开关 |
| `SELF_EVAL_INTERVAL_ROUNDS` / `SELF_EVAL_MIN_SAMPLES` / `SELF_EVAL_SPAN` | 50 / 5 / 50 | 评估触发间隔 / 样本阈值 / 聚合窗口 |
| `METHOD_REFLECTION_MODE` | off | Method post-run reflection：off/auto；auto 仅在 final 已确定后按机械 friction 触发，失败不影响原任务 |
| `METHOD_REFLECTION_MIN_ROUNDS` / `METHOD_REFLECTION_MIN_TOOLS` / `METHOD_REFLECTION_MIN_FAILURES` | 6 / 6 / 2 | auto 模式 friction 触发阈值 |
| `METHOD_REFLECTION_TIMEOUT_S` | 120 | reflection 单次模型调用超时（秒） |
| `VALIDATE_SEMANTIC` / `VALIDATE_SEMANTIC_THRESHOLD` | 0 / — | 声明-回执语义匹配（默认关） |
| `SELFHEAL_MAX_ATTEMPTS` / `SELFHEAL_MAX_PER_ROUND` | 3 / 2 | 自愈尝试预算 |
| `PARAM_ADJUST_PER_ROUND` | 2 | 每轮参数调整频次上限（PARAM-03） |
| `SYSTEM_PROMPT_EXTRA` | — | 叠加自定义 AI 规则段（无需改代码） |
| `RUN_MODE` | standard | 运行模式（A1 文档化，2026-08-14）: **standard** 全工具集（默认）/ **ptc** 程序化工具调用强化（web 类工具默认降级，命令执行为主；playwright 隐藏——EVO-20260816-96215428 注册层门控，浏览器执行类仅 standard/creative 可见）/ **minimal** 精简工具集（只读+必要执行，web/飞书/playwright 等外围禁用）/ **creative** 宽松默认参数（超时×1.5、输出×2）。弱模型选 minimal 减小工具选择压力；工具密集任务选 ptc；非法值回退 standard |

## 七、安全与执行

| 变量 | 默认 | 说明 / 坑 |
|:---|:---|:---|
| `EXEC_MODE` | 空（不启用） | 命令分级: readonly（只读放行）/ allowlist（前缀白名单）/ blocked（全禁）。**坑**：显式设置后未匹配规则即拒绝（fail-closed）；默认不设=AI 可执行任意 shell（仅灾难性硬阻断） |
| `EXEC_ALLOWLIST` | 空 | allowlist 模式的前缀白名单 |
| `TOOL_TIMEOUT_S` | 60 | 工具执行超时 |

## 八、Web

| 变量 | 默认 | 说明 |
|:---|:---|:---|
| `WEB_API_KEY` | 空 | 远程访问令牌（回环默认豁免；远程绑定未配置 key → 启动报错） |
| `WEB_AUTH_REQUIRE` | 0 | 1=回环也强制令牌；**fail-closed**：设为 1 但未配置 WEB_API_KEY → 启动拒绝 + 请求 503（v0.5.0 起，不再静默放行）。回环豁免部署下 mutating 端点自带 Origin 跨站写防护（非回环来源 403） |
| `WEB_HOST` / `WEB_PORT` | 127.0.0.1 / 8902 | 绑定地址 / 端口 |
| `SESSION_CONCURRENCY_LOCK` | 1 | 会话级并发锁（0=无锁） |
| `WEB_FETCH_BLOCK_FAKE_IP` | 0 | web_fetch 代理假 IP 段（198.18/15，Surge/Clash fake-ip）严格拦截开关；默认 0=放行+回执如实标注（真实连接由代理通道完成），1=严格拦截 |
| `LONG_LINE_THRESHOLD` | 200 | 长内容分块粒度（前端展示；v0.5.2 起回复不折叠，超长代码块按 200 行/段顺序分段全量展示） |
| `FEISHU_CROSS_SYNC` | 1 | 飞书 ← Web 跨端同步（2026-08-15）：Web 侧对映射会话（含 owner 共享当前会话）的新增消息实时推送到飞书聊天；0=关闭。轮询 1.5s、推送最小间隔 3s、单条上限 10000 字、超出分段显示（i/N，信息零丢失不截断，2026-08-16）（`FEISHU_CROSS_SYNC_POLL_S` / `_MIN_INTERVAL_S` / `_MAX_CHARS` 可调，启动时装配需重启） |
| `FEISHU_FOLD_LONG_REPLY` | 0 | 飞书长回复折叠选择加入（1=恢复旧折叠行为：摘要卡+「展开全文」取回；默认 0=不折叠全量分段推送） |

## 九、飞书桥

| 变量 | 默认 | 说明 |
|:---|:---|:---|
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | — | 飞书应用凭证（env 或 `.feishu.env`） |
| `FEISHU_WS_ENABLED` | 1 | 长连接开关 |
| `FEISHU_OWNER_OPEN_ID` | 空 | 跨端共享会话（owner 私聊与 Web 同上下文） |
| `FEISHU_TYPING_ACK` / `FEISHU_STREAMING` | 1 / 1 | 处理中动作显示（Typing 回执 / 流式状态卡） |
| `FEISHU_OUTBOUND_ENABLED` | false | **AI 主动出站飞书**（涉安全边界，默认禁用；须显式 true） |
| `FEISHU_OUTBOUND_ALLOWED_USERS` | 空 | 出站白名单（空=全部拒绝） |
| `FEISHU_OUTBOUND_RATE_PER_MIN` | 5 | 出站速率限制（防风暴） |
| `FEISHU_HEARTBEAT_HISTORY_MAX_MB` | 空 | 心跳历史轮转阈值（空=不限制；超阈值 `.1` 保留 1 份） |

## 十、事件溯源（D1）

| 变量 | 默认 | 说明 |
|:---|:---|:---|
| `EVENT_LOG_ENABLED` | 1 | 事件日志开关（0=写入零行为） |
| `EVENT_LOGS_DIR` | 空 | 目录覆盖（空=从 data_dir 派生） |
| `READ_PATH_SOURCE` | session_json | 读路径分派（session_json / event_log replay） |
| `EVENT_LOG_ROTATE_BYTES` / `EVENT_LOG_ROTATE_DAYS` / `EVENT_LOG_ROTATE_ON_SESSION_END` | 10MB / 30 / 1 | 事件日志滚动 |
| `EVENT_HOOKS_CONFIG` | 空 | 过滤钩子配置（filter/desensitize/transform；空=零行为） |

## 十一、数据与目录

| 变量 | 默认 | 说明 |
|:---|:---|:---|
| `DATA_DIR` | ./data | 运行时数据根（会话/记忆/审计/事件日志） |
| `DOCS_DIR` | ./docs | search_docs 扫描目录（*.md） |
| `SKILLS_DIR` | ./skills | 插件化 Skill 目录（skills/<name>/SKILL.md；不存在=零行为） |
| `METHOD_SEED_DIR` | ./methods | reviewed Method/Teacher seed 资产目录（tracked） |
| `METHODS_DIR` | ./data/methods | runtime-learned Method candidate/lifecycle 状态目录（默认被 data/ 忽略，不自动发布） |

---

## 认知运行时（Cognitive Runtime · CR-R1）

| env | 默认 | 说明 |
|---|---|---|
| COG_RUNTIME_MODE | shadow | 三态：off=语义分支整体短路（纯旧行为）；shadow=与 enforce 同构执行 load/Read Barrier/compile/telemetry（含零槽安静轮）但 packet 不进 prompt；enforce=同一 packet 进入 prompt（前置条件：`tests/unit/test_cr_r1_invariants.py` 不变量 CI 全绿；非法值回退 shadow） |
| COG_RUNTIME_PACKET_BUDGET | 2000 | decision packet 预算（chars）；超预算降级 HOT-only（compiler 既有降级路径，telemetry 记 tier_degraded） |
| COG_RUNTIME_TELEMETRY | 0 | cognitive_telemetry.jsonl 事件流开关（state_rebuild/packet_compile/tier_degraded；session/round/goal/revision 可归因，run_id 无运行时来源时诚实留空） |
| COG_RUNTIME_TIER_ENABLED | 1 | tier 分级聚合：HOT 原文 inline / WARM compact_repr（原文零 inline）/ COLD 仅 evidence ref（raw=0）；=0 回退平铺原行为 |
| COG_RUNTIME_ANCHOR_MODE | auto | semantic=语义投影替代锚点 / anchor=旧行为 / auto=投影可用则替代否则回退 |

- **信封分片**：`data/audit/cognitive/state.<sha16>.yaml`（`sha16=sha256(session_id)[:16]`，schema v2 身份头）；读取后再次校验 envelope `session_id`，不匹配视为 `STALE_UNTRUSTED`。
- **Read Barrier**：按 strict-session 读取 GoalStore，并核验 session_id + goal_id + goal_updated_at + 最近 checkpoint_ts；信封缺失/STALE/不一致且本会话 Goal 可安全确认时首轮即 rebuild + 回存；无法确认才宁缺勿错。
- **冷启动**：active Goal 已存在而信封缺失时，shadow/enforce 首轮都会经 Read Barrier 建立可信信封；enforce 首轮即可投影 header，shadow 仅计算与记录 telemetry、不修改 prompt。

## 常见坑速查

1. **所有模型调用失败/超时** → 查 `HISTORY_MAX_CHARS` 是否超过模型窗口（默认 100K 安全）。
2. **deepseek 流式断连 `peer closed connection (incomplete chunked read)`（"出错了"）** → 大上下文（150K+ 字符）下 deepseek 服务端流式偶发不稳（2026-08-24 实测：150K-230K 字符会话 0 压缩、多次断连、单轮 50 万+ tokens 白烧）。修复：`data/providers.json` deepseek 条目 `history_budget_chars` 保持 **150000**（≈75K tokens）——80% `[预算预警]` 与 90% 程序兜底压缩自动前移到 ~120K/~135K 字符，载荷被约束在失效线以下；另有断连自动重试（`LLM_RETRY_DISCONNECT`，默认 1 次，仅在尚无输出已产出时重试）。**教训**：预算不是越大越好——它同时决定"何时预警/何时兜底压缩"，须落在模型服务端稳定区间内；压缩断缓存是物理必然，但断连白烧更贵。
3. **本地模型（LM Studio/Ollama）调用超时 `LLM 请求超时（120.0s）`** → 本地大模型 prefill 慢（27B 量化实测 ~5s/千字，40K 字上下文首 token 需 200s+），120s 必然超时。三步：① `data/providers.json` 的 `local` 条目设 `"timeout_s": 600` + `"history_budget_chars": 12000`（已默认配置，后者把发给本地模型的历史压到 ~12K 字符≈9K tokens，prefill 降到 1-2 分钟内）；若仍报 120s（而非 600s），说明请求未走 providers.json 的 `local` 条目（如用 `LLM_BASE_URL` 直配的默认通道）——请在模型下拉/`/model` 目录里选 `local/qwen3.6-…` 走注册表路径（600s 生效），或直接调大 `LLM_TIMEOUT_S`；② 控制上下文——本地模型窗口小（如 131K tokens），大会话需先压缩/新开会话；③ 仍慢则换更小模型（如 9B Q4）。`[预算预警]` 的占用率统计的是**实际发送载荷**（已压缩归档的历史不计入），数字可信。
3. **"经常到轮数上限"** → `LLM_MAX_ITERATIONS` 调大（默认 40；AI 也会在 80% 时收到 `[轮数预警]` 并可自行调大）。
4. **AI 无法执行命令** → 检查是否显式设置了 `EXEC_MODE`（readonly/blocked 会拦；默认不设=不拦）。
5. **AI 能主动发飞书消息？** → 不会：`FEISHU_OUTBOUND_ENABLED` 默认 false（安全边界）。
6. **改了 .env 没生效** → web/feishu 需要 `bash scripts/restart_system.sh restart`（CLI 免重启）。
7. **AI 调参不生效** → `adjust_strategy` 白名单仅限 max_iterations/timeout_s/history_budget/memory_top_k/extract_interval_msgs/retrieve_semantic_top_k，且受 `PARAM_ADJUST_PER_ROUND` 与全局硬上限约束。
