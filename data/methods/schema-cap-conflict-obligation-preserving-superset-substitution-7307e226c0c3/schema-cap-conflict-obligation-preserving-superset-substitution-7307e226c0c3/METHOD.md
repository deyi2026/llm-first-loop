---
method_id: schema-cap-conflict-obligation-preserving-superset-substitution-7307e226c0c3
name: schema-cap-conflict-obligation-preserving-superset-substitution
description: 调用方点名'精确逐项'参数（全部41个改动路径）而目标工具 schema 读出硬上限（paths≤40）与之冲突，且 schema 写明省略该参数会静默降级语义（patch→tree）时：不按字面硬发重试、不丢参降级、不擅自拆多次调用；改为构造能机械验证覆盖全部精确条目的最小祖先级超集条目（目录+顶层文件），保持声明 scope 语义不变，核对回执 effective scope 与 paths 回显，并在最终交付显式披露该偏差与覆盖组合方式。
aliases: 路径太多传不过去怎么办, 目录级条目代替逐个文件, 参数和任务书打架, 省略paths会变整树审查, 清单上限比条目数少一条, 不拆批不降级的传参改法
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:a9874acd-12f3-436f-9b3f-f5affe983b4a:1:a4eaae3157f75314897d
evidence_refs: learning:learn:5d48f1f9ea2e
created_at: 2026-11-20T09:16:12.757066+08:00
updated_at: 2026-11-20T09:16:12.757066+08:00
---
## Trigger
上游指令要求以精确逐项清单调用某工具（如 admission start 的 paths=全部 N 个精确路径），但调用前读到的 schema 存在与之冲突的硬约束（条目数上限/格式限制），且该参数的省略回退会改变冻结语义

## Discriminator
两条当时可见事实：(1) schema 字段定义给出确定上限（≤40条），而已枚举条目数（41）越界；(2) schema 自身文档写明不传 paths 会退化为 tree——即'丢参数'不是中性缺省而是语义变更。二者合起来把候选动作空间从 {字面硬发重试 / 丢参 / 拆批 / 换 tree} 缩成唯一动作：保 scope 的最小可验证超集替换

## Short path
- 先用权威命令枚举精确条目（git diff --name-only BASE HEAD），这是义务的对象，不可省
- 首次 start 前完整读取目标工具 schema，确定参数契约、硬上限与省略回退语义
- 冲突时把指令改写为义务陈述（'patch 冻结须覆盖全部41个精确路径'），据义务推导最小祖先级超集条目（目录 + 顶层文件）
- 机械核验覆盖：每一条精确路径都能映射到至少一个超集条目之下
- 带超集条目调用 start；核对回执 accepted、scope.effective 仍为 patch、paths_ignored=false、paths 被回显
- 按 waiting_protocol 轮询期间对 diff 做独立审查；status 到终态后核对资格、独立模型身份与冻结指纹，报告并披露超集替换偏差

## Stop conditions
- 回执确认 accepted 且 effective scope 与原义务一致（patch、paths 未被忽略）→ 停止参数工程，进入等待与审查
- 超集替换无法保持义务语义（gate 资格必须逐文件绑定、或条目分散无共同祖先使超集不缩空间）→ 不强行替换，HOLD 并给精确证据，不产出假 PASS
- 机械覆盖核验失败（存在精确路径不落任何超集条目之下）→ 回到条目推导，不得带缺口启动

## Verification
- 确定性覆盖检查：diff --name-only 输出中每条路径都在至少一个声明条目之下
- 回执字段核对：scope.effective==requested、paths_ignored==false、声明 paths 原样回显
- 最终报告含显式偏差披露段：上限冲突、替换方式、覆盖组合（子审覆盖面 + 自己深读补齐的缺口）

## Counterexamples
- 闸的资格判定必须逐文件绑定（逐文件 attestation/指纹签名）时，目录级条目会让被点名文件脱离资格绑定——应拆分多次 start 或向闸索要例外，不做超集
- 精确条目分散在大量无共同祖先的根下，'最小超集'退化为原条目数、不缩空间——超集替换不适用，转按闸的 split_plan 分批
- 指令的'精确逐项'本身就是义务（明说 paths 必须逐字等于这 N 条）——替换即违约，应 HOLD 陈述冲突，不擅自替换
- schema 无硬上限、或省略回退不改变语义（仅可选提示）——不存在冲突，按字面传参即可，不要过度改造
