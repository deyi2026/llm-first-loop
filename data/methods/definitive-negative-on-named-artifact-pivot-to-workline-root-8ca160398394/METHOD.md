---
method_id: definitive-negative-on-named-artifact-pivot-to-workline-root-8ca160398394
name: definitive-negative-on-named-artifact-pivot-to-workline-root
description: 延续型任务按角色+章节号点名既有工件（『修订表 §3』『结论 3』），且 task state/evidence 恢复为空时，若在 cwd 内对工件名的作用域检索返回确定性无匹配（success 的 no-match，非超时/截断），下一个未知量应是『工件所在的工作区根』而非『在本工作区内换模式再搜』：先 pwd/ls 确认 cwd 身份，再枚举兄弟项目根或利用上下文中已有工作区指针（如镜像仓 docs 声明的外部 research workspace），用带显式根的 rg 定点检索。超时的全库搜索应换工具+显式根，而非同工具重试。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:4262a65a-bd51-4405-bed5-57af83e2e1ab:335:e7d7320de54d7416c8ba
evidence_refs: learning:learn:9714a6e7a23d
created_at: 2026-10-22T07:47:45.050483+08:00
updated_at: 2026-10-22T07:47:45.050483+08:00
---
## Trigger
用户指令以角色/章节号点名一个既有工件（明显延续上一工作线），会话状态与 Evidence 恢复均为空，随后在当前工作区对工件名做的作用域检索返回确定性 no-match

## Discriminator
作用域内文件名检索返回 success+无匹配（工具级否定证据，区别于超时/截断），同时指令中的 §编号/结论编号证明工件属于既有工作线 ⇒ 工件大概率不在 cwd 而在另一项目根；此时 cwd 身份与兄弟根是可用一步动作解决的未知量

## Short path
- 尝试恢复 task state/evidence → 均空；记下用户按角色+章节号点名工件 ⇒ 判定为跨会话延续任务
- 对工件名做 cwd 作用域文件名检索 → 确定性无匹配 ⇒ 结论：工件不在当前工作区，不要在本区内继续加宽
- pwd;ls 确认 cwd 身份（如为镜像仓/辅助仓则必非工作线主场），枚举兄弟项目根或从上下文指针（docs 中声明的外部工作区）取候选根
- 用 rg 携带显式根 + 工件名/工作线关键词定点检索 → 命中修订表及其指向文件
- 读取点名章节（§3）与被引用的目标文件，执行任务；用文件内 SHA/版本链验证同一性后停止

## Stop conditions
- 工件已被定位并读取，其自述（标题/章节结构/指向文件）与用户点名一致
- 文件内 version_token/SHA 与引用链一致，用户点名的条目（如 §3 各项与结论 3）全部有对应处理

## Verification
- 命中文件自称该修订表且含用户点名的 § 编号与『结论 3』对应位置
- 其指向的下游文件存在且哈希/行数与文中声明一致，或差异被显式记录

## Counterexamples
- 工件其实在 cwd 内、只是命名不同（草稿名/扩展名差异）：确定性无匹配后应先在 cwd 内做名称变体+内容定点 grep，而不是立即跳出工作区
- 非延续任务（用户要求新建该工件）：无匹配意味着『需要创建』而非『在别处』
- 单项目环境无兄弟根：cwd 内 mtime/内容检索仍是正确升级路径，只需换带显式根的 rg 避免超时重试
