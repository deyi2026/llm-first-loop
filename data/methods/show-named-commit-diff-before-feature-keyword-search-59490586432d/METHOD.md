---
method_id: show-named-commit-diff-before-feature-keyword-search-59490586432d
name: show-named-commit-diff-before-feature-keyword-search
description: 当目标变更已被当前输出中的精确标识符钉住（git log/status 显示 hash + 与目标特性名逐字匹配的提交信息）时，直接 git show <hash> 读权威 diff（一次得到实现文件、触发条件、回执字段与测试断言），而不是用特性领域词做全库内容搜索。领域词常跨子系统同词异义：本集关键词搜索的头部命中全部来自语义碰撞的无关子系统（config.py 的模型降级链注释），目标实现文件反而未进前列，该轮搜索对缩小空间零贡献。一次 git show 同时覆盖定义面与测试面，替代多轮关键词枚举。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:40eeca85-e561-4f26-9faf-efda5823cb4b:263:3eb2ec3ad91325aae6f2
evidence_refs: learning:learn:4dc9928484c8
created_at: 2026-10-11T01:46:14.393496+08:00
updated_at: 2026-10-11T01:46:14.393496+08:00
---
## Trigger
需要确认某个已上线修复/特性的实现机制或触发条件，而当前会话输出（git status/log、任务上下文）中已出现与目标特性名精确匹配的提交行（hash+提交信息）；此时不要转而用特性关键词做全库内容搜索。

## Discriminator
第一步 git status/log 的输出中已存在与目标特性名逐字匹配的提交行（本例 '692aef752 EVO-...: web_search 词典降级检测+回执标注' 与 '9e8f3abd9 sanitize_slug 保留 Unicode'）。该 hash 是指向权威 diff 的直接 provenance 边，在进入任何搜索之前就可用、可验证（提交信息与任务目标字面吻合）。

## Short path
- 从当前 git 输出中识别与目标特性名匹配的提交 hash（未知量：目标机制的实现位置与触发条件是什么）
- git show <hash> 一次获取权威 diff：文件路径、检测逻辑、诊断字段、测试断言（未知量在此解决）
- 仅当 diff 被截断或上下文不足时，沿 diff 给出的文件路径做精确读取
- 带着 diff 给出的机制细节进入真实验证（按触发条件实跑、核对回执字段），随后停止发现

## Stop conditions
- diff 已包含目标机制的定义、触发条件与测试，后续只剩按其做运行态验证，不再做任何发现类动作
- 提交信息与目标特性名不匹配（provenance 边断裂）——此时才回退到关键词/文件搜索定位

## Verification
- git show 输出必须包含任务所称机制对应的代码与字段名；若没有，说明该 hash 不是目标边，停止沿用它
- 按 diff 中的触发条件做一次实跑，确认诊断字段/行为在运行态真实出现（本例 live 查询回执中出现 degraded_backend 标注），而非只看单测

## Counterexamples
- 没有任何标识符指向目标变更（如审计'全库哪些地方做 X'、或变更历史无法从 log 定位）——内容/文件搜索此时才是正确定位手段
- 需要穷举同一概念跨子系统、跨版本的所有触点——单个 commit diff 覆盖不了，必须搜索
- git 输出中没有与目标特性名匹配的提交行（提交名漂移、被 rebase 压缩或来自外部仓库）——名称匹配这条判别边不存在，不得硬套
