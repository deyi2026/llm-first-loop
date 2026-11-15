---
title: 无空格中文标题的「首词」提取必须按标点切：用 split() 会把整句标题当成首词，让标题规范门禁空转
scenario: "LFL 推广 d89 晚班（2026-11-15）：稿子标题《对话历史改干净后，接手模型做对的比例从50%掉到44%》没有空格，派生自 d88 的构建脚本用 title.split()[0] 取「标题首词」，结果首词=整句标题；而排期硬门（§五）要判的是「标题是否以 AI/人工智能/大模型/智能体/Agent 等抽象词开头」。空转的判定让这条门禁形同虚设——本班靠人工阅读才发现首词其实是「对话」。"
root_cause: "中文标题天然无空格，沿用英文场景的 split()[0] 提取首词，判定键失效却不会报错"
solution: 中文标题的「首词」必须按标点切（，。：、！？；及空格、全角括号）取第一个非空片段；再拿它对抽象词集合做前缀判定，判定结果写进机检回执（title_first_token / title_starts_with_abstract），不要只留整句。当前性验证：跑 `python3 docs/promotion/_d89_closeout.py` 后读 receipts/d89-closeout.json，应看到 title_first_token 与 title_starts_with_abstract 两个字段，且 title_starts_with_abstract=false。
evidence: docs/promotion/receipts/d89-closeout.json（title_first_token=对话历史改干净后、title_starts_with_abstract=false、title_chars=27）；修改前 receipts/d89-build.json 的 title_first_word 字段=整句标题（空转证据）；修正脚本 /tmp/lfl_fix_audit_d89.py（closeout 增加首 token 判定）
tags: [推广班, 标题规范, 机检口径, 中文分词]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-15T20:48:55.896389+08:00"
updated_at: "2026-11-15T20:48:55.896389+08:00"
---