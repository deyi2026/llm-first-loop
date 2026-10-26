---
title: 科普配图重绘：论文区间/不等式读数禁止取自造代表值，标签保留原口径
scenario: "第 30 期头条科普配图 fig123（论文图 4 重绘）：论文原文写 ASR@1 \"below 20%\"，绘图脚本为图面好看写成了「约18%」，read_image 验图前的自查发现该数字系自造，改回「<20%」并重新生成、重建 HTML、重冻结。"
root_cause: ""
solution: 重绘实验图前，先列出源文本中每个读数的原始口径（精确值/约数/不等式）；图标签只允许出现源文本已有的数字形态，不等式保留不等式（<20%），约数保留约（约50%）；生成后逐标签回对源句，发现标签数字在源文本找不到即视为缺陷返工。
evidence: "docs/promotion/figures/_d30.py 修正前后标签 diff（约18%→<20%）；docs/promotion/receipts/d30research/sua_full.txt:641（原文 \"below 20%\"）；修正后 read_image 复核 fig123 确认「<20%、<20%、约50%」无 18% 残留"
tags: [配图, 科普绘图, 数据保真, R5台账, 推广]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-22T20:51:52.777863+08:00"
updated_at: "2026-10-22T20:51:52.777863+08:00"
---

重绘论文实验图为科普配图时，源数据常给的是不等式或区间（"below 20%"、"about 50%"、"nearly 90%"）。本期把 "below 20%" 画成标签「约18%」——18% 这个数字论文里不存在，属于自造代表值；被写前 R5 自检发现，若漏检会以伪造数据进发布图。规则：凡论文只给不等式/区间/约数的读数，图内标签必须原样保留口径（如「<20%」「约50%」「近90%」），条形长度可用保守示意但不得在标签处生成新的具体数值；图注同样保留"约/近/不到"限定词。校验法：画完逐标签与源句比对，标签中出现的每个数字都必须能在源文本中逐字找到（或明确标注为作者自拟示意）。\n当前性验证：grep -n 'below 20%' docs/promotion/receipts/d30research/sua_full.txt 应命中 :641；grep -c '约18%' docs/promotion/img 脚本产物与 figures/_d30.py 应为 0、grep -c '<20%' figures/_d30.py 应 ≥1。