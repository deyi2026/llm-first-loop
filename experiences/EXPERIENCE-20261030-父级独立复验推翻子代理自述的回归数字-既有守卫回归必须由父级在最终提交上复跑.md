---
title: 父级独立复验推翻子代理自述的回归数字：既有守卫回归必须由父级在最终提交上复跑
scenario: "接管一个长 Goal 的收尾阶段，前序会话的文档里写着「既有测试全量回归 12223 passed（子代理回执）」，且「既有测试零修改」。父级不采信自述，在最终提交 566e5b09f 上独立复跑全量回归（pytest tests/ -q -m \"not real_llm and not serial_signal\"），实测 1 failed / 12254 passed / 834.89s——唯一失败是既有守卫 tests/unit/test_inspect_code.py::test_factory_registered，因为同批提交 ab86dde5b 为满足 R9 棘轮把 build_engine 的基础工具注册抽成模块级 _register_basic_tools(register_basic) helper，字面量断言 `_register_basic(\"inspect_code\"` 失效。"
root_cause: 前序会话把子代理回执的回归数字写进设计文档当成既成事实，且未在其「抽 helper」的重构提交后复跑全量套件；守卫红灯被文档的乐观陈述掩盖，直到父级独立复跑才暴露。
solution: 1) 父级必须在最终提交上独立复跑全量回归，不采信前序子代理/文档中的通过数字；2) 失败先查职责问题（责任在改动一侧），既不改 src/ 迁就测试、也不抬 baseline 或加豁免，而是把字面量断言升级为行为级断言（直接调用 helper 收集注册表 + 断言工具在册且类型正确 + 用 ast.parse 判定确有调用，避免子串断言被注释满足）；3) 文档里的不实陈述就地标注更正并追加 §13.8 记录发现与处置，不删改历史记录；4) 修完再跑一遍聚焦回归 + ruff 棘轮门，最后用 review_admission 在隔离 worktree 上跑 canonical 全量门禁取得独立 PASS。
evidence: "evidence://v1/d97ab7f4d82737ea8d53c218249f79caceefd5ecf57649365cde0abd2a9d6ecf（修前全量 1 failed/12254 passed/834.89s）；evidence://v1/e707432f845ced6c5351e3d8a5c2b831c1336df60ad42ebc8f176b3ba5a1a7f1（聚焦 181 passed/1 skipped）；evidence://v1/eb86e1181bd89ab2ea8aac9f1db8ae9bbdf2956c6815a867c5a9b73ef9bf85fb（ruff 棘轮门 PASS）；evidence://v1/024e928cf34d87e6d363d02fca382479b0e13b4aa5afb42acac710db5545efa2（full_test 准入 PASS）"
tags: [rule-ai-24, rule-ai-01, 验收, 回归, 既有守卫, 子代理自述]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-30T16:06:27.769795+08:00"
updated_at: "2026-10-30T16:06:27.769795+08:00"
---