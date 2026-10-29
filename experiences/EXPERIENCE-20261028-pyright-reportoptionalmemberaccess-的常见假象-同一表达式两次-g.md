---
title: pyright reportOptionalMemberAccess 的常见假象：同一表达式两次 .get() 无法让 isinstance 收窄
scenario: "Python 代码 `x = d.get(\"k\") if isinstance(d.get(\"k\"), dict) else {}` 后对 x 调用 .items()/.get()，pyright 报 \"items is not a known attribute of None\"。属类型检查器不把两次独立调用关联（不是真 None 缺陷），但静态门禁按修改文件零红阻断。"
root_cause: ""
solution: |
  先取值到局部变量再收窄：`raw = d.get("k"); v = raw if isinstance(raw, dict) else {}`。行为与原写法完全一致（非 dict 仍回落 {}），只去掉重复调用，使收窄对同一符号生效。
  当前性验证：在目标文件跑 `pyright <file>` 应得 "0 errors"、`ruff check <file>` 应得 "All checks passed!"；若该写法已被改成局部变量形式，则 pyright 不再报 reportOptionalMemberAccess（说明本卡已落地，无需重复修）。
evidence: "src/llm_loop/web/provider_routes.py:147-152 修前 pyright 报 2 处（:150 .items()、:152 .get()）；改为 prev_models_raw/next_models_raw 局部变量后 pyright \"0 errors, 0 warnings\"、ruff \"All checks passed!\"、tests/web/test_provider_admin.py 30 passed；提交 f554ac908，仓库 pyright ratchet new=0/changed_file_diagnostics=0。"
tags: [pyright, type-narrowing, static-gate, optional-member-access]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-28T23:02:38.522111+08:00"
updated_at: "2026-10-28T23:02:38.522111+08:00"
---