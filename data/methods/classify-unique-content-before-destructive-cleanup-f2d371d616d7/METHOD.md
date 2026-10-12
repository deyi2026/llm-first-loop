---
method_id: classify-unique-content-before-destructive-cleanup-f2d371d616d7
name: classify-unique-content-before-destructive-cleanup
description: 面对批量删除/合并 workspace、worktree 等条目且删除不可逆时，不要逐个打开条目或先做宽枚举，而是用一次确定性脚本从权威注册表(git worktree list --porcelain)对每个条目算出分类：已并入基线 / AHEAD(可能是 squash 残留) / detached / 有未提交改动 / 孤儿目录(在文件系统但不在注册表)。'已并入+干净+久未动'即安全删；AHEAD 需内容等价检查区分 squash 残留与真未合并；dirty、detached、孤儿中含独有内容者先固化为 branch/tag/ref 再删。删除时写可恢复 manifest，最后只把价值判断类决策留给用户。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f88bda21-3714-409e-a903-eeb08b562780:0:3643193d8025a7a35f1b
evidence_refs: learning:learn:e68f1eff23f4
created_at: 2026-09-22T23:26:33.689366+00:00
updated_at: 2026-09-22T23:26:33.689366+00:00
---
## Trigger
用户要求清理大量可再生性未知的工作区条目（worktree/workspace/分支/快照目录），操作不可逆且条目可能含未合并、未提交或未注册的独有内容

## Discriminator
一次 worktree list 已给出每条目的 path+branch+HEAD+detached；随后每条目一次 status 计数 + 与基线的 merge-base + 最后提交时间，即可把 N 个候选压成三类：安全删（MERGED 且 tracked_dirty=0 且 stale）、需查等价（AHEAD，可能是 squash 合并残留）、需保全（dirty/detached/孤儿目录）。'MERGED+clean' 这条事实就是安全删除的充分判据，无需再枚举文件系统或逐个打开 worktree

## Short path
- 单次 porcelain 清单调用取全量条目（path/branch/detached），未知量：有哪些待清理对象
- 一条循环对每条目算 status 计数、与基线 merge-base、最后提交时间，未知量：谁安全、谁存疑
- 注册表与文件系统目录做差找孤儿目录，并用进程检查确认无运行中占用，未知量：注册表之外还有谁
- 对 AHEAD 分支跑内容等价性计数（not_equiv/already_in），未知量：squash 残留还是真有未合并工作
- 删除前把独有内容固化为可恢复 ref：dirty 提交到 preserve 分支、detached 独有提交打 tag、孤儿目录独有文件移入归档
- 删安全类并写含一键恢复命令的 manifest；仍属价值判断的少数决策（大体积旧归档去留、未合并修复是否合入）上报用户而非自决

## Stop conditions
- 所有条目已归入'已验证并入/等价'或'独有内容已固化为 ref'两类，无未分类残留
- 剩余问题属于用户价值判断（旧数据去留、是否 cherry-pick）时停止并上报，不自行扩大操作范围

## Verification
- 删除后注册表只剩预期存活条目
- 每个被删条目的 tip 提交仍可达（分支保留或已建 preserve 分支/tag），脏文件存在于 preserve 分支
- manifest 中的恢复命令对任一被删条目可执行
- 并入/等价判定使用同一最新基线，避免拿旧基线把已合并内容误判为 AHEAD

## Counterexamples
- 条目可再生且用户已明确授权直接删（构建缓存、可随时 re-clone 的远端工作副本）——全量审计是浪费，直接删
- 仅两三个 worktree 且状态一目了然——分类脚本开销超过收益，逐个人工看更快
- 对象不在任何注册表内（纯目录堆放的工作区）——注册表驱动分类不适用，需先做内容级比对
- 存在运行中服务从某 worktree 启动——合并状态分类让位于活性检查，先解决占用再谈删留
