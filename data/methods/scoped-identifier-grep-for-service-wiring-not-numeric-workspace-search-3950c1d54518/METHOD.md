---
method_id: scoped-identifier-grep-for-service-wiring-not-numeric-workspace-search-3950c1d54518
name: scoped-identifier-grep-for-service-wiring-not-numeric-workspace-search
description: 定位某个已知本地运行服务（端口/进程）在代码库里的消费方与接线时，先从其监管配置（launchd plist/systemd unit）提取专属标识——label、二进制名、以及 WorkingDirectory 把服务锚定到的仓库根——再用这些高区分度 token 在代码树上做排除日志/输出目录的定向 grep。不要拿端口号这类短数字 token 做全工作区搜索：在含大量随机 hex ID 日志/eval 输出的仓库里只会命中碰撞噪声，且截断的全噪声结果绝不能推出『无任何引用』的否定结论（本集曾据此误判，下一步定向 grep 即推翻——该误判若未被纠正，将直接导致『闭环未接线』的错误结论）。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:72b1f325-1293-4022-9fb8-46f58685873e:86:e2d71f0ca42b4cdae82c
evidence_refs: learning:learn:7597e0b697f0
created_at: 2026-10-17T10:56:08.502666+08:00
updated_at: 2026-10-17T10:56:08.502666+08:00
---
## Trigger
需要确认某个由 launchd/systemd 等监管的本地服务由哪个组件调用/接线、或是否会与编排层冲突，且目标仓库内存在大量含随机 ID 的日志或 eval 输出目录时

## Discriminator
监管配置里当时已经有的专属标识：服务 label（如 local.xxx.decisionNNNN）、二进制名、以及 WorkingDirectory 明确把服务锚定到仓库根路径——这证明消费方就在同一仓库内、可用独特字符串一次定位；而纯数字端口号区分度低，在随机 ID 日志目录必然产生碰撞噪声，命中全部落在 jsonl 事件日志且被截断时，正确读法是『未知』而非『不存在』

## Short path
- 读监管配置（plist/unit），提取 label/二进制名/端口/工作目录，确认服务归属的仓库根与管理者唯一性
- 在仓库根用最独特的标识（label 或二进制名）做 grep，并 --exclude-dir 掉 evals/.lfldata/tmp 等输出目录，直接定位消费方及其设计文档
- 读消费方 README/入口获得全链路设计，再 grep src 运行时代码确认接线钩子存在
- 查执行产物（autorun 日志、scores/index 文件的时间戳与行数增量）验证链路真实转过，而非仅有静态接线
- 如需验证当前监管进程行为，对其 endpoint 做一次端到端探针
- 管理者唯一性、接线、实跑、当前进程四个未知量各有权威证据即停

## Stop conditions
- 消费方与运行时接线均已由代码引用证实（引用方向：调用方→服务 endpoint）
- 执行产物时间戳/增量证明管线真实运行过（必要时加端到端探针）
- 监管进程域与编排层进程集的交集已枚举确认为空

## Verification
- 定向 grep 命中的文件确实包含对该服务 endpoint/label 的真实调用引用
- 『无引用』类否定结论只能来自排除噪声目录后的定向 grep，不得来自截断的全库搜索
- 执行日志时间戳与输出产物 mtime 相互印证

## Counterexamples
- 仓库干净、无随机 ID 日志目录（或搜索工具默认忽略输出目录）时，直接搜端口号即可命中，无需先读监管配置
- 服务完全外部于该仓库（监管配置不指向仓库内路径）时，仓库 grep 是错误工具，应从进程/网络层（lsof 连接、netstat）入手
- 问题只是『谁在监听该端口/谁管理该进程』时，lsof+launchctl 一步即得，grep 无用
