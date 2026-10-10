---
method_id: pull-bug-contract-blocks-before-source-work-1816d48afc09
name: pull-bug-contract-blocks-before-source-work
description: 把结构化审计/缺陷报告拆成工作包后，开工每个包前先用一次确定性区间抽取取回该包全部 BUG 块（依据/复现/修复边界/验收），再按块内引用行号读源码、先写红测。本集可见的绕点：已开始读 errors.py/fallback.py 之后才自认“此前只读了工作包概述”，回头用 awk 补取 BUG-02..05 的精确复现与验收矩阵。概述级 acceptance 不足以支撑红测与最小修复，差距本身是开工前的行动信号。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:18e51b8e-580f-47b5-a867-ad21b62684b1:19:6b7b740327406488e7f2
evidence_refs: learning:learn:f1c6df33fd6d
created_at: 2026-10-08T18:47:17.034502+08:00
updated_at: 2026-10-08T18:47:17.034502+08:00
---
## Trigger
用户要求按审计/缺陷报告修复；报告按 ‘### BUG-XX’ 块组织且每块含 依据/复现/验收 小节；工作包任务只携带概述级 acceptance。

## Discriminator
报告的分块结构当时已可见（早期 hydration 已露出 ‘复现输入与结果’ 表与依据行号格式），即每个缺陷的复现输入、引用文件行号、验收矩阵可由一次 ranged 抽取确定性取回；而当时手里只有概述级 acceptance——这一可观察差距在动第一行源码前就存在。

## Short path
- 建包时只记录 BUG-ID 到工作包的映射，不把概述当完整契约
- 开工某包前：一次 awk/sed 区间抽取该包全部 BUG 块，得到依据行号、复现输入、验收矩阵
- 只读块内引用的文件与行号范围（沿用本集已做对的动作：先 pin baseline 并核验目标文件未变，行号才适用）
- 由 复现+验收 先写红测，再做最小修复转绿
- 块内引用断裂或与当前树不符时，才扩大为宽读/重新定位

## Stop conditions
- 该包所有 BUG 块的验收项均已映射到具名回归测试并转绿
- 依据行号指向的内容与当前 baseline 源码一致，无需进一步发现

## Verification
- 红测在修复前确实失败，且失败签名与报告复现表一致
- 每条验收列表项（如 1302/1311/1113/未知码/403/5xx/SSE）能对应至少一个具名测试
- 不存在先改实现再回头配测试的顺序倒置

## Counterexamples
- 单缺陷小报告且概述已内联完整 依据/复现/验收——直接读码，无需再抽取
- 报告为自由叙述、无确定性分块结构——宽读源码属正当 discovery，不套用
- 报告绑定行号的 commit 与当前树不一致且目标文件已被改动——先重核 baseline/重定位行号，而不是沿用旧行号或沿用本方法
