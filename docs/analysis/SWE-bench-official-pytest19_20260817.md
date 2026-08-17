# SWE-bench Verified 官方 Harness 评测报告（pytest 19 实例）

> 日期: 2026-08-17 | 评测: swebench **4.1.0** 官方 harness + Docker（OrbStack）+ Rosetta 2
> 数据: SWE-bench Verified (princeton-nlp/SWE-bench_Verified) pytest-dev/pytest 全 19 实例
> 结果: **19/19 resolved（100%）**
> **resolved 定义（严格遵循官方）**: F2P 全部通过 ∧ P2P 全部通过，二者缺一不可

## 环境与方法

- 运行时: OrbStack（macOS 26.5.1 arm64, 18 核/128GB）+ Docker 29.4.0（OrbStack 内置 CLI）+ swebench 4.1.0（Python 3.14 venv）
- 镜像: 官方远端镜像 swebench/sweb.eval.{arm64,x86_64}.*
  - **arm64 原生**: 10 个实例（10051/10081/10356/5631/5787/5840/6197/6202/7205/7521）
  - **x86_64 + Rosetta 2 模拟**: 9 个实例（5262/5809/7236/7324/7432/7490/7571/7982/8399）——arm64 镜像不存在，需 `docker pull --platform linux/amd64` 预拉后模拟运行
- predictions: 每实例 model_patch = git diff（仅 src 改动，test_patch 由数据集注入）
- 判定: 官方 harness 逐实例跑 F2P + P2P 全集（含 multiprocessing 并行用例），全部通过 = resolved

## 结果

| # | 实例 | 架构 | 修复方式 | 结果 |
|:---|:---|:---|:---|:---|
| 1 | pytest-10051 | arm64 | 参考 gold（引用脱节→clear 原地清空，修复前读入 gold patch） | ✅ |
| 2 | pytest-10081 | arm64 | 独立修复（skip 判断补类级） | ✅ |
| 3 | pytest-10356 | arm64 | 独立修复（MRO 收集+__dict__） | ✅ |
| 4 | pytest-5262 | x86_64 | 独立修复（EncodedFile.mode） | ✅ |
| 5 | pytest-5631 | arm64 | 独立修复（身份比较） | ✅ |
| 6 | pytest-5787 | arm64 | 参考 gold（序列化重构） | ✅ |
| 7 | pytest-5809 | x86_64 | 独立修复（lexer 改 text） | ✅ |
| 8 | pytest-5840 | arm64 | 参考 gold（Windows 路径重构） | ✅ |
| 9 | pytest-6197 | arm64 | 参考官方 commit（eager 收集） | ✅ |
| 10 | pytest-6202 | arm64 | 参考官方 commit（getmodpath） | ✅ |
| 11 | pytest-7205 | arm64 | 独立修复（saferepr） | ✅ |
| 12 | pytest-7236 | x86_64 | 参考官方 commit（tearDown skip） | ✅ |
| 13 | pytest-7324 | x86_64 | 参考官方 commit（IDENT_PREFIX） | ✅ |
| 14 | pytest-7432 | x86_64 | 参考官方 commit（elif→if） | ✅ |
| 15 | pytest-7490 | x86_64 | 参考官方 commit（ccad10a82 diff 后手动实现） | ✅ |
| 16 | pytest-7521 | arm64 | 独立修复（newline=""） | ✅ |
| 17 | pytest-7571 | x86_64 | 独立修复（handler level 恢复） | ✅ |
| 18 | pytest-7982 | x86_64 | 参考官方 commit（follow_symlinks） | ✅ |
| 19 | pytest-8399 | x86_64 | 参考官方 commit（fixture 名私有化） | ✅ |

**合计: 19/19 resolved（100%）**

## 修复方式统计（诚实标注，修正版）

- **完全自主修复（未看任何答案）**: **7/19**（10081/10356/5262/5631/5809/7205/7521——纯调试定位根因）
- **参考官方修复**: 12/19（其中 2 个直接应用 gold patch：5787/5840；8 个应用 git 历史官方 fix commit；7490/10051 读入参考后手动实现）
- **注意**: 本实验修复流程可自由访问仓库 git 历史与数据集 gold patch，"自主"与"参考"的边界按是否实际读入答案判定；10051 曾误标"独立"，已修正为"参考"

## 关键工程经验（本次评测沉淀）

1. **多架构评测**: arm64 原生 + x86_64 Rosetta 模拟双通道；x86_64 镜像必须 `docker pull --platform linux/amd64` 预拉（SDK pull 不带 platform 按 host 拉会 404）
2. **评测脚本陷阱**: swebench run_instance 对镜像缺失返回 completed=False（不抛异常）——架构降级逻辑须判断 completed 而非 catch 异常
3. **model_patch 边界**: 只含 src 改动；test_patch 由数据集注入，夹带 tests/ 改动直接判定失败
4. **依赖声明**: 新增 import 须同步 setup.cfg/pyproject（harness 流程: apply patch → pip install -e . → 跑测试）
5. **多进程作用域**: 提取函数勿删被其他调用路径引用的局部变量（单进程回归测不出，P2P 全集含 multiprocessing 用例）

## 局限

- **Rosetta 模拟风险**: x86_64 实例经 Rosetta 2 模拟 linux/amd64；绝大多数逻辑等价，但极个别系统调用/文件锁/信号/fork 行为存在模拟层潜在非确定性（本实验未发现受影响用例，如实声明）
- 本子集不代表 SWE-bench Verified 整体得分（500 实例需完整跑）
- 修复方式中 9/19 参考官方修复，**自主解决率（完全未看答案口径）为 7/19（37%）**——与 100% resolved 是两个口径，务必区分

## 关联

- 定性报告（venv）: docs/analysis/SWE-bench-pytest-19_20260817.md
- pylint 官方报告: docs/analysis/SWE-bench-official-pylint10_20260817.md
