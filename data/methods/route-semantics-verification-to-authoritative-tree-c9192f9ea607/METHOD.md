---
method_id: route-semantics-verification-to-authoritative-tree-c9192f9ea607
name: route-semantics-verification-to-authoritative-tree
description: 当同一源码存在多份拷贝（主工作树、evals/*/results/runtime-* 快照、.tmp-ci 或 .worktrees 镜像）时，先从部署/服务状态元数据拿 code_root 与 git_head，把『确认当前实现语义』的读取与 grep 定向到该权威树；搜索命中排最前的镜像副本只当线索，结论必须由运行系统实际使用的那份源码盖章，避免先读陈旧镜像再回头补主树验证。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:863879fe-d8f5-48d9-bbdc-6ddc6eaf4b8b:215:00fd02fd4eb97014b939
evidence_refs: learning:learn:0cd0aa2b3329
created_at: 2026-09-19T07:22:51.046608+00:00
updated_at: 2026-09-19T07:22:51.046608+00:00
---
## Trigger
需要确认某 CLI 命令/模块/函数的当前实现语义，而 search_files 或 grep 的命中结果里同时出现主工作树路径与 evals/*/results/runtime-*、.tmp-ci/*、.worktrees/* 等快照/镜像路径

## Discriminator
在发起代码检索之前，服务/部署状态已显式给出 code_root、runtime_root 与 git_head；且搜索命中路径本身带 evals/.../results/runtime-... 等快照目录前缀。这两点在读任何副本前即可知，足以把候选从『全部命中』缩为『code_root 下对应文件的一次定向 grep』

## Short path
- 取服务/部署状态：解决两个未知量——是否需要 restart（generation/started_at/git_head 对比代码落盘时间）与权威源码根（code_root）
- 对 code_root 下已知入口文件做定向 grep（命令集、目标子命令、锁定语义的注释/测试语句），一次同时拿到 CLI 管理面与 evolve-complete 的人工通道语义；未知量=当前树语义是否支持结论
- git status/log 确认工作树改动与 HEAD 差异；未知量=restart 将激活哪些变更（脏工作树 or 已合入 PR）
- 带过滤/分页参数拉演进清单中相关条目；未知量=目标条目当前 state（accepted/executing/executed）
- 携带正确 generation 发起 service_control restart，收到异步回执即停止，不轮询
- 人工通道命令以可粘贴形式交还用户执行，不代跑

## Stop conditions
- 目标语义已由 code_root 主树源码（含注释或测试 docstring）直接确认，无需再读任何镜像副本
- restart 回执已接受并给出 action_id，本轮立即结束，终态留待下一轮 status 查询
- 用户所需事实（状态、边界、下一步选项）均已由权威来源验证

## Verification
- 最终据以下结论的文件路径必须位于部署状态给出的 code_root 之下，而非 evals/results 或 tmp worktree
- 关键结论（如 executor=human 的人工通道边界）应有主树内注释或测试锁定语句呼应，而非仅存在于快照副本
- restart 请求的 generation 与状态查询返回值一致

## Counterexamples
- 任务本身就是考古某次历史 eval 运行：results/runtime-* 下的快照才是权威目标，读主树反而会得出错误结论
- 没有任何部署/清单元数据指示哪份是运行副本时，应先宽搜索并显式消歧，不能凭路径猜测主树
- 问题是『服务此刻在跑什么』：权威是已部署 git_head 对应的提交内容，而非脏工作树或任何快照副本
