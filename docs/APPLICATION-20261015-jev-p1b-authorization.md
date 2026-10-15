# P1b 外发授权申请单（Jev 有界外部 shadow）

| 项 | 值 |
|---|---|
| 申请日期 | 2026-10-15（Asia/Shanghai） |
| 申请人 | LFL（依据 DESIGN v0.8 §11.1 预注册与用户 2026-10-15 指示"做完这步，P1b 就只剩你的授权决定"） |
| 申请事项 | 授权 P1b：向 TypeSafe API 真实外发一次有界 shadow 校准批次 |
| 设计依据 | `docs/DESIGN-20261014-jev-experience-method-loop-governance.md` v0.8（§11.1 预注册已冻结） |

## 1. 前置条件状态（"可以授权 P1b"如何做实）

| 前置项 | 状态 | 证据 |
|---|---|---|
| wire/守卫/负例/预算闸 | P1a 已实现，88+ 定向测试 | `src/llm_loop/knowledge/jev/`；代码闸三轮回执 `data/audit/code_gates/RULE-AI-28-jev-p1a-20261015.md` |
| 盲评集标签独立性 | 已从作者标签升级为双源一致 | `outputs/jev-blind-eval-20261015/blind_eval_result.json`：deepseek-v4-pro 隔离子代理、0 工具调用、9/9 取值一致，premise 子集 6/6 verified |
| 参数预注册 | 已冻结于任何外发之前 | DESIGN §11.1（v0.8）；policy.py provisional 已转 False |
| 机会分母/业务标签 producer 字段 | 已实施（收益归因链） | run.end `knowledge_run_ref`/`knowledge_advisor_mode`、run_outcome `advisor_mode`；代码闸回执 `data/audit/code_gates/RULE-AI-28-p0b-fields-20261015.md` |

## 2. 授权范围（冻结值，授权后不可改闸）

- **固定模型**：`jev-1.13.0`；每响应绑定 resolved model，漂移即停退 HOLD。
- **单一用途**：仅 `premise_check`（choice yes/no/unknown）。不含 dup/score/分类/noul。
- **任务集**：`tests/fixtures/jev/blind_eval_v1/`（manifest SHA-256 `2fc40cfa4226b5c5024c0a874b7ca6168202cbf8a671abe6efdd7476cba8227d`）的 6 道 premise 题：case-001/002/003/006 `premise_linux` + case-004 `premise_bare_metal`/`premise_systemd`。总量 6 题/≤2 HTTP 批，不追加。
- **预算四面**：HTTP ≤2；每请求 input ≤2000 tokens、output ≤2000 tokens；重试 0（隐式/显式均关）；单请求 deadline 2s。
- **对账**：逐题 confusion + §9.2 全链分母；样本 6 题只证明链路可运行，不构成校准资格。
- **中止条件**：任一预算面超限 / 守卫任何命中 / resolved model 漂移 / 出现隐式重试 / schema-invalid 原因未明——任一即停退 HOLD。

## 3. 泄出边界与守卫

**外发内容仅限**：6 题的 task_snapshot 受控投影（allowlist 字段）+ 题目 instructions/criteria + subject_ref/hash 标识。
**不外发**：Rules、会话正文、凭证、私有 reasoning/思维链、跨 scope 源。
**守卫（P1a 已实现且有测试）**：红线键、凭证样式（11 类 pattern）、工具授权字段（15 别名）三重扫描，递归全深度含容器，深度>8 fail-closed；注入文本按数据处理（case-006 反例已入盲评集并通过独立盲评）。
**残留风险（如实声明）**：封闭选项不证明免疫 prompt injection；SDK 隐式重试关闭需实测复核；费用以响应 usage 如实记录，缺失记 unknown。

## 4. 需用户决定的三项

1. **是否授权本批次真实外发**（是/否/改期）。
2. **费用上限数值**：当前 `cost_cap=0.0`（mock 语义：任何非零费用都未授权）。真实外发需你给定一个显式费用上限（例如单批 ≤ US$1）；该值属授权参数，将在授权记录中补录，不属于改闸。
3. **endpoint/账户确认**：§13.4 待关闭项——签约 endpoint、鉴权账户、数据保留区域未核。请提供签约 endpoint 或确认使用官方默认 `https://api.typesafe.ai/v1/systemone`；授权前不发送任何请求。

## 5. 回滚与停止路径

停止=停新调度、取消未发队列、核实际已发结算、隔离投影与派生结果、保留账本（§2 Q20）；已外发数据不可撤回，故本批次规模刻意压到 6 题/2 请求。
