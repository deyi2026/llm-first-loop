---
method_id: exclude-masked-landing-dir-audit-relocate-single-file-not-unexclude-dc8279e416e7
name: exclude-masked-landing-dir-audit-relocate-single-file-not-unexclude
description: 当 exclude/gitignore 遮蔽的目录同时是治理约定的产物落点（审查回执、分析记录）时，或要为新产物给入库/存放建议时，先用 tracked 数/在盘数/最近提交日期三项只读测量定性：「旧文件已跟踪、新文件被遮蔽」不等于「目录不受版本控制」。建议因此从『移除 exclude/整目录搬家』翻转为『单文件迁移或 add -f』；改写 exclude 前必须 git add -n 干跑验证（d/ 后 !d/sub/ 无效，须写 d/*）；规则文本与实测落点冲突时，作为二选一上报而不是停在含糊态；同时可检出『指定目录静默停止接收提交』的断链。
aliases: git add 不进新文件但旧文件还在库里, gitignore 反选子目录不生效, 回执目录很久没有提交了怎么查, ignored 目录里单个文件要不要进版本控制, exclude 把审查回执链弄断了, 怎么判断目录是不是真的没被 git 管理
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:ccfcc676-9c54-41d9-8c5c-5dab5ce0e5b2:144:f4b2b44fc589635391e1
evidence_refs: learning:learn:44d8c876c8ed
created_at: 2026-11-09T23:50:06.978162+08:00
updated_at: 2026-11-09T23:50:06.978162+08:00
---
## Trigger
即将对 exclude/gitignore 遆蔽目录下的产物给出存放/入库/搬迁建议（放哪、能不能 add、要不要改 ignore），或需要根据规则文本/上一轮断言判断某目录是否受版本控制、约定产物链是否仍然活着

## Discriminator
一次测量分离状态：git ls-files <dir>|wc -l（跟踪数）vs 在盘文件数 vs git log -1 --format=%cs -- <dir>（最近提交日）vs git status --porcelain --ignored 的 !!。tracked>0 且最近提交停在旧日期、新文件全 !! → 旧跟踪新遮蔽（exclude 只拦新增 add，不作用已跟踪文件），『拿掉 exclude』会暴露全部被遮蔽草稿。改写放行模式必须 add -n 实测：d/ 后接 !d/sub/ 会被 git 拒绝，须写成 d/* + !d/sub/ + !d/sub/**

## Short path
- 用手中已有的精确文件名（回执/分析文档名）直接定位目标产物，不做全目录 ls，也不对含 .releases/ 快照树的仓库做文件名宽搜
- 一组只读测量（跟踪数/在盘数/最近提交日/check-ignore -v 命中行）给目录定性，纠正『不受版本控制』这类未实测断言
- 处于『旧跟踪新遮蔽』时：默认建议是把单文件迁入有同类先例且未被忽略的目录，或 git add -f；不动 exclude（拿掉会放行上千草稿）；仅当确认『产物必须进历史』才改写 exclude，且先用 add -n 验证 d/* 否定形式
- 把规则文本点名的落点与实测状态对账；不一致时作为『改 exclude 还是改规则』的二选一显式上报，不留在中间含糊态（共享 ignore/规则文本变更需人工授权）
- 每条建议附带可执行验证命令后停止，不再枚举目录其余内容

## Stop conditions
- 每条存放建议都带已实跑的验证回执（add -n / ls-files / log），而非由规则文本推断
- 落点目录状态已标注：跟踪 N / 在盘 M / 最近提交日期 / exclude 来源行
- 治理文本与实测的冲突已变成显式决策点交给用户，未获授权不自行改 exclude 或规则

## Verification
- git add -n <目标路径> 干跑：建议路径可 add，且同目录其他被遮蔽文件仍不进暂存
- git log -1 --format=%cs -- <落点目录> 对照在盘新增文件量：新文件全 !! 且日期停更 → 断链成立
- 改写后的 exclude 模式用 git check-ignore -v 在真实路径上指到预期行
- 迁移后 git ls-files 含该文件；涉及规则文本时跑对应 SoT/sync 锚点测试

## Counterexamples
- 目录 tracked=0 且本应整体入库 → 正确建议是移除 ignore 或加目录，不是单文件搬迁
- 回执不入库本身就是设计的 local-only 行为、无规则指定版本化落点 → 『断链』不是缺陷，不要制造问题
- 下游工具硬编码原路径、搬文件会破坏消费方 → 用 add -f 保路径，放弃整洁
- exclude 位于团队共享 .gitignore，改写是团队级变更 → 本组针对本地 .git/info/exclude 的判断不适用，须人工决策
- 上一轮断言无具体锚点且不可只读测量 → 直接做常规发现，跳过整套状态审计
