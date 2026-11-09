---
method_id: receipt-echoed-env-facts-bind-params-and-claims-not-prior-prose-4e6c2b24440b
name: receipt-echoed-env-facts-bind-params-and-claims-not-prior-prose
description: 恢复/继续型会话中，上一轮消息常含未经验证的环境断言（仓库路径、HEAD、ahead 数、阻塞项）。本集第一处扩散即由此而来：紧邻的重启状态回执已逐字回显 runtime_root/git_head 等权威值，下一个调用却用了记忆里另一个用户的路径，触发参数拒绝后又花一次探测重新推导回执里已有的值。方法：任何带路径/ref/计数参数的调用，先回扫本会话成功回执的回显字段并以其绑定；对上一轮 prose 断言的环境事实，核到回执或回执导出值后才写进对外结论；参数被拒先重读回执，再做一次有界探测，而不是放任记忆值继续驱动后续动作。
aliases: 回执里已有的值别靠记忆脑补, 先翻回执再填 workdir, 上一轮说的路径要先对回执, 路径参数被拒先重读回执别急着探测
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:fb85cea0-beb4-424d-b482-2819180ee46f:2212:26f7c1377d42f687e2b2
evidence_refs: learning:learn:1ac2612bac6e
created_at: 2026-11-09T15:35:01.232569+08:00
updated_at: 2026-11-09T15:35:01.232569+08:00
---
## Trigger
恢复/续跑会话中，上一轮曾断言环境事实（仓库路径、HEAD、领先数、阻塞项）且本轮需继续操作；或即将发出的工具调用要从记忆/上轮文本取 workdir、ref、路径类参数，而本会话已有成功回执回显过同类值

## Discriminator
紧邻的成功回执是否已逐字回显该参数/事实的权威值（runtime_root、code_root、命令回执的 cwd 回显、git_head、generation 等字段）——命中即以回执值为准并弃用记忆值；仅当无任何回执覆盖所需范围时，探测才是合法首跳

## Short path
- 发出带路径/ref 参数的调用前，回扫最近成功回执的回显字段，命中即直接绑定，跳过记忆值与上轮 prose 值
- 参数被拒（如 workdir 无效）视为『所用值与回执脱钩』的信号：先重读回执对齐，仍无覆盖才做一次有界候选探测（并排列出候选并标注存在/缺失），一次收敛
- 对上一轮 prose 断言的每条环境事实（路径/HEAD/ahead 数/阻塞项），逐条映射到回执字段或一次窄命令核验，未核验的不得进入对外结论
- 回执字段与问题范围不符时（如指向部署副本而非源码工作区），按字段语义另取正确来源，而不是机械复用

## Stop conditions
- 所有对外声称的路径/ref/计数都能逐字指回某条回执回显或其直接导出值
- 参数拒绝在重读回执后消除，且未产生第二次探测

## Verification
- 下一次带路径/ref 参数的调用所用值，能指回先前回执的具体字段
- 上一轮 prose 与回执冲突时，最终报告采用回执值并显式勘误，而不是保留记忆版本

## Counterexamples
- 所需路径属于本会话从未触及的另一仓库或临时目录，任何回执都不含它——此时 pwd/列目录探测是正当首跳，本方法不适用
- 回执字段语义与问题范围错位（runtime_root 指向部署 release 副本而用户问源码工作区）——须按字段语义匹配来源，机械复用回执值反而绑错
- 用户本轮显式给出新路径或新目标——用户显式指令优先于旧回执，仅以一次存在性探测确认
