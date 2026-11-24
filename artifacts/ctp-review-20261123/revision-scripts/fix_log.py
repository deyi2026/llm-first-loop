# -*- coding: utf-8 -*-
import sys, pathlib
p = pathlib.Path("artifacts/ctp-review-20261123/adjudication-and-revision-log.md")
t = p.read_text(encoding="utf-8")
pairs = [
("| SPEC v0.9 | md5 5f627aee… / 325 行 | v0.9.2 / 334 行 | +48 / −38（含新增 §14 两行、§15 变更历史一行） |",
 "| SPEC v0.9 | md5 5f627aee… / 325 行 | v0.9.2 / 337 行 | +51 / −35（含 §14 新增两行、§15 变更历史一行） |"),
("| PROP 0.1 | md5 d2d93c60… / 87 行 | 0.2 / 91 行 | +16 / −2 |",
 "| PROP 0.1 | md5 d2d93c60… / 87 行 | 0.2 / 91 行 | +16 / −2 |"),
("| DESIGN v1.2.2 | md5 f21dd873… / 409 行 | v1.2.3 / 409 行 | +9 / −8（等行替换） |",
 "| DESIGN v1.2.2 | md5 f21dd873… / 409 行 | v1.2.3 / 409 行 | +10 / −9（等行替换） |"),
("修订实现方式：55 处定点替换",
 "修订实现方式：54 处定点替换"),
]
for o,n in pairs:
    c = t.count(o)
    if c != 1:
        print(f"[ABORT] match={c}: {o[:40]!r}"); sys.exit(2)
    t = t.replace(o,n)
p.write_text(t, encoding="utf-8")
print("[OK] log numbers corrected")
