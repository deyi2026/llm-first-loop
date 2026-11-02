---
method_id: probe-dont-guess-env-constants-before-first-call-b30b6377c221
name: probe-dont-guess-env-constants-before-first-call
description: 新会话/新环境首次需要把 workdir、文件名集合、解释器命令名等环境常量作为工具或 shell 参数时，若本会话尚无任何回执建立过该值，不要凭项目名联想或记忆猜测：猜错一次就多付一轮参数校验失败+恢复往返。先用一条不携带该常量的廉价只读探测取权威值：仓库根用 pwd && git rev-parse --show-toplevel，文件集合用 glob/ls 列举实际存在的名字，命令名用 command -v 或读项目 CI/workflow 里钉死的权威调用方式；一次探测全会话复用。本集三次同类摩擦：workdir 猜成不存在目录、测试文件名凭记忆点名不存在、python 命令名跨执行方式不稳定。
aliases: 先探测再传环境参数, 别猜workdir先查仓库根, 文件名不确定先通配列举, python还是python3先探测, 新环境首次调工具先取路径
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:4aea0dd4-3b3b-4874-8090-870678230df3:288:4bcc7cca70e9d879fbc6
evidence_refs: learning:learn:05531641ebe5
created_at: 2026-11-03T00:20:40.938525+08:00
updated_at: 2026-11-03T00:20:40.938525+08:00
---
## Trigger
新会话或新执行环境里，第一次需要把环境常量（workdir 路径、目标文件名集合、解释器/命令名）作为工具参数或 shell 参数传入，且本次会话没有任何回执、指令或已读配置建立过该值。

## Discriminator
两个当时已知事实的组合：(1) 会话内零先例——没有任何先前输出给出过该常量值；(2) 参数合同强校验——workdir 必须是有效目录、文件必须存在、命令必须在 PATH。二者合起来意味着猜测值大概率一次失败，而一条不依赖该常量的只读探测能确定性返回权威值。

## Short path
- 传参前自问：该常量是否已被本会话某条回执建立？是→直接复用；否→进入探测。
- 按常量类型做一次探测：仓库根用 pwd && git rev-parse --show-toplevel；文件名集合用 glob/ls 模式列举实际名字；命令名用 command -v 或读项目 CI/workflow 中的权威调用行。
- 用探测返回的权威值填参执行原任务动作，不再枚举猜测变体。
- 探测结果作为本会话该常量的唯一权威复用，同类参数不第二次猜。

## Stop conditions
- 权威值已由探测输出或先前回执建立，可直接填参。
- 工具支持省略参数走默认行为（如不带 workdir 即当前目录）时，直接省略而不是探测。
- 探测手段不可用（无 shell、无列举工具）且失败消息自描述、可指导恢复时，才允许一次带错误处理的直接尝试。

## Verification
- 首次使用该参数即通过校验：无 'not a valid directory' / 'command not found' / 'No such file' 类失败。
- 每个环境常量都能指回一条建立它的回执（探测输出或先前证据），可审计。

## Counterexamples
- 任务文本或先前回执已给出绝对路径/命令名 → 直接使用，探测反而是多余往返。
- 项目 CI/workflow 已钉死权威调用方式（如 uv run python -m pytest）→ 沿用该调用，而不是探测系统默认解释器。
- 一次性低风险动作且失败消息会直接给出正确格式 → 允许直接尝试，但同会话同类参数失败后必须转探测，不许换一个猜测值再试。
- 文件名由上游调用方逐字给出 → 点名直读，不做 glob 枚举。
