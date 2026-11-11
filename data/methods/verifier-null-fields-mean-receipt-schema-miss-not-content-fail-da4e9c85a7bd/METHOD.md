---
method_id: verifier-null-fields-mean-receipt-schema-miss-not-content-fail-da4e9c85a7bd
name: verifier-null-fields-mean-receipt-schema-miss-not-content-fail
description: 自写或跨稿派生的收口/审计/验收脚本按字段名引用已落盘的机器回执并输出聚合裁决时，字段绑定必须以回执实际键集为准。首跑出现 FAIL 先看失败项的原始值：若为 null/缺省、且同一脚本从同一回执读出的兄弟字段（ID、URL、正文字数、关键句命中）全部有值，说明是字段名没对上（绑定落空），不是内容失败——一条只读命令列出源回执键名、改名重跑即翻绿。臆测字段名还会因 .get 默认值双向出错：默认 False 产假 FAIL（本集 title_public_match/ai_decl_public 实为 title_match/has_ai_decl），默认 True 则产假 PASS。只有『字段存在且为 False』才是真内容失败。
aliases: 收口脚本假 FAIL 怎么排查, 校验字段名和回执对不上, 审计脚本读不到回执字段值, 裁决里 null 不是 false, closeout 误报失败项
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:13f39914-a9ea-4989-8ca7-500081175c59:604:4c0911931a5ababd3273
evidence_refs: learning:learn:34523a59cb93
created_at: 2026-11-11T21:30:28.013838+08:00
updated_at: 2026-11-11T21:30:28.013838+08:00
---
## Trigger
自写或跨稿派生的收口/审计/验收脚本按字段名引用已落盘的机器回执（verified/readings/回执 JSON）并输出聚合裁决（PASS/FAIL + 失败清单），首跑或换稿复用后首跑出现 FAIL 项

## Discriminator
失败项在裁决输出里的原始值是 null/缺省而非明确 False，且同一脚本从同一回执读出的其它字段（如 pgc_id、public_url、正文字数、关键句命中）全部成功取值——回执文件已被读到，只是失败项的字段名在回执键集中不存在

## Short path
- 写脚本（或首跑后）先用一条只读命令列出源回执全部实际键名，字段引用全部从该键集绑定，不凭记忆臆测字段名
- 缺失键显式报 key_absent 并终止该项判定，禁止用 .get 默认值顶替后继续聚合裁决
- 遇 FAIL 先取失败项原始值分流：null → 定位为字段绑定未命中，对照键集改名重跑；字段存在且为 False → 才进入内容失败处理
- 翻绿后核对修复 diff 只含字段名/取键路径改动，判定逻辑与阈值零改动，且内容产物指纹（publish_sha256、URL、字数）与修复前一致

## Stop conditions
- 裁决涉及的全部字段都能在源回执键集中找到并取到原值（含明确 False）
- 失败清单里不再有 null 值字段，剩余失败均为『字段存在且为 False』的内容性失败
- 修复前后内容产物指纹完全一致，本次改动未触碰任何待发布内容

## Verification
- 用只读命令打印源回执全部键名，逐字段核对脚本引用与键集一致
- 修复前后脚本 diff 仅出现字段名/取键路径变化，判定阈值与聚合逻辑零改动
- 重跑后裁决与失败清单一致翻绿，且无任何内容产物被重写

## Counterexamples
- 源回执本来就没记录该字段（可选字段从未生成）：改字段名救不了，应换证据源或如实登记『无法核验』，而不是硬绑一个近似键
- 字段存在且值确为 False（如公网标题真不一致）：这是真内容失败，禁止靠改字段名把裁决修绿
- 失败字段是脚本自算而非引自回执（如 editor_chars=null）：指向脚本自身取数逻辑 bug，修法在取数处而非键名
- 回执 schema 整体刚升级、旧字段名大面积失效：单点改名不够，应整体重绑新键集
