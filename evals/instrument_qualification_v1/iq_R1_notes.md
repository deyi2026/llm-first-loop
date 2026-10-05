# IQ-V1 R1 评分旁注与偏离登记（非密封，评分后公开）

## 偏离登记 DEV-1（按 PREREG §9 留痕）

- PREREG §2/§4 冻结定义：R1 = operator（人类，主参照评者）。
- 2026-10-05 23:03 operator 指令：「你把文件整理好，让GPT代替我评审操作」——R1 评审由
  operator 显式授权代位给 GPT。本登记即偏离留痕，不回改冻结件。
- 后果（如实）：Q1 的 κ 从「人类×代理」降为「模型×模型」一致性；「载重证据挂 R1」中
  R1 的人类锚点缺失，标签效度的人类旁证不再存在。裁决照常按 §5 门槛执行，但 IQ-RESULT
  披露节必须引用本条。

## R1 代位评者与评分窗口

- 评者：web-gpt（chatgpt-web browser surface），隔离子代理（fresh session，inherit=false，
  无父会话上下文），child_id=subagent_df2c9f96f4e5。
- 评分窗口：2026-10-05 23:06:41–约 23:10:33 (+08:00)；8 轮、16 次工具调用。
- ts 约定：评者无时钟，40 行统一使用 harness 指定字面值 2026-10-05T23:07:00+08:00
  （窗口起点），实际完成时刻以本注记录为准。
- 评分输入：仅 iq_sheet.md（任务文本指定唯一允许文件）；冻结问句原文随任务下发。

## 机械盲评隔离（执行记录）

- 评分窗口内 8 份答案/标签文件被移出仓库根（仓库外同卷隔离目录 .iqv1_quarantine_20261005T2305，
  评分后原位恢复、sha256 -c 全 OK、隔离目录删除）：iq_R2.jsonl、iq_R2_notes.md、iq_sealed.json、
  iq_candidates.json、v1 目录 FORENSIC.md / FORENSIC-DATA.json / pool.json / pool.freeze.json。
- 子代理工具面限 read_file（实际轨迹：read_file×2 + read_evidence×8 分页，无其他文件访问），
  无网络，无 session 继承。
- 残余盲点（如实）：workspace 内 .worktrees/ 与 data/private-archive/ 存在 FORENSIC 相关
  历史副本，未做物理隔离；子代理为全新会话、未被告知任何路径、工具仅 read_file，风险为
  指令级而非机械级。此处登记留痕。

## 答卷

- iq_R1.jsonl，40 行，盲表呈序，sha256 5055d8312da02efae69c0a4be5a628a84df05ab4facfbace0ee39c2350699dfb，
  APPLY 20 / SKIP 20。
- 誊录：本代理（R2 会话）将子代理最终输出逐字转录落盘，零内容改动；校验 40/40、
  顺序=模板=盲表、verdict 合法、ts 字面值一致。权威原始记录：subagent_result observation
  blob sha256 6bb23dc71c02c6e1fc10b6e64a5773bdc8f4c04ffc98591e95ca7bac6b37ee68。
- 开封时点：R1（本卷）与 R2（22:58，sha256 d48715cc…）均已提交后才运行 iq_analyze.py。

## 偏离登记 DEV-2（分析器确定性 bug 修正）

- 首跑（23:13:54）在渲染 IQ-RESULT.md 时崩溃：gates 循环对无 `threshold` 键的
  Q1_kappa / Q3_headroom 直接取键（KeyError）；IQ-RESULT.json 已写出但含第二处 bug——
  `r1_acd_rate = r1_acd / 34`，而 A/C/D 构造确定格合计 = 6+8+6 = 20，分母硬编码错误，
  致 R1_vs_intended_ACD 误算 0.5882（真实值 20/20 = 1.0，PASS）。
- 修正：分母改为 len(acd_ids)（=20）；MD 表格对 Q1/Q3 行显式渲染；文案 "34 例" 改为
  实际数。修正仅涉展示与该分母，κ/bootstrap/CI/per_cell/headroom 计算路径未动。
- 修正后重跑（seed=20261005 固定，确定性）：κ/CI/raw agreement 与首跑一致；仅
  R1_vs_intended_ACD 由假 HOLD 恢复为 PASS。评级文件未变（R1 5055d831… / R2 d48715cc…）。
