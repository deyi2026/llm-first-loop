---
method_id: assertions-as-spec-first-for-behavior-edits-c1f836aa31cd
name: assertions-as-spec-first-for-behavior-edits
description: 修改既有行为/指标口径（分母、判定规则、文案）时，把测试断言点当作当前行为的权威契约：先做一次跨 src+tests 的 grep 定位目标符号的定义点与断言点，从断言中的期望值与 note 文案反推现行口径，再让实现与断言同批修改、三处口径一致（实现/断言/note），按受影响子集→全量顺序验证。避免先分块通读上千行源文件、最后才'看看测试了解现有规范'导致的口径返工与调用数膨胀。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d8f59859-1341-4560-9f92-9163e49963d5:161:006dc3f353fbb307035d
evidence_refs: learning:learn:564e98e5de28
created_at: 2026-09-30T09:02:05.878126+08:00
updated_at: 2026-09-30T09:02:05.878126+08:00
---
## Trigger
任务为修改/优化既有实现中的行为或指标口径（如改某指标分母、判定规则、note 文案），且早前 find/grep 回执已列出对应测试文件；此时尚未查看这些测试对该符号的断言。

## Discriminator
测试中对目标行为存在精确断言（期望值、比率、note 文案），且这些测试文件路径在更早的列目录/find 回执中已出现——断言点本身就是'当前契约+必改面'，一次 grep 即可在通读源码前获得。本 episode 中模型读完两个约 540 行源文件后才执行 'grep honesty tests/unit/test_evaluator.py'，而该 grep 一次就给出了精确现行口径（含 note 原文）。

## Short path
- 把变更清单逐项映射到文件/符号（此类任务起点通常已有明确项列表）
- 对目标符号做一次 src+tests 的 grep，得到定义点与断言点清单
- 只精读断言点附近与定义点区域：从断言的期望值/note 反推当前口径（分母、单位、文案）
- 实现与断言同批修改，保持实现、断言、note/文档三处口径一致
- 先跑受影响单测子集，绿后再全量测试与 lint 各一次收尾

## Stop conditions
- 受影响单测子集通过，且 grep 确认 src 与 tests 中无旧口径残留字面值（旧期望值、旧 note 文案）
- 实现、断言、note 三处口径一致；全量 suite 与 lint 已各跑一次并绿

## Verification
- grep 目标符号及其 note/文案关键字，确认无旧口径残留
- 先跑受影响测试子集再跑全量；若有失败，先核对是否为断言与实现的口径差而非环境问题

## Counterexamples
- 全新功能/新增指标（无既有断言可作 spec）：grep-first 无对象，仍需按现有结构阅读源码并新写测试
- 纯结构重构、行为不变：断言是回归护栏而非变更面，通读定义仍然必要
- 目标文件很小或变更覆盖大半文件：整体阅读成本低，先读全文件不构成绕路，不必强套本方法
