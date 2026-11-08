---
method_id: plumbing-merge-via-verified-tree-identity-when-others-staged-files-block-9603b0860195
name: plumbing-merge-via-verified-tree-identity-when-others-staged-files-block-shared-worktree
description: 多会话共享 main 工作树里，已过队列/审查闸的合并被 git 以『会覆盖他人已 staged 未提交文件』拒绝时，不 stash、不 reset、不替人提交也不干等：先 merge-tree 预演合并树并与已独立验证的 lane 树做字节级等价证明；相等即用 commit-tree 造双亲合并提交、update-ref CAS 推进 main，再只把自己 lane 的路径 restore 进工作树，他人 staged 清单不动。仅适用于机械性索引阻塞；策略性守卫 fail-closed（如他人 active lane 挡 push）则接受拒绝，不规避。
aliases: git merge 被别人 staged 文件挡住, 不 stash 别人未提交的改动完成合并, 共享主仓工作树脏怎么合并, 先证明合并树一模一样再提交, commit-tree 造合并提交不动工作树
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:5ecfad99-3bb7-48d5-a854-2c6d3ca3727d:2031:a44ccc2399798ef1271e
evidence_refs: learning:learn:2a3e6256320f
created_at: 2026-11-08T13:17:47.025840+08:00
updated_at: 2026-11-08T13:17:47.025840+08:00
---
## Trigger
共享 main 检出区存在他人会话已 git add 未提交的文件，导致本会话已授权合并被 git merge 以会覆盖本地改动为由拒绝；或按已知共享状态可预判 porcelain 合并必被此类索引污染挡住

## Discriminator
拒绝原因可归为机械性索引污染而非策略门拒绝（他人 staged 路径与本次合并路径零交集）；且合并树已被独立验证、tree digest 已知——因此合并结果可用 merge-tree 预先确定并与已验证树做字节级比较，相等即证明工作树执行是多余的

## Short path
- 队列 confirm 取得合并授权后，先 git merge-tree --write-tree <main> <lane_head> 只读预演，不碰工作树；未知量：合并树是否等于已验证树
- 比较预演 tree hash 与验证回执冻结的 lane 树 hash；相等 → 合并语义已被既有验证覆盖
- git commit-tree <tree> -p <main> -p <lane_head> 造合并提交；git update-ref 带 --expect 旧 main 值 CAS 推进，失败说明并发推进，重读真值再裁决
- 仅对本 lane 拥有的路径 git restore --source=新 main 落入共享工作树；他人 staged 文件一律不碰
- 复核他人 staged 清单/计数前后不变且 main^{tree}==已验证树 → 停止

## Stop conditions
- merge-tree 预演树 ≠ 已验证树（真实冲突或验证后内容漂移）→ 停止对象层路径，走真冲突合并
- 他人 staged 文件与本次合并路径有交集 → 任何物化都会覆盖他人在途工作，停止并上报协调
- 合并尚未通过仓内自身闸（队列机检/独立审查）→ 先取得授权再执行
- 拒绝来自策略性守卫或审查闸 fail-closed（如他人 active lane 挡 push、探测载荷被拦）→ 接受拒绝并在回执标注『代码推定，非实测』，不找等价绕行

## Verification
- 合并前后 git status --porcelain 中他人 staged 文件清单与逐项计数不变
- main^{tree} hash 与已验证 lane 合并树字节级相等
- update-ref 采用对旧 main 的期望值 CAS；CAS 失败即视为有并发写者，重读再裁决

## Counterexamples
- 单人仓库、索引干净 → 直接 porcelain merge，对象层操作纯属开销与风险
- 存在真实冲突或 base 漂移造成树差异 → 等价证明不成立，必须真合并解冲突
- 仓规要求合并必须触发 porcelain 钩子链（额外检查只在 git merge 路径上生效）→ 绕钩子不被治理允许，除非验证链已被仓内闸独立覆盖
- 他人未提交改动与目标路径重叠 → 只能协调或等待，不可选择性物化
