---
method_id: ops-verify-triangulate-manifest-process-receipt-60eb4eef7189
name: ops-verify-triangulate-manifest-process-receipt
description: 核实运维状态变更（重启/部署/发布）结果时，先闭合三方对照环：期望状态 manifest（generation/git_head/artifact sha）、实际状态进程表（pid/started_at/运行 git_head/code_current）、操作自身回执（每动作 rc + 失败 detail 唯一字面量）。三者已能回答大半「成功与否」与「哪个组件失败」；剩余未知量由回执中的失败字面量作为 provenance edge 直达操作者专用日志与动作队列，再按需单点探活。在此之前不做 evidence ledger 枚举、全仓 schema 字面量搜索或路径猜测。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16a8c1d8-ae5f-4244-8906-98819ee583ec:248:609dce0fd1487026ad0c
evidence_refs: learning:learn:f08b5a241b52
created_at: 2026-09-18T15:16:07.750102+00:00
updated_at: 2026-09-18T15:16:07.750102+00:00
---
## Trigger
用户报告某带回执的状态变更操作（重启/部署/发布/迁移）已执行，需要核实真实结果；环境中存在该操作的 manifest、进程状态检查与回执三类 artifact。

## Discriminator
摩擦发生前已可见：manifest 给出期望态（generation 33 @ HEAD），进程表已给出各服务新 pid/started_at 且 code_current=false（直接证明部分组件已重启但落后一 commit），而回执是操作自身的固定输出、携带 rc 与 detail 失败命名字面量——这几条当时即可把「重启到底成没成」缩成「对表 + 追一个字面量」，无需任何宽搜索。

## Short path
- 读部署 manifest：确定期望态（generation、git_head、artifact sha）——未知量：目标状态是什么。
- 读进程/服务状态表：各服务 pid、started_at、运行 git_head、code_current——未知量：现在实际跑什么、何时启动；不在列表中的组件（如 learning）本身即异常线索。
- 读操作回执（命令固定输出路径）：每动作 rc、detail、涉及 pid——未知量：操作自身报告了哪些成败与失败命名。
- 用回执 detail 失败字面量定向 grep 操作者专用日志与动作队列目录——未知量：失败原因、是否有在途重试。
- 对存活组件单点探针（端口/ps）——未知量：失败是否波及现役进程。
- 三方对照合成结论；仅当回执缺失或时间戳早于进程启动时才扩大到搜索/枚举。

## Stop conditions
- manifest、进程表、回执三方一致，且失败字面量已在专用日志中定位并解释。
- 回执 rc=0 且进程 started_at/运行版本与 manifest 对齐。
- 发现回执过期（ts 早于当前进程 started_at）——改以进程表+探针为准并停止追旧回执。

## Verification
- 回执记录的 pid 与进程表实际 pid 一致。
- 回执 ts 不早于被核验进程的 started_at。
- 失败 detail 字面量在专用日志中有时间戳吻合的对应条目。
- 在途重试动作绑定的 generation/git_head 与期望 manifest 一致。

## Counterexamples
- 用户手动在 shell 执行且无回执/专用日志 artifact：闭环缺一角，只能靠进程表+端点探针，本方法不适用。
- 目标是修复失败实现而非核实操作结果：此时全仓定位 governing code（schema 字面量搜索）才是合理路径。
- 回执存在但早于当前运行进程（旧回执）：不可作为当前依据，须以进程表为准。
- 进程表全部 code_current=true 且无失败迹象：直接确认成功并停止，无需日志追踪。
