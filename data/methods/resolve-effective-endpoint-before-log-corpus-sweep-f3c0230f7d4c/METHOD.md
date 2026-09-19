---
method_id: resolve-effective-endpoint-before-log-corpus-sweep-f3c0230f7d4c
name: resolve-effective-endpoint-before-log-corpus-sweep
description: 现象为调用层失败（闪退/崩溃/连接失败）时，先把错误类别映射到故障层，再判断未知量属于哪一类：是「当前实际生效的配置是什么」（解析问题），还是「过去发生了什么事件」（记录问题）。前者沿配置解析链（env > registry > 合成）取真值并对解析结果做一次定向连通性探测；后者才去枚举日志。若需要的字段在已采集 artifact 的结构里根本不存在（如异常记录只带 phase/type/message 而无目标地址），就不要继续换文件、换目录、换工具扩大搜索，而应转为最小复现或向调用方索取只有他持有的可观察量。episode 观察：Connection refused（errno 61）出现在 llm_call 阶段、异常记录不含目标地址、.env 中 active model 与 base_url 分属不同 provider、本机端口均在 LISTEN、云端端点实测可达。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:1853:c376d0b8a1bbb22b3234
evidence_refs: learning:learn:10db9d866bc6
created_at: 2026-09-18T07:26:34.992635+00:00
updated_at: 2026-09-18T07:26:34.992635+00:00
---
## Trigger
用户报告一个与远程/本机服务调用相关的现象（闪退、崩溃、连接失败），错误发生在网络/模型调用阶段，且当前生效的 provider/model/endpoint 可能被多处配置（env、注册表、前端 payload、会话 override）覆盖。

## Discriminator
结构化异常记录已给出错误类别与阶段（errno 61 / Connection refused = TCP 层无监听，可立即排除 auth、模型名、限流、provider 5xx），但该记录本身不含目标地址字段；同时 .env 里 active model 与 LLM_BASE_URL 属于不同 provider。=> 未知量是“当前实际解析到哪个 endpoint”（配置解析问题），而不是“哪个历史事件发生过”（日志取证问题）。

## Short path
- 取状态与异常日志：先确认服务是否真崩（pid_alive / 退出信号是 SIGTERM 还是 crash）、错误类别与 phase、model fallback 是否激活——把“服务挂了”与“调用被拒”分开。
- 取当前生效模型配置（env + provider registry）：比对 active model 与 LLM_BASE_URL 是否同一 provider，是否存在多处覆盖源（会话 override、前端 payload）。
- 沿配置解析链确定 active model 实际解析出的 base_url（env > providers.json > 合成），而不是先去扫日志语料找“被拒目标”。
- 只对该解析结果做定向探测：云端端点一次连通性请求（401=TCP 通，仅认证层）、本机相关端口 LISTEN 状态——确认拒绝是否可复现。
- 检查记录 schema 是否包含未知量所需字段；若结构性缺失，停止枚举，改为：列可核实缺陷 + 向调用方索取只有他持有的可观察量（在哪操作、现象具体形态）。
- 用时间锚点（进程启动行号/时间）把异常记录限定到本次症状窗口，把更早的、被消息内容携带的历史错误单独标注为无关。

## Stop conditions
- 已确定 active model 实际解析到的 endpoint 并完成一次可达性/监听探测。
- 未知量所需字段在所有已采集 artifact 中结构性缺失（记录 schema 不携带目标地址）——停止搜索，转为最小复现或追问。
- 已能把可核实事实与假设分开，且剩余假设所依赖的未知量只能由调用方回答。

## Verification
- 解析出的 base_url 与实际做连通性测试的 URL 必须一致，否则探测不构成对该假设的检验。
- 拒绝记录的时间戳相对进程启动锚点的位置（是否落在当前 generation 之后），不要把更早记录算作本次症状。
- 检查被检索命中的记录是否为“历史消息内容里嵌的错误文本”（看日期/seq），与当前运行期真实异常区分。
- 同一错误在文件中的出现次数与时间分布（间歇 vs 独有）要与结论一致。

## Counterexamples
- 未知量确实是历史事件，且日志/traceback 明确包含所需字段（如带 host/port 的连接栈）——此时日志枚举就是最短路径。
- 配置真值不在本地（远端注册表、secret 管理、部署平台注入），无法从解析链读出——只能靠实测或复现推断。
- resolver 本身就是嫌疑对象（配置解析 bug 导致解析到错误 endpoint）——此时需要请求级证据：带 tracing 的最小复现，而不是读配置代码。
- 错误类别是 401/400/429/超时而非 TCP 拒绝——故障层不同，配置解析与端口探测不是首要嫌疑，应先看认证/模型名/配额。
