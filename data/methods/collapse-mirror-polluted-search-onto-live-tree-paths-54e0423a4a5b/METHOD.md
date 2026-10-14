---
method_id: collapse-mirror-polluted-search-onto-live-tree-paths-54e0423a4a5b
name: collapse-mirror-polluted-search-onto-live-tree-paths
description: 仓库级内容搜索的命中被带版本前缀的冻结镜像目录（如 .releases/<hash>/ 快照）大量重复污染时，立即把候选空间折叠为去前缀后的活树路径集合：镜像命中视为噪声，对活树文件做作用域内 grep/read 定位符号与行号，不再追加仓库级全量搜索、不读镜像副本当当前事实。仅当符号只存在于镜像（历史 release 考古）时镜像才是目标。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b1e2c610-ff59-483f-a50b-9ef6586aaae0:426:b519e2a53d170cd5ec70
evidence_refs: learning:learn:d3446237723d
created_at: 2026-10-14T16:43:56.716968+08:00
updated_at: 2026-10-14T16:43:56.716968+08:00
---
## Trigger
对代码库做仓库级文件名+内容搜索以定位符号或调用点，回执命中列表大量来自共享版本前缀目录（.releases/<hash>/ 等冻结快照），且同一相对路径存在无前缀的活树命中

## Discriminator
命中回执中，镜像路径去掉 .releases/<hash>/ 前缀后与列表顶端的活树命中同符号重复（同文件同符号甚至同行号）——此刻活树目标文件路径已可直接从回执导出，无需再做全仓搜索

## Short path
- 从首批搜索命中剥离版本前缀目录并按相对路径去重，得到活树候选文件集（src/ 与 tests/ 的具体路径）
- 对该活树文件集做作用域内 grep（目标符号、状态机/枚举字面量）拿行号与定义位置，不发起第二次仓库级搜索
- 按行号 read_file 目标区段确认契约后直接进入实现
- 后续所有定位与回读命令的作用路径均不含镜像前缀

## Stop conditions
- 活树目标文件与关键符号行号已确定，改动点已定位到具体函数
- 发现符号仅存在于镜像目录，转为以镜像为目标的考古模式

## Verification
- 后续每条 grep/read 命令的作用路径都不含镜像前缀目录
- 最终改动的文件相对路径与最初命中折叠出的活树路径一致
- 镜像命中未再被读取或当作当前版本事实引用

## Counterexamples
- 任务目标本身就是某个历史 release 的内容（活树已改写或删除）——镜像命中是唯一真值，折叠会丢目标
- 命中全部来自测试文件且无 src 命中——测试是合法的行为契约发现面，不是噪声
- 仓库没有快照/镜像目录——直接正常搜索，无需折叠
