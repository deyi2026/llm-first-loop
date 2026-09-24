---
method_id: env-self-query-before-guess-enumeration-a98f32371d18
name: env-self-query-before-guess-enumeration
description: 操作 remembered/guessed 值(绝对路径、remote 名)之前，先查询环境自描述事实：pwd+ls -a 定位当前 repo，git remote -v 拿真实 remote 名；把任何确定性负回执（目录不存在/remote 不存在）当作整组记忆候选作废的证据，而不是继续换参数枚举更多猜测路径。对存在性否定结论（上游无新提交/无缺失）只信 raw 输出——grep/过滤视图可能恰好隐藏决定结论的 + 行，下结论前重跑未过滤输出核对。这将跨会话过期记忆引发的枚举与过滤输出返工，收缩为两步自描述查询加一次 raw 核对。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7d3df8c3-848b-4bf3-b66b-1dbd2f791ac4:1166:6131027ccd1042132290
evidence_refs: learning:learn:1de29999b089
created_at: 2026-09-23T15:46:32.660177+00:00
updated_at: 2026-09-23T15:46:32.660177+00:00
---
## Trigger
需要在当前机器定位 repo/目录/remote 名，或需回答"上游今天有没有新东西/本地有没有缺"这类否定性结论，而手中的候选值来自记忆或上一会话回忆（Evidence 查询为空、无 provenance 支撑）

## Discriminator
环境已给出确定性负回执（[目录不存在]、remote 'X' does not exist）或 Evidence 查询返回空——这同时证明记忆候选集不可信；而环境的自描述状态（pwd、ls -a、git remote -v）随时可一条命令取得，能把 N 个猜测路径/remote 名缩到 1 个已验证值

## Short path
- pwd; ls -a：解决"当前环境就是哪个 repo"——cwd 含 .git 即为目标，无需猜测绝对路径
- git remote -v：解决"上游 remote 真名是什么"——用列出的名字 fetch，避免凭记忆的 remote 名首连失败
- fetch 真实 remote（确认退出码 0）+ git log <upstream> --since=今日零点：解决"上游今天有几条提交"，直接在 fetch 后的 remote-tracking 分支上数
- git cherry <local> <upstream> 或区间比较，保持 raw 输出不过滤：解决"上游有什么是本地没有的"
- git merge-base + git merge-tree 试合并（不落地）：解决"未并项合并冲突面"，把"太旧是否影响稳定"分解为冲突面+行为变更两层
- 今日更新数与未并项冲突面均拿到权威回执后立即停止，不扩大时间窗或延伸再确认

## Stop conditions
- fetch 成功（退出码 0）后在 remote-tracking 分支上直接数出今日提交数
- 未并项的冲突面（merge-base 文件交集 + merge-tree 试合并）与行为影响已有回执
- 所有否定性结论（今日无更新/本地无缺失）已经用 raw 输出交叉核对

## Verification
- 重读用于否定结论的 log/cherry 的原始输出，确认没有 + 行被过滤器隐藏
- remote 名与 repo 路径来自本会话 git remote -v / pwd 的回执，而非记忆或上轮口误
- "零提交"结论以 fetch 成功为前提，排除网络失败造成的假性无更新

## Counterexamples
- pwd 显示 cwd 与目标 repo 无关（全新容器/空白 shell）——自描述查询定位不到目标，目录级搜索/枚举确有必要
- 目标不是 git repo（纯文件导出包）——remote/merge 基验证不适用，应改用文件级比对
- 用户本轮已明确给出并验证过的路径/remote 名——直接使用，自查询是冗余动作
- 过滤器是为已知正向特征设计（如 grep 特定错误码）而非服务否定性结论——重跑 raw 输出属无信息重复
