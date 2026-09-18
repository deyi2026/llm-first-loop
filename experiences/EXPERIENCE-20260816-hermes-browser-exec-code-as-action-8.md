---
title: Hermes browser_exec 调研：code-as-action 工具设计的 8 个可复用模式
scenario: 设计或改进 agent 的浏览器/exec 类工具、撰写工具描述（状态契约/何时不要用/降级提示）、实现并行子代理的浏览器资源隔离时
root_cause: 传统逐动作浏览器工具集每个动作一次 LLM 往返、token 高；动态拉取技能文本注入 prompt 有供应链与版本漂移风险；并行会话共享浏览器连接互相踩踏。
solution: "借鉴组合：①单 exec 工具+预置 helper 取代逐动作工具集；②把\"什么持久/什么不持久+落盘纪律\"显式写进工具描述；③prompt/schema 内容用基准（固定任务×多模型×多次重复）验证后再定，偏好钉死摘要；④并行场景用命名会话隔离（独立守护进程/浏览器）；⑤降级提示用 stamp 限频；⑥工具描述开头写\"何时不要用\"；⑦执行模型代码必须配门控/沙箱（参考：仅 terminal 工具集会话才注册）。"
evidence: docs/local/RESEARCH-20260816-hermes-browser-exec.md（本会话 web_fetch 官方文档+源码调研，含基准数字与实现细节引用）
tags: [agent-design, tool-description, browser-automation, code-as-action, hermes, session-isolation]
source: {}
status: active
created_at: "2026-08-16T14:35:18.507744+08:00"
updated_at: "2026-08-16T14:35:18.507744+08:00"
---

来源：NousResearch/hermes-agent 官方文档与源码（tools/browser_use_cli.py 833行、agent/browser_provider.py、browser-use SKILL.md），完整报告见 docs/local/RESEARCH-20260816-hermes-browser-exec.md。

【核心模式】Hermes 用单个 browser_exec(code) 工具取代传统 browser_click/type/snapshot 工具集：模型写 Python，在 browser-harness 守护进程中执行（预置 goto_url/fill_input/click_at_xy/js/截图/原始CDP 等 helper），页面用 CDP Accessibility 树转文本。官方自测 token 较旧 toolset 降约 60%（未独立验证）。

【8 个可复用模式】
1. ⭐ 状态契约写进工具描述：每次调用全新解释器但浏览器+workspace 目录持久；教模型边采集边写 JSON/CSV、agent_helpers.py 自动 import、聚合用代码别用脑算、长任务拆多次调用防超时丢进度。
2. 钉死的 helper 摘要取代动态拉取技能文本：108 次 A/B 证明等效，消除供应链注入/版本漂移/prompt 字节不稳定。
3. 命名会话隔离：session=<name> → 独立守护进程/独立云浏览器；共享本地浏览器时注入 preamble 强制各开 tab（marker 以 daemon pid 为键）。
4. 默认开启+优雅降级+降级提示 stamp 限频 24h（nudge without nagging）。
5. driver 与浏览器来源解耦（统一 CDP URL）；私有地址自动路由本地 sidecar，公网走云，云厂商看不到内网 URL，默认开启。
6. 工具文档开头写"何时不要用"：纯 HTTP 能拿到的别起浏览器。
7. 安全边界进 prompt + 工具注册门控：登录墙停下问用户；browser_exec 仅在有 terminal 工具集的会话注册。
8. 低成本可观测性：代码首行 ≤60 字符注释直接当 UI 步骤标签。