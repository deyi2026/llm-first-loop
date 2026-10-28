---
method_id: reconcile-verification-set-with-change-manifest-before-green-6270b7b51333
name: reconcile-verification-set-with-change-manifest-before-green
description: 以"测试套件全绿"作为改动放行/合并判据时，退出码绿不等于验证完整：先用净改动 manifest（diff --stat / name-status）提取新增或修改的测试文件清单，并与验证运行实际收集/执行的文件集及已知基线计数做集合差；差集非空或总数低于基线，即存在已进改动但未被验证的面，先只补跑残留再宣布全绿。本集曾以 7 套件 138 passed 判绿，而同一批输出的 diff stat 已列出新增 tests/web/test_artifact_hydration.py、分支基线为 8 套件 140，补跑 2 passed 后账目才闭合，避免了带着未执行的新测试进入原子合并。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6c50a13c-1fe0-4283-ac06-c9bca4e9d637:647:f39d524f373ff0d04d68
evidence_refs: learning:learn:22a1d87c7c13
created_at: 2026-10-17T06:50:55.041533+08:00
updated_at: 2026-10-17T06:50:55.041533+08:00
---
## Trigger
对一次改动（merge/rebase/patch/重构）运行验证套件并准备以"全绿"作为放行、收口或合并判据，且该改动的 diff manifest 中存在新增/修改的测试文件，或存在可对照的历史/分支基线验证计数

## Discriminator
同一批工具输出中已并存两个可直接对照的事实：净 diff manifest 列出的新增/变更测试文件清单，与验证运行实际执行的套件数/文件集（含分支基线总数）；二者集合差非空、或执行总数低于基线计数，即当场证明存在已进改动但未被验证的文件——无需任何额外探测即可判定验证不完整

## Short path
- 产出净改动 manifest：用 diff --stat / name-status 提取本次新增与修改的测试文件（及其他可验证产物）清单
- 运行验证套件时同时捕获其实际收集/执行的文件集与总数（套件计数、collection 输出），并与分支/历史基线计数对照
- 计算差集 = manifest 测试文件 − 已执行文件；执行总数相对基线的缺口作为第二判据
- 差集非空 → 仅针对残留文件补跑，再全量对账；差集为空且计数与基线一致 → 才允许宣布"验证全绿"并进入放行/合并动作
- 在放行回执中同时记录 manifest 清单、执行清单与最终计数，证明对照确实发生而非仅凭退出码

## Stop conditions
- 差集为空且执行总数与基线一致（或差异可解释且已作为排除项记录）
- 改动 manifest 不含任何测试文件或可验证产物（纯文档、归档移动类改动），此时套件退出码即可收口

## Verification
- 补跑的残留测试文件全部通过，且全量重跑总数与基线对账一致（本集 138 → 140 闭合）
- 放行/合并回执中可同时追溯 manifest 清单与实际执行清单，两清单的对照关系成立

## Counterexamples
- 纯 docs/归档类改动，manifest 中无测试文件：无需对照，套件绿即可收口，强行对账是空转
- 新增测试文件在当前环境被显式 skip 或依赖真机等不可用资源：差集残留是预期内的，应记录为排除项并转入后续任务，而不是在本环境补跑（如本集真机门经用户裁定转独立 goal）
- 测试由运行时动态生成、文件名与用例无稳定映射：文件名集合差不可靠，应改用 collection/执行输出本身作为对照基准
