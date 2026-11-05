---
title: R5 台账的两个列级陷阱：来源列含裸竖线会让整行被解析跳过、值列必须是正文原文子串
scenario: "LFL 推广班次的 R5 写前量化台账（docs/promotion/YYYYMMDD-daily-NN-sources.md）与其机械审计脚本（正则抽正文数值 → 逐条对台账）：台账用 markdown 三列表，行解析依赖列分隔符；若来源列里写入含竖线的 shell 命令（如 find … | wc -l），该行会被解析成多列而整行跳过，审计随即报「正文数值缺台账行」，实际是台账写了、只是没被解析到；反过来，值列若写成正文的改写（如把「3,582 次」写成含加粗标记的形态、或把值列写成正文里不存在的组合），审计会报「台账有行但正文没有」。"
root_cause: ""
solution: 台账行来源列禁止出现裸竖线（要写管道命令就改写成「… 计数结果 536，见回执路径 …」这类描述，或把竖线写成全角/转义）；值列必须是正文里逐字出现的子串（可取正文原句片段），不要自造组合。审计脚本的 MISSING 报错先怀疑「行被列分隔符切坏」，再回填。
evidence: "本班 d63 审计实测：首轮 MISSING 含 392/394/536（其中 536 那行的来源列含 `|` 被跳过），改写来源列后转为 EXTRA（值列写成「3,582 次」与正文加粗形态不一致），再把值列改成「3,582」后 AUDIT PASS；终态 receipts/d63-audit.json（AUDIT PASS，113 个数值 token、108 行台账、缺行 0、多行 0）。"
tags: [LFL推广, R5台账, 审计, markdown表格, 误报]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-05T20:31:12.098734+08:00"
updated_at: "2026-11-05T20:31:12.098734+08:00"
supersedes: [EXPERIENCE-20261102-台账数值写法要避开正则分组陷阱-pp后缀与千分位逗号会让审计假报缺失]
---