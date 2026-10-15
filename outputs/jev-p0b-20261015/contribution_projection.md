# P0b 复用链只读贡献投影（一条 run）

- run_ref: `de7f7e47-443e-42f9-9513-57ee99c8a21e:turn:27:run:058dc3b808c543eeb2398a817e69d1fc`
- contribution_id: `contribution:b02593f4eec54b63` / schema `knowledge-contribution/v1`
- 归属 session: `de7f7e47-443e-42f9-9513-57ee99c8a21e`（task_id / goal_id：事件层缺失，保留 null）
- seq 509–812 / 2026-10-12T23:30:56.856751+08:00 → 2026-10-12T23:35:00.658261+08:00
- 事件 8 条，来源文件 ['de7f7e47-443e-42f9-9513-57ee99c8a21e.jsonl']
- terminal_event_ref: `event:119bac6e-181a-4995-9247-396e22722458`
- task_outcome: `unknown`；contribution_state: `unclear`

## 1. §5.3 contributions[]

| subject_ref | kind | use_decision | authority | hydration | helped | attribution_level | evidence_refs |
|---|---|---|---|---|---|---|---:|
| `method:locate-project-env-before-symptom-workarounds-f7dd29f1718b` | method | applied | None | False | **unclear** | insufficient | 2 |
| `experience:EXPERIENCE-20260909-lfl-llm-pytest-tail` | experience | applied | model_declared | True | **unclear** | insufficient | 1 |
| `experience:EXPERIENCE-20260909-lfl-shell-pytest-web-auth-require-web-origin-allow` | experience | applied | model_declared | True | **unclear** | insufficient | 1 |

## 2. 呈现 / 声明 的四分

- presented_without_declaration（已呈现未声明）3 条：
  - `experience:EXPERIENCE-20261008-drc-t2-contextmanager-tmp`
  - `experience:EXPERIENCE-20261010-verified-2-unverified`
  - `method:stop-on-identical-failure-receipt-75253a27634f`
- declared_without_presentation_in_run（本 run 无 discovery hint 却被声明）3 条：
  - `experience:EXPERIENCE-20260909-lfl-llm-pytest-tail`
  - `experience:EXPERIENCE-20260909-lfl-shell-pytest-web-auth-require-web-origin-allow`
  - `method:locate-project-env-before-symptom-workarounds-f7dd29f1718b`

## 3. 链路层与落地率

| 层 | 条数 |
|---|---:|
| `knowledge.hydration_observed` | 2 |
| `knowledge.method_declaration` | 1 |
| `knowledge.failure_observed` | 1 |
| `knowledge.discovery` | 1 |
| `knowledge.experience_declaration` | 2 |
| `knowledge.run_outcome` | 1 |

- hint 展示 3 条，run 内被声明 0 条 （**0/3**）
- 口径：分母只含本 run discovery 已给出的 hint，不含 advisor 未触发/被裁剪的窗口（不可测）

## 4. unknown / 不可测报告

| 项 | 值 | 依据 |
|---|---|---|
| 净贡献/反事实增益 | `UNMEASURABLE` | 无对照组、无独立事实标签；单条轨迹无法分离『有知识』与『无知识』的结果差 |
| task_benefit | `all-not_evaluated` | 账本 3 行 + run_outcome 1 行全为 not_evaluated |
| task_id / goal_id | `absent` | 本 run 事件 payload 不含 task_id/goal_id（§5.2 允许保留 unknown，不猜） |
| provider_delivery / model_attention | `unknown` | 本 run 无 knowledge.reference_prepared 送达事件，模型是否读到属 protocol 层不可知 |
| 机会分母（advisor 未触发/被裁剪窗口） | `UNMEASURABLE` | 无事件即无痕迹；hint 分母只覆盖已触发窗口 |
| helped / attribution_level 的独立可核性 | `unverified_in_this_session` | 账本 application_proven=true 但 authority=model_declared；其 evidence:// 句柄在本会话不可解析，本轮未复验，故 helped 一律 unclear、attribution_level=insufficient |
| discovery→declaration 时序（逐条配对） | `checked` | discovery seq [759]；declaration seq [724, 791, 792]。hint 3 条，其中 3 条在其 discovery 之后无 declaration 命中 → 不是时序伪影。1 条声明早于全部 discovery，不计入落地率 |
| run.outcome 与 run.end 一致性 | `checked` | run_outcome.reason='completed' vs run.end.reason='completed'（join=seq-adjacent(seq 812 >= run max 812)） |
| hydration_observed 与 run_outcome.hydrated_refs 一致性 | `checked` | hydrated_refs 2 条；declaration 中 hydration_observed=True 的 2 条 |

## 5. 只读性证据

- 账本匹配方式：session_id exact（exp 2/20，method 1/22）
- experiences/usage.jsonl sha256: `67e7f4aedf3df66bbf70520de93f88b6de0ef3a18480c7d81003cbc94a52dcc2`
- data/methods/usage.jsonl sha256: `55ff92c2113fdd4207d1b51f6306a380258beeed8a88358dc699a2484edc6f1b`
- 本脚本只读：未写账本、未写 EventStore、未补造终态、未新建 journal/worker。
