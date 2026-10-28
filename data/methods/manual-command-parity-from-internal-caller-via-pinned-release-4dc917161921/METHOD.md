---
method_id: manual-command-parity-from-internal-caller-via-pinned-release-4dc917161921
name: manual-command-parity-from-internal-caller-via-pinned-release
description: 用户要『命令给我，我自己跑』的受管服务操作时，命令的权威等价物既不是脚本默认值，也不是 N 份镜像副本中任一份：先用 desired-state 部署回执钉死唯一权威 release（code_root/runtime_root），再读该 release 内部构造权威调用的代码（注入的 env/argv/cwd），照抄拼装手动命令。本集 14 份同名脚本枚举、1 次越权搜索、20 份二次枚举本可省去：回执里的 code_root 已直接给出唯一副本，内部调用点的 env 注入才是『等价』的定义（默认 RUNTIME_ROOT=脚本目录≠真实运行根，裸跑会把回执/数据写错根）。
aliases: 手动命令照系统内部调用拼, 重启脚本一堆镜像副本选哪份, 裸跑脚本和受管重启差在哪, 给用户的命令要带哪些环境变量从哪查, 部署状态回执定权威脚本副本
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:1ee6738f-0a1e-46fa-9522-fd9f35a8933a:959:2a50b41ee917923b8d00
evidence_refs: learning:learn:5b327e24304c
created_at: 2026-10-27T23:30:00.777116+08:00
updated_at: 2026-10-27T23:30:00.777116+08:00
---
## Trigger
用户要求提供其将亲自执行的手动命令（重启/启停/发布类），该操作存在系统管理通道（deployment store/service_control），且工作区含多份同名脚本或快照镜像副本

## Discriminator
受管服务的 desired-state 部署回执可一步取到，且回执字段显式给出 code_root（唯一权威 release）与 runtime_root；同时脚本参数默认值与内部调用注入不一致（如默认根=脚本所在目录），证明裸命令必然不等价

## Short path
- 先取受管服务 desired-state 回执（status 工具或 evidence 检索），读出 code_root、runtime_root、deployment_id——未知量：N 份副本中哪份权威
- 只读该 release 下目标脚本的关键段（头部警告+入口参数+权威通道注释）——未知量：脚本契约与已知陷阱
- 在同一 release 内 grep 脚本名/env 前缀，定位内部构造调用的函数，读其注入的 env、argv、cwd——未知量：权威调用的等价契约是什么
- 照该契约组装手动命令（显式 env + 正确 cwd），附一条读 runtime manifest 的验证命令
- 命令与权威调用逐项对上即停，不再枚举其他副本或全仓搜索

## Stop conditions
- 命令中脚本路径 == 回执 code_root 下的路径，且 env 集合与内部调用点注入逐字一致
- 已向用户说明直连通道的非权威审计标注（如脚本注释声明了该语义）

## Verification
- 命令里每个环境变量都能在内部调用点源码中逐字找到来源
- 验证命令读取的 manifest/回执路径位于 runtime_root 而非 release 目录
- 脚本路径来自部署回执，而非任何 cache/mirror/worktree 副本

## Counterexamples
- 无内部调用方的独立脚本（无 deployment store）：脚本默认值即契约，直接给裸命令即可，不必追调用点
- 脚本默认值与内部调用注入完全一致（无 env 差异）：读脚本本身已足够，查调用点是多余动作
- 用户明确要复现历史/缓存副本的行为：desired 回执指向当前 desired release，不是用户点名的那份
- 操作无状态副作用（不写回执/日志/manifest）：env 契约无关紧要，等价性退化为 argv 等价
