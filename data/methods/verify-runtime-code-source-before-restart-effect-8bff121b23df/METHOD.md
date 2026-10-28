---
method_id: verify-runtime-code-source-before-restart-effect-8bff121b23df
name: verify-runtime-code-source-before-restart-effect
description: 执行『重启/重载使其生效』类动作前，先验证因果链最后一环：运行进程实际加载的代码 artifact（进程 env 的 PYTHONPATH / runtime manifest 指向的 release 快照）是否包含修复，而不是默认它读工作树。用修复独有新符号做成员检查，0 命中即证明重启是无效中断，应停止执行。真实生效路径由部署工具自身契约决定（update/publish 链及其硬门槛：干净树、dist 指纹）；当树中混有非本修复的未授权改动时，把前置链与受限选项呈报用户裁决，不擅自重启或发布。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:59688c5b-5ae5-42ee-9d63-23685fb569d6:563:1d2356799584205e75da
evidence_refs: learning:learn:b696c6521ca2
created_at: 2026-10-17T21:55:43.029805+08:00
updated_at: 2026-10-17T21:55:43.029805+08:00
---
## Trigger
用户要求、或自己即将声称/执行『重启即可让修复生效』，且修复目前只存在于工作树或未发布产物中，同时存在一个正在运行的常驻服务进程。

## Discriminator
运行进程实际加载的代码 artifact 与工作树是否同一份：用 runtime manifest 的 pid + ps eww 的进程 PYTHONPATH 双源定位真实代码根（如 .releases/<git_head>/src），再在定位到的 artifact 内对本修复的独有新符号 grep；0 命中即证明重启不会加载修复。最早期锐利信号：执行环境 import 一个工作树中确证存在的模块报 ModuleNotFoundError——说明运行环境根本不读工作树。工具契约原文（restart 只重 exec 已部署快照，update 才内部编排 publish+restart，且 publish 要求树干净）也是当场可读的判别事实。

## Short path
- 收到重启指令，先解第一个未知量『重启会加载哪份代码』：由 runtime manifest 的 pid + ps eww 的进程 PYTHONPATH 定位运行代码的真实根（release 快照），而非假设它读工作树。
- 在定位到的 artifact 内对本修复的独有新符号做存在性检查；0 命中 ⇒ 修复不在运行代码 ⇒ 判定 restart=纯中断无收益，取消执行。
- 解第二个未知量『让修复上线需要什么』：读部署/重启工具自身契约——restart 与 update/publish 的语义分界、publish 硬门槛（tracked 树干净、webui dist 指纹与工作树一致）。
- git status 分拣改动归属：仅少数文件属本修复，其余为另线 WIP ⇒ 任何发布动作都会牵动未授权改动，超出重启授权。
- 一次性跑本修复对应测试确认质量，然后把『不重启的结论 + 生效前置链 + 受限选项（只发本修复/等整线收尾/只提交不发布）』呈报用户等待裁决。

## Stop conditions
- 已双源（进程 env + manifest）证实运行 artifact 不含修复，且发布链门槛（脏树/dist 指纹）已核实并呈报 ⇒ 停止，不执行 restart/publish。
- 若证实进程以 dev/editable 模式直接读工作树 ⇒ 重启即合法生效，立即执行，跳过发布链分析。
- 用户在选项之外给出明确授权后，按其选择执行对应链路。

## Verification
- 代码来源结论必须双源交叉：ps eww 的进程 env 与 runtime manifest 的 git_head/pid 互相印证，不单信其一。
- 修复是否在运行 artifact 中，用修复独有新符号的命中/0 命中判定，不用模糊功能名匹配。
- 动作语义与门槛以工具契约/源码原文为准（update=publish+restart、publish 要求 porcelain 干净），不凭记忆推断。

## Counterexamples
- 进程以 editable/dev 模式直接读工作树：重启即可加载变更，再验证 release 快照纯属拖延。
- 待生效的是启动时加载的配置/数据而非代码：重启可能真的足够，无需 publish 链分析。
- 工作树干净且全部改动均属本修复且在授权范围内：不必停下来出选择题，按契约直接 update。
- 用户要的是运营性重启（恢复状态/清缓存），与代码生效无关：验证代码链是多余仪式。
