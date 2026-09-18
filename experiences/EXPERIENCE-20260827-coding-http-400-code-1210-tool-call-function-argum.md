---
title: "智谱 coding 端点 HTTP 400 {code:1210} 根因：tool_call.function.arguments 非字符串"
scenario: "llm-first-loop 运行时长会话中反复出现 LLMHTTPError 400 1210（\"API 调用参数有误\"笼统无定位），同一会话内成功与失败交织，特定请求形态可精确复现；调用方怀疑是本地重复调用拦截或规则阻断所致。"
root_cause: "二分探测（15 个请求变体直发智谱 coding 端点）证明唯一触发器是 assistant 消息中 tool_call 的 function.arguments 缺失或为 dict（非 JSON 字符串）——服务端整轮拒收返回 1210。本地不存在任何出站调用拦截机制：停滞指纹仅事后统计、RULE-AI-03 为提示词约束、6 处相邻完全重复调用均被放行。来源为 ToolCall dataclass arguments: dict 类型标注下的隐式构建路径 + 发送前 provider 折叠（message.cache_compacted_for）对 wire 视图的 dict 重建，污染驻留内存历史对象图后每轮必炸；存储层（event log）落盘干净全为字符串。排查轮次自身也被 1210 打死，证明与思维链/决策语义无关，纯 wire 序列化层问题。"
solution: "V2（d5f538b）：chat_stream 出站前 _sanitize_openai_tool_pairs 双向清洗孤儿配对（主签名）。V3（e7d54f9）：_normalize_tool_call_args 在发送边界强制串化所有非 str arguments（两遍扫描 + copy-on-write + fail-open warning），并在 except LLMHTTPError 处挂载 msg#call#tool 归因诊断。验证 py_compile + 定向单测 327 passed；生效需重启进程载入（运行中的旧代码不受提交影响）。扩展经验：provider 笼统错误码先做最小变体二分探测定位真实触发器，再看时间轴与内部事件的耦合（折叠伴随 vs 正常轮零折叠）。"
evidence: ""
tags: [智谱, HTTP-400, 1210, tool_calls, arguments-dict, wire序列化, 故障取证, LLM-first-loop]
source: {}
status: archived
created_at: "2026-08-27T08:03:51.273506+08:00"
updated_at: "2026-09-06T00:09:26.141519+08:00"
superseded_by: "experience:EXPERIENCE-20260906-err1210-current-tail-user-contract"
---
