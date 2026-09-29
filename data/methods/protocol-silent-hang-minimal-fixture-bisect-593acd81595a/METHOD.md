---
method_id: protocol-silent-hang-minimal-fixture-bisect-593acd81595a
name: protocol-silent-hang-minimal-fixture-bisect
description: 为握手型有状态协议服务（LSP/MCP/DAP 等 JSON-RPC 类）编写或调试客户端时，若握手成功、启动日志正常，但后续请求零响应且无错误/无超时/无关闭，这是客户端协议生命周期缺陷的签名（如漏发初始化通知、漏应答 server→client 请求），而非数据规模问题。应先用最小 fixture 在同一 server 上复现以排除规模假设，再对照协议规范补齐完整生命周期；不要归因'仓库太大'并反复重写全量探针。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bc07ea9d-6ab9-44b7-b385-65eea54960b6:615:4b38de3bf314017f14a7
evidence_refs: learning:learn:0a0e5d430e8b
created_at: 2026-09-28T21:26:18.424952+08:00
updated_at: 2026-09-28T21:26:18.424952+08:00
---
## Trigger
开发或调用握手型协议客户端（语言服务器、MCP、daemon 等）过程中：capabilities/握手响应正常返回且 server 日志正常，但本应秒级完成的请求长时间零响应，同时无错误、无超时、无连接关闭——'静默挂起'签名。

## Discriminator
挂起回执在当时已包含协议级证据：握手响应亚秒返回（进程与传输帧正常）、且客户端至少有一项已漏答的 server→client 请求（回执中可见未应答的进度请求）。我方客户端已知漏掉一项协议义务 ⇒ 应推断可能还有生命周期缺口（如 initialize 后必须先发 initialized 通知，server 才处理请求），并把'同一客户端对 3 文件 fixture 是否同样挂起'当作区分协议缺陷与规模问题的一次性二分实验。

## Short path
- 看到'握手成功+请求静默'签名后，先做规模对照：同一客户端、同一 server 二进制，对 3 文件级 fixture 跑一次（秒级成本），解决未知量：协议缺陷还是数据规模。
- fixture 同样挂起 ⇒ 排除规模，锁定协议一致性；对照协议规范核对完整握手序列（initialize → 必需的初始化通知 → 才发请求；所有 server→client 请求必须应答）。
- 补齐缺口后先在 fixture 上验证请求能返回，再回真实仓库。
- 真实仓库结果非空且抽查若干已知命中点核对召回后，停止排查，不再加探针变体。

## Stop conditions
- fixture 复现挂起并定位到具体缺失的协议步骤，修复后在真实仓库得到非空且抽查通过的结果——排查即止。
- fixture 不挂起而真实仓库挂起 ⇒ 转向规模/资源假设（剖析、分批处理），不再修改协议代码。
- server 给出显式错误文本 ⇒ 直接按错误信息修复，无需进入 fixture 二分。

## Verification
- 协议层结论必须有最小 fixture 的复现/消除回执支撑，不能只凭'改了以后好像就好了'。
- 警惕假成功：rc=0 且输出合法但结果近空（未过就绪门时召回可低至 0.14% 且无任何报错）；抽查已知应有命中的符号，与独立来源（如 grep 计数）交叉核对。

## Counterexamples
- 握手本身失败、连接报错或被关闭（无 capabilities 响应）⇒ 传输/二进制/参数问题，直接读错误信息，不适用本方法。
- server 返回明确错误（如 'server not initialized'）⇒ 错误已指出缺口，照修即可，不需要 fixture 二分。
- 小输入正常、挂起时长随输入规模单调增长 ⇒ 规模/资源问题，做性能剖析与分批，而非协议排查。
- 无握手/生命周期概念的一次性命令行工具静默变慢 ⇒ 与协议生命周期无关，不套用。
