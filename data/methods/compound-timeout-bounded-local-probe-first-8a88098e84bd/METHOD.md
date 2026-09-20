---
method_id: compound-timeout-bounded-local-probe-first-8a88098e84bd
name: compound-timeout-bounded-local-probe-first
description: 复合命令链（本地段在前、网络段在后）在工具超时上限被截断、各段完成状态未知时，不要重跑整链、也不要执行混合本地+网络的'全面核查'——其网络部分会再次挂死，再耗尽一个超时窗。利用先验分区：本环境此前所有纯本地操作回执均秒级返回，故超时几乎必然落在网络尾段或锁上。先用零网络、天然有界的本地探针确定本地前缀落点，再用带硬上限的分端点探测（curl -m 逐 host）测各网络通道死活；通道独立失败时把网络余段转后台有界重试+定时续跑，本地终态单独核验并如实汇报。预防面：本地确定性操作与慢网络尾段不要捆绑进同一个有界调用。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:32d694c9-dbcd-4dc8-a941-0885c617868c:840:6fa72dfbbf7ac621f096
evidence_refs: learning:learn:9de579af1a72
created_at: 2026-09-19T23:56:26.499144+00:00
updated_at: 2026-09-19T23:56:26.499144+00:00
---
## Trigger
复合命令链（本地 git/文件操作在前，push/gh/远端调用在后）收到工具级超时回执，commit/stage/push/PR 等各段完成状态未知

## Discriminator
超时回执本身 + 此前全部纯本地操作回执均为秒级成功（knowledge-at-time 可用）：说明挂点在网络尾段或锁，而非本地段；本地段完成态可完全用零网络探针（git log -1 / status / ls .git/index.lock / ps）测出，无需触碰网络

## Short path
- 收到复合链超时回执 → 未知量：本地段（commit/stage）是否已落定？先不重跑整链、不跑混合核查
- 零网络有界探针：git log --oneline -3、git status --porcelain、ls .git/index.lock、ps 查残留进程 → 直接读出本地真实落点
- 若探针见 index.lock 或残留进程：先清锁/清进程再复探（探针事实优先于先验）
- 分端点硬上限探测网络通道：curl -m 10 逐 host 分开测（如 git 传输 host 与 API host 各测一次），用内建上限而非 GNU timeout（macOS 无此命令）
- 本地已完备且某网络通道不通：push/PR 等余段转后台有界重试循环（次数×间隔）+ 定时续跑；当前会话只做本地终态核验，如实汇报阻塞点与已落定事实
- 预防复用：后续把本地确定性操作与网络尾段拆成独立调用，使超时可分区定态

## Stop conditions
- 本地各段落点已由零网络探针完全确定（commit 哈希可见/工作区干净/无锁无残留进程）
- 每个网络端点通道的死活均已被硬上限探测分别测出
- 发现锁/残留进程并已处置、探针复核通过
- 网络余段已交由有界后台任务承担，会话内不再重复发起会挂死的同步网络调用

## Verification
- 本地探针读出的状态与后台任务最终输出一致（commit 哈希、push/PR 结果）
- 最终汇报中每条状态均对应一次已测量的探针或通道结果，而非推断
- 重试任务有界（明确次数与间隔），不会无限占用会话；探针命令本身无网络依赖、秒级返回

## Counterexamples
- 超时的是单一长本地操作（如对 683M/8.6 万文件目录的构建或全量扫描）：本地秒级先验不成立，应后台化或提高上限，而非假设网络挂死
- 探针发现 index.lock 或残留 git 进程：本地前缀可能并未完成，分区假设让位于探针事实，先解锁清进程
- 链完全无网络段且操作幂等只读：直接安全重跑即可，分区定态只增加开销
