---
method_id: none-result-triage-control-probe-then-domain-enable-before-env-hypothese-03e7ab1ff8a7
name: none-result-triage-control-probe-then-domain-enable-before-env-hypotheses
description: 当远端协议调用（CDP/JSON-RPC/WebSocket API 类）在传输握手成功后返回空值/None 而非显式错误时，不要立即枚举环境侧假设（状态丢失、SPA 换代、上下文竞争、id 失效）。先用一轮受控探测三分归因：①用不依赖域启用的控制命令（getVersion/getTargets 类）验证自家客户端的响应管道；②启用目标调用所属协议域（如 Runtime.enable）；③原样重放失败调用。多数『玄学 None』是协议前置条件未满足或客户端管道 bug，而非环境漂移。找到可用配置后，在同一连接内批量完成全部读取，中途不要 navigate/reload 破坏已验证状态。每失败一次就编一个合理叙事再换参数重试，是本方法要消除的核心反模式。
status: active
source_model: workbuddy/step-5-preview
source_episode_refs: episode:1c391008-9819-4e88-92ce-117820e41b2e:749:febe83322c26d42677c0
evidence_refs: learning:learn:d343c7132da5
created_at: 2026-10-18T20:19:05.165099+08:00
updated_at: 2026-10-18T23:31:44.310525+08:00
---
## Trigger
远程协议调用在握手成功后返回 None/空 result 且无 error 字段；或同一调用签名不变而结果持续为空，并已开始产生多个环境侧解释（执行上下文丢失/版本漂移/多上下文竞争/target 失效）

## Discriminator
当时已可观察的三件事：握手 101 成功（传输层已证好）、响应无 error 字段（非协议拒绝）、同客户端上一版刚被标记过 result 管道有 bug（管道是活嫌疑）。这三点把候选空间从『任意环境故障』压成『客户端管道 vs 协议前置条件』两个可各用一次探测验证的假设，环境漂移应排在最后

## Short path
- 传输层异常时先逐字读错误文本并照做（如 403 提示 Origin 被拒→抑制 Origin 头重试），不另行猜测
- 首次拿到 None：同一连接内先跑免域启用的控制命令（getVersion/getTargets 类）——未知量：客户端响应管道是否正常，本次结果是否真的到达过我这边
- 控制命令正常→一行探测：启用目标调用所属域（如 Runtime.enable）后，原样重放与失败时完全相同的调用表达式——未知量：是否协议前置条件未满足
- 调用恢复返回真实数据→立即在同一连接内批量完成所有需要的读取（标题/元素计数/草稿状态），不 navigate、不重连、不换参数
- 仅当控制命令也开始失败、或参数未变而结果改变时，才升级为环境漂移假设并换 target/重建会话，停止在本 target 上变式重试

## Stop conditions
- 控制命令正常 + 域启用 + 原样重放后调用返回真实数据：停止假设枚举，转入单连接批量读取并一次性收齐
- 控制命令本身拿不到任何响应：判定为客户端管道 bug，先修客户端代码，期间不再触碰环境
- 域启用后仍 None 且控制命令也开始失败且调用参数未变：判定为环境漂移，停止当前 target 上的变参重试

## Verification
- 重放的调用表达式与失败时逐字相同（未换参数、未换 context），成功才可归因于域启用而非其他变量
- 控制命令与目标命令必须走同一条响应管道，二者一成一败才能把归因定位到协议层
- 批量读取期间确认无 navigate/reload/reconnect 事件插入，全部结果来自同一活跃会话

## Counterexamples
- 调用返回显式错误（403/404/JSON-RPC error 对象）时：错误文本本身就是判别器，直接按提示修复即可，无需控制探测三步（本集 Origin 403 即被这样正确高效地解决）
- 本地纯函数或同进程调用返回 None：先查自身代码空值路径，域启用/控制命令概念不适用
- 协议文档明确该调用无需 enable、控制命令也正常、且『参数未变结果已变』：这才是真实环境漂移，应换路重绑而非继续加 enable
- 每次连接都是全新会话、上下文天然跨连接失效的环境：单连接批量读取是前提条件，不构成对方法的证伪
