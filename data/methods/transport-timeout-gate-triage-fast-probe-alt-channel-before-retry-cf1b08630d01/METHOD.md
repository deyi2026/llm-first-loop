---
method_id: transport-timeout-gate-triage-fast-probe-alt-channel-before-retry-cf1b08630d01
name: transport-timeout-gate-triage-fast-probe-alt-channel-before-retry
description: 门禁/预检（如 review_admission start 的远端 ls-remote preflight）失败回执点名完整命令+目标主机+超时秒数（transport 类超时）时：首次可原样重试一次；第二次仍超时后，禁止以更长预算重跑同一条已知会挂起的命令，改用单条有界快探测（curl --max-time ≤8 打 baseline 站/失败主机/替代通道）一次性回答『端点级劣化还是本机离线』；若预检要确认的事实存在更快的已知权威替代通道（任务书或环境已示，如官方 API 查远端 main SHA），先用替代通道推进事实核验；网络有吞吐即短候原样重试门禁，参数逐字不动。
aliases: ls-remote 预检超时怎么排查, start 门禁网络超时重试, 超时了别加大预算硬跑, 先测网络再重试准入, 区分单站劣化和本机断网, 用 API 通道先核远端 SHA
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:4719d425-c1da-4544-874e-bf639948d263:61:25721a161e66984511c0
evidence_refs: learning:learn:a8376347d44d
created_at: 2026-11-12T18:56:57.224846+08:00
updated_at: 2026-11-12T18:56:57.224846+08:00
---
## Trigger
准入/门禁或其网络预检连续超时，且失败回执明确点名被挂起的命令、目标主机与超时预算（传输层失败），而非 4xx/权限/命名字段类确定性拒绝

## Discriminator
回执中被点名的主机与命令本身就是判别事实：失败是『到特定主机的网络路径超时』而非参数或资格问题；两次同型超时已排除单次瞬时抖动。且预检要确认的事实（如远端 main SHA）若存在任务书/环境已示的替代权威通道，该通道名在当时已经可得，不需要任何事后信息。

## Short path
- 首次超时可原样重试一次（瞬时网络常见，12 秒级失败成本低）；仍失败即停止盲重试
- 单条快命令做三点有界探测：curl --max-time≤8 分别打 baseline 站、失败主机、替代通道，区分『端点级劣化（有部分吞吐/高延迟）』与『本机离线（baseline 也挂）』
- 若为端点劣化且替代权威通道可达：先用替代通道回答预检要确认的那个事实（结果落盘再解析，避免管道直连解释器触发安全闸），保持事实核验链前进
- 短候后原样重试门禁（参数/workdir/kind 逐字不动）；成功即进入正常等待/轮询协议
- 若 baseline 也失败或目标主机完全拒绝连接：判定环境故障，停止重试并如实上报已核事实，不再烧满超时预算

## Stop conditions
- 门禁重试成功并返回新 child_id/新指纹，转入后续等待协议
- 探测证明本机离线或目标端点长时间不可达：停止重试，报告环境故障与已核事实

## Verification
- 替代通道取得的事实与门禁成功回执的对应字段一致（如 push_remote_commit == 替代通道查得的远端 SHA）
- 最终重试成功的回执参数与任务书逐字一致：网络故障未诱发任何参数/scope 变更

## Counterexamples
- 回执是 404/403/命名字段缺失等确定性错误：非传输类失败，重试与网络探测均无益，应走合同差分或授权流程
- 失败主机是目标事实的唯一权威通道（无替代源）：只能有界退避重试，不存在替代通道分流一步
- baseline 探测同样超时：结论已变为环境离线，继续探测或重试门禁属浪费
