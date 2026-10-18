# 响应流断连恢复（2026-10-18）

## 已核验事故

Web 会话 35effbfe-0312-45d2-a1bd-0418c1706ecd，event seq 788–804：GLM-5.3 请求返回 HTTP 200，9.92 秒后 RemoteProtocolError / incomplete chunked read；已接收普通思考 1934 字符，无正文、无工具片段。120 秒 timeout 与 65536 输出预算未耗尽。另一次 20:43:14 为 HTTP 200 后 ReadError（44.39 秒）。现有事实无法将断开归因至服务端、网关或本机代理。

## 实现边界

- 区分 HTTP 响应开始后的传输中断与未建立连接。错误提供 provider/model、最后 attempt 耗时、正文/思考字符数、工具片段、已重试次数。
- 仅 OpenAI-compatible 显式普通 reasoning/reasoning_content 且无正文/工具/签名或 opaque 状态、无终态 finish_reason 时，允许一次原 payload 同模型恢复；共享既有 retry_disconnect 预算，0 可关闭。
- 恢复时流式显示未完成边界；失败思考和程序标注不混入成功 LLMResponse 或下一轮 provider replay。已执行工具所属的前轮不重跑。
- timeout、content 中的 think 标签、reasoning_details 与工具片段均不扩展恢复；Stop 按当前 run/child authority 生效。
- 不修改模型能力参数、不新建控制面、不换模型、不触碰生产配置和服务。

## 防退化六问

1. 原请求与逐 attempt 传输事实保持在既有 journal；失败输出沿既有增量展示/checkpoint 通道保留，不宣称中断 source 完整。
2. 会话事件与既有 hydration 入口保留；不新增裁剪或覆盖恢复路径。
3. 真实 provider-view/事件参数已核验：HTTP 200、plain reasoning、max_tokens=65536、timeout=120。
4. 仅改变该失败路径的 transport retry；不照搬其它 runtime 参数。
5. 仅判机械字段与取消状态，不判任务语义或完成；retry_disconnect=0 可禁用。
6. 从 main 302948e3c 的独立 worktree 实现，冻结暂存候选后独立 GLM-5.3 审查，PASS 后原版 R9。

## 验证

- RED：新增事故回归初次 4 failed / 6 passed。
- GREEN：最终定向与相邻回归 169 passed，含真实 httpx 流式断连、逐 attempt 结算与相同 payload、Stop、正文/工具/opaque 禁止重放；Ruff/diff-check PASS。Pyright 结果另存验证日志。
- 独立审查、完整 R9 和隔离提交尚待执行。
- 尚未合并 main、推送、发布或重启。
