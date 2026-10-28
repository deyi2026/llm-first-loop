---
method_id: capability-oracle-is-the-real-operation-not-the-permission-bit-616a2c522aae
name: capability-oracle-is-the-real-operation-not-the-permission-bit
description: 工具可用性判定挂在系统授权/预检 API（AXIsProcessTrusted、CGPreflightScreenCaptureAccess、sudo -n 类）上，且出现『授权位=false 但最小真实操作成功』的可复现矛盾时，授权位不是能力真值：改用该工具真正要做的最小只读操作作为能力 oracle（成功返回码即可用），授权位降级为回执中的信息性字段，并用回归测试锁住，避免 status 假阴性把用户赶去无用的授权流程。适用于 TCC/sandbox 等预检位与实际操作可能不一致的环境。
aliases: 权限检查说没权限但实际能用, 授权位假阴性怎么判能力, 用真实操作探测能力而不是问权限API, 沙箱里权限判定失真, preflight权限检查不可信
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:36553398-1c59-4c05-927f-23e13f8396e6:1166:d8d2b288e4e1eac04cc6
evidence_refs: learning:learn:a837f8479608
created_at: 2026-10-28T01:42:35.531428+08:00
updated_at: 2026-10-28T01:42:35.531428+08:00
---
## Trigger
实现或评审一个把系统授权预检 API 当作能力真值的 status/probe/preflight 判定；或权威报告（dev 交付自述、探测报告）中出现『授权位与实际操作结果矛盾』的反直觉观察

## Discriminator
同进程内可复现的 gatekeeper-vs-operation 分歧：预检 API 报 false/denied，而工具自身的最小只读操作（如对前台 pid 读 AXWindows，err==0）成功，重复多次一致（本集 4/4）。该事实在读到权威报告的反直觉结论时即已暴露，无需事后答案

## Short path
- 权威报告中的反直觉观察（trusted=false 但 AX 读得到）不当噪声跳过：立『授权位是否是可靠能力 oracle』为第一未知量
- 同进程最小复现：执行工具本要做的只读操作并核对返回码，重复 N 次
- 复现成立 → 把能力判定重定义为该最小操作本身（成功码即可用），授权位只作信息性字段随回执展示
- 加回归测试锁住新判定语义，防止实现退回 trust-the-bit
- 回执分开上报两个信号（授权位值 + 实测探测结果），并显式标注假阴性方向与未验证边界

## Stop conditions
- 分歧不可复现或仅出现一次 → 按瞬态处理重试，不重构探测
- 唯一可行的真实操作有副作用或用户可见代价 → 不能当廉价探针，回退授权位并显式标注不确定性
- 分歧方向相反（授权位 true 但操作失败）→ 是真实能力缺口而非假阴性，修能力不修探测

## Verification
- 同进程重复探测 N 次，授权位与操作结果稳定不一致才下结论
- 修复后 status 结论与实测能力一致，回归测试覆盖『位=false + 操作成功』组合

## Counterexamples
- 授权 API 对该操作类契约上权威、无已知沙箱/TCC 干扰 → 矛盾另寻原因（版本不匹配、目标进程异常），不必改探测
- 真实操作是破坏性或不可逆的（真实投递点击、发送消息、写状态）→ 禁止拿操作当探针；本方法只适用于非变更只读操作
- 系统级探针失败但目标操作成功只证明探针选择不当；目标层能力仍必须在目标对象上实测（如 AX 树未达网页层即不得声明网页层能力）
