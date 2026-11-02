---
method_id: search-hit-path-enoent-resolve-via-tracked-file-index-721555815ee9
name: search-hit-path-enoent-resolve-via-tracked-file-index
description: 内容搜索命中目标文件后，对显示路径直接 grep/read 报确定性 ENOENT（父目录确实存在、非超时/权限）时，说明索引展示路径被规范化/剥前缀，不是文件系统真值；第一个未知量是真实路径而非文件内容。收口动作：git ls-files | grep -i <basename> 一次解析权威路径（顺带拿到同名测试簇），随后只在真实路径上定点操作。避免猜前缀变体重试、原样重发重命令烧超时预算、或退回全量文件枚举。未跟踪新文件改用 find；permission denied 属另一失败类。
aliases: 搜索命中的路径打不开, 搜索结果路径和实际文件对不上, grep 说文件不存在但搜索刚命中, 搜索被 venv 噪声淹没怎么办, 按文件名反查仓库真实路径, 索引路径和磁盘路径不一致
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:7e91da8b-4d11-4df5-84fc-7666790cb2fb:242:ac6944525b69f21080b5
evidence_refs: learning:learn:d39a164c2a88
created_at: 2026-10-31T21:25:16.280632+08:00
updated_at: 2026-10-31T21:25:16.280632+08:00
---
## Trigger
内容搜索回执已给出目标文件的 basename 与精确命中行，但对该显示路径的直接访问报 'No such file or directory'；或内容命中被未跟踪 vendor/.venv 树噪声淹没、且仓库存在 git 跟踪索引可用作权威路径源

## Discriminator
回执冲突本身：搜索索引说该路径存在（还给出精确行号），文件系统说 ENOENT，而目录列表确认父目录存在——两侧证据都可信时，唯一被证伪的是'显示路径=真实路径'这一假设

## Short path
- 内容搜索命中目标标识符，记下 basename 与命中行内容，不把显示路径当真值
- 对显示路径直接访问得到确定性 ENOENT → 判定显示路径被规范化（前缀被剥）
- 单次权威解析：git ls-files | grep -i <basename> → 真实实现路径 + 同名测试文件（一次拿到制品簇）
- 在真实路径上定点 grep 常量/标识符并读关键段落，回到原任务；后续所有读写基于解析后路径

## Stop conditions
- 已从 git 索引（或 find）取得真实路径，并在其上读回与原搜索命中行一致的内容
- 不再对原显示路径或其猜测前缀变体发出任何重复命令

## Verification
- 用解析出的真实路径 grep 原命中标识符/常量，行内容与搜索回执一致
- 确认后续 grep/read/test 均使用解析后路径，无第二次同因 ENOENT

## Counterexamples
- 目标文件是本轮新建、未被 git 跟踪：git ls-files 查不到，应直接用写入回执路径或 find 限定工作区
- ENOENT 源于拼写/大小写笔误而非索引口径：basename 肉眼比对即可修复，无需索引解析
- 搜索工具回执自带已 stat 的绝对路径：显示路径即真值，直接读取
- 失败是 permission denied/沙箱拦截而非 ENOENT：路径可能本就正确，应走授权分支
- 未知量是'哪个文件含此语义'而非'此文件真实路径'：那是内容搜索的活，索引解析不替代语义定位
