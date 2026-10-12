---
method_id: exhaustive-hit-list-as-change-manifest-773f35db6472
name: exhaustive-hit-list-as-change-manifest
description: 修改在多处重复定义或被测试钉住的字面常量/默认值时，把穷举搜索返回的命中清单直接当作修改清单：每处要么同步更新、要么显式记录保留理由（区分“机械传播默认值的 pin”与“有意的行为契约”），全部闭合后才验证；测试须以独立命令运行并直接观察退出码，禁止把 verify 与 commit 链进会吞退出码的管道。本例 pre-edit grep 已列出另一测试文件的两处 pin，却只改其一，导致两测试失败且 commit 落在红测上，事后失败行号正是 grep 早已给出的。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:2448:d61d45a1047ca0aaae93
evidence_refs: learning:learn:ed6aaa683a35
created_at: 2026-09-18T09:20:17.070428+00:00
updated_at: 2026-09-18T09:20:17.070428+00:00
---
## Trigger
需要修改一个在多处重复定义/钉住的字面常量或默认值（符号常量、config 字段默认、env 回退默认、测试断言 pin），且可用一次穷举搜索列出全部出现点。

## Discriminator
编辑前的穷举搜索输出已包含完整命中清单，尤其是否出现测试文件中钉住该字面值的断言行。本例 grep 在任何编辑前就列出 test_smc_browser_live_perception_v01.py:227/286 的 max_frame_bytes=67_108_864；命中测试行即预告“不改必红”，无需等 pytest 事后暴露。

## Short path
- 由失败 diag 定位根因与待改常量；用一次穷举搜索（src+tests）取得全部出现点，作为唯一修改清单。
- 对每个命中显式分诊：机械传播默认值的 pin→同步更新；有意行为契约/失败路径 fixture→保留并记录理由。
- 一轮完成全部编辑后，重跑同一搜索确认旧字面值零未分诊残留。
- 以独立命令运行测试并直接观察退出码与失败清单；verify 未绿前不执行任何状态变更（commit/部署）。
- 绿灯后才提交，并用触发本次修改的原始场景（如大页 CDP snapshot）做端到端复测。

## Stop conditions
- 重跑出现点搜索，旧值残留均为显式分诊保留项。
- 测试独立运行且退出码被直接观察为 0（非管道推断）。
- 原始失败模式（如 frame_too_large）在新值下不再复现。

## Verification
- re-grep 旧字面值，逐条核对残留是否有记录理由。
- pytest 单独执行、退出码直接可见之后才 commit。
- 各默认位点（符号常量、config 字段、env 回退、测试 pin）数值一致。
- 用真实触发场景复测通过。

## Counterexamples
- 命中断言是有意行为契约：如测试故意设 1MiB 小上限验证 1009 失败路径，或断言内存安全硬上限不变，更新它等于摧毁测试意图，应保留并重新审视改动本身。
- 常量只有单一权威定义、其余均通过符号引用（无重复字面值）——直接改一处即可，穷举清单无增益。
- 同值命中属于数值巧合的其他子系统或历史记录（changelog/git 历史），不可机械全改，必须逐条语义分诊。
