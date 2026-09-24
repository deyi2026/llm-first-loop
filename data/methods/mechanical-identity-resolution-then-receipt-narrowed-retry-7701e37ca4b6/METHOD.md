---
method_id: mechanical-identity-resolution-then-receipt-narrowed-retry-7701e37ca4b6
name: mechanical-identity-resolution-then-receipt-narrowed-retry
description: 当工具调用需要环境身份参数（workdir、code_root、仓库根等）而会话内尚无其权威观察值时，不要按项目名猜测路径，先用机械解析（pwd、git rev-parse --show-toplevel、git log）作为独立一步求值，并把解析结果穿透到后续所有要求同一身份的调用；若调用因参数失败，回执点名的缺口就是唯一未知量，补齐后重发同一调用，不换工具、不扩大排查。本集两次参数类失败（猜测 workdir、publish 缺 code_root）各浪费一跳，均可由该规则避免。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:152a76d5-3fea-40cf-8a6d-00de8ac369c2:439:3b8d3bfacffb1e4fc769
evidence_refs: learning:learn:275c181c81a4
created_at: 2026-09-24T09:24:57.701688+00:00
updated_at: 2026-09-24T09:24:57.701688+00:00
---
## Trigger
工具签名要求文件系统/git 身份参数（workdir、code_root、runtime_root 等），且当前上下文没有该参数的权威观察值；或动作失败回执显式点名缺失/无效参数。

## Discriminator
上下文中是否已存在该身份的机械解析结果（如 git rev-parse --show-toplevel 的输出）却未被使用；失败回执是否明确指出唯一缺口（例如『必须提供 code_root』『workdir 不是有效目录: <被猜的路径>』）。

## Short path
- 需要身份参数且无观察值时，先执行 pwd && git rev-parse --show-toplevel && git log，解析仓库真实根与 HEAD（未知量：code_root 与待发布 git_head）
- 用解析值一次性带齐参数调用目标工具，而不是按项目名猜路径或省略必填项
- 若仍失败，只补回执点名的那个参数重发同一调用，不换工具、不改用宽搜索
- 把解析出的根继续用于后续要求同一身份的调用，并核对回执中的路径/git_head 与解析值一致

## Stop conditions
- 身份参数已由机械解析权威取得，并被一次成功调用验证
- 回执不再报参数类错误，转入结果与协议解读阶段

## Verification
- 成功回执中的 code_root/git_head 与 git rev-parse、git log 的机械输出一致
- 同一参数只失败一次，无重复的参数类失败调用

## Counterexamples
- 工具从 cwd 自行推导路径或接受仓库相对路径时，无需显式解析，直接调用更短
- 远程 API / 无本地 shell 场景中 pwd 与 git rev-parse 不可用，需改用清单或配置类权威来源求身份
- 失败原因是权限、语义或状态冲突而非参数缺失时，补参重发无效，应按错误类别分支处理
