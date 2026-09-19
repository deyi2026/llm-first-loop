---
method_id: transcript-artifacts-before-source-probing-eab39cf41436
name: transcript-artifacts-before-source-probing
description: 用户粘贴原始终端报错求助时，先从粘贴文本自身的可观测痕迹诊断病因：报错产生者是谁（shell 内建 vs 目标程序）、有无粘贴损坏痕迹（token 粘连、行内反斜杠）、提示符是否已显示目标 cwd。本例病因（换行丢失导致 cd 多收参数）在用户第一条消息里已完整可见，却先走了 7 次工具调用去定位并核对 CLI 源码。用报错文本把『命令/CLI 是否有错』先缩成『shell 层粘贴问题』，即可把搜索空间缩到零次探测；只有报错确实来自程序本身时才去读它的接口定义。这样更短：诊断所需的全部判别事实已在粘贴文本中，无需外部枚举。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5adf278f-405b-44db-95e5-3d3b94e1b8d9:850:51df1aa7d04442d8e8df
evidence_refs: learning:learn:b9c0d33ff960
created_at: 2026-09-19T12:17:41.552464+00:00
updated_at: 2026-09-19T12:17:41.552464+00:00
---
## Trigger
用户粘贴原始 shell 会话/报错作为任务输入，且报错产生者是 shell 层（cd: too many arguments、语法错误、token 粘连导致的 command not found），而非被调用程序本身

## Discriminator
粘贴文本中当时已可见的判别事实：(1) 目录名与 python3 粘连成一个 token；(2) 本应作为续行符的反斜杠变成了行内转义；(3) 报错来自 cd（shell 内建），说明命令从未到达目标程序；(4) 提示符已显示 cwd 即目标目录。四点合计即可把候选病因从『CLI 拼写/路径/参数错误』缩为唯一解释：粘贴时换行丢失

## Short path
- 从粘贴文本定位报错产生者：是 cd（shell 内建）报错而非 python/argparse，未知量『命令哪里错了』首先在 shell 解析层解决
- 检查粘贴痕迹：token 粘连 + 行内反斜杠 → 判定多行命令被压成一行、cd 收到多余参数，与报错文本完全一致
- 从提示符确认 cwd 已是目标目录 → cd 本可省略；用用户原命令的 token 逐字重组单行版命令
- 交付原因说明 + 可直接粘贴的单行命令后即停；仅当报错来自程序自身（如 argparse 报未知参数）才定位源码核对 CLI

## Stop conditions
- 报错原因已被粘贴痕迹唯一解释，且已交付可直接重跑的修正命令
- 用户所需仅为失败解释与可运行命令，无剩余未知量需要环境探测

## Verification
- 重组命令的每个 token 均可逐字追溯到用户粘贴原文，未引入任何未经验证的新参数
- 诊断与报错产生者一致：是 cd 收到多余参数，而非 python/CLI 层报错；若二者不符则回到第一步重新归因
- 若最终仍需引用源码（可选步），确认文件路径来自实际包布局发现（如 src-layout），而非根目录猜测

## Counterexamples
- 报错来自目标程序本身（argparse: unrecognized arguments、ModuleNotFoundError）→ 粘贴文本给不出正确 flag/模块路径，定位并读取真实 CLI/源码才是正解
- 粘贴无任何损坏痕迹且报错为 cd: no such file or directory → 病因是路径写错，应验证目录存在而非归因粘贴
- flag 系用户手写、该程序从未成功运行过 → 交付修正命令前快速核对一次源码 CLI 是合理且必要的
- 提示符显示 cwd 并非目标目录 → 不能建议省略 cd，需保留 cd 或改用绝对路径
