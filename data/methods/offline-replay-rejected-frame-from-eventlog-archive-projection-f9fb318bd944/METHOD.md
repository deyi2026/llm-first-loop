---
method_id: offline-replay-rejected-frame-from-eventlog-archive-projection-f9fb318bd944
name: offline-replay-rejected-frame-from-eventlog-archive-projection
description: 排查『哪一具体请求帧被 provider 拒绝』时，即使任务默认建议抓网络 payload 或线上二分复现，先走离线确定性重放路线：grep 错误码找 in-repo 注释里已写明的 provider 拒绝语义；用结构化事件日志的逐调用 status_code/provider_code 加 message.appended 角色序列定位失败调用与消息形状；按 session id 直取持久化归档（路径可由 id 直接推出，不枚举目录）；用仓库内生产投影函数重放该轮参数，确定性重建精确 wire 并验证形状假设。只有记录缺失或投影含未落盘的非确定性状态时才退回抓包/线上二分。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:59688c5b-5ae5-42ee-9d63-23685fb569d6:317:807821cf1d4834bfae72
evidence_refs: learning:learn:bae40ae1950c
created_at: 2026-10-17T21:09:52.071392+08:00
updated_at: 2026-10-17T21:09:52.071392+08:00
---
## Trigger
需要定位『外部系统拒绝的确切出站请求帧』（provider/协议错误码、请求形状被 400 拒绝等），且任务/用户默认建议抓取网络 payload 或线上二分复现；同时系统具备结构化事件日志（含逐调用 outcome 码）、按会话 id 持久化的消息存储，且构造请求的投影代码就在当前仓库内。

## Discriminator
决定走抓包路线之前已同时存在三条事实：(1) 在仓库内 grep 错误码即返回写明拒绝语义的注释（如 history.py:885『GLM rejects assistant/tool-only histories with HTTP 1214』），拒绝条件可能已被文档化；(2) 事件日志 provider.transport.settled 逐调用携带 status_code/provider_code，可精确定位首个失败调用及其前的 message.appended 角色序列；(3) grep dump/capture 类机制返回零命中——抓包不是既有能力，自建属于昂贵分支。三者合计把『搭抓包再二分』缩成『离线重放验证形状假设』。

## Short path
- 从缺陷记录或日志文件名提取失败会话 id 与目标错误码
- 单遍解析事件日志：找出第一条命中 provider_code 的调用 seq，并列出此前全部 message.appended 的角色/顺序（未知量：哪次调用、什么消息形状）
- 对照仓库内 grep 到的注释语义建立可证伪的 wire 形状假设（如『无任何 user 消息』），直接在角色序列上验证，零线上调用
- 按 session id 直读持久化归档（data/archives/<session_id>.jsonl，路径由 id 直接推出，不枚举 data/ 目录），用仓库内生产投影函数在失败轮参数下重放，确定性重建精确 wire
- 仅在 in-repo 语义可能过期或需独立确证时做最小在线对照实验（如有/无 user 两形状各一发）；wire 形状、provider 语义、生产代码路径三方一致即停

## Stop conditions
- 离线重放的 wire 角色组成与事件日志序列、归档行一致，且匹配已文档化的拒绝语义，产出该形状的投影代码路径已定位
- 事件日志缺少逐调用 outcome 码或消息序列、归档不完整、或投影依赖未落盘的运行时状态——此时转抓包/线上二分才是正当的

## Verification
- 重放 wire 的角色组成逐条对齐 message.appended 序列与归档记录（含被压缩归档的消息行）
- 最小在线对照实验表确认 provider 语义；若省略实验须显式标注结论基于 in-repo 注释
- 修复后用同一重放在参数扫描（如多档预算）下验证不变量恢复（如 user=1），且相关单元测试通过

## Counterexamples
- 投影函数依赖未持久化的运行时状态（随机 id、时间戳、缓存水位、实时网络响应）——离线重放无法复现精确帧，必须抓包或线上复现
- 错误是瞬态类（429/超时/网络抖动）而非确定性的请求形状拒绝——『找到那一帧』无意义，应审计重试/退避策略
- in-repo 注释语义已过期（provider 行为随版本变化）——注释只能作假设，必须以最小在线实验为裁决标准
- 事件日志不含逐调用 status/provider_code——记录不足以定位帧，插桩取证合理
