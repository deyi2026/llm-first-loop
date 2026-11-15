---
method_id: probe-named-anchor-existence-then-ship-verifiable-later-checklist-55f5e8745dc9
name: probe-named-anchor-existence-then-ship-verifiable-later-checklist
description: 用户要求产出『对着被点名系统/接口 X 逐条自查』的清单，而 X 是否在本机可核未知时：先用有界探针（精确标识符文件名搜索 + tracked-only git grep，避开全仓 content search 在大仓的超时与 .venv 噪音）裁决 X 有无；判无后不拒绝任务也不照常编写，而是把交付物改写为『必答问题+通过判据+失效信号+最小注入测试』形态，附显式未核验声明（范围=实际探针覆盖面，不外推全局不存在），并给出『提供仓库路径即转实测结论』的升级路径。
aliases: 点名系统查不到怎么写清单, 对着别人的代码写自查表, 仓库里没有目标实现还要不要写实测结论, 全仓搜索超时后怎么缩范围, 没读过的代码不能出什么结论, 外部文章提到的系统能不能核验
status: candidate
source_model: cognilocal/qwen3.8-flash-next
source_episode_refs: episode:43f1a49b-8500-4a12-9ddd-6c067043a5bd:56:23ddaaeb61ece33b590c
evidence_refs: learning:learn:abafefa73d4c
created_at: 2026-11-15T17:28:09.961817+08:00
updated_at: 2026-11-15T17:28:09.961817+08:00
---
## Trigger
任务要求产出『对着某个被点名的系统/接口/传输层（如 X-Agent / X.call）逐条自查/审查/对照』的清单或文档，且 X 在可达工作面是否存在尚未验证（典型：X 来自外部文章或第三方作者）。

## Discriminator
一次有界探针的回执即可裁决：精确标识符文件名搜索零命中，且内容搜索命中全部落在 .venv/site-packages/vendor 或评测夹具目录（第三方噪音）；配合 pwd/git log 确认当前仓身份与 X 无关。这些当时已可见的事实把『X 可能藏在大仓 50+ 目录任何地方』缩成『X 不在第一方代码，缺席即结论，剩余未知量只是交付物形态』。

## Short path
- 从任务文本提取被点名的锚标识符；未知量①：X 是否在本机可核？
- 有界存在性探针：精确标识符文件名搜索 + tracked-only git grep（天然排除 .venv/未跟踪目录，大仓不超时）；不要先做全仓 content search 或全树 find
- 身份探针：pwd/git log 确认当前仓是谁，可选 coordination_status 查在途工作是否提及 X；命中全为 vendor/夹具噪音即判 X 缺席
- 缺席成立 → 交付物改写为『每条=必答问题+通过判据+失效信号』，附 3-4 条最小注入测试与显式未核验声明，声明范围严格限定为实际探针覆盖面
- 收尾给出升级路径（提供仓库路径即可把判据逐条转成实测结论），停止继续存在性搜索

## Stop conditions
- 探针出现任一第一方命中（src/运行路径）→ 退出缺席分支，沿命中直读实现写实测结论
- 已交付『问题+判据+失效信号+未核验声明』形态 → 停止继续搜索『说不定还有别处』
- 用户给出仓库路径或澄清 X 归属 → 按新输入重走，不重复旧探针

## Verification
- 缺席声明中每一项『已查过』都对应一次真实有界探针，可复述命令与范围
- 交付物至少含一条拿到源码即可机械执行、期望结果明确的注入测试
- 未核验声明的覆盖范围与探针一致（如 tracked *.py + 文件名 + 在途 goals），未声称全局不存在

## Counterexamples
- 探针命中 X 的第一方实现（哪怕一处）→ 不改写形态，直接沿命中读代码出实测结论
- 任务没有点名锚（纯概念/通用清单）→ 跳过存在性探针直接写，探针反而是浪费调用
- 小仓或有索引的工作面 → 全文搜索代价低更省事，超时规避分支不适用
- 用户明确拒绝『问题+判据』形态、只要设计正文 → 先索要仓库路径或澄清，而不是自行更改交付形态
