---
title: DRC T2 写路径：锁 contextmanager 不得吞临界区异常；tmp 创建后所有失败分支必须清理残骸
scenario: Durable Store T2 迁移（tmp+fsync+link/replace 写路径）通用场景：任何用 @contextmanager 实现跨进程锁（flock）并把 yield 包在 except OSError 内的实现。
root_cause: ""
solution: "锁 contextmanager 的异常映射只覆盖获取段（os.open/flock），临界区 yield 放独立 try/finally，让调用方异常原样穿透；tmp 文件创建后的每一条失败分支都必须显式清理（suppress(OSError)+unlink(missing_ok=True)），并用\"错误路径零 tmp 残骸\"作为故障注入固定断言。当前性验证：grep -n \"仅锁获取失败映射\" src/llm_loop/recovery/backup.py 命中 _store_lock docstring；python3 -m pytest tests/unit/test_backup_store_durability.py -q → 13 passed。"
evidence: "tests/unit/test_backup_store_durability.py 13 例故障注入全绿（含 lock 前分型+无残骸+可重试、mark replace 失败原样保真）；冒烟复现见 evidence://v1/b32a9ed6736b1dc010132433fcce9ea3e7e6578040c90a0a55cbbbd4d91a6c8a（12/13→暴露残留缺陷）；修复后 evidence://v1/94b73bbdddc732cd1930c36692aaeb88bac2a81662bbab01c7c95945d9fa728d（71 passed）；提交 500ee8f3e。"
tags: [drc, t2-migration, flock, contextmanager, fault-injection, tmp-cleanup]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-08T11:13:28.126090+08:00"
updated_at: "2026-10-08T11:13:28.126090+08:00"
---

DRC T2 写路径迁移中，两个缺陷都是先写实现、后由故障注入测试/冒烟暴露的，且都不是一眼可见的逻辑错误：i) @contextmanager 锁把 yield 放进 try/except OSError → 临界区内调用方抛出的 FileExistsError（OSError 子类）被误分类为"锁失败"并二次包装，破坏 typed 分型真值；ii) mark_recovered 的 os.replace 失败路径只 log+return，没清理已成功创建并 fsync 的 tmp 文件，留下孤儿残骸。修复：锁的 except 仅覆盖 os.open+flock 获取段，yield 放独立 try/finally；所有"tmp 已创建"之后的失败分支统一 contextlib.suppress(OSError)+unlink(missing_ok=True) 清理。当前性验证：grep -n "仅锁获取失败映射" src/llm_loop/recovery/backup.py 应命中 _store_lock docstring；python3 -m pytest tests/unit/test_backup_store_durability.py -q 应得 13 passed（环境变迁后若失效，按 solution 重核实现再引用本卡）。