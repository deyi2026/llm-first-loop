---
method_id: probe-session-cwd-before-unprovenanced-workdir-params-1296495e0fd5
name: probe-session-cwd-before-unprovenanced-workdir-params
description: 给本地命令/工具填 workdir 或绝对路径参数前，若该路径在会话内（用户消息、回执、引用）从未出现过，它就是凭记忆拼的猜测，首发即失败。把第一未知量换成『本会话锚定在哪个工作区』，用一次零副作用自定位探针（pwd、git rev-parse --show-toplevel、顶层结构 ls）拿权威答案：会话 cwd 是继续型任务的第一候选工作区，结构与所谈变更匹配即可直接采用；不匹配才转 token 定位/有界发现。禁止用记忆中典型布局（他人用户名/别的项目名）拼路径，也禁止失败一次后换一个猜测再试。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a33fbd45-6151-492f-b5eb-5fc45e989f08:74:40fe9c66bc423bfb16c8
evidence_refs: learning:learn:0d1e86111672
created_at: 2026-10-21T12:28:01.973401+08:00
updated_at: 2026-10-21T12:28:01.973401+08:00
---
## Trigger
任务要求在本机某工作区上执行命令或查询（跨会话续问『下一步建议/状态』最常见），且即将给工具调用填入 workdir/绝对路径参数，而会话内不存在该路径的任何 provenance（用户未给、回执未引用、报错未指向）

## Discriminator
出手前即可观察的事实：将要填入的路径在用户消息与已有回执中零出现（无任何绝对路径/工作区标识）——事后助手自己也承认『路径是我猜的』；同时本地执行环境自带免费权威锚点：cwd 可由 pwd / git rev-parse --show-toplevel 零成本读出。『路径无 provenance』+『存在零成本权威自定位』两条同时成立时，猜路径必然劣于先探针。

## Short path
- 意识到将要填入的绝对路径在会话内无 provenance → 停止拼路径，把第一未知量改为『本会话 cwd 是否就是目标工作区』
- 发一次零副作用探针：pwd && git rev-parse --show-toplevel && git status --short（可附 ls -d */ 看顶层结构）
- 若根目录结构与任务所谈对象匹配（任务点名的子项目目录存在、git 变更集包含所谈工作线的文件）→ 以它为唯一工作区，后续全部定向检查（如 grep CI workflow 验证建议前提），不再定位
- 若 cwd 与任务无关（结构不匹配/非 git）→ 不要枚举猜想的绝对路径，切换到 token 定位或其它有界发现分支

## Stop conditions
- 探针已返回与任务结构匹配的权威根目录，后续动作全部以它为基准，定位结束
- 探针证明 cwd 与任务无关后已切换到 token 定位分支，不再产生任何凭记忆拼出的路径参数
- 用户或中途回执显式给出路径 provenance → 立即改用该路径，探针流程终止

## Verification
- 探针输出的顶层目录/子项目名与任务上下文点名的对象一致
- git status 变更集包含所谈工作线的文件（如所讨论的包清单文件确在未提交清单中）
- 全程不再出现『workdir 不是有效目录/目录不存在』类参数级失败

## Counterexamples
- 用户或早前回执已显式给出目标路径：直接用该 provenance，即使它与 cwd 不同（cwd 可能只是会话默认目录而非目标 repo）
- 目标路径属于远端主机或另一执行环境：本地 pwd 不具权威性
- 探针显示 cwd 与任务结构不匹配：pwd 不足以为凭，需 token 定位/有界发现，此时『直接信 cwd』反而错
- 工具调用不接收路径参数（纯网络抓取/纯计算）：无路径可猜，方法不适用
