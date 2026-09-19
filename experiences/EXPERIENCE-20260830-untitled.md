---
title: 本地弱模型漂移根治三层法：证据豁免截断+自查时机约束+回执就近取样
scenario: "本地 27B 模型（cognilocal/lms-chat 文本工具协议）在多工具任务中答非所问：工具抓取成功后输出\"我能做什么\"能力清单/身份说明而非任务分析。"
root_cause: "①证据型回执被本地摘要通道（threshold 4000/head-tail 800）压成不完整摘要，任务证据\"在场但不完整\"；②生成位尾部被元状态语料（architecture_status 深查回执+声明提醒+注入块）占满，27B 注意力被尾部主导；③RULE-AI-10\"每轮自查\"被过度执行——证据到手后仍深查，自查语料自我污染。"
solution: "①证据型工具豁免本地截断：registry.py EVIDENCE_TOOL_NAMES={web_fetch,web_search,read_file,search_records,search_archive,search_docs,dsh_session_read,inspect_code}，这些工具回执走全局阈值（15000/2500/2500）不被本地 4000/800/800 压缩；②自查时机规则（ai_rules.lite v7 规则10）：自查=轮首或任务边界，证据在手待回答时禁止 architecture_status 深查；③声明提醒回执就近取样 receipts[-3:]（防身份话题旧回执诱导）。"
evidence: 镜像提交 79b7527（registry.py 豁免+测试+规则v7）；主区应用 grep 验证 EVIDENCE_TOOL_NAMES×3、version=7；主区+镜像测试 100% 通过；web PID 50685/feishu PID 50806 重启健康；漂移轮 payload 实测（32条/15061字符/DFlash 文档缺失）
tags: [本地模型漂移, 证据豁免, 截断策略, 生成前自查, prompt工程, 防漂移]
source: {}
status: archived
created_at: "2026-08-30T00:06:05.056541+08:00"
updated_at: "2026-09-06T00:06:07.826813+08:00"
---

漂移链完整归因（会话 68fed5f5，2026-08-29）：用户任务"GitHub 深挖 DFlash 2"→ web_fetch 两份大文档成功 → 本地摘要通道把 9k/15k 字符证据压成 ~1600c 首尾摘要 → 模型连查两次 architecture_status（规则 10 过度执行）把元状态注入生成位尾部 → 输出漂移为"我能做什么"能力清单。诊断关键：payload_trace.jsonl 只存哈希+chars 元数据，用 chars 求和反推单轮实际输入规模（15k 字符，未溢出 131k 窗口）与消息构成（DFlash 文档不在请求中）。三层修复：①registry.py EVIDENCE_TOOL_NAMES（web_fetch/web_search/read_file 等）豁免本地 4000 阈值走全局 15000——证据完整到达是防漂移的第一道闸；②ai_rules.lite v7 规则 10：自查时机=轮首或任务边界，证据在手直接分析输出，交付后再自查；③上批已落：声明提醒回执就近取样（receipts[-3:]）+ 锚点保护总量上限。核心教训：截断警告标注不足以防弱模型漂移——模型看到"可取回"提示仍会直接生成；必须让证据本身完整在场。
