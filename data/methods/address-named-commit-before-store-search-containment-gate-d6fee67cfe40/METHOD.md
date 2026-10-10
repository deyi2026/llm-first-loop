---
method_id: address-named-commit-before-store-search-containment-gate-d6fee67cfe40
name: address-named-commit-before-store-search-containment-gate
description: 当回执/任务已给出精确版本库对象地址（commit hash/tag/PR），且未知量是该变更的内容或它是否已进入某条发布线时，先做寻址操作：git show <ref> 取主题与文件清单，git show <ref>:<path> 读该 commit 内的文档，git branch --contains / merge-base --is-ancestor 判落线；并把『发布前必须包含该修复』持久化为机器可查的 merge-base 门禁。不要在 evidence/event 存储里换词枚举：存储只答『是否已有记录』，首轮 miss 且视图边界已明时重试零信息。区别于 resume-continuation（清点剩余 delta 的续跑场景）：本方法是单对象寻址+落线门禁。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:fd840981-a906-404c-8c80-1c3452e1c66a:0:bedbbdc1e59a5e8ecd48
evidence_refs: learning:learn:d559dba692cf
created_at: 2026-10-09T18:03:58.307725+08:00
updated_at: 2026-10-09T18:03:58.307725+08:00
---
## Trigger
回执或任务文本含精确 commit hash 等 VCS 直接地址，待解未知量=『该变更改了什么/在哪些分支/下一条发布线是否会带上它』，而行动正转向对 evidence/event 记录存储做关键词枚举。

## Discriminator
knowledge-at-time 两条：(1) 用户首条回执已命名 14352cc6f——『今天修了什么』存在一次 git show 即可答的权威对象；(2) event_stream 首条回执只含当前会话自身动作，已证明该视图不覆盖跨会话历史，继续换词查询不可能缩小范围。

## Short path
- 一次运行态核验（service status）+ 一次 search_records 去重检查；miss 即停，不换词重试
- git show 14352cc6f --stat → 修复主题与文件清单（解『改了什么』）
- 对清单中的事故文档用 git show <其所属 ref>:<path> 读取；文件属于未合入当前分支的 commit 时，不在工作树 read_file
- git branch --contains <hash> + git merge-base --is-ancestor <hash> <main/各插件分支> → 落线事实（解『插件发布会否重新带入问题』）
- 将义务写成含 merge-base 门禁的 lesson 落库；停止

## Stop conditions
- 命名对象已给出内容与落线事实，且义务已持久化为可核验门禁
- search_records 首轮 miss 且存在直接地址 → 立即转寻址，不做第三轮换词
- hash 解析失败/无 git 访问 → 才回退到宽搜索或向用户求证

## Verification
- merge-base --is-ancestor 的布尔结果作为发布门禁，不凭记忆断言『会被合入』
- commit stat 文件清单与事故文档所述修复范围互相印证后才下结论
- 运行态结论（gen212/屏障空）引用 service status 回执而非转述用户消息

## Counterexamples
- 未知量是『是否已有持久化记录』：只有 search_records 能回答，git 不存这类记录——本集前两轮去重检索正当，不应被本方法跳过
- 用户只有模糊指称（『今天那个修复』）且无 git 访问或非 git 仓库：关键词/事件检索才是正确首步
- 未知量是运行态事实（当前 serving generation、健康、准入屏障）：git 对象答不了 live state，须用 service/status 类工具
