# docs/ 文档导航索引（INDEX.md）

> **定位**：docs/ 目录全部文档的导航索引——报告清单 + 一句话摘要 + spec 章节映射 + playbook 关联 + 更新约定。AI 或人类经本索引可 1 步直达目标文档，无需目录遍历/glob/grep 兜底。
> **版本**：v1.0（M35，2026-08-10）｜ 依据：docs/m34_ux_revisit_report.md §八 建议 1（M34 拍板 A 落地，spec §30）
> **数据来源声明**：本索引全部条目引自 docs/ 既有文档（各报告标题/摘要 + spec 章节号 + playbook 小节），不引入新数据；如与源文档不一致，以源文档为准。

---

## 一、文档定位说明

docs/ 目录共 **26 个 Markdown 文档**，分四类：
- **验收报告**（m11-m34 各里程碑）：m11_audit_report.md ~ m34_ux_revisit_report.md，每个里程碑的验收结论与数据
- **规则与手册**（ai_rules.md / ai_guidance_playbook.md）：规则 SoT + 引导规范手册（实践引用与复用指引）
- **审计/评审报告**（ai_first_review.md / config_integrity_audit.md / four_principles_audit.md / metrics_fixed_revalidation_report.md / p01_program_audit_report.md / program_minimalism_review.md）：各轮程序面/文档面/架构面审计与评审
- **登记**（CHANGES.md）：全里程碑变更登记

**导航方式**：按报告名 glob（`docs/mNN_*.md`）或经本索引 spec 章节映射直达。

## 二、报告清单

| # | 文件 | 一句话摘要 | 类型 | spec 章节 |
|:--:|:---|:---|:---|:---|
| 1 | `CHANGES.md` | 全里程碑变更登记（M10-M35） | 登记 | — |
| 2 | `ai_rules.md` | AI 自主规则清单（RULE-AI-01~08，唯一规则真相源 SoT） | 规则 | §8 |
| 3 | `ai_guidance_playbook.md` | AI 引导规范手册 v1.1（有效引导/负结果/SOP/统计纪律四部分） | 手册 | §24/§26/§29 |
| 4 | `ai_first_review.md` | AI 视角全面审查报告（T21） | 审计 | §7 |
| 5 | `config_integrity_audit.md` | config.py 完整性审计报告（M22 执行阶段补充） | 审计 | §17 |
| 6 | `four_principles_audit.md` | 四原则合规体检报告（M22 后） | 审计 | §17 |
| 7 | `m11_audit_report.md` | M11 文档与架构 AI 视角审计报告 | 验收 | §8 |
| 8 | `m12_deepening_audit_report.md` | M12 深化程序面 AI 视角审计报告 | 验收 | §9-§11 |
| 9 | `m16_review_audit_report.md` | M16 落地复核与全程序面 AI 视角复核报告 | 验收 | §12 |
| 10 | `m19_real_link_acceptance_report.md` | M19 移交语义真实链路验收与 AI 使用友好性审计报告 | 验收 | §14 |
| 11 | `m20_llm_v4_report.md` | M20 LLM 调用链路最新化与思考模式验收报告 | 验收 | §15 |
| 12 | `m21_exec_execution_report.md` | M21 思考模式真实执行力全链路验收报告（must 型负结果） | 验收 | §16 |
| 13 | `m22_prompt_guidance_report.md` | M22 工具调用执行力提升——文档规则层引导验收报告 | 验收 | §17 |
| 14 | `m23_chain_completeness_report.md` | M23 动作链完整性引导验收报告 | 验收 | §18 |
| 15 | `m24_adj_step_report.md` | M24 必调整场景调整步达成率验证验收报告 | 验收 | §19 |
| 16 | `m25_wording_report.md` | M25 RULE-AI-08 措辞强化与调整步达成率复测验收报告 | 验收 | §20 |
| 17 | `m26_sample_report.md` | M26 调整步达成率样本量扩展复测验收报告（N=6） | 验收 | §21 |
| 18 | `m27_signal_report.md` | M27 注入信号规模扩展复测验收报告（负结果 2/6） | 验收 | §22 |
| 19 | `m28_restore_report.md` | M28 注入信号规模恢复回归复测验收报告（5/6） | 验收 | §23 |
| 20 | `m30_model_compare_report.md` | M30 换模型复测 RULE-AI-08 命令句服从度验收报告 | 验收 | §25 |
| 21 | `m32_cmd_boundary_report.md` | M32 命令句再强化边界评估验收报告（拍板 B 维持） | 验收 | §27 |
| 22 | `m33_four_principles_audit_report.md` | M33 四原则合规体检报告（总体合规） | 验收 | §28 |
| 23 | `m34_ux_revisit_report.md` | M34 AI 使用体验回访报告（导航/可检索/定位三维评估） | 验收 | §29 |
| 24 | `metrics_fixed_revalidation_report.md` | 度量修正后真实链路复核报告 | 审计 | §16 补充 |
| 25 | `p01_program_audit_report.md` | P0/P1 既有程序面 AI 视角审计报告 | 审计 | §13 |
| 26 | `program_minimalism_review.md` | 程序最小化审查报告 | 审计 | §7 |

## 三、spec 章节映射

| 报告 | spec 章节 | 章节主题 |
|:---|:---:|:---|
| ai_rules.md | §8 | 文档与架构 AI 视角审计（SoT 引入） |
| ai_first_review.md | §7 | P1 能力增强增量需求 |
| m11_audit_report.md | §8 | 文档与架构 AI 视角审计 |
| m12_deepening_audit_report.md | §9-§11 | AI 自主闭环深化 + 深化审计 |
| m16_review_audit_report.md | §12 | M16 落地复核 |
| m19_real_link_acceptance_report.md | §14 | M19 移交语义真实链路验收 |
| m20_llm_v4_report.md | §15 | LLM 调用链路最新化 |
| m21_exec_execution_report.md | §16 | 思考模式真实执行力验收 |
| m22_prompt_guidance_report.md | §17 | 工具调用执行力提升 |
| m23_chain_completeness_report.md | §18 | 动作链完整性引导 |
| m24_adj_step_report.md | §19 | 必调整场景设计 |
| m25_wording_report.md | §20 | RULE-AI-08 措辞强化 |
| m26_sample_report.md | §21 | 样本量扩展复测 |
| m27_signal_report.md | §22 | 注入信号规模扩展 |
| m28_restore_report.md | §23 | 注入信号规模恢复 |
| m30_model_compare_report.md | §25 | 换模型复测 |
| m32_cmd_boundary_report.md | §27 | 命令句再强化边界评估 |
| m33_four_principles_audit_report.md | §28 | 四原则合规体检 |
| m34_ux_revisit_report.md | §29 | AI 使用体验回访 |

> 注：ai_guidance_playbook.md 关联 §24（playbook 沉淀）/§26（v1.1 增补）/§29（回访建议）；M31 无独立报告（playbook v1.1 增补并入 §26）。映射基于 spec §1-§30 章节号连续性核验。

## 四、playbook 关联

| 报告 | playbook 小节 | 小节主题 |
|:---|:---:|:---|
| m22_prompt_guidance_report.md | 1.1 | 工具存在性引导（RULE-AI-07） |
| m23_chain_completeness_report.md | 1.2 | 动作链完整性引导（RULE-AI-08） |
| m24_adj_step_report.md | 1.3 | 必调整场景配置表 |
| m25_wording_report.md | 1.4 | 措辞强化方法 |
| m26_sample_report.md | 1.5 | 稳定基线汇总表（达成率链） |
| m27_signal_report.md | 2.1 / 2.2 | 信号规模负结果 + 关键洞察 |
| m28_restore_report.md | 1.5 / 2.2 | 稳定基线 + 措辞杠杆洞察 |
| m30_model_compare_report.md | 1.6 / 2.4 | 模型对比实践 + 装配缺陷教训 |
| m21_exec_execution_report.md | 2.2 / 2.3 | 度量缺陷教训（负结果） |
| m32_cmd_boundary_report.md | 1.2 | "应调用"非"必须"复用指引 |

> 注：playbook 关联基于各报告结论在 playbook 中的沉淀小节，无虚构关联（design 26.6 核验）。

## 五、更新约定

1. **新里程碑产出报告时**：同步在本索引"报告清单"追加新条目（文件名 + 一句话摘要 + 类型 + spec 章节映射）——对齐 CHANGES.md 登记惯例（每里程碑在 CHANGES.md 登记）。
2. **spec 新增章节时**：同步更新本索引"spec 章节映射"表（新报告 ↔ 新章节号）。
3. **playbook 增补时**：同步更新"playbook 关联"表（报告 ↔ 新小节）。
4. **维护职责**：由各里程碑执行阶段负责（与 CHANGES.md 登记同步执行），文档规则承载，不程序化强制。

## 六、数据来源声明

- 本索引全部条目引自 docs/ 既有文档（26 文件标题/摘要 + spec §1-§30 章节号 + playbook 1.1-4.3 小节），**不引入新数据**（FR-IDX-TRC-01）。
- 驱动来源：docs/m34_ux_revisit_report.md §八（建议 1 内容设计）+ §九（拍板结果记录，M35 立项）——引用非改写。
- 如本索引与源文档不一致，**以源文档为准**（内容如实，不夸大导航收益）。

*（docs/ 文档导航索引 v1.0 完——M35 docs/INDEX.md 文档导航文件）*