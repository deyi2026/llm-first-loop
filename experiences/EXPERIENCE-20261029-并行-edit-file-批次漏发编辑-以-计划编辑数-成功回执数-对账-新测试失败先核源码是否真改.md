---
title: "并行 edit_file 批次漏发编辑：以\"计划编辑数=成功回执数\"对账，新测试失败先核源码是否真改到"
scenario: 多文件多处 edit_file 的批量修改任务（安全审查 P2 修复：3 源文件 + 4 测试文件 12 处编辑）
root_cause: ""
solution: "把计划编辑清单当 checklist：每处编辑回执后标记；批次结束数\"已回执数==计划数\"再跑测试。新测试失败时先 read_file 目标函数核对源码是否真改到（10 秒判别），再怀疑改错。"
evidence: "失败复现：.venv pytest 三个测试文件 4 failed, 75 passed（test_rule_asset_facts_wheel_manifest_match_disclosed / _mismatch_flags_tamper / test_doctor_rule_assets_fail_on_manifest_hash_mismatch / test_revise_note_carries_preview…），installation.py:119-122 现文仍旧代码；补发逻辑块编辑（artifact://v1/164545913adf4f998d12af050678191d）后同组 79 passed；最终相关面 345+4 passed，commit 67704b794。"
tags: [edit_file, 并行编辑, 漏发, 回归测试守门]
source:
  artifact_sha256: 51f98bb19f634734a1f9b57bb3b63e75c921404be97b163135a4a6181fe95d3a
  commit: 67704b79495dc1c210d9c906310ea613d750407a
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-29T10:11:40.884183+08:00"
updated_at: "2026-10-29T10:11:40.884183+08:00"
---

场景：一次任务要改 6 个文件、计划 12 处 edit_file，分批并行提交。某批漏发了 installation.py 的逻辑块编辑（docstring 编辑发了、逻辑块没发），且没对照"计划编辑清单 vs 成功回执"清点。首轮回归 4 个测试失败（新增的 mismatch 测试 + doctor 集成测试），读源码确认逻辑块仍旧代码。
修复：补发编辑后 79 passed。
两条做法：1) 并行 edit_file 批次完成后数回执，已回执数<计划数=漏发；2) 新测试失败先 read_file 目标函数核对源码是否真改到，再怀疑改错。