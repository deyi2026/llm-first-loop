---
method_id: durable-job-defer-terminal-check-2a5ca0503c58
name: durable-job-defer-terminal-check
description: 后台任务受理回执已确认（ok=true 且带 action_id/job_id 查询句柄）、任务元数据为 durable/running 时，剩余未知量只是『何时到终态』这一时间型未知，而非信息型未知。此时应立刻注册一次性延迟唤醒（间隔按已知或估算时长设定），到点读一次终态输出再做验证；不要调用无关命名空间的等待/感知工具（如对重启中的 webui 做 browser perceive），也不要零延迟重复轮询同一 job_output。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:fc0ed66c-e669-41c4-94d7-7e05031bbac6:1143:79226dbde04aea5ebe48
evidence_refs: learning:learn:6a033f81ee45
created_at: 2026-09-22T18:02:00.851072+00:00
updated_at: 2026-09-22T18:02:00.851072+00:00
---
## Trigger
长时物理操作（服务重启/部署/批量迁移）以 durable 后台任务提交，回执 ok=true 且状态 running，唯一待解决量是终态何时出现

## Discriminator
首查 job_output 已同时给出：受理回执 ok=true + action_id + generation 匹配，且 durable=true/running。这两个事实把『继续查信息』与『只需等时间』区分开；紧随其后的零延迟重查返回逐字节相同输出，证明再查无新信息。任务仍在 stop/start 阶段时，对目标服务做外部感知也不可能成功

## Short path
- 核对部署 manifest，确认目标 generation/git_head/code_root 已固定（未知量：目标代是否已发布）
- 提交受控重启并读受理回执，确认 ok/action_id/generation（未知量：是否被受理）
- 单次 job_output 查询确认回执可见、任务 running——据此把剩余未知量归类为时间型而非信息型
- 立即注册一次性延迟唤醒，间隔按已知时长参照设定；受理与唤醒之间不再调用任何等待或轮询
- 唤醒后读一次终态输出，核对 action_id/generation 与受理回执一致，再执行验证清单（manifest/回执/屏障/渲染）

## Stop conditions
- 回执非 ok 或首查即失败：不延后，立即转诊断
- 首查已到终态（带终态输出）：立即验证，不再注册唤醒
- 唤醒后取得终态输出且验证清单通过：停止

## Verification
- 延迟间隔须由已知时长参照（如上一代同类操作耗时）导出，而非任意值
- 终态输出的 action_id/generation 与受理回执一致
- 受理与唤醒之间不应出现产生新信息的轮询；若出现，说明间隔判断错误，需修正而非继续等

## Counterexamples
- 任务为亚秒级同步操作：受理后立刻单次复查即可拿到终态，注册延迟唤醒反而拖慢整个流程
- 任务系统不提供延迟唤醒原语：只能退避轮询，不应套用此法
- 任务日志为流式增量输出，每次轮询都有新行：短间隔轮询有信息量，不算冗余，禁止强行延后
