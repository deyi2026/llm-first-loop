---
method_id: sandbox-write-root-anchored-at-workdir-not-shell-cd-7e0cfb29f114
name: sandbox-write-root-anchored-at-workdir-not-shell-cd
description: 沙箱 shell（回执注明仅允许写工作区/缓存目录）下，对工作区之外的目标仓库执行写操作（commit/merge/落回执）时，命令内 cd 到仓库只换来读权限，写一律 Operation not permitted：写白名单锚定在工具调用的 workdir 参数（沙箱根），不随 shell cwd 移动。判别靠一次写探针矩阵：cwd 可写、仓库根/.git 不可写、同路径只读 git 命令全部成功。命中即直接显式传 workdir=仓库根重锚，一次探针复验后继续任务；不再枚举写边界、不复制仓库绕行。注意 isolation=true 与显式 workdir 互斥（隔离树根即 cwd），报参数错误时二选一换模式，而非重试同一组合。
aliases: cd 了还是写不了仓库, touch 报 Operation not permitted, 沙箱里提交不了代码怎么办, sandbox 只读仓库怎么写, 隔离模式不支持指定目录
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:62423b4e-2e2c-44f3-82e5-45126a6bce95:112:c065475bd25f12478b33
evidence_refs: learning:learn:8f638bc862f3
created_at: 2026-10-26T14:54:29.456680+08:00
updated_at: 2026-10-26T14:54:29.456680+08:00
---
## Trigger
沙箱化 shell（如 macOS sandbox-exec，banner 声明『仅允许写工作区与缓存目录』）中，需要对位于工作区之外的仓库执行写操作（git commit/merge、落盘回执/文件），或写前需要探明写权限边界

## Discriminator
写探针的不对称结果：session 工作区内 touch 成功；同一仓库根、.git、.releases 下 touch 返回 Operation not permitted；而同一路径的只读 git 命令（status/log/merge-tree 预览）全部成功——这把候选从『文件权限坏了/git 问题/需要换工具』缩成『按路径划定的沙箱写根，需要用工具参数重锚』

## Short path
- 写类动作前跑两行探针：touch <workspace> 与 touch <repo root>；前者成功后者 EPERM 即命中（若 sandbox banner 已写明允许写根=工作区/缓存且目标仓库在其外，可跳过探针直接重锚）
- 把整条命令以显式 workdir=<repo root> 重新发出，使沙箱写根锚到仓库；命令内不再依赖 cd 获取写权
- workdir 模式下再探针一次写（或直接执行目标写操作看退出码），成功即继续合并/提交/落回执
- 若显式 workdir 被拒且错误文本说明 isolation=true 的隔离树根即本次 cwd：在 isolation 与 workdir 两种模式间二选一切换，不重试同一组合

## Stop conditions
- workdir 重锚后写探针或首个写操作成功：立即停止权限枚举，回到任务本体
- workdir 模式下仍 EPERM：判定为磁盘级只读或宿主沙箱配置问题，升级给用户/调配置，不复制仓库绕行

## Verification
- workdir 模式下 touch+rm 探针（或实际写操作退出码 0）确认写权已获得
- 核对读写同源：workdir 传入的仓库根与此前只读收集事实所用路径一致，确认没有在副本/镜像上做写操作

## Counterexamples
- 仓库文件本身只读或属主不符（磁盘权限问题）：重锚 workdir 无效，应修权限或请用户处理
- 本次只需只读事实（status/log/diff/merge-tree 预览）：无需重锚，直接 cd 读即可，不要多此一举
- EPERM 出现在 SIP 保护的系统路径：与沙箱写根机制无关，路径重锚不适用
- 所用工具根本没有 workdir/isolation 参数：正确动作是换执行通道或申请配置变更，而不是反复换 cd 措辞重试
