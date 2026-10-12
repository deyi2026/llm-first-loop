# SPEC-20261005 Method Subject-Binding 效能预注册（P1-1）

Date: 2026-10-05
Status: **PRE-REGISTERED — 冻结于任何数据收集之前**
上游机制: `src/llm_loop/introspection/registry_experience.py`（env `LFL_METHOD_SUBJECT_BINDING_EXPERIMENTAL` → `save_experience` 描述追加 subject-binding 指引）
上游审查: 2026-10-05 五条建议之 P1-1（Method 闭环未闭合：visible ≠ adoption ≠ efficacy）

---

## 0. 冻结声明

本文档在实验数据收集开始之前冻结。冻结后**不得**修改研究问题、判据、阈值、样本量、
停止规则与分析计划；执行期任何偏离必须在结果报告中以"偏离登记"章节显式披露。
冻结凭证：本文件 sha256 记录于
`docs/verification/2026-10-05-subject-binding-visibility/REPORT.md`，并以 git commit 固定。

## 1. 研究问题

`save_experience` 工具描述中的 subject-binding 指引
（"以当前任务 claim subject 为判别对象；experience/result/fixture 仅为证据载体，不得替换 subject"）
是否提升 Method 适用性判断正确率，且不以显著成本/采纳损失为代价？

## 2. 设计

- 2×2：arm（C1 binding 可见 / C0 binding 不可见）× case（subject-match / subject-mismatch）
- C1：进程 env `LFL_METHOD_SUBJECT_BINDING_EXPERIMENTAL=1`；C0：同一二进制、同一配置、env 缺省
- case 池：每臂 40 例（20 match + 20 mismatch），从既有 method 卡片池机械生成；
  池文件与 sha256 在首跑前冻结发布；案例顺序以 seed=20261005 随机化
- 任务模板要求输出结构化裁决行（唯一判分依据）：
  `APPLICABILITY_VERDICT: APPLY|SKIP SUBJECT: <string> REASON: <≤40字>`
- 判分：机械字符串对照 ground truth（match→APPLY，mismatch→SKIP）；无人工判分

## 3. 预注册指标与阈值

主指标 **M1 subject-accuracy**（正确裁决率）：
- PASS：`C1 − C0 ≥ +0.15` 且两比例单侧检验 95% CI 下界 > 0（α=0.05 单侧 z 检验）
- FAIL：CI 下界 ≤ 0 → 维持 flag 现状，结论登记"无证据"，不得扩大 rollout

护栏（副指标，任一违反则结论降级为"有收益但护栏违反"，不得宣称净收益）：
- G1 采纳率（应 APPLY 案例中 APPLY 且 `record_use` applied 的比例）：`C1 ≥ C0 − 0.05`
- G2 成本（每例总 token 与墙钟）：`C1 增幅 ≤ 15%`

## 4. 样本量与停止规则

- n=40/arm 固定，一次跑完；**无期中分析、无 peeking**
- 案例技术性失败（工具错误/输出截断）如实计入 OTHER，不剔除；同一案例至多 1 次重跑且必须登记
- 不得事后增补或替换案例

## 5. 分析计划

- 主检验：两比例单侧 z 检验（预注册公式，无备选模型挑选）
- 分层（探索性，不作判据）：match/mismatch 分层正确率
- 全部裁决行原始输出落盘 jsonl + sha256

## 6. 混杂控制

两臂除该 env 外全同：同 provider、同模型（单一固定模型）、同温度、同工具集、同提示模板。
模型选择在执行前登记（候选：deepseek-v4-flash——2026-10-05 矩阵中 C1 可见率 10/10 的臂）。

## 7. 执行前提（可核验）

1. C1 可见性已由 2026-10-05 gen177 矩阵证实（见 REPORT.md）
2. C0 实施后须先跑同 prompt 可见性 smoke n=5，确认 MISSING 率 5/5，方可开跑正式案例
3. C0 进程为无 flag 的 headless/CLI engine；若 C0 无法建立，实验中止并登记，不得以"假 C0"替代

## 8. 明确不做

- 不改 flag 语义或指引文本
- 不动 `record_use` 通道语义
- 实验结论不直接改生产 default；是否推广由 operator 依据本预注册判据裁决
