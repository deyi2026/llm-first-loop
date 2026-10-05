# IQ-CTOR-v2 构造器登记簿（启用 + 已知噪声底 + 使用日志）

登记时间：2026-10-05T23:28:45+08:00 ｜ 登记人：LFL 会话（operator 授权）
性质：**增量登记，不回改任何冻结件**（PREREG/盲表/密封件/双评答卷/分析器均保持 git 0bf74d5dd 原样）。

## 1. 状态：ACTIVE（启用）

- 名称：IQ-CTOR-v2（方法卡适用性仪器构造器，2×2 池设计，A6/B20/C8/D6）
- 资格依据：IQ v1 一次性裁决 **PASS**（κ(R1,R2)=1.0000，0/40 分歧；A 6/6｜B 14/20｜C 8/8｜D 6/6；H⁺=14/H⁻=8）
  证据：`IQ-RESULT.json` sha256 c4dae01c0e224157…（全文见同目录 IQ-RESULT.md）
- 资格边界（如实）：R1 为 web-gpt 代位（DEV-1，见 iq_R1_notes.md），κ 属"模型×模型"一致性，**人类锚缺失**；
  补验包见 `anchor/`（预注册 ANCHOR-PREREG.md，裁决前本登记簿状态不变）。
- 资格边界更新（2026-10-05T23:41 裁决后）：人类锚补验 **HOLD**——operator×R1 = 9/12（门 ≥10）未过，A 层 6/6 过；
  答卷为批量裁定（证据力不足，详见 §4 事件 #1）。资格声明**维持不升级**：仍为"模型×模型一致性，人类锚未确立"。
- 启用含义：后续任何"方法卡适用性仪器"构造任务可直接指名 IQ-CTOR-v2 起池；构造规则源 = `iq_build.py`（git 0bf74d5dd）。

## 2. 已知噪声底（known noise floor）：B 格 6 例 ↔ v1 L 型缺陷精确重合

IQ v1 中 B 格未获认证的 6 例，其 subject（陷阱卡）与 v1 FORENSIC 判为 L（标签噪声/真双适用）的 6 例一一对应：

| IQ 例 | 陷阱卡（subject 前缀） | v1 源例 | v1 判类 |
|---|---|---|---|
| iq-B09 | adjudicate-from-alert-payload-audit-claims-before-write | mb-018 | L(弱) |
| iq-B13 | ambiguous-timeout-verify-landed-before-rerun | mb-026 | L |
| iq-B14 | anaphora-artifact-first-context-recovery | mb-028 | L |
| iq-B15 | anchor-and-derive-environment-parameters | mb-030 | L |
| iq-B16 | anchor-background-job-polling-to-duration-prior | mb-032 | L |
| iq-B19 | anchor-declared-worktree-root-before-commands | mb-038 | L |

- 机制：L 类陷阱卡与呈现 trigger 同域（sibling），卡片对任务实质适用，expected=SKIP 在实质上不成立——评分者判 APPLY 是**裁定级合理分歧**而非判别失败（v1 FORENSIC 判类口径原文）。
- 量化边界：该噪声底使 B 格认证上限 ≈ 14/20；本次 14/20 恰为顶格，**无超出噪声底的新失败模式**。
- 证据：`iq_sealed.json` sha256 2f02962faef3fc91…（subject 映射）＋ `../method_binding_efficacy_v1/FORENSIC.md` sha256 c0bd1a9c0cc01acd…（L 判类表）＋ IQ-RESULT.json certified_B_case_ids。
- 处置：**登记为已知问题，不触发 v2.1 重构**（κ=1.0 下边际收益低）。复核触发条件（满足其一才重构生成规则）：
  1. 下次 IQ 运行 B 格未认证 > 6 例，或
  2. 出现非 L-重合型的新失败模式（subject 不在 v1 L 清单内）。

## 3. 使用日志

| # | 日期 | 下游任务 | 池规格 | 结果 | 备注 |
|---|---|---|---|---|---|
| — | — | 待 operator 指定首个下游构造目标 | — | — | 首用前每行需附 IQ 结果文件引用 |

## 4. 事件记录

### 事件 #1｜2026-10-05T23:41:09+08:00｜人类锚补验裁决：**HOLD**（一次性，不重测）

- 机械结果（anchor_verify.py，prereg sha256 60c4252b…）：G1 = 9/12（门 ≥10）**FAIL**；G2 = A 层 6/6（门 ≥5/6）PASS；
  分歧例：`iq-B10`（B 认证层）、`iq-D01`、`iq-D02`（D 层）——operator=APPLY vs R1=SKIP，共 3 例。
  裁决文件：`anchor/ANCHOR-RESULT.json` / `ANCHOR-RESULT.md`；答卷 `anchor/ANCHOR-ANSWER.jsonl`。
- 操作侧 provenance（如实登记）：operator 答卷为**批量裁定**——2026-10-05T23:39:08+08:00 会话指示"全部都：APPLY，理由：可用"
  （背景：web 端打开仅可预览无法编辑，由 LFL 代填答卷，ts 记指示时刻，逐例 reason 均为同一"可用"两字）。
- 证据力诊断（HOLD 映射要求的分歧对照）：三例分歧的 operator 理由无任何逐例区分信息；且 R1 子样 12 例中 9 例为 APPLY，
  统一 APPLY 的内容盲策略期望一致率恰为 9/12——**本次一致率与内容盲基线完全重合，不携带人类×模型对齐信息**。
  故正确读法是"人类锚未确立（证据力不足）"，而非"差 1 例接近通过"；A 层 6/6 同理不构成标签效度旁证。
- B19 披露（PREREG §4）：operator=APPLY（可用）与 R1=APPLY 方向相合；但受批量裁定限制，作为"L 类=裁定级合理分歧"
  的人类旁证仅有方向意义，无理由级区分度。
- 后续（不自动执行；按 PREREG §3，HOLD 后是否补测由 operator 另立新预注册决定）：若仍需真人类锚，新预注册应要求
  逐例独立理由，并把"全部 verdict 相同且 reason 逐字相同"定义为无效提交（答卷区分度前置门）。

> 变更纪律：本簿只增不改；状态变更（如人类锚补验裁决）追加 §4 事件记录，不覆写历史行。
