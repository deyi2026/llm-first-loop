---
title: 资格证据文件是历史运行的不可变记录：源前进时更新钉扎+加 evidence_note，绝不改写证据本体
scenario: StateBraid/llama.cpp 联仓发布流程：llama.cpp 源前进（预算上限→驱逐→evicted 字段，04329aac→1b9d0fc7a→09a4891dd）后同步 StateBraid 侧 fail-closed 钉扎时，一度更新了资格证据文件 compact_evidence.json 的 SHA，自查后回退。
root_cause: ""
solution: 改写前自查发现：证据文件是 2026-09-07 真实运行（录于 04329aac）的不可变记录，改写即伪造证据归属。回退证据文件，改为 manifest.json 增设 evidence_note：声明正式证据录于 04329aac、源已前进、再鉴定待做；runtime_qualified 保持 false。
evidence: "evidence://v1/16ccce60a869485fe4cc0441458cbcc321f27345c690619d92128efc9565eec2（compact_evidence.json 仅 91501b6 触碰、无 diff；manifest evidence_note + 3 SHA 更新）；evidence://v1/155dde9bab62e4b9691e1da28c57d9ef491889b9c46faca44e88c338c11a5e50（patch 1011 行/sha256 36eb956e/路径集与 git diff-tree 465e49b9..09a4891dd 完全一致）"
tags: [release-pinning, qualification-evidence, immutability, fail-closed, manifest]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-14T20:27:38.146897+08:00"
updated_at: "2026-09-14T20:27:38.146897+08:00"
---

分发包身份钉扎（manifest 的 source/tree/patch SHA、常量、测试断言）与资格证据记录（compact_evidence.json 等真实运行产物）是两类对象：前者必须随源前进同步更新，后者是对历史代码点（如 04329aac）的不可变记录，改写等于把旧证据冒充新代码。源前进后的正确做法：常量+测试+patch 重生成同步，证据文件保持不动，manifest 增设 evidence_note 声明"证据录于旧 SHA、再鉴定待做"，runtime_qualified 维持 false 直到新证据落盘。核验方法：git log --oneline -- <evidence> 确认最后触碰点早于源前进提交，git diff <evidence-commit>..HEAD -- <evidence> 为空；patch 用 wc -l + sha256 + diff <(git diff-tree base..HEAD) <(grep '^diff --git' patch) 三对一。