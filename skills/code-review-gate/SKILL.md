---
name: code-review-gate
description: 代码审查闸（RULE-AI-28 第 1 条）——代码任务全量测试前的独立子代理审查清单与回执格式
---
# 代码审查闸（全量测试前）

触发：修改 src/ tests/ scripts/ tools/ webui/ 等代码文件的任务，全量测试前必走（RULE-AI-28）。

## 审查者纪律
- 独立子代理执行，不复用执行上下文；工具面收窄为只读感知 + 回执写入。
- 启动前按需检索相关 method/experience（如 patch-apply-verify-by-content-diff、release-pr-green-is-not-closure），历史坑优先复用；检索 limit ≤5。

## 审查清单（按序执行，逐项留痕）
1. **正确性**：逐文件读 diff 全文（不凭描述）；修改是否实现声明意图；逻辑分支覆盖。
2. **边界条件**：空输入/None/异常路径/并发与重入；错误处理是否吞错。
3. **安全面**：密钥/凭据硬编码；命令注入；路径逃逸；不受信输入直达执行面。
4. **回归面**：受影响模块的既有测试是否仍覆盖；`test_ai_rules_sync.py` 等 SoT/契约锚点是否被破坏；schema/接口变更是否同步了调用方。
5. **一致性**：与 docs/ai_rules.md、docs/governance/card-lifecycle.md 既有约定冲突；命名/结构与同目录现状一致。

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
