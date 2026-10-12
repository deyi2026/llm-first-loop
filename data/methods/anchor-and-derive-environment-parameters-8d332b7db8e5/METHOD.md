---
method_id: anchor-and-derive-environment-parameters-8d332b7db8e5
name: anchor-and-derive-environment-parameters
description: 当工具调用的参数编码了环境事实（workdir、Python 解释器、确切测试/源文件名），而这些事实未被任何输入权威建立时，先用一次廉价锚定观察（pwd && ls）取得根目录、布局、.venv、真实文件名，之后所有参数都从已观察事实推导（.venv/bin/python、真实测试文件名），不用通用默认值。参数猜测失败应视为'去观察该参数'的信号，而不是枚举相邻猜测。注意：对外部权威断言的定向核查（符号缺失搜索、引用 commit 的 diff、按真实文件名跑测试）属于在路径上，应保留，不属于浪费。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:72cadfe4-cbee-455c-ad5b-feaa06074185:0:b5cce925a90f140dadef
evidence_refs: learning:learn:e698d7b3e817
created_at: 2026-09-19T01:36:53.659952+00:00
updated_at: 2026-09-19T01:36:53.659952+00:00
---
## Trigger
任务要求发出其参数依赖未确立环境事实的调用：绝对路径/workdir、解释器、确切文件名；输入中只有相对引用（src/、模块名、测试描述），且当前会话尚未观察过这些参数的真值。

## Discriminator
检查输入或已完成观察中是否已存在该参数的锚点：输入无任何绝对路径 ⇒ workdir 是未知量，必须先 pwd；ls 输出含 .venv/ ⇒ 解释器应为 .venv/bin/python 而非裸 python；git show --stat 已列出确切测试文件名（如带 _p0a 后缀） ⇒ 不得再猜同族文件名。任一锚点已出现却仍用默认猜测，即为可避免的摩擦。

## Short path
- 第一步只解决'我在哪/有什么'：pwd && ls -la，一次性获得 repo 根目录、.venv 存在性、tests/、docs/ 布局。
- 用 git log/branch/ahead-count 把当前 HEAD 定位到外部评审引用的基线 commit 之上，确立'哪些是评审之后的新增'。
- 对外部断言逐条选最窄核查：'已实现' → git show 候选 commit（其 --stat 同时暴露确切测试文件名）；'不存在某实体' → 对 src/*.py 定向符号搜索；'测试通过' → 用观察到的 .venv/bin/python 与真实文件名跑 pytest。
- 任何参数类失败（目录不存在、command not found、file not found）触发一次观察（列目录/回看既有输出）来解析该参数，禁止枚举相邻猜测（/workspace/src、裸 python 重试）。
- 每条断言都映射到一个已验证事实（commit diff、搜索回执、测试通过数、ahead 数）后立即停止发现并作答。

## Stop conditions
- 外部评审/任务的每条断言都已有权威观察支撑（diff、定向搜索回执、测试通过计数、ahead-count），进入作答阶段。
- 同一参数类（路径/解释器/文件名）出现第一次失败即切换为观察模式；第二次同类猜测被禁止。

## Verification
- 追溯检查：会话中每个调用用到的路径、解释器、文件名都能在更早的观察输出（pwd/ls/git stat）中找到出处。
- 缺失类结论由对权威作用域（如 src/*.py）的定向搜索回执支撑，而非'没看到'。
- 计数类结论（测试通过数、领先 commit 数）直接来自命令输出，而非估算或记忆。

## Counterexamples
- 运行环境契约已明确保证 workdir 与解释器（如沙箱规范写明'所有命令在 /workspace 用 python3 执行'）——此时直接假设是正确的，先探测反而多一次调用。
- 权威输入逐字引用了确切文件路径/文件名——直接使用即可，先列目录不增加信息。
- 极廉价、幂等、无级联的只读探测（如 python 失败后立即试 python3）——fail-then-adjacent-retry 可能比 probe-first 更省；本方法前提是参数错误会触发多步失败或级联重跑（本 episode 中 workdir、测试文件名均属此类）。
