---
method_id: error-digest-literal-into-runtime-session-store-then-live-policy-code-9293972283b3
name: error-digest-literal-into-runtime-session-store-then-live-policy-code
description: 用户逐字粘贴本系统运行时生成的错误回执（含 provider 名、SSE 错误码、『今天』等时间限定词）并要求排查根因时，该 digest 是系统自产日志的字面量：先用最独特 token（错误码）+ mtime 窗口在按会话分片的结构化运行记录里定位失败会话，再在同库统计成败分布以区分『瞬时上游故障』与『系统性配置错误』，然后只读 live 源码树中该错误类流经的分类/重试白名单（避开 .releases/evals 快照噪声），并用同日兄弟错误类的正确降级作对照后即停。可省去全库 provider 名 grep、猜路径读 providers.json、以及对快照命中的绕行。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c60eb4a0-d9ee-464b-827e-35b800317988:0:4b4af060fdd585950db1
evidence_refs: learning:learn:7adb53e5552a
created_at: 2026-10-20T08:57:37.474800+08:00
updated_at: 2026-10-20T08:57:37.474800+08:00
---
## Trigger
用户报告某 provider/模型/会话『经常出错』并逐字引用了本系统运行时生成的错误回执（含错误码、provider 名、时间限定词），要求排查原因并给修复建议

## Discriminator
错误 digest 是本系统自产日志字面量（如 HTTP 200 + SSE 码 internal_error），且带时间限定（今天）；exception_log 回执已显示记录按 session_id 分片存在 → 目标失败记录必在近期的按会话运行日志文件中，一次字面 grep + mtime 排序即可命中，无需全库配置/代码考古

## Short path
- 从用户引文提取最独特 token（错误码，如 internal_error）+ provider 名 + 时间窗；不做全库内容搜索
- 按 mtime 枚举按会话分片的运行日志目录，取当日少数文件，grep 该 token 定位失败会话与失败事件（provider/model/transport_retry_index/run 结局 incomplete）
- 在同一记录库统计成败分布：高成功率+偶发失败 ⇒ 瞬时上游而非网络/Key/模型名配置问题；顺带找同日兄弟错误类被正确分类并降级的对照案例
- 只在 live 源码树（非 .releases/evals 快照）读该错误类流经的分类/重试白名单代码，确认具体错误码字符串是否缺条目
- 给出最小修复（补字符串 + 仿既有同构单测）即停

## Stop conditions
- 已从会话日志取得逐字匹配的失败事件、成败分布结论，以及 live 分类代码对该错误码的处理判定（缺/不缺白名单条目）与一个对照案例
- 若当日日志 grep 干净 0 命中且 token 选择确认无误，升级为『记录不在本地 store』分支（查日志去向/版本），而不是继续换词全库扫描

## Verification
- 定位到的失败事件 error_digest 与用户引文逐字一致；分布统计覆盖该会话全部 settled 事件而非抽样
- 对照案例（兄弟 provider/错误类同日被正确分类并自动降级）证明重试/降级机制本身可用，差异只在错误码字符串
- 修复建议指向 live 文件行号，且仓库已存在可仿写的同构单测用例

## Counterexamples
- digest 来自第三方 API 消息且本地从未持久化该日志 → 字面 grep 无从命中，应改走代码/配置/官方文档路径
- digest 高度泛化（仅 'Internal server error'，无错误码无上下文）→ grep 过命中退化，需先换更独特 token 或换证据源，本方法不适用
- 投诉是跨数月/数千会话的聚合频率问题 → mtime 窗口失效，需要聚合查询工具而非 ls+grep 少数近期文件
- 确定性参数/契约类错误（世界不变必复现）→ 频率分布判别无意义，应走『确定性回执不原样重试』分支
