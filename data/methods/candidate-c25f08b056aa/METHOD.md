---
method_id: candidate-c25f08b056aa
name: 有界审查派单契约——防审查子代理无边界探索截断
description: spawn_subagent 委派独立审查/终审子代理时，任务书必须自带范围锚定、取证预算、轮次预留、三态结论格式与 fail-closed 五要素；否则子代理倾向穷举取证直到轮次耗尽，零终审结论。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:376f20bb-9dc9-4200-8780-a7b8dfab31db:43:50cef82d34640363449a
evidence_refs: docs/governance/receipts/merge_GOAL-20261107-3f142c52_T9_v1.md,本会话 2026-11-08 核实：subagent_0a8d92209812 等连续 3 个审查子代理 truncated 无 VERDICT；skill_list 回执显示 merge-review-gate/code-review-gate 处于 modified 未审批被隐藏
created_at: 2026-11-08T21:35:25.962667+08:00
updated_at: 2026-11-08T21:35:25.962667+08:00
---
## 场景
spawn_subagent 委派「独立审查/终审」类子代理（合并审查、发布前审查、全量测试审查）时，若任务书只给审查目标、不给范围与停止条件，子代理会自发发明穷举式取证流程，把全部轮次花在取证上，最终 truncated 且无 VERDICT。实测案例 2026-11-08 GOAL-20261107-3f142c52 T9 合并审查：3 个连续子代理（deepseek-v3）合计 68 次调用、约 1.38M 输入 tokens、40 轮全部取证，无一产出终审结论；父会话收紧派单+换强模型（glm-5.3）后第 4 个子代理单轮收敛 PASS（回执 docs/governance/receipts/merge_GOAL-20261107-3f142c52_T9_v1.md，提交 834570518）。

## 契约五要素（必须写进 task 文本）
1. **范围锚定**：给出 base SHA + 提交清单 + 文件清单，明令「禁止探索清单外文件/目录」——防全仓库穷举。
2. **取证预算**：单命令优先（git diff 一次性取全、测试命令一次跑全量），每类证据至多 2 次尝试；禁止逐文件、逐行式探索。
3. **轮次预留**：总轮次最后 25% 禁止新取证，只准撰写结论（或明确「第 N 轮前必须停止取证」）。
4. **三态结论格式**：最终回复必须是 PASS / FAIL / BLOCK 三选一 + P0/P1/P2 分级清单；事实不足时不得继续取证凑证据。
5. **fail-closed**：无法在预算内验证的项按 BLOCK 处理，列明缺失的证据是什么，不猜、不默认通过。

## 派单参数
- 终审类用强模型（对指令遵循更好；本案例 glm-5.3 收敛 vs deepseek-v3 失败，注意与派单收紧同时变化、不能单独归因模型，但组合有效）。
- max_rounds 显式给值（如 20），不要用默认值放任。
- write_scope=deny 只读，取证面天然受限。

## 与相邻方法的边界
method:marginal-preflight-overshoot-split-review-into-dimension-briefs-8640441d5ff4 处理的是「上下文预检阶段被拒（零工作）」——按维度拆微型任务书；本方法处理的是「已受理后无边界探索直到截断」——靠契约五要素收边界。二者互补：先拆任务书防预检拒，再写契约防截断。

## 验证状态
对照案例已验证（收紧派单后单轮收敛 PASS）；尚无第二次独立复用验证，保持 candidate。
