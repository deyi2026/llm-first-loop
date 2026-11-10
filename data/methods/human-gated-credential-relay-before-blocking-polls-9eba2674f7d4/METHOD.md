---
method_id: human-gated-credential-relay-before-blocking-polls-9eba2674f7d4
name: human-gated-credential-relay-before-blocking-polls
description: 后台授权任务（gh auth refresh / OAuth 设备码 / 设备配对码）首份输出打印一次性 code 并提示人工打开浏览器 URL 时，下一个状态转移归外部用户所有：应立即把 code+URL+约15分钟有效期完整交给用户（顺手代开浏览器），然后驻停——最多一次有界等待或等用户信号。链式 wait 与重复轮询推进不了状态，只会消耗 code 有效期，甚至让用户迟迟拿不到 code 无法输入。恢复后用权威状态面（如 scopes 字符串）核效，不信命令回显。
aliases: 设备码等人点别一直wait, 先把一次性code交给用户再等, gh授权卡在浏览器那边怎么办, 后台任务等人工授权先交码, 轮询耗掉授权码有效期, 验证码只在agent手里用户看不到
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:ccfcc676-9c54-41d9-8c5c-5dab5ce0e5b2:2931:bc100497c0893b28d9f5
evidence_refs: learning:learn:11e428421efa
created_at: 2026-11-11T07:20:35.739679+08:00
updated_at: 2026-11-11T07:20:35.739679+08:00
---
## Trigger
后台/异步授权任务的首份输出明确点名下一步是外部人工操作：打印『copy your one-time code』并给出需在浏览器打开的授权 URL（补 token scope 的设备码流程、OAuth device grant、配对码等）。

## Discriminator
job 回执里已同时出现一次性凭据（code）与人工操作指令（授权 URL），且该 code 目前只在 agent 手中、用户尚未看到——此时唯一未知量是用户何时完成授权，这是人类拥有的状态转移，agent 侧任何 wait/轮询都无法改变它，反而消耗 code 有效期。

## Short path
- 预检照常完成（身份/scopes/可推送形态），确认缺口恰好是用户能授予的人工授权
- 后台发起授权命令，此刻唯一未知量=一次性 code
- 首次输出含 code 时同一步完成交接：代开浏览器 + 把 code、URL、过期时间完整发给用户，不要只宣布『code 已产出』却 withhold code 本身
- 驻停：一次有界等待或等用户回复，不再追加 wait、不重复查询同一状态的 job
- 终态后用权威面验证效果（如读取 scopes 字符串确认含新 scope），再进入被该授权保护的后续动作，并按唯一标识（目标 ref 的 SHA）复核落点

## Stop conditions
- 用户已收到完整 code+URL，任务驻停等待终态或用户信号
- code 过期（job 报过期/超时失败）→ 重新发起取新 code，再做一次同样的交接
- 权威状态面确认授权已生效 → 立即进入下一步受保护动作，停止一切等待

## Verification
- 恢复后对权威状态面核效：直接读取 scopes/授权列表的字符串本身，而不是命令退出码或自述成功
- 受保护动作（如 push）完成后用唯一标识（远端目标 ref 的 SHA）复核真实落点

## Counterexamples
- 子任务在等机器侧事件（CI 排队、服务端处理、锁释放）：有界轮询正是正确动作，不存在人工凭据，不适用
- 用户在自己终端发起流程、本人已能看到 code：无需转交，等待终态即可
- 授权链接已预填 code 或为无头非交互流程：没有交接需求，等终态后直接核效
- 凭据归属 agent 自身且不应外泄给用户：先判断 code 归属，不能机械转发
