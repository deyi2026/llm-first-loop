---
title: 模板脚本按期派生后必须旧期 token 清零+新期 token 枚举双检（含无连字符变体）
scenario: 按期复用的发布/校验脚本（如 _publishNN_toutiao.py 系列）用 sed 从上期模板派生：主稿名、锚点版 html/txt、admission 回执、session 文件、图片文件名、FIG_BASE、TITLE 都嵌着期号
root_cause: 同一对象（期号）在文件名中存在多种书写变体（daily-23 / daily23），单一替换模式必然漏网；派生脚本未做残留 token 检查就直接使用
solution: 派生后双检放行：①grep 旧期 token（含带/不带连字符变体、上期图号）计数必须为 0；②断言新期关键 token（MD/TT_HTML/TT_TXT/ADMIT/SESSION/FILES/FIG_BASE/TITLE）逐项在位。再跑一次脚本自校验 phase（如 emit+校验 PASS）后才进入发布流程。
evidence: "docs/promotion/_publish24_toutiao.py 生成后 grep 断言失败一次（cd 短路导致主稿标题替换未执行的连锁）；二次 grep 定位 ADMIT/SESSION 仍为 20261020-daily23-*.json，定点替换后 sed -n '26,27p' 复核为 daily24 版本；confirm 前 validate_admission() GATE_OK（读 daily24-admission.json，qualification=PASS）"
tags: [发布流程, 脚本派生, sed, token 校验, 防退化]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-20T20:38:27.971559+08:00"
updated_at: "2026-10-20T20:38:27.971559+08:00"
---

现象：用 sed 把上期发布脚本派生成本期脚本时，替换 'daily-23'→'daily-24' 覆盖了主稿/toutiao 文件名，但 admission/session 回执文件名是 'daily23-admission.json'（无连字符变体）未被替换，生成的新脚本仍指向上期回执路径。若未拦截，confirm 阶段 validate_admission 会读错文件或误判闸门。
拦截与修复（2026-10-20 daily-24 实测）：派生后立即 grep 新脚本中旧期 token（grep -n 'daily-23\|daily23\|fig90\|fig91\|fig92\|fig93'）+ 断言新期关键 token（MD/TT_HTML/ADMIT/SESSION/FILES/FIG_BASE/TITLE）逐一存在；发现 ADMIT/SESSION 残留后定点替换，校验通过后放行。
运作规则：从模板脚本派生本期脚本（sed/复制品）后，放行前必须「旧期 token 清零 + 新期 token 枚举在位」双检；文件名替换模式要同时考虑带连字符与无连字符两种变体。