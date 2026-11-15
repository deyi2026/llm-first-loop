---
title: 收口脚本：布尔判定键必须在计算 fails 之前赋值，否则恒有一条假失败
scenario: 收口/门禁脚本里，先算 fails 再给 checks 赋布尔键，导致 fails 恒含一条假失败。
root_cause: ""
solution: 所有布尔判定键先赋值、再计算 fails；排查 FAIL 时先看 fails 里的键是否在 checks 中真实存在（None 被当成失败）。
evidence: "docs/promotion/_d87_closeout.py（修正前后对照）；回执 receipts/d87-closeout.json（CLOSEOUT_VERDICT=PASS, fails=[]）；STATUS-20261115-daily87.md 第十节第 4 条"
tags: [推广班次, 收口脚本, 布尔判定, 假失败]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-15T08:34:40.430431+08:00"
updated_at: "2026-11-15T08:34:40.430431+08:00"
---

场景：发布班次收口脚本里，布尔判定键（`checks["xxx_ok"] = ...`）的赋值写在 `fails = [k for k in hard if not checks.get(k)]` **之后**。

后果：`checks.get(k)` 取到 None → `not None` 为 True → `fails` 恒含一条假失败，机器判定 FAIL，而其余全部实检项其实通过；容易让人误判为「发布有问题」并去做无谓的补救。

对策：
1. 所有布尔键必须先算完、再算 fails；
2. 不要改成 `checks.get(k) is not True` 这类写法——那会把 None 当成通过，方向反了；
3. 排查 FAIL 时先看 fails 里的键是否在 checks 中真实存在（None 被当成失败）。

反例：本班 closeout 首次运行 `CLOSEOUT_VERDICT=FAIL, fails=["pgc_present"]`，而 `pgc_id` 实为 "7708188026622591523"；调整赋值顺序后 `fails=[]`、VERDICT=PASS。

当前性验证：跑 `python3 docs/promotion/_d87_closeout.py` 应得 `CLOSEOUT_VERDICT=PASS` 且 `fails=[]`；把 `checks["pgc_present"] = bool(PGC)` 移回 `fails = [...]` 之后重跑，应复现 `fails=["pgc_present"]` 的假失败。