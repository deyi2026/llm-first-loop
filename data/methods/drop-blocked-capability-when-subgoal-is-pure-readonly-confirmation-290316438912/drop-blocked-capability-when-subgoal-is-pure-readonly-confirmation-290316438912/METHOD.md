---
method_id: drop-blocked-capability-when-subgoal-is-pure-readonly-confirmation-290316438912
name: drop-blocked-capability-when-subgoal-is-pure-readonly-confirmation
description: 受管收尾任务中，为'只读确认'子步骤构造的命令被灾难级安全硬阻断（如管道直连解释器），回执给出提权重发与落盘 workaround 两条补救路时，先裁决一个更早的未知量：当前子目标是否真的需要被阻断的能力。若待核事实已逐字点名（main SHA/PR head/CI 结论/槽位占用）且每项都有直接只读一跳探针（rev-parse、gh pr view、status 工具），则解释器只承担格式化、不产生新信息——直接降级为无解释器复合只读命令，不提权、不落盘绕行、不枚举补救分支。cwd 未给时先一次 pwd/rev-parse 发现，不假设默认路径。后续写入类调用遇 version_conflict 按'回执点名工具重读一次+单次 CAS 重试'既有方法处理。
aliases: 被安全守卫拦下先看目标需不需要该能力, 核对远端状态别套解释器, 灾难级行为拦截的降级处置, 合并收尾前一次性只读探针清单, 提权与落盘绕行之外的第三条路
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:c58155a8-b020-4f34-aa57-2d5ac74f217a:63:dd083c45a4e282b4db44
evidence_refs: learning:learn:d03bd9ac1fae
created_at: 2026-11-17T16:50:44.973775+08:00
updated_at: 2026-11-17T16:50:44.973775+08:00
---
## Trigger
受管合并/发布/门禁类任务的只读确认子步骤被安全守卫硬阻断（灾难级行为类回执），回执同时提供提权重发或落盘 workaround 等补救路径；且任务书已把该步骤定义为纯事实核对、逐字列出待核值并禁止无关循环。

## Discriminator
阻断发生前已可见：待核事实清单精确（main SHA/PR head/CI 结论/槽位）且每项存在直接只读一跳来源，本步骤无任何计算或数据变换需求——被拦的解释器在管道里只做格式化。即'子目标不需要该能力'在动手前即可从任务书措辞判定，无需预知守卫存在。

## Short path
- 从任务书抄出待确认事实清单（未知量已精确到值）
- 逐项映射到无解释器只读探针：git fetch+rev-parse、gh pr view --json、专用 status/queue 工具
- 本地 cwd 未在任务书给出时，先一次 pwd + git rev-parse --show-toplevel 发现，不假设默认路径
- 合成一次复合只读命令逐项取回，与权威值逐字比对
- 全部吻合即进入受管下一步；写入类调用若遇 version_conflict，按回执点名工具重读一次再单次 CAS 重试

## Stop conditions
- 待核事实全部与任务书权威值逐字一致 → 停止确认，进入下一步受管动作
- 任一探针回执与权威值矛盾 → HOLD 并如实上报，不自行改写或发起变更
- 工具自动机检未 PASS → HOLD 上报

## Verification
- 回执中的 SHA、conclusion、slot 占用状态与任务书权威值逐字一致
- preflight 机检各项 PASS（base 主当前/合并树干净/路径不相交/verify 覆盖 base）作为第二道独立确认

## Counterexamples
- 子目标确需解释器做真实计算/聚合（非纯格式化）时不得硬降级——按回执走落盘姿势或提权通道
- 待核事实没有直接一跳探针、需要推理或跨源聚合时，裸复合只读命令不适用
- 阻断是参数错误类（如 workdir 无效）而非能力类时，直接按回执修正参数即可，不涉及能力取舍
- 环境无此类灾难级守卫且解释器管道是既有惯例时，该方法无收益
