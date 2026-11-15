---
method_id: repeated-identical-rejections-diagnose-gate-release-conditions-c10e44d0c444
name: repeated-identical-rejections-diagnose-gate-release-conditions
description: 解释『同一错误提示反复出现』时，若遥测显示拒绝发生在发送前且 reason 为固定字面量（如 hold、provider_sent=false），判定即为视图状态的确定性函数：状态不变重发必得同结果，原地重试永远无效。路径：用逐字 reason 查事件流按 session 分组→同一字面量在工作区做精确内容检索（shell rg 限定 *.py，不用会超时的宽枚举工具）直读闸函数→读判定输入与失败分支、枚举解除条件→取当次组装数字（窗口/固定 schema 占比）验证必然触发→遥测缺失的逐次数值显式标假设。行动结论落在『改变状态』（投影成功或新 run 更小观察足迹），而非重试。
aliases: 错误一直刷屏怎么排查, 连着失败几次还能重试吗, 每次都拦在发送前, 卡住后换新会话还是原地重试, 提示不断重复出现的原因
status: candidate
source_model: cognilocal/qwen3.8-flash-next
source_episode_refs: episode:43f1a49b-8500-4a12-9ddd-6c067043a5bd:17:a0ce0bb717321afe11e7
evidence_refs: learning:learn:1a95d04bcc1e
created_at: 2026-11-15T16:34:02.349227+08:00
updated_at: 2026-11-15T16:34:02.349227+08:00
---
## Trigger
某内部错误提示或前置闸拒绝（如发送前被 hold、固定 reason 字面量、provider_sent=false 类回执）在同一会话或相邻轮次反复出现，需要解释『为什么反复』或决定『重试还是换路径』时。

## Discriminator
事件流条目显示该拒绝发生在动作发送之前、带固定 reason 字面量、且同一 session 时间紧密成簇（相邻几秒到几分钟内连发）——即判定是当前状态的确定性函数，状态不变重发必得同一结果。这个当时已知的事实把『逐次当偶发处理/原地重试』收缩为『读产生该 reason 的闸代码、枚举解除条件』。

## Short path
- 用逐字 reason 串检索事件流，取全部出现并按 session/run 分组；未知量：是同 run 连续还是跨 run 复发。
- 同一字面量在工作区做精确内容检索（shell rg 限定 *.py，规避会超时的宽搜索工具），命中即直读产生该 reason 的闸函数。
- 读闸的判定输入与失败分支；未知量：判定是否为视图状态的纯函数、解除条件有哪些（如投影成功、run 结束后新历史起跑）。
- 取当次组装数字（模型窗口、effective 预算、固定 schema 占比）验证为什么恰好这个 run 顶到上限。
- 遥测中缺失的逐次数值（如逐次投影字符数）对应解释显式标为假设；行动建议落在改变状态而非原地重试。

## Stop conditions
- 闸的判定逻辑、反复的确定性原因（状态不变⇒同结果）、解除条件均已由代码与遥测双面钉死；
- 缺失数值已显式标为假设，不再延长搜索试图补证。

## Verification
- 出现次数与 session 分组同事件流一致（如共 8 次、其中 4 次同 session 连续）；
- 闸代码中无随机/时间分支，判定输入全部来自当 run 的视图状态与预算；
- 解除条件与观察吻合：旧 run 连续被拦、新 run（更小观察足迹）一次通过。

## Counterexamples
- 拒绝来自外部 transient（限流 429、网络超时）：每次发生条件不同，原地重试可能成功，不能下『必然同结果』结论；
- 检出的闸代码不是故障实例实际运行的版本或部署（镜像/多实例）：必须先钉运行实例再下结论；
- 『反复』的主体是模型重复同一工具调用（provider 侧循环）：应改为比对相邻轮 prompt 身份（messages/budget 一致性），不适用本卡；
- 判定含随机采样或竞态：同一状态下重试结果可能不同，枚举解除条件无意义。
