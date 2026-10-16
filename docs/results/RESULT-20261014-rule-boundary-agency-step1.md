# RESULT-20261014 — Rule 精确水合与知识发现首包：步骤 1 隔离候选

> 状态：步骤 1 已完成 focused/adjacent 回归；**独立 Reviewer、全量 R9、merge、release、重启与真实 Provider 效能资格均未执行**。
> 基线：`main@6447784319b01f08393f49c2c288f51e7ea4aef5`；独立分支：`fix/rule-boundary-agency-20261014`。
> 上游设计：`docs/evidence-method-agency-20261014@df32123e3`（独立分支；不把当前仓库未合并的设计文件冒称为 main 现值）。

## 当前问题和最小修复

1. 原 `RuleIndex._load()` 以“下一条带 RULE-AI 编号的 H2 或文件末尾”截取完整 Rule；新增 RULE-AI-32 后，RULE-AI-31 正文不再越界，但**最后的 RULE-AI-32 会把同级非规则 H2《配置扩展》等内容误当成规则正文**。
2. 修复仅把 Rule exact hydration 的末端改为**下一任意同级 Markdown H2**；H3 子节依旧保留，原始 `docs/ai_rules.md` 不更改，稳定引用和 `source_version_token` 仍引用全量源文件 SHA。
3. `search_records` Full/Lazy 的工具描述精确表达现有 RULE-AI-31：有实质工具/多步工作开局只在 method/experience/lesson 选择最多两类、每类最多五条，同任务窗口不重复，简单问答豁免；候选仅供模型自行决定是否采纳，完整 Method ref 需 exact hydration。没有改变 tool allowlist、系统 prompt、运行权限、Method 状态或自动调用策略。

## 现场测试与对照

| 项目 | 本轮真实结论 |
|---|---|
| 同步主分支事实 | 工作开始 `main@6447784319b0`；后续 main 已前进，最终差分检查确认 RuleIndex/Registry/对应测试和 docs/ai_rules.md 从冻结基线至当时 main 无变化；并行其他 Agent 工作未改动 |
| 补丁前真实 RED | 3 新回归 **3 failed**：最后规则截断、真实 RULE32 tool receipt、FakeLLM 首包工具契约 |
| 补丁后 GREEN | 新回归 **3 passed**；包括实际 `docs/ai_rules.md` 的 Rule 索引及 `run_search_records` 真实回执 |
| 规则/方法/经验邻接 | **77 passed，1 deselected**（见下方存量红） |
| KnowledgeRuntime/Advisor 邻接 | **55 passed** |
| 静态检查 | 针对五个 Python 变更文件 Ruff PASS，Python `py_compile` PASS，Git diff whitespace PASS |
| 精简描述预算 | Compact 430→**416** 字符；Full 572→**564** 字符；既有 Compact 上限 390+80=470，不扩大首包上下文 |
| 模型首包 | 使用真实 LoopEngine + ToolRegistry + 可编程 FakeLLM 观察第一轮 Provider-bound tool schema，Full/Lazy 含同一 Rule31 约束；**不是**真实外部 Provider 的物理送达/模型阅读证明 |

## 已知存量问题及不能冒认的验证

- 原始未改代码测试集合已经失败：`tests/unit/test_rule_presence_contract.py::test_ledger_covers_all_sot_rules`，因主分支新增 RULE-AI-32 后，私有 `.codeartsdoer/specs/rule_presence/rule-presence-ledger.md` 尚未覆盖该规则。该旧红没有因本候选新增；本轮邻接测试显式剔除**这一条**以隔离变更效果，不改写规则账本、不抬测试基线、不声称完整 R9 绿。
- 当前规则段界以真实 Markdown 同级 `##` 标题为界；未引入第三方 Markdown AST 或上下文语义分类器，不虚称对任意不规范/多层级 Markdown 的通用解析资格。
- 未外发用户任务或 Method/Experience，未使用真实 GLM-5.3/弱模型评测，未证明知识机制的任务收益；这仍属于计划的后续冻结对照阶段。

## 交接门槛

下一步须由符合 RULE-AI-28 的**独立 Reviewer**审核本候选的精确 commit SHA、真实源码/测试 diff 与潜在副作用，解决所有 P0/P1 并复审；之后按独立阶段执行完整 R9（含存量红的责任归属与治理），取得明确有效性及受控发布授权后，才考虑 merge/publish/restart。当前候选不具有生产推广资格。
