---
title: 基线原始记录必须不可变：重跑前先固化快照，输出目录禁止复用
scenario: "Phase3 M0：01:32 产出 12 份基线 JSON（pre-M1 代码），01:34 报告引用其数字；01:41 我在 M1 开发中途重跑同一测试套件，输出目录未参数化，原始基线 JSON 被含 M1 字段的新记录整体覆盖且无法恢复（reports/ 未入 git）。基线快照不可变性破坏，M1/M2 对照基线险些失效。"
root_cause: 基线输出目录硬编码固定，且 M0 验收与 M1 开发共用同一工作树同一测试文件；重跑测试=重写基线，无版本区分。
solution: 事故如实留痕（README + 报告 §0 时间线，不掩盖）；REPORT_DIR 环境变量参数化；Rec 增加 ran_under 字段；原始数字以成文报告为可靠载体。
evidence: reports/phase3/m0/README.md；test_m0_scenarios.py REPORT_DIR 参数化；S01.json 覆盖后含 grade=accepted 字段（M1 行为）
tags: [基线快照, 数据不可变, 覆盖事故, 对照实验, Phase3]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-13T01:51:59.808916+08:00"
updated_at: "2026-10-13T01:51:59.808916+08:00"
---

基线/对照实验的原始数据一经产生即固化：①输出目录参数化（PHASE3_REPORT_DIR），重跑必须指向新目录；②报告引用数字与 JSON 文件一一对应，覆盖后报告即失去可复核性（本次靠审查者在覆盖前恰读得全部原始记录才保住对照）；③长期看应把基线 JSON 纳入 git 或转存 immutable snapshot（artifact://），或在每次基线运行后立即 commit。修复动作已落地：REPORT_DIR 参数化 + reports/phase3/m0/README.md 事故留痕 + ran_under 字段标注代码版本。