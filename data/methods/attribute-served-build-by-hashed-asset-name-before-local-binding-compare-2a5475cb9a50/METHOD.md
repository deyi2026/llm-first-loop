---
method_id: attribute-served-build-by-hashed-asset-name-before-local-binding-compare-2a5475cb9a50
name: attribute-served-build-by-hashed-asset-name-before-local-binding-compare
description: 重启/发布后核验静态前端改动是否生效时，先取线上入口 HTML，提取其引用的 content-hashed 资源名并下载，grep 改动唯一标识——『生效与否』当场有答案。未生效要根因时，不要拿工作区 dist 的 binding/清单当线上证据：hash 不同即不同对象。以线上 hash 文件名在所有构建树（工作区 dist、.releases/<sha> 快照等）反查同名文件来归属『实际服务根』，多命中用快照 mtime 对齐重启/进程启动时间消歧，读该树 binding 得部署源 SHA，再对修复提交做 ahead/behind+包含检查，定死部署线与修复线的分叉关系，并据此判断 restart 无效、需要 update/publish。不必回溯自己早前构建产物去了哪。
aliases: 线上到底在跑哪个构建, 重启了前端还是旧版怎么定位, 工作区 dist 和发布产物混淆, 线上 bundle 查不到新文案, 部署的是另一条分支, 服务根归属
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:1ee6738f-0a1e-46fa-9522-fd9f35a8933a:628:08e9375805586c0e848a
evidence_refs: learning:learn:d8d1117d2b01
created_at: 2026-10-27T19:49:19.750909+08:00
updated_at: 2026-10-27T19:49:19.750909+08:00
---
## Trigger
重启/发布后被问『改动是否生效』，服务以入口 HTML 引用 content-hashed 静态资源，且仓库同时存在多个候选构建树（工作区 dist、release 快照、CI 产物）可被误当线上对象

## Discriminator
线上入口 HTML 里的 hashed 资源名（index-<hash>.js）是内容地址：与工作区 dist 当前 hash 不同，即证明工作区构建不是被服务对象；同名 hashed 文件只存在于哪个快照树，那个树就是服务根，且其 mtime 应不早于本次 restart 时间

## Short path
- curl 线上入口 → 提取 hashed 资源名并拉取该资源；未知量：被服务的构建是否包含本次改动
- 对被服务资源 grep 改动的唯一标识（新文案/新符号/新字段名）；『生效与否』此步即有确定答案
- 未生效时：在全部构建树中按该 hash 文件名反查同名文件；未知量：实际服务根是哪棵树（不读工作区 binding，不找自己早前的构建产物）
- 多命中用快照 mtime vs 重启/进程启动时间消歧，读服务根内 binding/source SHA；未知量：部署的到底是哪个 git head
- 对该 head 与修复提交做 ahead/behind 计数+包含检查；未知量：修复为何缺席、restart 还是 update/publish 才能改变结果

## Stop conditions
- 被服务资源对改动标识的 grep 已给出确定 yes/no，且服务根对应的 git head 与修复提交的血缘关系已定

## Verification
- 服务根内 binding 的 source SHA 与快照目录名/控制面回执 git_head 一致
- 服务快照 mtime 不早于本次 restart 时间，且线上入口引用的 hash 与该树文件名一致
- 『不在部署历史』的结论必须来自 ahead/behind+包含计数，而非单点 SHA 查询（cherry-pick 会换 SHA）

## Counterexamples
- dev server 直接服务工作区 dist（线上 hash 与工作区一致）→ 直接字节比对即可，不需要快照反查
- 资源名不带 content hash（固定文件名）→ 文件名不是内容地址，改用 binding 文件/进程 cwd/stat 做归属
- 用户只问『重启是否成功』（进程层）→ 回执+进程启动时间足够，无需构建归属与分支血缘分析
