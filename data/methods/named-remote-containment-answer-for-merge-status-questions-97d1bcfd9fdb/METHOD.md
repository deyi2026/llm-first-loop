---
method_id: named-remote-containment-answer-for-merge-status-questions-97d1bcfd9fdb
name: named-remote-containment-answer-for-merge-status-questions
description: 用户问『工作并入 <具名远端>/main 了吗』这类成员资格问题时，问题文本本身已点名唯一权威真值来源——该远端的 remote-tracking ref。一次定向 fetch + ahead/behind 算术 + remote..local delta 枚举即是完整答案；本地 log 漫扫、治理/审计信号探针、线上服务健康检查都不改变该真值。本集 6 次调用中约 2 次（audit 信号探测、服务端点 curl）不服务于该未知量，核心答案在 fetch+remote..local 比较后即已完备；附带验证项（关闭上轮待验证承诺）应显式标注为附带、置于核心答案之后。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d643a7c4-20a9-438d-a61f-dd25be27bf55:1203:5776a0104a38e599289b
evidence_refs: learning:learn:7386a8dd49e2
created_at: 2026-10-17T01:31:06.093189+08:00
updated_at: 2026-10-17T01:31:06.093189+08:00
---
## Trigger
用户提出关于本地工作是否已到达某个具名上游/远端分支（<remote>/main、PR 目标分支等）的是非/成员资格问题，且问题文本本身已点名目标 ref

## Discriminator
问题点名的具体远端 ref 使未知量可机械求解：fetch 该远端后 rev-list --count <remote>..<local>（ahead）与 <local>..<remote>（behind）加 log <remote>..<local> 直接给出未并入 delta；任何本地状态枚举、audit/governance 信号或运行态服务探测都不影响这个包含性真值

## Short path
- 从问题解析出唯一未知量：具名远端 ref 是否包含本地分支新提交，忽略一切不改变该真值的仓库健康/运行态探针
- git fetch <该远端> 只刷新这一个权威记录，并读取远端 HEAD
- git rev-list --left-right --count <remote>/<branch>...<local> 得 ahead/behind，判断是否纯 fast-forward
- git log --oneline <remote>/<branch>..<local> 枚举未并入提交作为答案证据
- 直接给出是非答案（含 delta 数字与提交清单）即停止；附带验证项显式标注为附带且置于核心答案之后

## Stop conditions
- ahead/behind 与未并入清单已取得：答案完备，不再追加任何不改变该真值的状态探测
- 若 behind>0 或历史被改写（非 FF）：停止模板化回答，转入 rebase/冲突面评估
- 附带承诺的关闭动作最多一项且必须显式标注为附带，不得挤占或混淆核心答案

## Verification
- fetch 后以 remote-tracking ref 的 SHA 作为远端真值并在答案中引用，而非缓存的旧 ref
- 抽验代表提交确不在远端祖先中：git merge-base --is-ancestor <sha> <remote>/<branch> 返回非零
- ahead/behind 数字与 log 清单条数一致

## Counterexamples
- 问题指向 forge 平台的 PR/squash merge：squash 后原 SHA 不在远端祖先里但工作实际已并入，本地包含性测试会误报『未并入』，需 git cherry 或平台 API
- 远端存在并发 force-push/改写者：单次 ahead/behind 可能基于被改写历史，需 merge-base/contains 复核并叠加成稿前重读权威记录的方法
- 用户问的是本地集成分支是否并入本地 main：不 fetch，直接 git branch --contains / log main..feature
- 问题本身是『部署/上线了吗』这类运行态问题：git ref 比较不充分，服务健康与审计信号此时在范围内不可跳过
