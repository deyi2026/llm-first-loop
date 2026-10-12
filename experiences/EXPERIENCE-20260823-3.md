---
title: 本地模型回答规范：先给'你可以这样做'的具体动作；边界模糊时主动声明默认规则（≤3文件自主/涉生产先列方案）；引用代号须附一句话证据；不确定先检索再答
scenario: "本地大模型（qwen3.8-27b-mlx）在 LFL 镜像的评测中暴露三短板：①给态度不给动作（\"我要真实信息/边界/允许质疑\"无一条\"你可以这样做\"）；②边界模糊时把责任推给用户（\"你会越界或保守\"不给默认决策规则）；③引用代号自证（\"M22 验证过的\"无证据展开）。目标：通过 LFL tips 注入通道，在本地模型工具执行后注入一条轻量（几十 token）行为提示，前置纠正这三类行为。"
root_cause: "本地 27B 模型默认行为缺\"给动作/给默认规则/带证据\"引导；LFL 已有 tips 注入通道（工具后按工具名检索经验库注入 title）可复用为轻量行为提示载体，无需改核心逻辑。"
solution: "存为经验（title=注入文本，几十 token），tags 覆盖本地常用工具名（execute_command/read_file/search_records/search_archive/architecture_status 等）。机制：tool_exec.py:_inject_experience_tips 在工具执行后按工具名检索经验库，命中注入经验 title 为 [经验提示] 尾部消息；27B 本地模型会收到、9B 跳过、会话级去重、尾部追加前缀稳定。注入后本地模型回答应：给具体动作（\"你可以这样做①…②…\"）而非态度；边界模糊时主动声明默认规则；引用代号附带证据；不确定先调 search_records/search_archive。验证：实测 list_active(query=工具名) 命中该经验 + prefill 增量微小（几十 token）。注意：关键词检索按文件名序取前2，新经验对命中多的工具可能排不进——若如此需调整检索排序或直接注入。"
evidence: "tool_exec.py:204-270（_inject_experience_tips：按工具名检索、命中注入 title、27B 收/9B 跳、会话去重、尾部追加）；store.py:170（summary=doc.title）；实测 list_active 输出 execute_command 命中 2 条为旧经验；LOCAL_TOOL_NAMES 含 search_records/search_archive（检索通道通）。"
tags: [本地模型, 行为规范, tips注入, execute_command, read_file, search_records, search_archive, architecture_status, qwen3.8-27b-mlx]
source:
  type: design
  id: local-model-behavior-tip
status: archived
created_at: "2026-08-23T07:17:28.373847+08:00"
updated_at: "2026-09-06T00:17:19.943416+08:00"
---

## 2026-09-06 lifecycle review

该记录依赖“工具执行后自动检索并注入 experience_tip”的旧机制。当前 `tool_cycle._inject_experience_tips` 明确为 on-demand-only compatibility observability：不得 query ExperienceStore、不得 append Message、prompt_chars=0；经验由模型显式 `search_records(kind=experience)` 发现并按 stable ref 水合。因此退出 active 普通召回，历史实现保留 exact-ref 考古。
