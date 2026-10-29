---
title: 诊断宿主安装布局缺陷的两个取证陷阱：别用宿主文件读权限下结论、别信被环境 PYTHONPATH 污染的探针
scenario: 诊断另一台主机的 LFL 自检报告（称「规则真值源不可核验、rules_version 为空」）时，如果直接沿用「文件读不到=真值源缺失」的结论，会漏掉真实缺陷；而在本机做安装布局复现时，环境里的 PYTHONPATH 会把 import 指向 release 检出树，让探针得出与 wheel 安装相反的结论。
root_cause: 调用方文件读权限与程序内部读权限是两套权限；模型用前者推断后者会得出假缺口。PYTHONPATH 优先级高于 site-packages，会让「装好的 wheel」实际被源码树顶替。
solution: "1) 规则正文是否可达，用程序级通道判定而非自己读文件：search_records(kind=\"rule\", query=\"RULE-AI-xx\") 与 search_docs(query=\"规则二十四\")——程序自己解析规则根，不受调用方文件系统权限限制；只有「程序级通道也拿不到」才是真值源缺失。2) 复现 wheel 布局时，探针必须 env -u PYTHONPATH（或用干净 venv），否则 import 会落到 release 检出树（bundle_root()=None，rules_version 读法完全不同）。3) 版本信号与规则正文要分开判定：正文可达 + 版本号为空 = 打包清单/解析根不一致，不是真值源缺失。"
evidence: "第一次 wheel 探针返回 bundle_root=None、rules_version=''，是因为宿主 PYTHONPATH=/Users/<user>/Project/llm-first-loop-mirror/.releases/dfb627bee.../src 顶替了 site-packages（打印 llm_loop.__file__ 即发现指向 release 检出树）；env -u PYTHONPATH 后同一 wheel 正确显示 bundle_root=site-packages/llm_loop/_bundled、ai_rules.md=True、rules_version=''。规则正文可达性：同机 search_records(kind=\"rule\") 返回 RULE-AI-24 完整正文，source 指向 .releases/<sha>/docs/ai_rules.md；search_docs(query=\"规则二十四\") 亦命中同一文件（长 query \"RULE-AI-24 开发与修复防退化契约\" 不命中，说明 docs 检索按词切分，需短中文词）。"
tags: [diagnostics, pythonpath, rule-hydration, evidence-discipline]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-28T20:41:54.589480+08:00"
updated_at: "2026-10-28T20:41:54.589480+08:00"
supersedes: [EXPERIENCE-20261028-wheel-安装布局下-rules-version-恒为空-随包清单缺-ai-rules-lite]
---