---
name: code-review-gate
description: 代码审查闸（RULE-AI-28 第 1 条）——代码任务全量测试前的独立子代理审查清单与回执格式
---
# 代码审查闸（全量测试前）

触发：修改 src/ tests/ scripts/ tools/ webui/ 等代码文件的任务，全量测试前必走（RULE-AI-28）。

## 前置义务与资格
审查是强制前置义务。父 agent 主动安排对应独立审查子代理，取得覆盖当前产物的有效 PASS 回执后方可执行目标动作；缺失、未完成、未通过或失效时暂缓该动作，继续其他可推进工作。核实真实子会话终态、审查类型、产物指纹及实际覆盖；completed、工具文本中的 PASS 或父 agent 自查均不构成资格。改动后走窄复审并保留覆盖关系。泛化的“继续 / 按建议执行 / 授权发布”不构成免审；用户明确豁免须留痕。程序观测提示不等于有效回执。

## 审查者纪律
- 未参与产出的专门独立子代理执行，不复用执行上下文；应能读取完整候选、关联上下文与证据，按需运行定向检查，不由审查者提前跑待准入的全量测试；工具面为必要只读感知 + 指定回执写入。
- 启动前按需检索相关 method/experience（如 patch-apply-verify-by-content-diff、release-pr-green-is-not-closure），历史坑优先复用；检索 limit ≤5。

## 审查清单（按序执行，逐项留痕）
1. **正确性**：逐文件读 diff 全文（不凭描述）；修改是否实现声明意图；逻辑分支覆盖。
2. **边界条件**：空输入/None/异常路径/并发与重入；错误处理是否吞错。
3. **安全面**：密钥/凭据硬编码；命令注入；路径逃逸；不受信输入直达执行面。
4. **回归面**：受影响模块的既有测试是否仍覆盖；`test_ai_rules_sync.py` 等 SoT/契约锚点是否被破坏；schema/接口变更是否同步了调用方。
5. **一致性**：与 docs/ai_rules.md、docs/governance/card-lifecycle.md 既有约定冲突；命名/结构与同目录现状一致。
6. **护栏实测（门槛类变更专项）**：护栏/门槛类变更（新增/修改拦截判据、阻断清单、正则、阈值）——核验应拦输入实测证据存在且对应真实入口（RULE-AI-35）；未实测的完成声明只可停在"代码已提交"，不得升级为"护栏已生效"。

## 发现分级与 verdict
- **P0**：错误行为/数据损坏/安全洞/契约破坏——必须修，否则 BLOCK。
- **P1**：明确缺陷或遗漏，影响正确性或可维护性——必改，修后窄复审。
- **P2**：改进建议（命名、结构、冗余）——记录，采纳与否由执行方答复时说明。
- verdict 三态：PASS / REVISE / BLOCK。REVISE 后窄复审只复核修订点 + 新增扫描，不全量重审。

## 回执（落盘 docs/governance/receipts/，无回执不得声称已审查）
```json
{"gate": "code", "reviewer": "<subagent_id>", "verdict": "PASS|REVISE|BLOCK",
 "scope_files": [...], "findings": [{"id": "P1-1", "severity": "P1", "file": "...", "issue": "...", "fix_hint": "..."}],
 "applied": [...], "rejected": [{"id": "...", "reason": "..."}],
 "artifact_sha256": "...", "narrow_recheck": null | {"reviewer": "...", "verdict": "..."}}
```

## 沉淀循环
审查结束把新坑按载体归位：单次坑 save_experience；可复用流程 method_manage；清单缺陷改回本 skill；反复出现的系统性问题按 card-lifecycle 升格规则候选。
