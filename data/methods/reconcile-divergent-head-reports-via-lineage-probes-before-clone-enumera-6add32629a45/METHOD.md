---
method_id: reconcile-divergent-head-reports-via-lineage-probes-before-clone-enumera-6add32629a45
name: reconcile-divergent-head-reports-via-lineage-probes-before-clone-enumeration
description: 两个组件对同一仓库报出不同 HEAD SHA，或服务自报版本串与源码树版本不一致时，先把这些标识当作谱系探针在权威 checkout 上跑只读判定：git cat-file 测对象归属、merge-base --is-ancestor 测先后 vs 分叉、git describe --tags 逐字节比对 describe 格式版本串内嵌的 g<shortsha>、进程回执的 git_head/cwd/启动时间钉住运行代码。四项短输出探针即可区分『同谱系时间先后（旧报告/旧代码进程）』与『独立 clone/worktree』，不必先枚举 worktree/remotes 全清单，也不需重启验证。仅当对象不存在或 cwd 外指才转入枚举分支。
aliases: 两个HEAD对不上先查祖先关系, Console和本地HEAD不一致怎么判, 服务版本比源码旧是旧进程吗, git判断是不是同一个clone, 版本串里的g短SHA当探针
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6b58eeb0-73eb-421f-ace1-50ae51782327:31:3265b88fd2dce9e904ac
evidence_refs: learning:learn:c187ff9f0130
created_at: 2026-11-07T13:09:35.019220+08:00
updated_at: 2026-11-07T13:09:35.019220+08:00
---
## Trigger
两个独立组件/控制面对『同一仓库』报出不同 HEAD SHA（如远端 Console 报的 HEAD vs 本地 Host HEAD），或常驻服务自报版本串与源码树 pyproject/HEAD 不一致，且当前处于只读约束，需要判定是分叉 clone、独立 checkout 还是同一谱系的时间先后。

## Discriminator
对方报出的标识本身可作谱系探针：完整/短 SHA 可用 cat-file 测对象是否属于本仓库、merge-base --is-ancestor 测先后或分叉；describe 格式版本串内嵌 g<shortsha>，可与 git describe --tags <sha> 逐字节比对；运行时回执（进程 git_head、启动时间、cwd 线索）在首轮已可用——这四类当时已存在的廉价只读探针足以把『所有 clone/worktree 都有可能』缩成一两个假设，无需先收集 repo 全量清单。

## Short path
- 把每个被质疑标识当探针，在权威 checkout 逐一跑 cat-file 存在性 + merge-base --is-ancestor，先解决『同谱系时间先后 vs 分叉/外来对象』这一未知量
- 版本串为 describe 格式时：对内嵌 shortsha 跑 git describe --tags 逐字节比对，并测其是否为 HEAD 祖先，解决『进程跑的是哪份代码、新旧关系』
- 用进程回执的 cwd（lsof）与启动时间 vs 争议提交时间戳，钉住『同一 checkout 的旧代码 vs 独立 checkout/release 分离』
- rev-parse origin/main 与本地 HEAD 实测对齐，声明唯一权威 main
- 只有 cat-file 失败（对象不在本仓库）或 cwd 指向其他 checkout 时，才扩大到 worktree list / remotes / 其他 clone 枚举

## Stop conditions
- 四类探针（存在性/祖先/describe 逐字节/cwd+启动时间）结论一致，身份未知量已闭合
- 对象不存在或 cwd 外指——停止本路径，转入枚举分支
- 无法物理接触报告方实例时，结论止步于『同谱系、无分叉证据』，不得升级为『已证明同一 clone』

## Verification
- cat-file、merge-base、describe 逐字节、cwd/启动时间四项回执相互一致，且与争议标识逐字符对上
- 权威 main 声明以 rev-parse origin/main 与本地 HEAD 的最新实测对齐为据（多会话活跃仓库中分钟级旧快照可能已过期）
- 结论措辞强度与证据级别匹配：谱系证明不等于物理 clone 归属证明

## Counterexamples
- 自报版本是无内嵌 SHA 的纯版本号（如 0.6.40）——describe 探针不可用，应改用部署实例运行时自身的 desired/live 回执或文件指纹作身份证据
- 浅克隆/部分克隆中对象存在但祖先链不完整——merge-base 不可判定，需 fetch 或换证据面
- 两报告确实来自另一台主机的部署实例——本地谱系只证明共同历史，不能定位报告来源，应对该实例自身端点取证而非本地仓库
