---
method_id: ignore-stack-audit-before-editing-negation-safe-dir-star-00c008a4e2c5
name: ignore-stack-audit-before-editing-negation-safe-dir-star
description: 当 git 忽略结果与声明意图矛盾（反选例外失效、知识资产在 git status 不可见）时，把忽略判定当作多源栈（嵌套 .gitignore > 根 .gitignore > .git/info/exclude > core.excludesFile）处理：先读全栈每个源再动笔编辑，找意图已在哪层表达，在权威（入库共享）层修复、本地 exclude 只留机器私有增量；写目录排除永远用 dir/* + !dir/keep/ 而非裸 dir/（父目录被整棵排除后任何反选都救不回）；放宽后 check-ignore 双向实测并清点历史被遮蔽资产浮出。
aliases: exclude 压过 gitignore 负规则, gitignore 反选例外不生效怎么查, 目录整棵排除导致 ! 救不回, 改 exclude 前先读全忽略栈, 新目录被忽略规则挡住不入库
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9982762e-d202-481b-9ca3-178124e943de:4381:78fba4020a4b9b935f25
evidence_refs: learning:learn:fa0714ed26d2
created_at: 2026-10-26T07:34:00.152178+08:00
updated_at: 2026-10-26T07:34:00.152178+08:00
---
## Trigger
忽略/遮蔽结果与意图矛盾：.gitignore 反选例外不生效、应入库的资产目录（method/experience 等）在 git status 长期不可见、check-ignore -v 把责任指向某个尚未读过的忽略源；或需要新增/修改目录级排除且该目录未来可能需要子路径例外。

## Discriminator
check-ignore -v 实测回执已指名决定性规则所在的具体源与行号；而忽略判定天然横跨多个源。在只读过其中一个源时，『意图已在别处表达、只是被更粗规则压过』与『意图根本没写』无法区分——这个未读事实必须在任何编辑动作之前用一次廉价读取（cat/grep 相关前缀）解决，否则会在本地 exclude 里复制出与 .gitignore 重复的策略，留下双源漂移。

## Short path
- 对代表性路径跑 git check-ignore -v，确证遮蔽并拿到决定性来源（文件:行）
- 一次性读全忽略栈中与目标前缀相关的规则段（根/嵌套 .gitignore、.git/info/exclude、core.excludesFile）——未知量：意图已在哪层表达、是否被裸 dir/ 粗规则压过
- 在权威层修复：若 .gitignore 已有正确意图，删除本地 exclude 里压过它的冗余粗规则，而不是把反选复制进 exclude；仅对 .gitignore 未覆盖的机器私有路径在 exclude 写 dir/* + !dir/keep/
- check-ignore -v 双向实测：应放行样本须无命中或 ！ 负命中，应排除样本仍命中预期规则
- 放宽后清点浮出的历史被遮蔽资产（git status --others 目标子树），交归属筛查分批处理，不一次全收
- 涉共享策略或需人工决策的事项登记 EVO/review 后停止

## Stop conditions
- 双向 check-ignore 全 PASS，且冲突/冗余粗规则已在正确层级移除
- 历史浮出资产已清点并进入归属/人工流程，未擅自批量 add
- 改的是入库共享的 .gitignore 时已走评审而非本地独断

## Verification
- git check-ignore -v：应放行路径无命中或负规则命中，应排除路径命中预期规则行
- git status / ls-files --others 中应放行子树可见、运行时状态文件仍不可见
- 修复后决定性来源指向预期的权威规则行，而非被删的粗规则

## Counterexamples
- 粗规则本身在入库的 .gitignore（团队共享策略）里：不能本地删除，本地 exclude 也无法反选被更高优先级源排除的父目录——必须改 .gitignore 并走正常评审
- 遮蔽是刻意的（密钥、大二进制、运行时状态）：不应放宽，方法不适用
- 单人草稿仓库、.gitignore 与 exclude 同为本地文件：分层权威性区分消失，就地最小修复即可
- 路径不可见的根因不是忽略栈而是文件确实不存在或在别的 worktree：先查存在性，别调忽略规则
