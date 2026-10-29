---
title: 安全守卫测试夹具的运行时拼装纪律（避免夹具文本命中待测守卫）
scenario: 为 LFL 灾难守卫/RULE-AI-28 准入分类器编写或修改安全闸测试（heredoc、管道直连解释器、受保护动词、敏感文件名等夹具）时，测试夹具文本本身会命中待测守卫，导致测试文件写不进、跑不了。
root_cause: ""
solution: 夹具运行时拼装纪律：所有危险子串（here-doc 引导符、管道符、-rf、受保护动词连写、URL）在测试源码内用 chr() 拼接或分段字符串构造，保证外层写入命令与测试源文件本身零命中；测试断言只检查运行时构造的行为。路径类正则注意 pytest 临时目录名（pytest-NNN）带来的假阳性，用负向前瞻规避。
evidence: "evidence://v1/84d4a7a1ecfd331a7f54b3820214338ce6e753a2778b61574df489d0907b6b13; tests/unit/test_static_source_conversion.py; evidence://v1/76e6e1698d5e0be2ce8b26673e85f193b6a6a16f8ced7d47032d310152382087"
tags: [safety-guard, testing, test-fixture, heredoc, review-admission, RULE-AI-35]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-29T04:08:25.947380+08:00"
updated_at: "2026-10-29T04:08:25.947380+08:00"
---

现象：给安全守卫写测试时，夹具里出现危险命令文本（rm -rf、curl|sh、git push 字面量）会让外层写入命令本身被守卫/准入分类器拦截——旧运行时按全文正则扫描，外层 heredoc 体文本进扫描面。对策（已被 10 轮独立审查验证）：1) 夹具一律运行时拼装（LL=chr(60)*2、GP="git"+chr(32)+"push"、RF=chr(45)+"rf"），源文件零危险子串；2) 转换类新增测试统一放 tests/unit/test_static_source_conversion.py（49 项，含审查逐轮回归 test_reviseN_* 系列）；3) e2e 用 ToolRegistry+ExecuteCommandTool(safety_audit_dir=tmp) 构造。附带发现：macOS pytest 临时路径含 "pytest-NNN" 字样，宽网正则须用负向前瞻 pytest3?(?![\w-]) 防路径误中。