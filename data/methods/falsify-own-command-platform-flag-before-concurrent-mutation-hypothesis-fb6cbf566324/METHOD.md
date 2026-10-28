---
method_id: falsify-own-command-platform-flag-before-concurrent-mutation-hypothesis-fb6cbf566324
name: falsify-own-command-platform-flag-before-concurrent-mutation-hypothesis
description: 只读探针（ls/stat/find）失败且错误文本缺失或含糊时，若片刻前的权威索引（git status 等）仍显示目标存在、且环境信号（如 /Users/ 家目录路径）指向非 GNU 用户态，应先把失败归因于自己的命令用了平台专属 flag，用一次无 flag 的裸探针判别，而不是假设目标被并发移动并展开全树定位搜索。判别成立后直接换可移植等价命令（macOS 用 stat -f / ls -lT）一次取全所需元数据。本集把 BSD ls 拒绝 --time-style 误读成'施工线正在移动文件'，触发全树 find 超时与连环重试，而 stat -f 一发即中。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f3bcb24f-1f02-4da7-aaad-75bb446ffa88:1329:c4ab679acb3b9f7ab548
evidence_refs: learning:learn:390625f78e36
created_at: 2026-10-16T11:35:08.055852+08:00
updated_at: 2026-10-16T11:35:08.055852+08:00
---
## Trigger
只读探针（ls/stat/find 等）异常退出且错误文本缺失或含糊，同时（a）片刻前的权威索引（如刚取的 git status / 目录列表）仍列出目标对象，存在性证据未被证伪；（b）环境信号（pwd 显示 /Users/... 等）表明可能是非 GNU 用户态；（c）尚无并发写者实际动作的直接证据，只有'可能正在变更'的猜测。

## Discriminator
探针失败那一刻已知的两条事实：pwd 已打印 /Users/<user>/Project/...（macOS/BSD 用户态信号，GNU 专属 flag 如 ls --time-style 大概率不被支持）；且一步之前的 git status 已把目标文件列为存在（?? 未跟踪条目）。两条合起来把候选解释从'文件被并发移动'缩到'命令 flag 被平台拒绝'——一次无 flag 的裸 ls <path>（stderr 可见）即可判别，无需任何宽搜索。

## Short path
- 探针失败时先做最小判别重试：同一目标、去掉全部平台专属 flag 的裸命令（如 ls <path>），确保 stderr 可见；未知量：失败属于命令自身还是目标消失/被移动？
- 裸命令成功 -> 归因为 flag/平台不兼容，立即改用可移植等价命令（macOS: stat -f '%Sm %N' -t fmt 或 ls -lT）一次取全所需元数据，不再重复原命令
- 裸命令报 No such file -> '目标被并发移动'假设此时才成立，改做受限定位（指定目录、限深度 find），绝不做全树搜索
- 元数据到手即回到任务主线（本集为进程/日志/时间线核对与结论输出），停止一切探针与定位类枚举

## Stop conditions
- 裸探针成功且可移植等价命令已取得所需元数据 -> 停止所有定位/搬迁假设类搜索
- 已确认失败归因于命令 flag 而非目标缺失 -> 撤销并发变更假设，不再为它花费动作

## Verification
- 对比重放：仅带平台专属 flag 的版本失败、裸版本成功 -> 平台不兼容归因成立
- 最终取得的文件路径与元数据和权威索引（git status 所列路径）一致，且任务所需事实（修改时间/进程/日志）均来自该一致来源

## Counterexamples
- 权威索引很旧或取自不同 cwd（索引目录与当前 pwd 不一致），其'目标存在'证据不约束当前探针 -> 并发移动仍是合理假设，本方法不适用
- 裸命令本身报 No such file or directory -> 目标确实缺失，应走定位/并发变更分支而非 flag 归因
- 环境确为 GNU Linux，所用 flag 本身合法，失败另有原因（权限、挂载、符号链接断链）-> 平台 flag 归因不成立，需另找判别探针
