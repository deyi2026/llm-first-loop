---
title: codearts 云 API 集成模块是未验证原型（发明契约+占位鉴权），不能靠补 env 启用
scenario: "任何\"补上配置即可启用\"类集成结论，必须先核三件事：(1) 调用的外部 API 契约是否有真实出处（官方文档/抓包/spec 提交）；(2) 鉴权是否真实现（占位 header ≠ 签名）；(3) tests 是打 mock 还是真端点。本例 CodeArts 云 API 模块三层全不满足，装配日志静默 fail-open 会掩盖这一点。"
root_cause: ""
solution: "决策前先 git log --all -- <模块目录> 看提交是否带 spec/design 文档；grep tests/<模块> 看 endpoint 是 example.com 还是真实域名；读 client._headers 判断鉴权是占位还是实现。三者任一存疑 → 结论降级为\"原型未验证\"，不得向用户承诺\"补凭证即用\"。"
evidence: git show 7b72df607 --stat（提交无 spec.md/design.md）；src/llm_loop/codearts/client.py L123-152（_headers 占位鉴权 + /agent/executions 路径）；tests/codearts/test_scheduler.py L35 与 test_sync.py L29（endpoint=codearts.example.com）；.env 全文无 CODEARTS_ 前缀；/Applications/CodeArts Agent.app/Contents/Resources/app/product.json（applicationName=codearts-agent）；lsof CodeArts pid 56372 仅监听内部端口 51798/51892/51897（Express/WS，OpenAPI 探测 404）。
tags: [integration-verification, codearts, fail-open, api-contract, evidence-discipline]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-25T11:44:23.045535+08:00"
updated_at: "2026-09-25T11:44:23.045535+08:00"
---

三层证据均不满足可启用条件：① API 契约无真实出处——docstring 称 spec.md/design.md 同目录但 git show 7b72df607 --stat 显示提交从未包含它们，client.py 调用 /v1/agent/executions 等路径在仓库与可达官方文档中均无对应；② 鉴权是占位——client.py L146-148 明文 X-AK/X-SK header，注释自认"实际签名由华为云 SDK 或签名中间件完成"（未实现，华为云要求 HMAC-SHA256 签名）；③ tests/codearts/* 全部打 https://codearts.example.com mock 端点，从未对真实华为云端点跑过。叠加 .env 无任何 CODEARTS_* 键、factory.py _assemble_codearts fail-open 静默跳过，形成"看起来能用"的假象。真免费额度在 CodeArts Agent 桌面 App（VSCode 换壳，product.json applicationName=codearts-agent，dataFolderName=.codearts-doer-for-coding），纯 GUI 无 CLI/无公开本地 API（监听端口为 VSCode 内部管道），工作区级状态在 .codeartsdoer/。