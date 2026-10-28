---
method_id: resolve-artifact-home-root-before-in-repo-hunt-when-nickname-misses-git--7c1619f7bdb8
name: resolve-artifact-home-root-before-in-repo-hunt-when-nickname-misses-git-scope
description: 用户用项目昵称（台账/状态文档/基线文档）指代一个带章节结构、未给路径的产物时，第一个未知量是『该产物的主目录在哪个根』，而不是『当前仓库里哪个文件匹配』。本集在代码镜像仓库里连做 token 内容搜索、grep 台账、grep §8、mtime 枚举 8+ 次全部落空，因为目标文档实际住在仓库外的兄弟工作区目录。开局即有的环境信号（cd 回退、task-state not found、特征 token 全仓负查）本可一步把搜索根从『仓库』切换到『工作区』。
aliases: 台账文档不在当前仓库里去哪找, 用户说的台账是哪个文件, git grep 搜不到基线 SHA 的文档在哪, 工作区目录和代码仓库不是一个目录, cd 失败 pwd 回退说明环境布局不对, 会话产物在工作区根不在 git 仓库
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:6e7b4358-a1b8-4e23-a99c-931d6e86bee2:125:012458e1ed5760028f6b
evidence_refs: learning:learn:227bc82dcf9c
created_at: 2026-10-28T09:40:46.320816+08:00
updated_at: 2026-10-28T09:40:46.320816+08:00
---
## Trigger
用户以昵称/俗称引用一个未给路径、带章节或基线内容的文档（如『把台账 §8 改成以某基线为准』）；当前 cwd 是代码/镜像仓库；且开局可观测信号显示会话工作区与 cwd 不是同一目录（cd 到预期工作区失败而 pwd 回退、会话状态工具报 not found），或仓库内特征 token 搜索已负向命中。

## Discriminator
三条当时即可见的事实，任一成立即不应继续在仓库内枚举：(1) 首条命令 cd 预期工作区路径失败、pwd 落在镜像仓库——环境布局与会话假设不符；(2) 对目标文档必然包含的特征 token（如被引用的基线 SHA）做 git grep 全仓 rc=1——文档不在仓库受控面内；(3) 工具回执明示 task state not found in current session/workspace。

## Short path
- 把用户指称解析成单一未知量：『该昵称文档的主目录是哪个根？』，不先在当前仓库内做内容/章节枚举
- 消费开局信号：cd 回退输出与 task-state 回执证明 cwd ≠ 会话工作区，列出 $HOME 下候选工作区根（ls -d ~/*workspace* 等有界深度探针）
- 做一次 git 范围负查：对文档必然包含的特征 token git grep 全仓，rc=1 即停止一切仓库内搜索（命中则文档在仓库内，直接打开）
- 在定位到的工作区根下按昵称同义词/日期/文档命名模式找到唯一目标文件，读取目标章节确认存在
- 备份后改写目标章节，sha/cmp 双验仅该节变化且引用值与实测回执一致，停止

## Stop conditions
- 特征 token 在仓库内 grep 命中——文档就是受控文件，转入直接读取，不做文件系统外探针
- 已在工作区根下找到唯一匹配昵称且含目标章节标记的文件——发现阶段结束，进入编辑与验证

## Verification
- 改写后与改前备份做 cmp/sha 比对，确认仅目标章节变化、其余行逐字节不变
- 文档写入的基线/状态值与权威实测回执（远端 ref、服务状态）一致，不引用未实测断言

## Counterexamples
- 昵称文档本就是仓库受控文件（token grep 命中）——直接读并改，外溢到文件系统探针是浪费
- 单仓单工作区环境，cwd 即工作区、无 cd 回退或 not-found 信号——判别不成立，仓库内按章节标记+mtime 收窄才是正确路径
- 昵称是通用词且仓库内存在多个含同名章节的文档——离开仓库前必须先做 token 负查佐证，否则会误判为外部产物
