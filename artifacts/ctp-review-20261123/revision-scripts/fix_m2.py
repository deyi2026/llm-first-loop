# -*- coding: utf-8 -*-
import sys, pathlib
p = "docs/SPEC-20261123-cooperative-target-protocol-v0.9.md"
old = "a) 阵列必须在注册表登记成对几何关系（距离、夹角）及其公差 [TBD-V3]；"
new = "a) 阵列必须在注册表登记成对几何关系（距离、夹角）及其公差 [TBD-M2]；"
t = pathlib.Path(p).read_text(encoding="utf-8")
n = t.count(old)
if n != 1:
    print(f"[ABORT] match={n}"); sys.exit(2)
pathlib.Path(p).write_text(t.replace(old, new), encoding="utf-8")
print("[OK] M-2a -> [TBD-M2]")
