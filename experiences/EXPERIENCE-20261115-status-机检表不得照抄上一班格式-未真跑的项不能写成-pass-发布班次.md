---
title: STATUS 机检表不得照抄上一班格式：未真跑的项不能写成 PASS（发布班次）
scenario: 收口 STATUS 的「门禁与机检」表要逐项填真实结果时，模型容易照抄上一班格式，把尚未执行的机检也写成 PASS。
root_cause: ""
solution: 机检行只填真跑过的结果；无法在原场景执行的先改成等价判据再跑；跑完把回执里的具体数值（match_ratio、problems 条数）写回；已写错的在「本班真实失败」里如实自曝。
evidence: "docs/promotion/STATUS-20261115-daily87.md 第十节第 11 条；回执 receipts/d87-caption-check.json（verdict=PASS, problems=[]）、receipts/d87-precheck.json（match_ratio=0.9592, consistent=true, unmatched 全为 md 图片行）"
tags: [推广班次, STATUS, 机检, 诚实, 未核验不得写成已核验]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-15T08:34:34.939740+08:00"
updated_at: "2026-11-15T08:34:34.939740+08:00"
---

场景：写 STATUS 收口文档时，习惯性把「机检表」按上一班的样式填成 PASS，但其中某几项其实在写文档时**还没有真正执行**（例如编辑页已在提交后离开，取不到 DOM；或脚本根本没写）。

后果：STATUS 变成「未核验却写成已核验」，是内容级失实；且下游班次会把它当既成事实继承。

对策：
1. 写 STATUS 的机检行时，逐行标注该机检的**执行状态**（已跑/未跑/不适用），不要凭上一班格式填。
2. 发现某项无法在原场景执行时，改成等价可执行的判据再真跑，而不是留空或照抄结论（例：一致性预演原为「编辑器 DOM 全文」，提交后改为「公网实见全文」调用宿主同款函数）。
3. 跑完后把回执里的**具体数值**写回 STATUS（如 match_ratio=0.9592、problems=[]），而不是只写 PASS。
4. 若已写错，如实自曝：在 STATUS「本班真实失败」里登记「初稿把未真跑的机检写成 PASS，写稿时发现后补跑并改正」——不要静默改正。

反例：本班初稿在 `caption_check` 与 `precheck` 两行写了 PASS，实际当时一项未跑、另一项的脚本对当前场景取不到数据；靠「补写真实执行 + 在失败登记里自曝」闭合。