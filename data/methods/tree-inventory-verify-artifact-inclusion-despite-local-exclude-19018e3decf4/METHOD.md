---
method_id: tree-inventory-verify-artifact-inclusion-despite-local-exclude-19018e3decf4
name: tree-inventory-verify-artifact-inclusion-despite-local-exclude
description: 冻结/提交一个验收要求『候选树中必须包含指定生成产物』的候选时，add/commit 成功回执与 git status 清洁都不是产物已入库的证据：本地 ignore 面（.git/info/exclude、全局 excludesfile）会让目标文件被静默跳过且零报错，所有常规信号全绿。本集因此先冻出缺产物的候选 A，被迫 add -f 重冻候选 B（SHA 全换）。正确做法：提交后立刻用 tree 清单（git ls-tree -r HEAD）对照『必须入库产物』清单逐项核对；缺项逐文件 add -f 补录并重新冻结，不改共享 ignore 面（避免波及 main 与其他 worktree）。
aliases: commit 成功但产物没进库, add 了文件提交里没有, 本地 exclude 吃掉产物, 冻结候选缺文件怎么查, status 干净但 tree 缺产物
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:59d664ee-98e2-4f7f-bf0b-79cdb910e980:418:1acde68f02607f8482e5
evidence_refs: learning:learn:6d31c0e52ae7
created_at: 2026-11-13T21:03:57.486315+08:00
updated_at: 2026-11-13T21:03:57.486315+08:00
---
## Trigger
冻结/提交的候选带有『独立复核者只凭冻结候选即可复核指定产物』类验收；且仓库存在本地 ignore 规则面，或上一轮审查已出现过『提交成功但产物缺失』的同源发现（已知复发风险）。

## Discriminator
被本地 exclude 的文件既不出现在 untracked 列表、也不会让 add/commit 报错——即没有任何失败信号可依赖；唯一能判别产物是否真正入库的观测面是提交后的 tree 清单本身。若上一轮已有产物缺失类审查发现，本风险在冻结前即为已知事实。

## Short path
- 冻结前把验收项逐条映射成『必须入库产物』的精确路径清单
- 提交后立即 ls-tree -r --name-only HEAD，与该清单逐项对照（不信 status/commit 回执）
- 缺项→逐文件 git add -f 补录（不编辑共享或本地 exclude，防止影响 main 及其他 worktree），重新冻结并记录新 commit/tree SHA 与指纹
- 在冻结树上复算产物哈希，确认独立复核者只凭候选即可复核
- 清单全命中即停；把『exclude 排除项（如 runtime lock）确实不在树内』作为双向验证一并记录

## Stop conditions
- 冻结候选的 tree 清单覆盖全部必须产物，且 SHA/指纹/测试回执在档
- 确认应排除项（运行时锁、探针垃圾）确实不在提交树中——此时静默排除是期望行为，禁止 add -f

## Verification
- git ls-tree -r HEAD 逐项包含每个应入库产物路径
- 从冻结树内容复算产物 sha256 与回执一致
- check-ignore 双向验证：应排除的被排除、应入库的未被忽略

## Counterexamples
- 产物本就不应进版本库（runtime *.lock、临时探针）→ 静默排除正是目标，add -f 反而制造垃圾提交
- 忽略规则全部来自版本库内共享 .gitignore（可审查、对所有 worktree 一致）→ 常规提交流程即可，tree 核对降为可选
- 无验收绑定的一次性草稿仓库或纯本地提交 → 不需要此核查，徒增成本
