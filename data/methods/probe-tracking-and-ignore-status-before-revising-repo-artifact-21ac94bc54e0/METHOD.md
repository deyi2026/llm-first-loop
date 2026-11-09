---
method_id: probe-tracking-and-ignore-status-before-revising-repo-artifact-21ac94bc54e0
name: probe-tracking-and-ignore-status-before-revising-repo-artifact
description: 修订一个磁盘上已存在、预期随提交/分支交付的仓库文档前，先把『它是否被跟踪/是否被 exclude 遮蔽』当先决未知量解析：文件确实存在却不出现在 git status 的 ?? 未跟踪清单里，唯一解释是路径被 ignore；一条 `git check-ignore -v` 加 `git ls-files` 即可证实并点名遮蔽规则出处。被遮蔽路径上写完后的空 diff / status 不显示 ≠ 没写成功，而是从未被跟踪、无法 commit。应在投入内容修订前把『移到被跟踪路径还是解除 exclude』作为用户决策浮出，不擅自移动文件或改共享 exclude。本集该边界直到 14 处修订全部落盘后才在收尾紧急披露，把交付形态问题拖成了收尾悬念。
aliases: 改完才发现提交不上去, 写入了但 git 看不到改动, 修订前先确认文档进不进版本库, 文件不在未跟踪清单里是什么意思, 收尾才发现产物没被跟踪
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:ccfcc676-9c54-41d9-8c5c-5dab5ce0e5b2:36:130397e78259c526e1cc
evidence_refs: learning:learn:e7d06283bced
created_at: 2026-11-09T23:32:07.336421+08:00
updated_at: 2026-11-09T23:32:07.336421+08:00
---
## Trigger
即将修订一个已存在于磁盘、且预期要作为仓库交付物（随分支/提交交付）的文档；开局或早前的 git status 回执里，该路径既不在已跟踪集合、也不以未跟踪条目形式出现在 ?? 清单中。

## Discriminator
文件可读、确实存在（马上要被编辑），却同时缺席于 tracked 集与 `??` 未跟踪清单——这是路径被 exclude/gitignore 遮蔽的可观察判别信号。用 `git check-ignore -v <path>` 一条命令证实并取得规则文件与行号。注意 git status 会把未跟踪目录折叠成 `?? dir/`，所以结论必须靠 probe 命令，不能靠目测清单缺席。

## Short path
- 定位目标文档路径后、读全文/动手修订之前，先跑 `git check-ignore -v <path>` 与 `git ls-files <path>`，一次解析『被跟踪 / 正常未跟踪 / 被遮蔽』这个先决未知量。
- 若被 ignore：在写任何内容前向用户浮出交付决策（移到被跟踪路径 / 解除 exclude / 明确仅工作区交付），或显式记录『本交付物不进版本库』约束后再继续。
- 若已跟踪或正常未跟踪：照常进行内容复核与原子写入，preflight 是廉价 no-op。
- 写入后用 `git ls-files <path>` / `git diff --stat` 加工具写后回读一致来确认改动真实落盘；遇到空 diff 先查 ignore，而不是怀疑写入失败或重写。

## Stop conditions
- 跟踪状态已由 check-ignore/ls-files 权威确认，且若被遮蔽，用户已拿到交付路径决策点。
- 环境不是 git 仓库，或任务本身规定该产物仅在工作区本地生效——不再做该探测与决策浮出。

## Verification
- `git check-ignore -v <path>` 命中并给出规则文件与行号，或无输出且 `git ls-files` 列出该文件——两种结果都必须有命令级回执，不靠清单目测。
- 修订落盘后核对 `git ls-files <path>` 在场性；被遮蔽路径上以文件级 sha/回读一致证明改动存在，并确认最终答复向用户声明了跟踪边界。

## Counterexamples
- 产物按任务定义就是工作区本地/临时文件（故意不入库的记录），跟踪状态已知 by design，preflight 与决策浮出都是噪音。
- 文件是本次运行新建的：它不在早前 status 的 ?? 里是平凡事实，不能拿旧回执推断被 ignore；probe 必须针对当前状态跑。
- 目标文件本就已被跟踪：check-ignore 无输出、ls-files 命中，preflight 不改变任何后续路径，也不应触发用户决策询问。
