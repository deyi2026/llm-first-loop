---
method_id: version-surface-preflight-by-literal-grep-and-guard-test-a55eda6950e0
name: version-surface-preflight-by-literal-grep-and-guard-test
description: 在存在多版本载体（pyproject/代码内版本常量/双语 README/CHANGELOG）且自带版本一致性测试的仓库里准备发版或'版本面对齐'时，不按上一轮的记忆清单增量修改：先读权威版本源，再对 tracked 自有文本 grep 版本字面量模式枚举全部载体，并跑仓库自带一致性测试作为红绿 oracle；有漂移则一次性全表面对齐、复跑转绿后才打 tag。本集上一轮发版按清单漏掉 SERVICE_VERSION 常量与本地化 README 两面，一致性测试在 HEAD 长红未被察觉；本轮发版前两条机械 grep 即暴露漂移，修复后顺带发出新版本。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:152a76d5-3fea-40cf-8a6d-00de8ac369c2:464:ba98e584f175a8b3cbb2
evidence_refs: learning:learn:42ca114ce65a
created_at: 2026-09-24T10:15:04.672206+00:00
updated_at: 2026-09-24T10:15:04.672206+00:00
---
## Trigger
任务要求 bump 版本、打 release tag、publish 绑定 git_head，或声明'版本面已对齐'；且仓库存在多个版本载体、守护性一致性测试，或历史上出现过版本面漂移。

## Discriminator
发版动作前即可零成本取得的机械事实：(1) 权威版本源（如 pyproject 的 ^version）的当前值；(2) 对 src/ 或全仓 grep 版本字面量模式是否回显不一致旧值（本集 pyproject=X 而 routes.SERVICE_VERSION=X-1，两条 grep 一步暴露）；(3) tests/ 中是否存在版本一致性测试可作红绿 oracle。任一不一致即把'按记忆清单改两处'缩成'机械枚举全表面对齐'。

## Short path
- 读权威版本源确定当前与目标版本——未知量：基准值与增量
- 对 tracked 自有文本 grep 版本字面量正则（排除 lock/vendored/changelog 历史条目）枚举全部版本面——未知量：载体完备清单
- 用仓库惯用测试入口与正确解释器跑版本一致性测试，确认当前红/绿——未知量：是否存在既有漂移
- 有漂移则一次性对齐所有命中的面，复跑测试转绿——未知量：对齐是否完备
- tag 打在测试转绿的那个 commit，并核对 publish/release 回执绑定的 git_head 与之一致——未知量：对外承诺与树态一致

## Stop conditions
- 版本一致性测试在待 tag 的 commit 上为绿，且 grep 旧版本字面量仅剩 changelog 等历史性命中
- 仓库确认只有单一版本面且无守护测试时，权威源更新本身即为停止点，无需枚举

## Verification
- 在 tag 指向的 commit 上复跑版本一致性测试为绿
- repo-wide grep 旧版本字面量在自有代码与文档面零残留（有意保留的历史记录除外）
- publish/release 回执中的 git_head 与 tag commit hash 一致

## Counterexamples
- 单一版本面仓库（版本只在一处定义）——grep 枚举无增量收益，直接编辑更短
- 版本字面量大量出现在 lock 文件或 vendored 依赖中——grep 噪声淹没信号，必须限定 tracked 自有文件
- CHANGELOG 里的历史版本号是有意保留的记录，不属于'未对齐面'，不得改写
- 无 git、无一致性测试的一次性脚本目录——不存在多表面约束，预检只有成本没有收益
