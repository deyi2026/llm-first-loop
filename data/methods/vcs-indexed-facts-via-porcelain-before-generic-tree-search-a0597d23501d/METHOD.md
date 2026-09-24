---
method_id: vcs-indexed-facts-via-porcelain-before-generic-tree-search-a0597d23501d
name: vcs-indexed-facts-via-porcelain-before-generic-tree-search
description: 在 git 仓库中，当未知量本身就是 VCS 权威索引的事实——未跟踪/变更文件集合与精确计数、被跟踪代码中的符号实现位置——先走 porcelain(-uall/pathspec)/git grep 等受限权威查询，而不是遍历全树（含大量未跟踪积压）的通用搜索工具；后者在此类仓库易超时。若通用搜索已超时，立即切换 git 原生限定查询而非重试同类工具。效果是把'全树候选空间'缩成'索引直答'，消除超时与重复发现。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:152a76d5-3fea-40cf-8a6d-00de8ac369c2:281:1d15d999431b10670c1b
evidence_refs: learning:learn:314e419837f1
created_at: 2026-09-24T08:57:27.121734+00:00
updated_at: 2026-09-24T08:57:27.121734+00:00
---
## Trigger
处于 VCS 仓库且本轮未知量是版本控制系统已索引的事实（未跟踪/变更集合与计数、被跟踪源码中的符号定位）；或通用 search_files/全树枚举在含大量未跟踪积压的仓库中已超时

## Discriminator
首次 git status --porcelain 已把未跟踪积压定位到单一路径前缀且由 git 权威枚举——'精确计数'这一未知量本身就是一条 git 查询；要定位的实现符号属于被跟踪源码，已知符号名可用 git grep/受限 grep 在 src+tests 内直接命中。两未知量都不需要全树内容枚举

## Short path
- 列出本轮未知量：未跟踪精确计数、目标实现文件、该实现的状态/写入副作用语义
- 集合/计数类未知量用 git status --porcelain -uall（可加 pathspec 限定）直取权威值，不经文件系统搜索工具
- 符号定位类未知量用 git grep/受限 grep 只扫 src 与 tests，读实现一次确认字段副作用（如 reasons 是否触发 quarantine 关写）
- 暂存用显式 pathspec 并核验 staged 集合构成（目标外=0）后提交
- 读相邻测试与路径绑定语义确定 fixture 布局，实现并验证后停止

## Stop conditions
- porcelain 计数与暂存/提交回执文件数一致，计数未知量闭合
- 实现字段语义已从源码确认，新信号通道（advisory vs 副作用字段）已定且不误触发既有副作用
- 测试在 git 与非 git fixture 下均通过

## Verification
- 对比 -uall 计数与 git add/commit 回执的文件总数
- 确认新增 advisory 字段未进入会触发 quarantine/禁写的 reasons
- 非 git 环境（tmp_path）降级为 None 且 preflight 仍 ok

## Counterexamples
- 目标内容在 .gitignore/未跟踪文件中且 git grep 不覆盖（运行日志、抓取包），必须用目录级文件系统检索
- 需要模糊/语义匹配而非精确符号名时，porcelain/grep 无法替代搜索工具
- 小仓库中通用搜索秒回，切换无收益；方法仅在树庞大或工具已超时场景有价值
- 非 VCS 环境根本没有权威索引可查，只能走发现式搜索
