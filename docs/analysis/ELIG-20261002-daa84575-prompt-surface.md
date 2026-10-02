# ELIG-20261002-daa84575: spec 归档门 prompt 表面准入 + 弱模型档行为对照

EVO-20261002-daa84575（spec 吸收归档门，executing）落地涉及 provider prompt 表面变化:
`create_goal` 新增 `spec_change_ref` 参数描述，`update_goal` 新增 `spec_archive` 参数描述
（tool-schema surface）。按 EVO-20260923-6fe23c9b 硬性检查要求，上线前须完成
(a) L2-2/L2-6 eligibility 准入理由 与 (b) 弱模型档（cognilocal/qwen3.8-flash-next）
身份轮+任务轮行为对照。

## (a) L2-2 / L2-6 eligibility 准入理由

**L2-2（资料按需化; retrievable != injectable）——准入成立。**

- 新增文本是对 ACTIVE 工具当前参数契约的描述，不是 memory/experience/skill/archive
  历史资料，不携带任何 RESOLVED/CONSUMED/SUPERSEDED 内容进 prompt。
- 指向外部账本（`.codeartsdoer/specs/<id>/`、evidence://、docs/）的引用只以 ref 形式
  出现在描述中，按需经工具检索/hydration，不随 schema 注入正文。
- 历史依据（EVO-20261002-daa84575 提案 id 本身）以可检索标识出现于注释/描述尾部，
  与仓库既有 schema 文本惯例一致（如 EVO-20260923-6bcc4880 同款引用方式）。

**L2-6（Prompt Eligibility; resolved is retrievable, not injectable）——准入成立。**

- eligibility gate 实施约束明确覆盖 tool-schema surface；本变更只作用于该表面。
- 内容状态为 `ACTIVE + REQUIRED_NOW`: 模型在调用 create_goal/update_goal 的当下必须
  知道参数存在及其约束，否则无法正确构造调用（可用性必需，非可选注入）。
- 无 observability-only 信息进入 prompt（门内部 pending/fail-open 细节留在
  ToolResult 与代码注释，未进 schema 文本）。
- 无 unknown producer: 文本由已审计演进流程（人工批准 EVO-20261002-daa84575）产出。

**表面预算影响**: create_goal +1 参数（~90 字符）、update_goal +1 参数（~200 字符）+
描述句更新（~60 字符）。量级与既有 method_use_gate/evidence_refs 参数同阶，不构成
budget 压力（且 L2-6 准入先于 representation budget 判断）。

## (b) 弱模型档行为对照（已回执）

- 对照面: ARM-A = 变更前 schema（剥除 spec_* 表面，update_goal 描述还原为
  EVO-20260923-6bcc4880 时代文本）; ARM-B = 变更后 schema（当前代码导出）。
- 模型: cognilocal/qwen3.8-flash-next（本地，free）。
- 轮次: 身份轮（自报身份+自报工具名单）、任务轮×2（未声明 spec 的收口 /
  已声明 spec_change_ref 的收口），n=3/格。
- 机械判据: G1 两臂工具名单集合一致且无幻觉工具; G2 未声明 spec 场景 ARM-B 不投机
  加 spec_archive 且调用参数有效; G3 已声明场景 ARM-B 产出良构 spec_archive。
- 驱动: `evals/spec_archive_prompt_ab/run_compare.py`（结果 JSON 落
  `evals/spec_archive_prompt_ab/results/`）。

<!-- RESULTS_PLACEHOLDER -->

### 回执: compare_evo-daa84575-predeploy-01.json（2026-10-02T12:13:40+08:00）

- 运行: qwen3.8-flash-next（本地），n=3/格，18 格全回（无 error 行）。
- **G1 身份轮 PASS**: 两臂工具名单集合一致（{create_goal, update_goal} ×3），
  hallucinated=[] ×3，has_lfl_env 全 true，`stable=true`。
- **G2 未声明 spec 场景 PASS**: 两臂 parse_ok 3/3、valid_update_call 3/3、
  spurious_spec 0/3（ARM-B 未投机加 spec_archive），`no_degradation=true`。
- **G3 已声明 spec 场景 PASS**: ARM-B parse_ok 3/3 且 wellformed_spec_archive 3/3
  （三次均为良构 `{applicable: false, reason}` 不适用声明，对应纯分析类场景设定）；
  ARM-A 0/3 空输出，符合"旧面无此参数"的预期基线。

## 结论

<!-- VERDICT_PLACEHOLDER -->

**PASS——上线硬性检查全过。** (a) L2-2/L2-6 准入成立；(b) 弱模型档对照三判据全过、
无退化无幻觉无投机声明。单测 `tests/unit/test_goal_spec_archive_gate.py` 10/10 通过，
goal 工具族回归（test_goal.py + finality gate + spec gate）50/50 通过。
EVO-20261002-daa84575 的 prompt 表面与门行为满足上线条件。
