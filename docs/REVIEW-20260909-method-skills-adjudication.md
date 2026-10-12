# 裁决清单：12 个未跟踪 method-* 技能（2026-09-09）

**事实基线**：skills/ 已跟踪 11 个操作类技能（cache-cost、incident-report、
md2pdf、swe-bench 等，12 个文件），**无一 method-\***；12 个 method-* 目录
全部 untracked。内容扫描：12 个 SKILL.md **零私有引用**（无绝对路径、
无 evidence:// / episode:// URI、无 research/localhost/deyi2026 提及）。

## 分层与逐条裁决

### Tier 1 · 成熟方法 → 建议入树（git add）

| 技能 | 行数 | 依据 |
|---|---|---|
| method-ab-experiment | 116 | A/B/qualification 实验纪律：锁自变量、隔离跨 run 状态、确认机制触发。泛化性强，与 docs/ 中 ablation 系列文档互证 |
| method-self-distill | 257 | 方法蒸馏元技能（本族生成器），族内最长、最成熟 |
| method-root-cause | 90 | 根因纪律：冻结 baseline→可证伪假设→单变量实验；与 R817 修复路径一致 |
| method-repo-api-discovery | 73 | 陌生/并行变化库的 API 一次查证法；与"当前定义+当前 callsite 才是真值"教训同源 |
| method-web-source-diagnosis | 83 | 网页来源诊断：先判 representation 再选工具，减少同参重试 |

建议命令（用户放行后执行）：
`git add skills/method-ab-experiment skills/method-self-distill skills/method-root-cause skills/method-repo-api-discovery skills/method-web-source-diagnosis`

### Tier 2 · 教师样板（3 个）→ 留观（不入树）

| 技能 | 行数 | 说明 |
|---|---|---|
| method-self-distill-ab | 38 | A/B 教师 exemplar，叙述内部工作集 receipts |
| method-self-distill-repo-api | 37 | 并行改动事故 exemplar，含"2026-09-03 必填参数变更"内部叙事 |
| method-self-distill-root-cause | 42 | relative-clock 事故 exemplar |

理由：内容虽零私有引用，但**叙事面向内部教学**，外部价值低于 Tier 1；
若入树建议降级为 `method-self-distill/exemplars/` 子目录。**默认留 untracked**。

### Tier 3 · 实验候选（4 个）→ 不入树，待 transfer qualification

| 技能 | 行数 | 自标注 |
|---|---|---|
| method-candidate-ab-validity-trigger-confound | 41 | experimental candidate only |
| method-candidate-current-callsite-refresh | 47 | experimental candidate only |
| method-candidate-hydrate-trace | 24 | experimental candidate only |
| method-candidate-relative-clock-never-state | 44 | experimental candidate only |

理由：SKILL.md 首行自述"Qwen3.8-27B 蒸馏实验 candidate，仅用于独立
transfer qualification，不代表 promotion"。入树会伪造 promotion 信号；
**qualification A/B 通过前一律 untracked**，不设期限。

## 汇总

- 入树候选：5（Tier 1）
- 留观：3（Tier 2，默认 untracked）
- 隔离待验：4（Tier 3，明确不得入树）
- 废弃：0（无内容损坏或过期技能）
- 公开移植面影响：untracked 目录不进入公开 port，无泄漏面。

---
*本清单只裁决，不执行任何 git add / 删除 / 移动。*
