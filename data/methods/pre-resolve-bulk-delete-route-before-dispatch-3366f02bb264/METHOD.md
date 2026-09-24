---
method_id: pre-resolve-bulk-delete-route-before-dispatch-3366f02bb264
name: pre-resolve-bulk-delete-route-before-dispatch
description: 在带灾难性行为硬安全边界（FR-SAFE-01类）的环境里，对用户主目录范围的绝对路径做批量删除前，先预判动作形状并选定合规删除路由：优先探测并使用可回收删除工具（如 trash），不要先派发 rm -rf。本例 rm -rf 被硬阻断后花了约5轮恢复（替代工具枚举、方法检索、行为探针、探针验证）；若派发前先做一次 command -v trash 的路由预判，可直接省去被拦截与事后恢复枚举。删除后原路径消失即为本环境可验证终点；沙箱无权读废纸篓时，磁盘是否真正释放需向用户披露待确认。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f88bda21-3714-409e-a903-eeb08b562780:52:7df5ac7deb4ab15392f6
evidence_refs: learning:learn:83a7dee25628
created_at: 2026-09-23T09:06:14.130687+00:00
updated_at: 2026-09-23T09:06:14.130687+00:00
---
## Trigger
下一步动作是对位于用户主目录范围（如 /Users/<user>/... 下的绝对路径）的多个大目录执行批量不可逆删除（rm -rf 类命令），且运行环境存在灾难性行为硬安全边界、可能提供 trash 类可回收删除工具。

## Discriminator
派发前即可观察的动作形状事实：命令是 rm -rf、目标是 $HOME 下的绝对路径、且为批量多目录删除——三者叠加即可预判会触发『用户目录范围不可逆删除』的硬阻断，把候选动作从『直接删』缩为『先探明合规删除路由（一次 command -v trash）』。

## Short path
- 完成用户要求的前置核验：目标存在与大小、无 git worktree 注册指向归档目录、需保留的 git 引用在主仓可解析（本例此步是任务要求本身，保留）
- 派发删除前判定动作形状：批量不可逆删除 + 用户目录范围绝对路径 → 预期触发硬边界，不直接派发 rm -rf
- 一次探测可回收删除路由：command -v trash；存在则采用，不存在则停止自动尝试并向用户请求决策
- 若该工具行为未经验证，用 /tmp 临时文件探针确认其能从原路径移除（退出码 0 + 原路径消失）
- 对已核验路径执行 trash 删除，回执中逐路径确认 No such file or directory
- 报告结果并披露残余不确定性：沙箱无权读 ~/.Trash 时，磁盘是否真正释放需用户清空废纸篓后确认

## Stop conditions
- 目标路径已从原路径消失（ls 返回 No such file or directory），即为本环境可验证终点，不再做额外确认性动作
- trash 类工具不存在且无等价物时，停止自动删除尝试，转为向用户披露并请求手动执行或豁免
- 用户目标要求立即释放磁盘且不接受数据滞留废纸篓时，停止 trash 路线并显式上报路线与目标的冲突

## Verification
- 探针验证：touch 临时文件 → trash → 退出码 0 且原路径 ls 失败
- 删除后逐目标路径 ls 确认 No such file or directory
- 保留项未受影响：相邻归档目录仍在、需保留的 git 引用仍可解析
- 若权限允许则检查废纸篓去向；不允许（Operation not permitted）则在最终报告中明确告知用户待确认

## Counterexamples
- 目标位于沙箱 /tmp、CI 工作区等非用户主目录范围：rm 不触发硬边界且 trash 可能不可用或语义不符，直接 rm 即可，路由预判与探针纯属开销
- 仅删除单个已知小文件：动作形状不构成灾难性判定，无需预判与探针
- 环境中没有任何可回收删除工具：方法不可用，应请用户手动删除或走明确豁免流程
- 用户明确要求立即释放磁盘空间：trash 会把 13.8G 留在废纸篓不释放，与目标冲突，应改由用户直接执行删除
