# 工具与规则稳定度契约（EVO-20261014-483ca6de #4）

目的：把「harness 可单方面变更哪些运行时行为」显式化，让模型与维护者对同一份分层有一致预期。本文档是元数据/文档层标注；不改变任何工具 schema 文案（见文末准入门说明）。

## 分层定义

- **stable**：行为契约冻结。变更须走演进审批；破坏性变更须有迁移期与双重回执（参照 v2.1.288 先例）。
- **experimental**：harness 可单方面变更（含回执字段增减、语义微调），不保证跨会话完全一致；变更尽量在 docs/CHANGES-\* 公告。模型依赖此类工具时应在关键路径预留降级/重试判断。
- **EARLY ACCESS**：experimental 且明确「可能撤回或重写」。依赖它的工作流必须自带降级路径，不得作为唯一承重面。

## 当前分层（登记于 2026-10-14，随演进更新）

| 层 | 工具/机制 | 说明 |
| --- | --- | --- |
| stable | execute_command、read_file、edit_file（file_contract v1）、get_goal、task_*、wait（租约语义） | 文件契约与任务图语义冻结；变更须演进审批 |
| experimental | browser_perceive / browser_operate | 寻址三选一 + name_normalized 归一键（EVO-20261010）；对象投影/回执形态可调 |
| experimental | read_evidence / search_evidence / list_evidence | 每页最多 4000 投影、单次检索 ≤20 条；分页回执形态可调（applied_limit/bounded_by_server_max/next_start 已契约锁定） |
| experimental | agent_followup / subagent_* / spawn_subagent | ≤2 次/child、≤4 次/parent/15min、租约累计 ≤600s；回执自带 used/ceiling（已测试锁定） |
| experimental | service_control | publish 的 CAS+generation 门、restart desired-state 语义可演进 |
| experimental | schedule / escalation 闭环 / source_synopsis / method_manage / refine_experience / search_records 卡片形态 | 回执与卡片字段可演进 |
| EARLY ACCESS | fix_loop、workflow_run、dsh_task（report_format）、browser_perceive 的 vision 投影 | 可能撤回或重写；工作流须自带降级路径 |

规则条目：docs/ai_rules.md 为唯一 SoT（RULE-AI-00..32，截至 2026-10-14），版本化演进；规则可经 search_records(kind=rule) 按需水合——可检索 ≠ 可注入（L2-2）。

## 本轮为何不触发 L2-2/L2-6 准入门（ELIG 说明）

- **#1 RULE-AI-30** 落在 docs/ai_rules.md（SoT 文档，非 universal prompt；tests/unit/test_ai_rules_sync.py 锁定规则不回注 prompt）→ 本轮无 prompt 表面字节变化。
- **#4 本文件** 仅是元数据/文档层标注，不修改任何工具 schema description 文案 → 同样无 prompt 表面字节变化。
- **未来把稳定度标注写入工具 schema description（模型每轮可见）时**：须按 docs/analysis/ELIG-20261003-\* 先例，先补 L2-2/L2-6 eligibility 说明与弱模型档（cognilocal / qwen3.8-flash-next）身份轮+任务轮行为对照，确认无劣化后方可上线。该启用路径本文显式登记，防止静默生效。
