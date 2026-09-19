---
method_id: commit-provenance-before-pattern-guessing-83624ca57d8d
name: commit-provenance-before-pattern-guessing
description: 代码库特性取证时，若基线 git 步骤已显示命名该特性的 commit 哈希/分支，先用 git show --stat / diff --name-only 确定性枚举该特性的改动文件集，再读结构与接线点。不要先按符号约定（def <toolname>）或文件名模式（*feature*.py）做全局猜测搜索——本仓工具是 class 且特性按目录组织，两次猜测均落空后才转宽内容枚举（12 条命中多为无关 docstring）。commit diff 是已到手的最窄 provenance 边。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:72cadfe4-cbee-455c-ad5b-feaa06074185:999:035fe6b5a3b1b78801c9
evidence_refs: learning:learn:7fef32fca983
created_at: 2026-09-19T03:18:16.371665+00:00
updated_at: 2026-09-19T03:18:16.371665+00:00
---
## Trigger
需要在仓库中定位某 feature slice 的实现面/接线点，且基线 git status/log 已显示点名该特性的 commit 哈希或分支名（如 'feat(fleet): slice 3 ... SubAgentRunner lifecycle, subagent_lease tool surface'）。

## Discriminator
基线 git 输出（第 1 步）已包含具体 slice commit 哈希 + 描述性 message，点名了组件与工具面；对该哈希执行 git show --stat 即可确定性列出该特性全部改动文件（store/coordinator/runner/工具/factory/tests），把"特性面在哪"从全仓模式猜测缩为一个命令。仅使用第 1 步已暴露事实，未用后续读到的文件名倒推。

## Short path
- git status/log 锚定基线，记录 slice commit 哈希与 message（未知量：基线与特性标识）
- 对 slice 哈希 git show --stat / git diff --name-only，确定性得到特性文件集（未知量：slice1-3 落地在哪些文件）
- 读该文件集的结构与导入，由构造点定向 grep 接线处（如 factory 中 SubAgentRunner( 是否传 project_coordinator）
- 读生命周期事实记录的确切行段（如 _begin_fleet_run 的 run_fact 字段）验证缺口细节
- 每个候选缺口拿到 file:line 证据即停，输出取证报告

## Stop conditions
- 报告中每个缺口均有 file:line 证据支撑
- 生产构造点是否注入参数已由定向 grep 二值确认
- 用户目标所需事实（缺口清单+scope 建议）已由权威文件证据覆盖，不再做全仓内容枚举

## Verification
- git show --stat 枚举的文件集与最终报告声称的特性面一致
- grep 生产构造文件确认接线存在/缺失的结论
- 报告引用的文件均在 commit diff 集内，或对集外引用给出理由
- 两次落空的模式搜索未被用于支撑任何结论

## Counterexamples
- 特性只存在于工作区/未提交（untracked），无 commit provenance——目录/内容搜索才是正确首步
- 基线只有跨特性大 merge/release commit，diff 过宽——应改用 git log -- <path> 或内容搜索收窄
- 目标本身是枚举全仓所有调用方/用法，而非特性自身文件——commit diff 天然漏掉消费者，必须补内容搜索
