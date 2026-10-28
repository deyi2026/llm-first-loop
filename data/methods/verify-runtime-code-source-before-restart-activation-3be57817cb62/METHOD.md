---
method_id: verify-runtime-code-source-before-restart-activation-3be57817cb62
name: verify-runtime-code-source-before-restart-activation
description: 当计划假设"重启/重载服务即可激活我的本地代码改动"时（含用户指令或自己上一轮结论中的此类断言），先核实运行时进程实际加载的代码源：查进程 env（PYTHONPATH）、import 解析路径、发布快照 vs 工作树分歧，并用行为探针验证改动语义是否已在运行环境生效。真实激活路径可能是 commit→publish→restart 而非仅 restart；绿色单测不等于运行时激活。同时盘点发布按 HEAD 会一并携带的非目标改动，并确认重启是否会终止执行者自身会话。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:abf83187-242a-4d8d-81bc-1d377b72db19:902:c009a1b3f87991691ccb
evidence_refs: learning:learn:269865c47d8b
created_at: 2026-10-18T00:47:48.180679+08:00
updated_at: 2026-10-18T00:47:48.180679+08:00
---
## Trigger
任务包含"重启/重载服务使刚修改的代码生效"的激活断言，且该断言尚未被运行时证据验证——尤其当仓库存在 editable 安装、.releases 发布快照目录、PYTHONPATH 覆盖或 publish/deploy 流水线时；断言来源可以是用户指令、他人陈述或自己早先的结论。

## Discriminator
运行中进程的 env 与模块解析路径（ps eww、/proc/<pid>/environ、匹配环境下 import 探针的 MODPATH）是否指向工作树；对被改函数在该环境下做行为探针，返回旧语义即为"重启≠激活"的直接证据。conftest 把项目根钉进 sys.path 的绿色单测不构成运行时激活证据——测试与生产进程可能解析到两份不同代码。

## Short path
- 把激活断言转为明确未知量：重启后的进程会从哪条路径加载被改模块？第一步直接查运行进程 env 与该环境下被改模块的 import 解析路径。
- 若解析源指向发布快照或其他非工作树路径：查发布机制（快照如何物化、基于 HEAD 还是工作树、是否要求干净树），得出真实激活序列（如 commit→publish→restart）。
- 盘点激活会携带的全部改动（git status/diff 按意图分组），将非目标改动作为显式决策点呈报用户，获批前不执行 commit/publish。
- 核查重启对执行者自身的影响（进程树：当前 shell/会话是否为目标服务子进程），必要时先登记续跑交接再触发重启。
- 执行后在真实运行环境（同源解释器与 env）对被改函数做行为探针，确认返回新语义。

## Stop conditions
- 运行进程解析路径已确认等于工作树且无环境覆盖：重启即激活，停止核查进入执行。
- 真实激活序列（如 commit→publish→restart）与发布携带的改动范围已获用户明确确认。

## Verification
- 重启后读取新进程 env/模块路径，确认指向预期的新快照或工作树。
- 用与运行时同源的解释器与 env 对被改函数做行为探针，确认输出新语义而非旧语义，再宣布"已生效"。

## Counterexamples
- 改动是数据/配置且重载只读已知数据目录，不涉及代码解析：模块路径检查无关，不套用。
- 纯 editable 安装、无 PYTHONPATH 覆盖，且近期已有回执证明重启加载工作树：无需重复全套核查。
- 一次性本地脚本由执行者自己调起解释器，模块路径完全可控：直接运行验证即可，无需进程 env 取证。
