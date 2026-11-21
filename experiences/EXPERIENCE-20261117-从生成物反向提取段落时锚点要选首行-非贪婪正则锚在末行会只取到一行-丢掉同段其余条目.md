---
title: 从生成物反向提取段落时锚点要选首行——非贪婪正则锚在末行会只取到一行、丢掉同段其余条目
scenario: "需要把已生成的 STATUS/报告里的一段「处置条目」原样搬进新版本时，用正则从生成物反向提取（`^锚点.*?(?=^## 下一节)`）。若锚点选在这段条目的**最后一行**（例如列表按时间顺序排列、「R3 结论之外」排在末位），非贪婪匹配只会取到这一行，前面同段的 D2/D5/D6 三条处置记录被静默丢弃，且生成脚本没有任何断言报错。"
root_cause: 非贪婪 `.*?` 的匹配起点由锚点决定；锚点在段末则前文被排除在外，而提取脚本无条数断言时缺陷不会显形。
solution: 锚点必须选该段的**首行**并断言命中条数下限；生成后回读校验目标条目是否逐条在位（本班用 grep 关键子串列表逐条 OK/FAIL 核对，FAIL 后用精确编辑补回，而不是重跑整条生成链）。与 EXPERIENCE-20261114（尾注/图注必须按段落边界切）同源：一处是切点错，一位是锚点错，都会静默产出残段。
evidence: "本班 docs/promotion/_d93_status_run.py 用 `(?ms)^- \*\*R3 结论之外.*?(?=^## 四、)` 从 STATUS-20261117-daily93.md 反向提取 R3 处置段，提取到的只有「R3 结论之外…」1 行，D2（P1 实开核对不成立）/D5（P2a 已处置）/D6（P2b 已采纳）三条处置记录被丢弃；由 _d93_fixstatus.py 精确编辑补回，并用 5 项 OK/FAIL 断言确认在位。"
tags: [regex, extraction, report-generation, verification]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-17T09:36:15.884620+08:00"
updated_at: "2026-11-17T09:36:15.884620+08:00"
---