---
method_id: resolve-actor-attributed-review-target-then-audit-scope-affa32d7cd8a
name: resolve-actor-attributed-review-target-then-audit-scope
description: 用户以『某 agent/会话做了某范围的大量更新，你审查』下指令但未给 ref 时：先在默认视图（main log）核对，不符即判定审查对象未解析；用 scope 关键词 + author 跨 --all refs 与 worktree 列表定位具体未合并分支及 fork 点。审查从 merge-base diff stat 开始，将实际路径对照『声称范围』——范围外文件（尤其 core 层改动与被删测试文件，可能是静默移除他人工作流）列为头号阻塞发现，并与 SPEC 验收项对照。验证阶段若分支 worktree 基线过旧跑不了测试，建临时集成分支跑全套，每个失败测试回纯 main 复跑判定归属，报告区分分支缺陷/主干固有/合并引入。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:afaf8a78-607b-4e8e-8fd2-0e3cc4e07be4:1:ae4bffd0bc0b2415eca2
evidence_refs: learning:learn:5dec7925325a
created_at: 2026-09-24T12:39:15.138804+00:00
updated_at: 2026-09-24T12:39:15.138804+00:00
---
## Trigger
用户要求审查由另一 actor（另一 agent/会话，如『GPT 做了 web 端更新』）提交的改动，但未指明分支或 commit 范围，且默认分支最近提交与该描述不匹配

## Discriminator
第一个命令（默认分支 git log）的顶部提交不含所述 actor+scope 的改动——该事实当时即已知，足以把『审查最近所有改动』缩小为『先跨 refs/worktrees 定位该 actor 的未合并分支』；随后首个 merge-base diff stat 中出现的范围外路径（core 引擎、被删 288 行测试文件）进一步把审查重心从『前端优化』校正为『含静默删除的语义变更』

## Short path
- 在默认分支 log 核对用户描述；顶部不匹配即判定 referent 未解析，不开始逐文件审查，也不枚举全仓时间窗
- git log --all --grep=<scope> -i + author/时间过滤 + git worktree list → 定位具体分支、fork 点、未合并状态与改动总量
- merge-base diff --stat 对照用户声称范围；范围外路径（core 层、被删测试文件）优先深查——静默删除他人工作 / SPEC-代码矛盾是阻塞级发现，先于逐块功能审查
- 验证环境选择：分支自身 worktree 基线过旧则建临时集成分支（merge-tree 预检 0 冲突）跑全套；对每个失败测试回纯 main 复跑确定归属
- 报告按归属分层（分支缺陷/主干固有/合并引入），列明范围外改动及处理建议，清理临时环境

## Stop conditions
- 审查对象已解析为具体 ref（分支+fork 点+未合并状态确认），diff 以 merge-base 全量枚举，无未解释的范围外文件
- 全部阻塞级发现均有可复现证据（失败测试经集成分支/纯 main 双跑归属，或 spec 对照），验证用临时环境已清理

## Verification
- 被审 commit 的 author/时间戳/所在分支与用户所述 actor 一致，未混入主干既有的同类 scope 提交
- 报告的每个测试失败：集成分支复现 + 纯 main 通过（归属分支），或反之（归属主干），双跑确认后才写结论
- diff stat 中每个范围外文件（含删除）都在报告中显式说明，并与相关 SPEC/验收项对照过

## Counterexamples
- 改动已合入 main 且提交信息清晰可辨——跳过定位阶段，直接审查指定范围
- 用户显式给出分支名/commit 范围——无需 referent 解析，直接进入 diff 审查
- 目标分支与 main 有真实冲突（merge-tree 非空）——不能简单建集成分支跑测试下结论，需逐 commit 审查或先解决冲突
- grep scope 无命中时不应换同义词无限重试——转查 worktree/远端列表或直接询问用户
