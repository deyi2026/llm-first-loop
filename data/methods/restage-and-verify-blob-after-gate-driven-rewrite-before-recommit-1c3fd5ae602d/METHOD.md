---
method_id: restage-and-verify-blob-after-gate-driven-rewrite-before-recommit-1c3fd5ae602d
name: restage-and-verify-blob-after-gate-driven-rewrite-before-recommit
description: 提交被仓内内容闸（如 git_security_scan 禁本地绝对路径）拦截后，按仓内既定口径（从已跟踪同类文件与提交信息推导，如 $HOME 泛化）对文件做无损改写；此时 commit 消费的是索引快照而非工作树——若改写晚于上一次 git add，直接重试 commit 必被同一 finding 再拦一次。固定顺序 transform→add→commit，并把『暂存 blob 摘要==改写后文件摘要』作为提交前置校验；改写前后 sha256 记入提交信息留档。
aliases: 改完文件忘了重新git add, 提交第二次还是被同样问题拦, git commit 提交的是暂存区不是工作区, security scan 拦绝对路径怎么改才能提交, 泛化成$HOME了还是被拦
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:ce8b88af-7349-4903-91ab-b37a329e0489:519:7c9485b329e7bdc5fc46
evidence_refs: learning:learn:ce89753d98f8
created_at: 2026-10-28T16:56:27.773806+08:00
updated_at: 2026-10-28T16:56:27.773806+08:00
---
## Trigger
git 提交被仓内内容闸（security scan / pre-commit 内容检查）拦截，且已通过改写工作区文件来满足闸门，而改写可能发生在上一次 git add 之后

## Discriminator
闸门校验的是将提交的暂存 blob，不是工作树现状：凡『先 add 后改写』序列，索引里仍是旧 blob。重试前一条命令即可判定——git diff --cached（或 git ls-files -s 对应 blob）若不含改写结果，commit 必然复现同一拦截，与闸门是否误报无关

## Short path
- 首次被拦：以闸门点名的违规模式为唯一未知量；先从已跟踪同类文件与历史提交信息找仓内既定改写口径，不自行发明编码
- 按口径做无损改写：只替换违规编码，不动裁决/计数/结构字段；改写前后 sha256 备好写入提交信息
- 改写完成后重新 git add，顺序固定 transform→add→commit，绝不复用旧索引直接重试 commit
- commit 前核对暂存 blob 摘要与改写后文件摘要一致；一致才提交，预期闸门 PASS

## Stop conditions
- 暂存 blob 与当前文件摘要一致且闸门回执 PASS
- 闸门要求的是删除/轮换（密钥、凭据类）而非编码改写：停止改写分支，转清除+轮换并处理历史
- 仓内无同类先例且口径不明：先问维护者/查贡献文档，不猜口径提交

## Verification
- git diff --cached 能看到改写后的文本，或 ls-files -s 指向的 blob 内容摘要==文件摘要
- commit 后提交内该文件 blob 与本地文件摘要一致，闸门/CI 回执 PASS
- 提交信息含改写前后摘要，原始文本可复核

## Counterexamples
- 违规物是 secret/token：不允许泛化或占位符化后照常提交，必须清除并轮换凭据
- 闸门在 push/审查侧（如 push 前需独立审查 PASS 凭据）而非 commit 侧：重新 add 无济于事，须先走审查流程
- 改写会篡改记录真值（如回执里登记的 sha 本就描述旧文本）：只允许可逆编码替换，原始摘要必须在提交信息留档
