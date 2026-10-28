---
method_id: live-tree-first-discovery-under-snapshot-mirrors-and-excludes-9a0fe7ca5ab2
name: live-tree-first-discovery-under-snapshot-mirrors-and-excludes
description: 在含 .releases/ 类发布快照镜像、且本地启用了 git exclude 的仓库里定位文件或判断存在性时，先消费已在手的输出再发起新发现：用早前输出的同类路径样例直接推导目标路径，用文件系统枚举判定存在性，全局文件名搜索只作最后手段且按"非快照目录"过滤。本集全局搜索约95%命中是快照副本，git status 的缺席在 exclude 激活时被误读成"文件不存在"，各造成一次失败/错误结论。效果是把"全仓候选集"缩成"活跃树唯一命中"。
status: active
source_model: glm/glm-5.3
source_episode_refs: episode:f5c1ffa0-2841-47fa-898f-b45a8c54ef12:9:1b8f6e318c295cac58e1
evidence_refs: learning:learn:fd4efd32d030
created_at: 2026-10-18T14:52:45.205059+08:00
updated_at: 2026-10-18T23:33:26.110418+08:00
---
## Trigger
需要在含发布快照镜像目录（如 .releases/<hash>/ 多副本）且 git status 输出带 exclude 段的仓库里，定位某个文件/测试/脚本的准确路径，或依据 git status 未列出某文件而推断其不存在时。

## Discriminator
两个当时已可见的事实：其一，早前 git status 输出已列出同类目标的路径样例（如 ?? tests/unit/test_*.py 已揭示测试布局在 tests/unit/ 下），可直接推导目标路径而无需猜约定路径；其二，上一次全局文件名搜索的命中绝大多数来自 .releases/ 快照副本、活跃树命中唯一，且 search_files 已在 src/ 命中的文件在 git status 中不出现——这两点足以把"再猜路径/再全局搜"缩成"沿样例直接验证 + 用文件系统枚举判存在"。

## Short path
- 发起定位动作前先回扫已收集的工具输出，找同类目标的路径样例（untracked 列表、先前 find/search 结果），按样例前缀直接读取或枚举目标子树
- 判断"文件是否存在"只以直接文件系统枚举为证据源；若 git status 带 EXCLUDE 段且 search 已命中该文件而 status 未列出，立即断定被 exclude 隐藏而非缺失，不再据此下"不存在"结论
- 确需文件名搜索时，把结果按"快照镜像目录=.噪声、活跃树=信号"过滤，只对活跃树命中分配后续动作
- 活跃树取得唯一命中且路径前缀与已知样例一致即停，不用变体词重复搜索确认

## Stop conditions
- 活跃树中已取得目标唯一路径，且其存在性有直接文件系统枚举证据
- 已确认 git status 未列出目标的原因（被 exclude 隐藏 vs 真缺失），不再混淆两种解释
- 连续两次搜索的活跃树命中完全相同（快照噪声不产生新信息）

## Verification
- 采用的每个路径，核对其前缀与早前输出中的同类路径样例一致
- 每个"存在/不存在"结论都能指向一次直接文件系统枚举记录，而非仅 git status
- 复查最终采纳的命中不在 .releases/ 等镜像目录下

## Counterexamples
- 仓库不含快照/镜像目录时，全局文件名搜索本就是低成本首选，先挖路径样例反而多余
- 任务目标本身在历史快照中（复现旧版本行为、对比 release 差异）时，.releases/ 命中是信号而非噪声，不应过滤
- git status 无 exclude 段且问题是 tracked-state（而非文件系统存在性）时，status 未列出就是有效证据，无须机械改跑 find
