---
method_id: session-cwd-and-receipt-hydration-before-fs-enumeration-4d6c6b6e0c87
name: session-cwd-and-receipt-hydration-before-fs-enumeration
description: 用户请求指代本会话早前已运行/构建的工件（『这两条命令』『刚加的 hook』）时，会话默认 cwd 与本会话 evidence 账本就是现成 provenance 锚：历史回执嵌有工件的相对路径调用，相对路径解析到默认 cwd。先跑无 cd 的 pwd/git rev-parse/git status 一次回答 repo/分支/tracked 状态；search_evidence 关键词 miss 不代表账本没有，list_evidence+按 ref 水合可取回确切命令行；再定向 grep 单符号定位挂点。反模式：开场 cd ~ 全量 ls、for-loop 枚举多候选项目目录。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d643a7c4-20a9-438d-a61f-dd25be27bf55:252:9e385444015199392251
evidence_refs: learning:learn:c419fc6507b5
created_at: 2026-10-16T21:49:19.364563+08:00
updated_at: 2026-10-16T21:49:19.364563+08:00
---
## Trigger
用户消息锚定本会话早前上下文产物（如『这两条命令』『按建议执行』『settlement 收尾流程』），而 agent 的第一冲动是 cd 离开默认 cwd、全量 ls home 或枚举多个候选项目目录去『找仓库/找文件』。

## Discriminator
两个当时即存在的事实：(1) 会话默认 cwd 从未失效——一条无 cd 的 `pwd; git rev-parse --show-toplevel; git status --porcelain` 可同时回答『哪个仓库、什么分支、工件是否 untracked』；(2) 本会话 evidence 账本（list_evidence 可见 120 条）里存在嵌入相对路径的历史 execute_command 回执（如 `python3 tools/krate/...`）——search_evidence 关键词 miss ≠ 账本无记录，按 ref 水合即得确切调用路径。

## Short path
- 保持默认 cwd，先跑 `pwd; git rev-parse --show-toplevel; git status --porcelain`：一次回答目标 repo、分支、工件目录是否 untracked（直接覆盖『并到 main 了吗』这类状态问题）。
- list_evidence 列近期回执，按 ref 水合含目标工件的 execute_command 回执：拿到相对路径命令行，确认工件位置与调用方式（不依赖关键词搜索命中）。
- 用回执中的相对路径在默认 cwd 下 ls/试跑验证实体存在，并按『纯 CLI+数据文件 vs 服务运行时代码』分层判断重启需求。
- 定向 `grep -rn <符号> src/ --include='*.py'` 定位挂点实现（如 settlement_submit 所在文件与调用链），再做修改/测试/发布编排。

## Stop conditions
- pwd/git 探针已确认 repo、分支与 tracked 状态，用户的状态类问题已被权威 git 输出回答；
- 水合回执已给出工件确切调用路径且实体在默认 cwd 下存在；
- 挂点文件经定向 grep 命中；此后不再产生对 home/workspace/多候选目录的枚举动作。

## Verification
- 最终状态断言（如『未并 main』）逐字对应 git rev-parse / git status 输出；
- 引用的命令路径来自水合回执，且该相对路径在默认 cwd 下可 ls 到实体；
- 复盘轨迹：开场动作之后不应再出现 cd ~ 后的全目录枚举或候选目录 for-loop 分支。

## Counterexamples
- 目标工件确实在会话 repo 之外（全局配置、另一个项目、远端主机）——cwd 锚定失效，目录枚举/搜索是合理首步；
- 全新会话且 evidence 账本为空、无任何历史回执——账本水合无从谈起，只能 pwd+定向 search；
- 历史回执记录时的 cwd 与当前不同（会话中途回切换过目录）——相对路径不可直接对当前 cwd 解析，需以 git toplevel 或回执上下文校准后再定位。
