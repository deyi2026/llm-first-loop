---
title: SWE-bench F2P 批量验证流程（pytest 版本兼容 + rc 权威判定）
scenario: SWE-bench 实例批量 F2P 验证（老代码仓库如 sympy/pylint）时，如何搭建环境、避免误判、高效跑完
root_cause: SWE-bench 验证失败常被误判：pytest 版本不匹配致 collection error（0.00s 假 FAILED）；输出 tail 截断看不到 passed；depth1 clone 无法 checkout base_commit
solution: python3.13 venv + collections 垫片 + pytest<8；全量 clone；验证判定用 rc 权威；test_patch 无新函数用 @@ def 提取；后台 job 拆分并行。详见本文。
evidence: 2026-08-18 实测：sympy mid 12/12 PASSED。pytest 9→7.4.4 解决 Unknown config option；tail-5→rc 判定修正；depth1→全量 clone；13031 无新函数用 @@ def 提取
tags: [SWE-bench, F2P验证, pytest, 环境搭建, 后台任务]
source: {}
status: active
created_at: "2026-08-18T08:44:43.614778+08:00"
updated_at: "2026-08-18T08:44:43.614778+08:00"
---

## SWE-bench F2P 批量验证流程（2026-08-18 实测，sympy mid 12/12）

### 环境搭建（老代码仓库专用）
1. **python3.13 venv**（3.14 不兼容老代码；sympy 需 3.13）
2. **collections 垫片**：sitecustomize.py 注入 venv site-packages（Mapping/Sequence/Set 等映射到 collections.abc，python 启动即加载）
3. **依赖**：setuptools<70 + mpmath + pytest
4. **pytest 版本必须匹配**：sympy 1.9 的 pytest.ini 与 pytest 9 不兼容（Unknown config option: doctestplus → collection error 0.00s 全 FAILED）→ **用 pytest<8（7.4.4 实测 OK）**

### 关键坑（都是踩过的）
- **depth 1 clone 不行**：SWE-bench 实例 base_commit 各不相同，须**全量 clone** 才能 checkout
- **判定必须用 rc（exit code）权威**：pytest 输出尾部全是 warnings（Deprecation/SyntaxWarning），`tail -5` 截断后看不到 "passed" 行 → 误判 FAILED。**pytest exit 0 = 全过**（即使前面一堆 config warning）
- test_patch 可能无新函数（在现有函数里插断言）→ 用 `@@ ... def fn_name` 上下文提取测试名
- 无测试函数实例（环境限制）→ test_patch 有内容但无 def → 用 diff 上下文函数名

### 验证脚本模式（verify_one.py）
checkout base_commit → git apply model_patch（失败 patch -p1 兜底）→ apply test_patch → pytest {test_file} -k "{tests}" → 判 rc

### 后台 job 拆分（长任务调度模式实践）
环境 4 job + 验证 1 job = 主循环少量轮次完成 12 实例验证——勿单循环逐个跑

### 流程
/tmp/swe_sympy_mid_verify/{sympy(全量clone), .venv, verify_one.py, run_all.sh, verify_results.log}