---
method_id: serve-content-needs-from-local-pinned-copy-before-remote-refetch-57c6ba5369cb
name: serve-content-needs-from-local-pinned-copy-before-remote-refetch
description: 当目标代码库/包已被克隆或下载到本地并固定在某一版本后，获取回执里的文件清单本身就是『内容已在本地』的判别事实；后续需要树内文件（README、manifest、changelog 等）时直接读本地副本。对同一文件改走远端抓取不仅多一次网络往返，还引入版本偏差风险——远端分支内容未必等于被审计的 pin 版本，却容易被当作同一来源引用。远端通道只保留给本地确实缺失的对象：发布产物、其他版本、上游 diff。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:136b8530-addf-4ead-941f-0a53520c54d8:47:277a7e141f40822691d6
evidence_refs: learning:learn:f44fa6cc22d2
created_at: 2026-10-11T19:18:59.628831+08:00
updated_at: 2026-10-11T19:18:59.628831+08:00
---
## Trigger
已通过 clone/download 拿到某个 pinned 版本的 artifact 树，之后需要读取树内文件内容来回答用户问题。

## Discriminator
获取动作的机械回执（clone 输出的文件清单、随后的目录列表）在抓取动作之前就已明确列出该文件存在于本地工作树，且本回合的分析对象正是这个 pinned 版本。

## Short path
- 拿到 clone/download 回执后先扫一遍文件清单，标记目标文件是否已在本地
- 需要内容时直接读本地路径，不对同一文件再发起网络请求
- 仅当清单中没有该文件、或需要的是另一版本/发布产物/上游差异时才走网络通道，并记录来源与版本
- 答案中版本相关的引用注明来自本地 pinned 树

## Stop conditions
- 已从本地副本取得所需内容，且其版本与被分析对象一致

## Verification
- 回答中引用的版本敏感事实（版本号、badge、changelog 行）能对应到本地 pinned 树内的文件
- 若答案混有远端来源，确认其针对的是与本地不同的对象（如已发布 tarball），而非同一文件的重复获取

## Counterexamples
- 需要的是与本地 checkout 不同的版本内容（例如 registry 上已发布的 tarball 与仓库 HEAD 可能不一致）——此时远端/registry 抓取是正确动作，本集内对已发布 package.json 的核对即属此类
- 任务问的是上游最新状态，而本地 clone 已落后于远端 main
- 目标文件根本不在 clone 内（被 gitignore/LFS/submodule 排除），本地读取会失败，必须走远端
