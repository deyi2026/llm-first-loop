---
method_id: state-record-first-for-stateful-command-params-2ec22b820b16
name: state-record-first-for-stateful-command-params
description: 当命令的必填参数是'当前状态值'（部署代号、code_root/runtime_root、数据目录等），且证据链已表明本地存在记录这些字段的权威状态文件（部署 store、runtime manifest）时，先读状态记录直接取值再执行，而不是探索实现源码反推默认值。只有记录缺失、与活证据矛盾或语义前置条件未被记录回答时，才做定向源码阅读。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:a8ca7a5d-9f35-462e-b02e-e13f15ff0023:361:d5bf74cc399dfa22b124
evidence_refs: learning:learn:ac39ea559acb
created_at: 2026-09-20T13:59:57.851953+00:00
updated_at: 2026-09-20T13:59:57.851953+00:00
---
## Trigger
CLI --help 列出的必填参数均为运行时状态值（根目录、代号、data 目录），同时任务叙述已引用对应记录存在于本地（如'记录 generation=55、git_head=…'、manifest head）

## Discriminator
进入源码探索前已可见两点：① publish --help 已列明全部必填参数（--expected-generation/--code-root/--runtime-root/--data-dir），即'要什么'已完全确定；② 用户核验消息确认存在含 generation=55/git_head 的部署记录——这些字段恰好就是参数要的值。未知量只剩'当前值是多少'，其权威持有者是状态记录本身，不是实现源码

## Short path
- git status/HEAD 确认工作区与核验一致（未知量：tracked dirty 是否属实）
- 定位 CLI 并读目标子命令 publish --help（未知量：必填参数清单）
- ls data/runtime 一步定位部署记录并读取（未知量：code_root/runtime_root/expected-generation 的当前值）
- 仅当记录缺字段时，读一份 runtime_manifest.json 补 data_dir
- 提交→publish 绑提交后新 HEAD→校验回执 generation=expected+1→restart→停止，异步验收留到下一轮

## Stop conditions
- --help + 状态记录已给出全部必填参数值时，立即转入用户给定的执行序列，不再读实现源码
- 用户已给有序计划且每步回执吻合时，按序推进，不添加计划外子命令（如 show --help）
- publish/restart 回执拿到且关键字段（generation、git_head）与预期一致即收尾，不轮询异步动作

## Verification
- publish 回执 git_head == 提交后的新 HEAD（而非记录中的旧 HEAD 或父提交）
- publish 回执 generation == expected_generation + 1
- 传入参数与部署记录/manifest 中的字段值逐字一致（code_root/runtime_root/data_dir）

## Counterexamples
- 全新环境无历史部署记录：状态值只能从安装文档或源码默认值推导，此时读源码是正路而非绕路
- 记录值与活进程/磁盘证据矛盾（如记录 HEAD ≠ 进程 manifest 的 HEAD）：记录可能过期，须先三角验证真伪再取值
- 参数涉及语义前置条件（如 expected-generation 的不变量语义、脏区检查行为）且记录无法回答：做一次定向源码阅读是合理的，但不等于全树 grep 枚举
