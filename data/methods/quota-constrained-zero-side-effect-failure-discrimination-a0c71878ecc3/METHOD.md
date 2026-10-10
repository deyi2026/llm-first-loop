---
method_id: quota-constrained-zero-side-effect-failure-discrimination-a0c71878ecc3
name: quota-constrained-zero-side-effect-failure-discrimination
description: 当生产失败已被 fail-closed 记账、原因不可归因，而真实重试受不可再生配额（如 physical_attempts=1）或授权/保护约束时：先只读失败账本，提取资源约束、安全侧状态与故障层；再为每个候选假设选择与其同层的零副作用等价探测——传输层假设用纯 TCP/TLS handshake 分直连/代理两路，编码层假设用现有 loopback 测试加库版本行为——以探测收敛假设，禁止用真实请求判别。真实尝试与新额度作为用户授权关口单列。这是根因流程在'判别实验自身副作用预算为0'约束下的专门化，核心新增判别：探测必须与假设同故障层，跨层通过不算裁决。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:fd840981-a906-404c-8c80-1c3452e1c66a:141:c5b7911f26e2c3676d60
evidence_refs: learning:learn:9e25e238fcfb
created_at: 2026-10-09T18:14:19.279548+08:00
updated_at: 2026-10-09T18:14:19.279548+08:00
---
## Trigger
诊断一次已发生、已被 fail-closed/一次性记账、失败原因不可归因的生产失败，且真实重试会消耗不可再生配额、需要用户授权或可能触碰用户刚修复的受保护链路。

## Discriminator
当时即可只读的失败账本显示 physical_attempts=1 且 reservation outcome=failure/phase=unknown——即真实重试不可得、安全机制已按设计工作；同时失败类为传输层（ConnectError）。这两个当时已知事实共同意味着：'瞬时环境 vs 确定性 bug'的判别完全不需要真实请求，同层零副作用探测（纯 TLS handshake / 现有 loopback 测试）即可裁决。

## Short path
- 只读失败账本 JSON：提取 physical_attempts / outcome / phase / 失败层 → 判定重试不可行、安全侧正常、故障层=传输
- 显式列出待判别假设（H1 环境瞬时 / H2 确定性编码 bug），再开始读机制代码
- 为每个假设选同层零副作用探测：网络假设→直连+代理两路纯 TLS handshake（0 请求 0 额度）；编码假设→现有 loopback 测试 + httpx 版本行为检查
- 探测证伪/收敛：存活假设唯一且机制可解释即停止探测
- 进入修复设计；真实尝试/新额度列为待用户授权关口，不自动执行

## Stop conditions
- 存活假设唯一、机制可解释：停止探测，转入修复设计
- 零副作用探测无法区分剩余假设：停在授权关口，绝不静默消耗真实配额做判别
- 探测开始需要携带凭据/业务请求体/写账本才能继续：已越过零副作用边界，停止并升级为显式授权

## Verification
- 每个探测命令可复核副作用为零：无 API key、无业务请求体、不写账本
- 探测结论只在声明的故障层内裁决对应假设；跨层结果不作为裁决（TLS 握手通 ≠ 应用层健康）
- 多源交叉（只读账本 + 传输层探测 + 离线测试套件）独立指向同一存活假设后才进入修复

## Counterexamples
- 失败可在本地零成本、可重复地真实复现（纯函数、mock、无配额约束）：直接复现比构造等价探测更短，不必套用本方法
- 故障层在探测面之外（如 TLS 握手必通但故障在认证/计费/请求体路径）：零副作用探测无裁决力，不得据此宣称'路径健康'，须标注覆盖面并保留该假设待真实尝试
- 无只读账本或账本缺少 kind/层/outcome 字段：探测设计失去依据，应先补可观测性而非盲测
