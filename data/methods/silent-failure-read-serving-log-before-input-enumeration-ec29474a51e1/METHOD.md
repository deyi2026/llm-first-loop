---
method_id: silent-failure-read-serving-log-before-input-enumeration-ec29474a51e1
name: silent-failure-read-serving-log-before-input-enumeration
description: 用户报告“已发送/已操作但没反馈”且 status 检查显示服务进程存活、endpoint healthy、服务级 exception_log 为空时，可判定这不是崩溃类故障：若失败发生，必然逐请求记录在服务组件自己的运行日志里。应直接按 mtime 定位该组件最新活跃日志并 grep 近窗口 ERROR/Traceback，而不是先在消息记录、事件流、全文搜索里枚举用户输入去了哪。本集 5 次无果探测（search_records、event_stream×2、search_files、根目录 ls）预设了“消息未被接收”，而 web.log 随后证明消息已被处理、失败发生在 provider 交换环节——假设方向从一开始就反了。一次 ls + 一次 grep 即命中 3 条后台 run 失败 traceback，根因（网络抖动+上游 UI 改版折叠）全部由日志直接给出。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8bc1cbb3-5fe5-44cb-9818-3acb329d2acb:0:cf198f5c486dbfb35e73
evidence_refs: learning:learn:a36e3454635a
created_at: 2026-10-11T16:19:32.545278+08:00
updated_at: 2026-10-11T16:19:32.545278+08:00
---
## Trigger
用户报告某发送/请求类操作“没有反馈/没响应”，且对目标服务刚完成的状态检查显示进程存活（state=running）、endpoint_healthy=true、服务级 exception_log 为空（排除崩溃类故障）。

## Discriminator
status 输出在当时已表明：服务存活 + 服务级异常日志为空 ⇒ 故障是逐请求级后台 run 失败，其权威记录位置是服务组件自己的运行日志，而不是消息库/事件流；“查用户输入在哪”只在日志显示消息根本没被接收时才成立。

## Short path
- 读服务/runtime status，确认存活与 exception_log（2 次调用，已具备）
- 存活且 exception_log 空 ⇒ 一次 ls -lat 定位该组件最新写入的日志文件，跳过消息库/事件流枚举
- tail/grep 该日志近窗口的 ERROR|Traceback|timeout，读出失败签名
- 沿 traceback 指向的组件目录/状态文件确认根因链
- 根因确认并完成修复/部署验证后停止；仅当日志显示消息未被接收时，才回退检索输入记录

## Stop conditions
- 日志中找到与用户症状时间窗/会话吻合的失败记录及其组件归属
- 根因由直接证据（traceback、组件状态文件）确认且修复已验证
- 日志近窗口无任何失败记录 ⇒ 推翻“处理失败”假设，转查消息接收链路

## Verification
- 日志中的 session id/时间戳与用户报告的症状对应（本集 9a7c8ffd、15:13–15:20）
- 受控重发一次以捕获失败实锤，区分“发送失败”与“发送成功但确认环节失败”
- 修复部署后，新版日志不再出现同一失败签名

## Counterexamples
- status 显示进程已死/endpoint 不健康：这是崩溃恢复类故障，应先走恢复流程与 exception/recovery 记录，而非 tail 运行日志找逐请求错误
- 用户症状是“消息/历史丢了”这类接收侧问题而非“发了没回”：此时消息库/事件流检索本来就是正确第一跳，判别方向相反
- 目标服务日志不可读（权限/纯远端）或近窗口日志为空：判别前提失效，回退从入口链路逐段排查
