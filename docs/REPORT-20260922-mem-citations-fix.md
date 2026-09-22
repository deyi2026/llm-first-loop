# REPORT: memory citations 提取修复（prompt 规则 + 真实 index 锚点）

- 日期: 2026-09-22
- 分支: `fix/mem-citations-index-anchor`（自 `main@5e4fe3342` cherry-pick 实验 commit `26da66f72`，落地为 `77269284b`）
- 改动范围: `src/llm_loop/memory/extractor.py` 单文件，+12/-3
- 状态: 待评审

## 1. 问题

生产链路中记忆提取的 `citations` 字段从未被 LLM 输出。A 组对照（生产 prompt 原样，deepseek-v4-flash，temperature=0，生产解析链路）×3 轮：15 entries，0 citations。

根因：`_EXTRACT_PROMPT` 的输出示例只有 `type/content/keywords`，没有 `citations` 字段示例与 ref 规则——模型从未被要求输出该字段。

## 2. 修复（两处，缺一不可）

1. **prompt 规则**（`_EXTRACT_PROMPT`）：记忆块示例加入 `citations: [{"kind": "message", "ref": "msg:3", ...}]`，并加三条规则——每块必含至少一条 citation；`ref` 为 `msg:N`，N 为出处消息在历史中的编号（历史每行以 `[N]` 开头）；不得编造编号。`.format` 模板已做 `{{}}` 转义。
2. **真实 index 锚点**（`_build_history_text`）：历史行首从 `[role]` 改为 `[idx][role]`。程序反馈类消息被过滤时"占号不占行"，`msg:N` 与 `session.messages[N]` 保持一一映射。

## 3. 对照实验（真实 LLM，temperature=0，生产解析链路）

| 组 | 配置 | 模型 | 轮次 | 结果 |
|---|---|---|---|---|
| A | 生产 prompt 原样 | deepseek-v4-flash | 3 | 15 entries，**0 citations**（根因复现） |
| B' | 新 prompt，历史无锚点（无过滤） | deepseek-v4-flash | 3 | 15/15 带 citations，refs `msg:1/3/5/7/9` 精确 |
| B | 新 prompt + 连续编号（无过滤） | deepseek-v4-flash | 3 | 15/15 带 citations，refs 精确 |
| NP | 新 prompt + 程序反馈过滤，无锚点 | deepseek-v4-flash | 2 | refs 全为 `msg:1/3/5/7/9`，**系统性错位 +1**（真实出处为 2/4/6/8/10） |
| IX | 新 prompt + 过滤 + 真实 index 锚点 | deepseek-v4-flash | 2 | refs `msg:2/4/6/8/10`，精确命中 |
| NP（复测） | 同 NP | glm-5.3-flash（thinking off） | 2 | 10/10 refs 判定 `wrong_idx`（系统性错位复现） |
| FIX（复测） | 同 IX | glm-5.3-flash（thinking off） | 2 | 10/10 refs 判定 `exact_ground` |

归因链（单一变量受控）：

- 只改 prompt 不加锚点（NP）：citations 有了，但程序反馈过滤使行序≠消息序，模型按可见行序自编号，两模型全部系统性错位。
- 只加锚点不改 prompt（即 A 组现状）：无 citations 输出，锚点无从消费。
- 两处同时改（IX/FIX）：两模型全部精确命中。

数据文件（本地 `.tmp-ci/mem-citations-exp/`，被 gitignore，不随 PR；本报告为其持久摘要）：
`results.json`（A×3；含首版 B/B' 因实验 harness 的 JSON 解析 bug 失败的原始记录）、
`rerun_bb.json`（B'/B 修复 harness 后重跑）、
`exp_offset.json`（deepseek NP/IX；该文件未回填逐 ref verdict 字段）、
`exp_offset_glm53f.json`（glm-5.3-flash NP/FIX，含逐 ref verdict：`wrong_idx` / `exact_ground`）。

## 4. 验证

- 冒烟（`smoke.py`）：prompt `.format` 转义正确；`_build_history_text` 锚点输出与 IX 组实验历史逐行一致。
- 单测：cherry-pick 到 main 基后 fresh 运行 `test_answer_origin` / `test_p0b_program_feedback` / `test_extractor` / `test_learning_plane_memory`：**26 passed in 0.54s**（2026-09-22，分支 `fix/mem-citations-index-anchor`）。

## 5. 局限（如实声明）

- 有效性样本为 5 记忆点 × 2 轮 × 2 模型（deepseek-v4-flash；glm-5.3-flash 且 thinking_mode=False）的**定向压力测试**，非大规模回归。
- 记忆类型仅覆盖 fact 型。
- 错位场景特指"程序反馈过滤导致消息缺席"；未来若新增其他过滤路径，需保持同样的"占号不占行"锚点纪律。

## 6. 回滚

单 commit 修复：`git revert 77269284b` 整体回退，无 schema / 存储迁移，无连带配置。
