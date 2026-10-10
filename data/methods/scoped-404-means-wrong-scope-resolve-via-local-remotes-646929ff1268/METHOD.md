---
method_id: scoped-404-means-wrong-scope-resolve-via-local-remotes-646929ff1268
name: scoped-404-means-wrong-scope-resolve-via-local-remotes
description: 当 repo/path/index 等带 scope 的资源直读返回 404，且错误体携带已解析的完整 URL/路径时，404 证明的是『该 scope 内不存在』而非『资源不存在』。错误体点名的 scope（如 URL 中的 repo 段）就是判别事实：把未知量从『资源在哪』缩成『正确 scope 是哪个』；而由当前工作区项目产生的资源，其候选 scope 就被 git remote -v 封闭枚举。因此应读错误体→一条命令枚举候选 remote→排除已证伪者→带显式 -R 重查，而不是先翻 evidence 库或全目录搜文档名。与 resume-continuation 方法不同：那是无目标续跑的状态重建，这是带明确目标的 API 调用失败后的 scope 重定向。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a5786c38-2507-4f58-a079-27d9e594ca12:596:5cb027f69a50ae71518c
evidence_refs: learning:learn:bdab8c2c7ed4
created_at: 2026-10-08T17:38:14.201800+08:00
updated_at: 2026-10-08T17:38:14.201800+08:00
---
## Trigger
对 run/file 等资源按默认 scope（如 gh 默认仓库）直读返回 404，且 stderr/回执内嵌已解析的完整 URL 或路径点名了被查 scope；该资源由当前项目/工作区的 CI 或工具产生。

## Discriminator
404 回执 URL 中的 repo 段点名了实际解析到的 scope（本例 repos/deyi2026/llm-first-loop-legacy/...）——失败是 scope 不匹配而非 ID 无效；同时工作区 git remote -v 给出封闭候选集（lfl→llm-first-loop 与 origin→legacy，≤2 个），无需任何宽搜索。

## Short path
- 重读 404 回执的完整 URL/路径，提取被查 scope；先按错误类分流（403/401/5xx/timeout 走权限或重试，不进本方法）
- 未知量=正确 scope：在工作区执行 git remote -v（或读该资源 producer 的配置）得到封闭候选集
- 排除已被 404 证伪的 scope，对剩余候选按相近度/活跃度带显式 -R 重查同一命令
- 命中即提取目标字段（status/conclusion/jobs），scope 定位立即停止，转入原任务（失败日志聚类分析）

## Stop conditions
- 带显式 -R 的重查返回目标资源及任务所需字段：立即转入内容分析，不再做任何仓库/路径定位动作
- 封闭候选集全部 404：停止枚举 scope，改去核实资源 ID 本身的来源（唤醒备忘/producer evidence）是否陈旧

## Verification
- 重查成功且返回字段满足原目标（本例 run 的 status/conclusion/jobs 齐全，定性 failure+失败 job 名）
- 每个重试所用 repo/scope 都能在 git remote -v 输出中找到，零猜测命名
- 全程未对 evidence 库或文件系统做无指向的宽枚举

## Counterexamples
- 所有 remote 候选均 404：问题可能不在 scope 而在 ID（被删/记错），应回到 ID 的 provenance 核实，而不是继续换词枚举仓库
- 工作区与资源非同一项目（git remote 集为空或无关）：本地 remote 不构成有效判别源，应先用被点名的续跑备忘/schedule evidence 定位 owner
- 错误是 403/401、5xx、timeout 或未登录：错误类不同，需 auth/重试处理，『scope 不匹配』判别不成立
