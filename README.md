# LLM-First Core Loop

大模型是核心，所有动作围绕大模型展开。架构核心 = **消息进 → 理解 → 行动 → 真诚回答 → 记住**。

程序是辅助大模型使用（及时反馈、如实反馈），不是约束大模型使用。大模型做对和出错都如实反馈；大模型可随时了解架构运行情况并自主修正。

## 架构原则（AI 视角）

- **程序最小化**：能由 AI 自主 + 文档规则（`docs/ai_rules.md`）实现的判断，尽量不用程序。程序只保留 AI 无法自完成的部分（工具真实执行、存储、灾难性安全硬边界）。
- **程序是便利与补充，不是约束**：工具成功/失败/异常如实构造（`[状态: xxx]` 标注），错误完整透传，不静默降级。
- **容错优先**：程序组件故障 → `[程序异常]` 如实告知 AI → 循环继续，不影响大模型发挥。
- **AI 自主规则**：诚实自查 / 参数自主规范 / 停滞自主调整 / 程序故障处理（见 `docs/ai_rules.md`，唯一规则真相源，内嵌于 system prompt）。

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
- **灾难性安全**：唯一硬边界 = 不可逆删除/系统破坏，其余一切反馈放行

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
.venv/bin/python -m llm_loop.cli --session <id> "消息"  # 复用会话继续对话
```

## 配置（.env.example 完整模板）

| 变量 | 默认 | 说明 |
|:---|:---|:---|
| `LLM_API_KEY` / `LLM_BASE_URL` | — | 必填 |
| `LLM_MODEL` | deepseek-v4-flash | 模型（缺省链: 显式 > OPENSYGAI_DEEPSEEK_DEFAULT_MODEL > 内置） |
| `LLM_THINKING_MODE` | enabled | DeepSeek V4 思考模式开关（非 DeepSeek 自动不发） |
| `LLM_REASONING_EFFORT` | high | 推理强度 low/high/max |
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

## 文档

- 需求规格：`.codeartsdoer/specs/llm_first_loop/spec.md`
- 实现方案：`.codeartsdoer/specs/llm_first_loop/design.md`
- 任务规划：`.codeartsdoer/specs/llm_first_loop/tasks.md`
- AI 自主规则（唯一规则真相源）：`docs/ai_rules.md`
- 审查基线：`docs/ai_first_review.md`（AI 视角）/ `docs/program_minimalism_review.md`（程序最小化）/ `docs/m11_audit_report.md`（M11 审计）
- 变更记录：`docs/CHANGES.md`
