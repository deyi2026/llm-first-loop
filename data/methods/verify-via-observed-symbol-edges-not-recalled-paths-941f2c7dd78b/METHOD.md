---
method_id: verify-via-observed-symbol-edges-not-recalled-paths-941f2c7dd78b
name: verify-via-observed-symbol-edges-not-recalled-paths
description: 核验关于代码行为的声明时，下一步读哪个文件应由本轮搜索回执推导（定义命中、唯一调用方命中、消费者命中），而不是凭记忆猜测目录布局；搜索结果中的 evals 快照/worktree 镜像拷贝应过滤掉，只认 canonical 活树根；file-not-found 与精确 no-match 回执对该路径就是终局判定，不应触发进一步的文件名枚举或重复搜索。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:855926d8-3b7a-4a6d-9c5e-34631b59df2b:19:7390a5864f0be87c67dd
evidence_refs: learning:learn:29173ce0e5f0
created_at: 2026-09-19T08:40:44.325239+00:00
updated_at: 2026-09-19T08:40:44.325239+00:00
---
## Trigger
需要核验外部（评审方）或自身关于具体函数/机制的事实声明，且即将打开的文件路径来自记忆而非本轮任何命中回执；或搜索输出中混入同一源码树的多份镜像拷贝（evals/results、.context-integrity-wt 等）导致命中列表膨胀。

## Discriminator
最早的符号搜索回执已同时给出：该符号的定义位置（file:line）、生产调用方（如 renew_lease 的 sole caller coordinator.py:116），且所有活树命中共享同一 canonical 根前缀；而凭记忆回忆出的路径从未出现在任何命中列表中——这足以把『去哪读运行边界行为』从全目录枚举缩为一个确定的下一跳。

## Short path
- 对声明中的每个符号做精确 search_files，从回执记录三类边：定义位置、生产调用方、消费者；把命中过滤到 canonical 活树根，忽略镜像拷贝。
- 直接读定义区域，对声明给出机制级判定（如 cumulative vs rolling TTL），不读周边无关区域。
- 需要运行边界行为时，沿回执中的 caller 命中读该文件，而不是猜测兄弟/同名路径（如不存在的 fleet/runner.py）。
- 对 guard/authority 类声明，再搜该 guard 符号的全部消费者，确认覆盖面（如 mutation authority 全库仅 browser 一处消费）。
- 缺失类声明用精确符号 no-match 回执作验证；所有声明均有活树 file:line 锚定后立即进入实现，不再探测已登记不存在的路径，不再重复同一搜索。

## Stop conditions
- 每条声明都有基于活树定义/调用方/消费者读取的判定，且引用的 file:line 均在 canonical 根下。
- 收到 file-not-found 回执后立即停止该路径的一切探测，改走符号搜索或向用户求证。
- 不再存在阻塞实现决策的未知量（声明的真值、覆盖面、缺失项均已由回执锚定）。

## Verification
- 逐条声明核对：判定引用的是活树 file:line，而非 evals/results 或 worktree 镜像中的拷贝。
- 缺失类声明必须由活树上精确符号搜索的 no-match 回执支撑。
- 用于行为推理的调用方确实是由消费者/调用方搜索确认的（唯一）生产调用方，而非假设。

## Counterexamples
- 符号只存在于 evals 快照或 worktree 镜像中，活树无边可沿——此时应定位真实源码树或询问用户，而不是沿镜像边走。
- 声明本身就是『某文件/功能不存在』——精确 no-match 搜索即答案，沿定义/调用方边反而是绕路。
- 定义命中仅出现在测试文件中且生产调用方未知——一次范围受限的文件名搜索是合理的，不应被此方法禁止。
- 路径来自本会话刚刚被工具回执确认过的结果——直接读即可；本方法只约束凭记忆回忆的目录布局。
