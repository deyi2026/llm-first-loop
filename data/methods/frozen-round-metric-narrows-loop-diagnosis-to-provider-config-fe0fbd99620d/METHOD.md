---
method_id: frozen-round-metric-narrows-loop-diagnosis-to-provider-config-fe0fbd99620d
name: frozen-round-metric-narrows-loop-diagnosis-to-provider-config
description: 诊断「另一会话卡住/重复输入」类报告时：先把事件流限定到目标会话的 build/round 事件；预算或 prompt 尺寸指标在连续多轮重复完全相同的数值 ⇒ 每轮 prompt 逐字节相同（重发循环），配合当前 status 的 exception_log 为空、无 fallback，即可排除错误路径与上下文溢出。剩余未知量只剩「模型为何每轮重发同样动作」→ 查本地推理服务进程（量化等级、ctx、端口）与采样 props（repeat_penalty/dry/temperature），再确认目标会话最终是否已产出答案或切换模型。避免对会记录你自己调用的事件流做含关键词的宽查询（会自匹配到自己），也避免在当前异常为空时去考古数天前的历史异常。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b26f8d55-84aa-438f-a8c8-fde86c81247c:4:bb18c95bb51ac9d7d0fe
evidence_refs: learning:learn:4d4f8efdcd27
created_at: 2026-09-22T16:49:15.121380+00:00
updated_at: 2026-09-22T16:49:15.121380+00:00
---
## Trigger
用户报告另一个会话/agent（尤其是跑在本地模型上）疑似不收敛、循环、或在重复发送相同输入；存在共享可观测事件流与系统状态接口可查。

## Discriminator
目标会话的 build_messages/round 预算指标在多个连续时间戳上出现完全相同的数值（如 130479 连刷约 14 分钟），且当前 status 显示 exception_log 为空、无 fallback 事件 ⇒ prompt 每轮逐字节重发；未知量从「查所有日志找原因」缩为「模型为何重发相同动作」，即 provider 端采样配置与量化，而非异常史或代码目录。

## Short path
- 读系统 status：确认 exception_log 为空、无相关 failed action → 排除错误路径；记下自己 session ID 供后续排除自匹配。
- 事件流按目标 session 过滤 build_messages：预算值冻结 = 相同 prompt 重发循环；记录所用模型名。
- ps aux 定位本地推理服务进程：模型文件（量化等级）、上下文大小、端口。
- curl 服务 /health + /props：采样参数（repeat_penalty、dry_multiplier、temperature）、slot 状态，确认有无防复读保护。
- 事件流限定目标 session、取循环起点之后的时间窗、排除自己 session：确认重复的具体工具调用、最终是否产出答案、是否已切模型。
- 给出根因（无防复读采样 + 极狠量化 → 同参工具调用复读）与分级修复建议。

## Stop conditions
- 服务 props 显示防复读全部关闭，且目标会话事件确有同参工具调用重复 → 根因已闭环，停止扩大调查。
- 目标会话事件显示已产出最终回答或已切换模型 → 「是否收敛」问题已回答。
- 若指标每轮在增长或存在异常/fallback 事件 → 本方法前提失效，改走内容增长或错误路径诊断。

## Verification
- 确认冻结指标是完全相同的值（而非近似增长）再下「相同 prompt」结论。
- 确认诊断时刻的当前 status 异常/fallback 为空，不引用数天前的异常记录作当前证据。
- 根因需两端互证：服务端采样参数关闭 + 目标会话原始事件里可见同参重复调用。
- 会话最终状态（已产出/已切模型）必须来自该会话自身事件，而非邻近会话或推测。

## Counterexamples
- 预算/prompt 尺寸每轮在增长 → prompt 并不相同，冻结判别式不适用，应定位消息内容增长点。
- 会话跑在远程 API 模型上 → 无本地 server props 可查，应查 API 错误、限流与客户端重试逻辑。
- 事件流中确有当日 exception/fallback 事件 → 先走错误路径，采样配置不是首要嫌疑。
- 重复来自客户端对超时的同参重试（传输层），而非模型重复生成 → 应修重试/退避策略，改采样参数无效。
