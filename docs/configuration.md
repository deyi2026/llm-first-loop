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
| `LLM_TIMEOUT_S` | 120 | 单次 LLM 调用超时。**坑**：量化/大上下文模型生成慢，120s 可能不够（调大或用轻模型） |
| `LLM_THINKING_MODE` | enabled | 思考模式（非 DeepSeek 自动不发） |
| `LLM_REASONING_EFFORT` | high | 推理强度 low/high/max |

## 三、上下文与历史

| 变量 | 默认 | 说明 / 坑 |
|:---|:---|:---|
| `HISTORY_MAX_CHARS` | 100000 | 提交给 LLM 的历史预算（字符 ≈ 50K tokens）。**坑**：1M 会撑爆窗口导致所有调用失败（已收敛 100K）；1M 窗口模型可调大，小窗模型调小 |
| `REASONING_TAIL` | 2 | 提交历史中保留最近 N 轮思考链（更早省略，可 search_records 回溯） |
| `TOOL_TRIM_ENABLED` | 1 | 旧 tool 消息分层降级（超阈值→首尾摘要+归档检索指引） |
| `TOOL_TRIM_THRESHOLD` / `TOOL_TRIM_AGE` | 2000 / 0 | 降级阈值（字符）/ 年龄（距最新消息条数） |
| `TOOL_MAX_OUTPUT_CHARS` | 100000 | 工具输出上限（超出→另存档案+截断标注，信息可检索找回） |

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
| `VALIDATE_SEMANTIC` / `VALIDATE_SEMANTIC_THRESHOLD` | 0 / — | 声明-回执语义匹配（默认关） |
| `SELFHEAL_MAX_ATTEMPTS` / `SELFHEAL_MAX_PER_ROUND` | 3 / 2 | 自愈尝试预算 |
| `PARAM_ADJUST_PER_ROUND` | 2 | 每轮参数调整频次上限（PARAM-03） |
| `SYSTEM_PROMPT_EXTRA` | — | 叠加自定义 AI 规则段（无需改代码） |

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
| `WEB_HOST` / `WEB_PORT` | 127.0.0.1 / 8902 | 绑定地址 / 端口 |
| `SESSION_CONCURRENCY_LOCK` | 1 | 会话级并发锁（0=无锁） |
| `LONG_LINE_THRESHOLD` / `LONG_CHAR_THRESHOLD` | — | 长内容折叠阈值（前端展示） |

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

---

## 常见坑速查

1. **所有模型调用失败/超时** → 查 `HISTORY_MAX_CHARS` 是否超过模型窗口（默认 100K 安全）。
2. **"经常到轮数上限"** → `LLM_MAX_ITERATIONS` 调大（默认 40；AI 也会在 80% 时收到 `[轮数预警]` 并可自行调大）。
3. **AI 无法执行命令** → 检查是否显式设置了 `EXEC_MODE`（readonly/blocked 会拦；默认不设=不拦）。
4. **AI 能主动发飞书消息？** → 不会：`FEISHU_OUTBOUND_ENABLED` 默认 false（安全边界）。
5. **改了 .env 没生效** → web/feishu 需要 `bash scripts/restart_system.sh restart`（CLI 免重启）。
6. **AI 调参不生效** → `adjust_strategy` 白名单仅限 max_iterations/timeout_s/history_budget/memory_top_k/extract_interval_msgs/retrieve_semantic_top_k，且受 `PARAM_ADJUST_PER_ROUND` 与全局硬上限约束。
