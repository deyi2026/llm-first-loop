---
method_id: recheck-artifact-existence-after-gated-push-before-manual-create-724d522517a8
name: recheck-artifact-existence-after-gated-push-before-manual-create
description: 受管流水线里受闸 git push 成功后，流水线可能在数秒内自动创建下游制品（如 PR）。手动撰写正文并创建前先做一次廉价存在性查询：已存在且 head SHA 一致则逐字段核验后报告停止；不存在才创建，且正文载荷用阻断回执点名的数据接收者通道（write_file/edit_file）落盘——解释器 heredoc 触发灾难级硬闸、cat heredoc 仍会被复合命令准入闸拆段拦截。把『撰写→创建→撞 already exists』的三连阻断级联缩成一次查询，同时守住任务书『避免重复』的硬约束。
aliases: 推送后先查PR再写正文, managed流程自动建了PR还要手动建吗, gh pr create already exists竞态, 受闸环境PR正文怎么落盘, heredoc写文档被复合闸拦, 避免重复建PR
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a43dc767-17c2-429a-82f3-1dd9d4aa5558:339:4a6d812e222de9a783f2
evidence_refs: learning:learn:78b85f95d169
created_at: 2026-11-15T23:29:58.933392+08:00
updated_at: 2026-11-15T23:29:58.933392+08:00
---
## Trigger
受管流水线中，一个受闸上游动作（带 pre-push 钩子/受管回执的 git push 新建远端分支）已成功，任务下一步要求手动创建其下游制品（如以该分支为 head 的 PR），且任务书明令避免重复创建同类制品。

## Discriminator
上游回执已显示受管自动化在场（pre-push 扫描、受管流程回执全程包裹）；此类流水线可能在 push 后数秒自动创建下游制品。在撰写任何正文之前，一次廉价存在性查询（gh pr list/view --head <branch>）即可把『先写正文再发现已存在』的整段级联缩成一个查询——该判据在推送成功回执到达时即可用，不需要事后知识。

## Short path
- 上游受闸动作成功后，先用权威远端核对结果：ls-remote 分支 SHA 与冻结 HEAD 逐字一致
- 立即按分支精确查询下游制品是否已存在（gh pr list/view --head <branch>）
- 已存在且 head SHA 一致：逐字段核验正文覆盖任务要求的声明（变更范围/验证结论/边界披露），报告编号/URL/CI 后停止，不再创建
- 不存在：用阻断回执点名的数据接收者通道（write_file/edit_file）撰写正文，避免 shell heredoc——解释器 heredoc 触发灾难级硬闸，cat heredoc 即便去掉附属命令仍被复合命令准入闸拆段拦截
- 以单条非复合命令创建；若返回 already exists（与自动化的竞态）视为成功，取回并核验字段而非重试

## Stop conditions
- 下游制品已存在、headRefOid 与冻结上游精确一致、正文覆盖任务书要求的全部声明项 → 报告并停止
- 创建被准入闸拒绝且回执点名的合规写入通道不可用 → 停止并报告，不在 shell 形态之间继续迭代重试
- 远端分支 SHA 与冻结 HEAD 不符 → 先处置上游，不做下游存在性判断

## Verification
- ls-remote 分支 SHA 与冻结 HEAD 逐字一致
- 制品 headRefOid == 冻结 HEAD、base 正确、正文含范围/双审查/门禁/边界等强制声明
- 同分支无重复制品：创建前查询为空，或创建回执 already exists 时以查询到的唯一制品为准

## Counterexamples
- 无受管自动化的普通仓库：push 不触发自动建 PR，先查存在性收益趋零（查询仍廉价但不改变路径），可直接撰写创建
- 永远不会被自动创建的制品（tag、Release finalize、工单）：存在性检查退化为形式，直接走合规通道撰写创建
- 自动创建的正文不满足任务书强制声明（缺范围/验证/边界）时：『已存在』不等于『已完成』，仍需经合规通道补充或重建
- 上游动作失败或被闸拒绝：不存在可验证的下游制品，先按上游回执处置
