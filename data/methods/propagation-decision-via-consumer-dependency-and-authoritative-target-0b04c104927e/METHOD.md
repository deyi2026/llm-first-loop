---
method_id: propagation-decision-via-consumer-dependency-and-authoritative-target-0b04c104927e
name: propagation-decision-via-consumer-dependency-and-authoritative-target
description: 回答『本地提交/状态是否需要推送到 main/主干/共享库』这类传播决策问题时，不从默认 tracking 远端直接下结论，而是先确立三个可验证事实：(1) 下游消费者实际读什么——若服务/部署绑定本地 git 树，推送不是运行时必需，只剩防丢等建议性理由；(2) 哪个目标是权威活跃目标——从 remote URL/命名（如 *-legacy 后缀）与 tracking 配置比对识别，而非默认 tracking；(3) 精确分歧——对每个候选远端做双向 ahead/behind 计数加祖先校验。答案拆成『不必需但建议』两层，并附前置条件（未提交文件不混入、审查门），把『要不要推』转成『推哪个目标+为什么』。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:78fffae1-3786-4a53-9158-71e2847e5ab7:1239:10f8376558b877c7d46d
evidence_refs: learning:learn:b70c21eb51d4
created_at: 2026-10-17T01:01:01.886965+08:00
updated_at: 2026-10-17T01:01:01.886965+08:00
---
## Trigger
用户询问本地已提交状态是否需要推送到远端 main / 合并到主干 / 同步到共享库（『是否需要到 main？』），且环境存在多个远端或 tracking 配置可能指向过期目标时。

## Discriminator
两条当时已由工具回执可见的事实可把候选空间收窄：(a) 权威运行时快照显示服务正从本地 git 树的当前 generation 运行——消费者不读远端，『不推会不会坏』立刻有答案；(b) remote 列表的 URL 语义显式暴露 origin 指向 *-legacy 旧仓库且另有活跃仓库远端——『到 main』实为『推哪个 main』。二者合用可跳过对默认 tracking 远端的权威性假设。

## Short path
- 读权威运行时快照，确立下游消费者读本地树还是远端（解决未知量：不推是否影响运行）
- 发路径型命令前先确认 cwd/仓库根；若路径假设失败（目录不存在回执），一次 PWD 查询恢复，不重试原错误路径
- 列全 remotes 及 URL，按命名/活跃性识别权威目标与 legacy，明确不把默认 tracking 当权威
- 对每个候选远端执行 rev-list --left-right --count 加 merge-base --is-ancestor，把『纯 fast-forward、零分歧』变成回执证据
- 按『运行时不必需 / 防丢建议 / 用户决策点（legacy 同步或切 tracking）』结构作答，并列出 dirty 文件与审查门等推送前置

## Stop conditions
- 消费者依赖、权威目标、分歧量三个事实均已有工具回执支撑，即停止收集并作答
- 发现任一远端 behind>0 或非祖先关系时，停止 fast-forward 框架，转入 merge/rebase 决策

## Verification
- 双向 rev-list 计数与 merge-base --is-ancestor 回执一致，才可声称纯 fast-forward 零分歧
- 活跃/legacy 判定依据来自 remote URL 列表回执，而非仅 branch -vv 的 tracking 行
- dirty 文件清单已核对，确认未混入拟推送集合
- 运行时快照时间戳晚于最近一次发布/重启事件，快照不过期

## Counterexamples
- CI/CD 或协作方从远端拉取构建——推送即运行时必需，『消费者读本地树』前提不成立，结论翻转为必须推
- 远端存在本地缺失提交（behind>0 或互不为祖先）——零分歧前提失效，需先做合并/变基决策而非直接推
- 只有一个远端且 tracking 正确——无需权威目标识别步骤，直接量化 delta 即可，套用本方法属多余
- 用户问的『到 main』实指本地分支合并（feature→main），与远端推送无关——应先消歧动作对象再套用
