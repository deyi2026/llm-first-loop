---
method_id: verify-plan-mechanism-can-produce-acceptance-signal-before-faithful-runb-73ef6ec1a1d0
name: verify-plan-mechanism-can-produce-acceptance-signal-before-faithful-runbook
description: 任务以上一轮菜单/交接绑定的既定路线到达，且路线点名具体机制并带可观察验收态（如面板绿=身份匹配）时，不要先通读指定机制的实现再照抄出 runbook：第一步先定位验收信号的计算代码（通常一个小模块），裁决该机制的产物布局能否结构性产出该信号（如 wheel→site-packages 无 .git→rev-parse 恒空→永不绿）。可行才写忠实手册；不可行则保持目标、按属性重释（带身份=目标提交的完整 git worktree），优先采用环境里已物化的等价产物（publish 落盘的 checkout），只补读修正方案必需的锚点（env 解析根/身份守卫/路径 sanity），产出只读冻结现场+分段闸门+回滚的手册，并显式声明对原路线的修正。
aliases: 接手既定路线先查达标可行性, 照抄方案出手册前先问验收信号从哪算出来, wheel 能不能带上 git 身份 先读身份计算模块, 计划字面机制达不了标就换已物化等价物, 菜单选中的方案先验证能不能收敛
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7007267a-8cde-4b7c-bcc4-b677b3653671:187:d92cb2b103df31870b64
evidence_refs: learning:learn:b6529e1f894c
created_at: 2026-11-07T06:43:38.557071+08:00
updated_at: 2026-11-07T06:43:38.557071+08:00
---
## Trigger
任务以预绑定计划/路线形式到达（前轮 A/B/C 菜单选中、交接指令、待执行 runbook），路线指定了具体机制（如『用官方安装器装 wheel』）且带明确可观察验收态（面板全绿、身份匹配、指标达标），本会话被要求直接执行或产出精确执行手册。

## Discriminator
验收信号在代码里有具体计算路径且通常是小模块（本例：identity 字段=对运行 workspace 做 git rev-parse，失败置空、无嵌入回退）；用验收字段名做一次精确检索即可拿到裁决所需事实。指定机制的产物布局是否喂得进这条计算（wheel 安装=site-packages 无 .git→恒空）当时即可判定，无需先读完机制的全部实现。

## Short path
- 冻结环境硬事实（哪台机、有无通道），决定交付物是直接执行还是精确 runbook。
- 从路线文本提取验收可观测量（如 git_head 匹配目标 sha）；用该字段名做一次精确检索，直读计算模块，裁决指定机制的产物能否结构性产出该信号。
- 能产出 → 只读机制实现中 runbook 必需的部分，写忠实手册，不再质疑机制。
- 不能产出 → 保留目标、按属性重释（『带身份 release』=目标提交的完整 git worktree），检查环境是否已有满足该属性的物化产物（本机同源 .releases/eb51e82 checkout 即证明 publish 会落盘 worktree）。
- 只补读修正方案真正需要的锚点（.env 按 workspace 根解析、身份守卫、sanity 路径数学），产出 Stage0 只读取数+分段闸门+一键回滚的 runbook，开头显式声明对原路线的修正及代码依据。

## Stop conditions
- 验收计算证明指定机制可产出信号：写忠实 runbook 即止，不再二次猜测机制。
- 机制结构性不可达且环境中无等价物化产物：不产手册，把『目标 vs 机制冲突』作为决策项交回。
- runbook 内每个代码级断言都有本 run 读到的 file:line 依据；宿主侧未知量留给只读 Stage 0，不假设。

## Verification
- 修正后 runbook 的验收段检查与原路线完全相同的可观测量（git_head==目标全 sha），确保是修机制而非换目标。
- 每个 Stage 附闸门命令与预期输出，并附已验证的回滚路径。
- 对原路线的修正显式声明并给代码依据，使用方可一眼否决。

## Counterexamples
- 验收是版本号/行为级（服务自报 0.6.36）而非谱系级：wheel 安装即可满足，忠实执行安装器路线就是对的，先读身份计算反而绕路。
- 运行时有构建期嵌入身份回退（build 时把 head 烤进 manifest）：wheel 也能带身份，字面路线可行，『切 checkout』是更重的不必要形态。
- 路线机制是用户或安全策略显式钉死的（只准 wheel 安装、禁止源码部署）：机制-目标冲突应交回决策者，不单方面改写机制。
