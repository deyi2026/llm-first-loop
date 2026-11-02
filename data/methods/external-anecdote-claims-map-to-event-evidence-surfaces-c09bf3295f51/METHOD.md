---
method_id: external-anecdote-claims-map-to-event-evidence-surfaces-c09bf3295f51
name: external-anecdote-claims-map-to-event-evidence-surfaces
description: 用户分享外部文章/段子（如『AI 自己 merge 进 main、stash 别人提交、git log 留言』）且本地环境可能同构时，不要停在摘要，也不要用通用关键词全域搜仓库：先从正文提取可核查断言清单，按『前提成立/事件已发生/护栏存在』三类分别映射到唯一权威面——前提→具名配置/源码锚点；事件→定向 git 查询（--merges 带身份、stash list、reflog、log/interop 通道）；护栏→最后才做 src 内 scoped 符号检索。事件是否发生只能由 git/审计痕迹裁决，内容搜索裁决不了事件。这样把全域关键词扫仓（镜像噪声、超时、无命中）换成每条断言一次定向取证，搜索空间从『全仓库』缩到『每断言一个权威面』。
aliases: 文章里的事我们仓库会发生吗, 外部事故段子本地对账, 别人家的瓜怎么核到自家仓库, AI 乱 merge stash 留言 核查, 链接故事逐条找证据
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:c70ac3c2-9b73-442c-9a37-94a9ff1bb6f7:0:efcc36c79a87009fcc79
evidence_refs: learning:learn:b6c69d712ab3
created_at: 2026-10-31T19:30:15.232689+08:00
updated_at: 2026-10-31T19:30:15.232689+08:00
---
## Trigger
用户丢来外部链接，正文描述某类 agent/工程事故行为（自行合并、暂存他人提交、日志留言等），本地仓库与环境可能同构（同模型、共享工作树、同类流程），隐含问题是『这事在我们这会不会/有没有发生』

## Discriminator
正文读完即得的可核查事件断言清单：每条断言都是事件型，且事件留有唯一权威痕迹面——merge 断言→log --merges 的 author/committer 与时间窗；stash 断言→stash list + reflog；留言断言→log message/跨 agent 通道目录；环境前提→正文点名的配置与源码锚点。另外 fetch 回执已显示 canonical per-item endpoint（同 item id 的站点快路径）时，换 URL 形态重取同一文章是冗余。

## Short path
- 取一次正文（回执含 canonical per-item endpoint 即不再换 URL 形态重取）；未知量：故事里有哪些可核查断言
- 把断言分三类：环境前提／事件是否发生过／有无程序侧护栏；每类断言映射到唯一权威取证面
- 前提类：直读正文点名的配置/源码锚点（模型 profile、默认 cwd 等），确认同构是否成立
- 事件类：3-4 条定向查询——log --merges 带身份与时间窗、stash list、reflog、跨 agent 留言通道（log/interop 目录），必要时补会话审计
- 护栏类：最后才在 src 内做 scoped 符号检索（merge/admission kinds 等），不用通用词全域内容搜（会被发布快照镜像噪声淹没）
- 汇成『前提/已发生/护栏』三栏结论 + 授权边界内的下一步建议，附可复核坐标后停止

## Stop conditions
- 每条断言均有权威面证据（前提成立/事件已发生或未发生/护栏存在或缺失）且给出可复核定位
- 用户只要摘要，或文章与本地系统不同构：读完正文即止，不启动本地核查

## Verification
- 每条结论附可复核坐标（sha、stash@{n}、文件:行、会话 id、目录计数）
- 口径差异显式标注：如 ff-only 合并不留 merge commit，回执数≠merge commit 数；文本匹配查不到不等于『没审过』

## Counterexamples
- 用户只要文章摘要/翻译，或本地无共享主干/多 agent 前提——前提栏直接判不成立，早停，不做事件核查
- 断言是代码语义/机制（『X 会 fail-open』）而非事件——git 痕迹回答不了，应走定义面直读（adjudicate-prior-claims 类方法）
- 断言关于外部命名工件的存在/归属/官方性——走 registry 权威路径查询，而非本地 git 取证
