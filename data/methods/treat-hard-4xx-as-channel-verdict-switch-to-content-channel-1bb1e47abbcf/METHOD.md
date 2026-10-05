---
method_id: treat-hard-4xx-as-channel-verdict-switch-to-content-channel-1bb1e47abbcf
name: treat-hard-4xx-as-channel-verdict-switch-to-content-channel
description: 获取目标是内容本身（源码、文件、正文）时，默认先打元数据/索引 API 属于通道错配。回执为硬性 4xx（401/403）时，它是该通道的策略判决而非瞬时故障：正确动作是立即换到直接分发目标内容的通道（git clone、raw 端点、正文来源），并优先选一步同时给出结构与内容的通道；而不是在被拒通道内轮换 UA/客户端或枚举同类端点。429/5xx/timeout 是瞬时限流，退避重试同一通道才可能是短路径。本集教训：两个 403 端点共约 12 次无效请求（3 UA × 2 客户端 × 2 端点），而浅克隆一步给出完整文件树+全部源码。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:932df416-c651-4aff-9348-962d36f4ff73:295:cc9394914250ce485d19
evidence_refs: learning:learn:176697a166ed
created_at: 2026-10-03T11:22:54.952198+08:00
updated_at: 2026-10-03T11:22:54.952198+08:00
---
## Trigger
需要读取公开托管仓库/站点的实际代码或文件内容，且当前抓取回执为硬性 4xx（401/403）；或正准备为『拿内容』类目标先请求元数据/索引 API。

## Discriminator
失败回执中可直接读到的状态码类别：403 是策略/权限拒绝（换 UA、换客户端无效），不是 transient timeout；同时目标内容存在独立于该 API 的分发通道——同一服务主域已验证可达（本集 github.com 页面抓取成功），clone/raw 端点服务同一内容。这两点在进入重试扇出之前就已可见。

## Short path
- 先定未知量：要的是『内容本身』还是『元数据』；内容本身则直接选内容分发通道，跳过元数据 API 探测。
- 收到硬性 4xx：记为该通道类的判决，立即换到内容通道，不做 UA/客户端轮换、不再试同类端点。
- 优先一步覆盖结构+内容的动作（如浅克隆同时给出文件树与全部源码，替代 API trees + HTML 树页 + raw 三种探测）。
- 元数据类需求（star/license 等）用已成功通道附带的数据满足，不另起通道。
- 每条结论落到具体 file:line 或成功工具回执；核不到的显式标 ⚠️ 未核实，随即停止发现。

## Stop conditions
- 目标事实已由内容通道取得，且有 file:line 或成功工具回执支撑。
- 剩余未知量在可达通道内无法核实时，标注『未核实』并结束，不为它再开新的发现分支。

## Verification
- 对外结论逐条映射到具体文件/行号或一次成功工具回执（如声明核验表每行有对应源码文件）。
- 结论区分『已核实/未核实』两档，未核实项不得写成肯定断言（本集正确地把 8~29MB、ladder 档位标为 ⚠️）。

## Counterexamples
- 状态码为 429/5xx/timeout：属瞬时限流，先退避重试同一通道更短，不应立即弃通道。
- 404 且指向单个具体路径：多半是路径拼写错误，修正路径后重试比换通道更短。
- 目标本身就是元数据（star 数、license、commit 历史）：metadata API 恰是权威来源，坚持该通道而非 clone。
- 私有仓库或需认证内容：clone 与匿名 API 同样被拒，应走带凭证通道，本方法不适用。
