---
method_id: hard-block-receipt-as-rewrite-playbook-split-warned-subactions-2623bf332bc0
name: hard-block-receipt-as-rewrite-playbook-split-warned-subactions
description: 带 FR-SAFE-01 类硬安全闸的执行环境里，heredoc 直交解释器会被 E6 级硬阻断，但阻断回执本身是重写说明书：内含规则 id、可复制的合规等价姿势（RULE-AI-36：cat 落盘 + python3 -I 执行）与二级拦截预告（payload 含 subprocess、受保护动作、敏感路径时第二步仍会被拦）。正确路径是逐字采用等价姿势、按预告把高危子动作拆出脚本：只读/常规部分用等价 shell 命令补齐，回执点名的受保护动作才走 review_admission/提权。不重试原命令、不枚举替代工具、不先提权。
aliases: heredoc 被安全闸拦了怎么重发, 回执里的等价命令直接抄, 先 cat 落盘再 python3 -I 执行, 被预告 subprocess 二次拦截先拆出来, 硬阻断后别重试按指引改写
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0bf4a1f9-e8ff-46ff-8388-7cefc89e47c9:51:c2526c541d9526860550
evidence_refs: learning:learn:b02562b823eb
created_at: 2026-11-12T13:10:26.342408+08:00
updated_at: 2026-11-12T13:10:26.342408+08:00
---
## Trigger
待发命令形状为 heredoc 直交解释器（python3/sh - <<），或该命令在带灾难行为硬安全闸的执行环境里已被硬阻断，且回执自带规则 id、等价合规姿势模板和二级拦截预告。

## Discriminator
回执是否给出可逐字复制的等价姿势、并显式列出会被二级拦截的载荷特征（subprocess/受保护动作/敏感路径）——满足即把『怎么重发』从开放枚举缩成机械变换+定点拆分，无需提权。

## Short path
- 派发前预判命令形状：heredoc→解释器、rm -rf 批删等已知高危形状，先改写成落盘姿势再发，省一次阻断
- 已被拦时：逐字采用回执内嵌的等价姿势（落盘+隔离模式执行），不重试原命令、不自行发明替代命令
- 对照回执二级预告清点载荷：subprocess 调用、受保护动作等会被再拦的部分从脚本中移除
- 拆出子动作按性质选通道：只读/常规命令（如 git rev-parse、git status --porcelain）直接 shell 补齐；回执点名的受保护动作才走 review_admission
- 把补齐命令输出映射回原脚本预期字段（porcelain 空→porcelain_empty=True），按原任务格式汇报原始回执

## Stop conditions
- 合规重写后的命令全部成功，输出覆盖原载荷预期打印的全部字段
- 等价姿势或其残余拆分仍被二级阻断且无更细拆分余地→停止自行改写，按回执指引走 escalation/review_admission 人工审批

## Verification
- 变换后脚本与原载荷除拆出部分外逐字一致（diff 核对）
- 拆出命令的输出能重建原脚本预期行（HEAD、porcelain_empty）
- 未新增原命令之外的副作用（不碰主工作区、不运行被禁动作）

## Counterexamples
- 回执只是通用错误码、无内嵌等价姿势与二级预告→不能机械套用，需自行推理或询问用户
- 等价姿势改变任务语义（如 trash 替代 rm 改变可恢复性、审计要求单命令逐字执行）→先确认再变换
- 阻断原因是超时/配额/权限类软限制而非动作形状→改写命令形状无效，走重试或权限流程
