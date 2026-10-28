---
method_id: job-receipt-embedded-command-pins-run-paths-before-filename-search-5b65acb00e1e
name: job-receipt-embedded-command-pins-run-paths-before-filename-search
description: 受管作业（job/task）状态回执里逐字嵌入的启动命令本身就是该次运行全部工件与代码树的权威 provenance 锚：日志绝对路径 = cd/cwd + 重定向目标；作业实际加载的源码树 = cwd（被 --code-source/--workdir 类标志钉死）。在含多个 worktree/镜像副本的工作区里，应先从命令串推导这些路径，而不是按文件名全局搜索——同名源码文件会命中一堆镜像拷贝，命中列表不提供任何判别信息。注意边界：运行期数据/锁目录这类由 env/config 解析链决定的路径，命令串答不了，仍须代码追踪。
aliases: 正在跑的作业把日志写到哪了, 同名源码文件搜出一堆worktree拷贝选哪个, job回执命令行里就有路径, eval跑批输出文件怎么定位, 先拆cd和重定向再搜文件名, 多克隆工作区找作业真正用的那棵树
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:89aa4eb4-d3e8-4612-9858-cce4b0fe5b6d:2191:d091411fdd6c2324b90a
evidence_refs: learning:learn:b74edaa04736
created_at: 2026-10-26T18:42:44.568590+08:00
updated_at: 2026-10-26T18:42:44.568590+08:00
---
## Trigger
需要定位某次可查回执的受管作业所写入的日志/输出文件、或该作业实际使用的源码树与配置，而工作区含多个克隆、worktree 或 .releases 镜像副本，存在按文件名搜索会命中大量同名拷贝的风险时

## Discriminator
作业状态回执中是否已逐字包含完整启动命令——若命令串里有 cd/cwd、输出重定向路径、code-source/workdir 类标志，则日志位置与代码树已被完全钉死，任何文件名发现都是零信息增益；反之若回执缺命令或只含相对路径且服务 cwd 不可知，才需要发现

## Short path
- 查作业状态回执：确认运行状态的同时，从嵌入命令串提取 cd/cwd、重定向目标、code-source/workdir 标志（未知量：这次运行写哪里、用哪棵树）
- 用 cwd + 重定向目标拼出日志绝对路径；用 cwd + 用户诊断已给出的模块相对路径拼出作业实际使用的源码文件路径（未知量：诊断所指实体在哪棵树的哪个文件）
- 把回执推导出的锚点写进委派书/后续动作，并显式区分两类未知量：代码树与日志位置已由回执钉死；运行期数据目录解析链（env/config 决定的 data/lock 目录）是回执不可解的，须作为独立代码追踪任务移交
- 仅当回执缺命令、命令只含相对路径且服务 cwd 未知、或目标从未出现在任何回执/引用/用户线索中时才做发现，且把发现限定在已钉死的树内，树外命中一律按镜像副本排除

## Stop conditions
- 日志路径、作业源码树、修复落点（canonical 主树）三个锚点均已由回执加工作区纪律导出且互相一致，无剩余路径类未知量
- 回执不可解的未知量（如数据目录解析链）已明确标注并作为代码追踪任务移交给执行者

## Verification
- 读到的日志/源码路径必须落在回执命令 cd 所指的树下；若仍做了文件名搜索，核对全部命中是否位于该树内，树外命中视为镜像副本不采用
- 委派书中『核对作业实际用的文件』的路径应与回执推导路径一致，而非搜索命中列表中任选的一条

## Counterexamples
- 回执只给相对路径且服务进程 cwd 不可知：命令串无法钉死绝对位置，应回退到有界发现（如 live-tree-first 类方法），本卡不适用
- 未知量是运行期数据/锁目录的解析结果（由 env/config 链决定，与命令 cwd 无关）：回执答不了，必须读配置解析代码——本集根因（data 目录落在镜像 release 目录）即属此类
- 目标文件从未被任何回执、命令或用户线索提及的全新发现需求：不存在 provenance 边，文件名/目录发现是正当第一步
- 同名日志由多个作业并发写入：须先按 job id 消歧而非按文件名搜索后猜测
