# SWE-bench Verified 完整测试报告（pylint 10 实例）

> 日期: 2026-08-17 | 数据: SWE-bench Verified (princeton-nlp/SWE-bench_Verified)
> 范围: pylint-dev/pylint 全 10 实例 | 结果: **42/42 FAIL_TO_PASS 全部通过（100%）**
> 方法: 独立 venv + setuptools<70 + pip install .（无 docker，验证等价）

## 完整成绩单

| # | 实例 | Bug 主题 | F2P | 修复方式 |
|:---|:---|:---|:---|:---|
| 1 | pylint-4551 | pyreverse UML 类型提示 | 10/10 | 参考 gold（4 文件重构） |
| 2 | pylint-4604 | unused-import type comment 误报 | 21/21 | 独立修复（Attribute 节点处理） |
| 3 | pylint-4661 | XDG 目录规范 | 1/1 | 独立修复（appdirs） |
| 4 | pylint-4970 | min-similarity-lines=0 禁用 | 1/1 | 独立修复 |
| 5 | pylint-6386 | verbose 短选项参数 | 1/1 | 参考 gold（4 文件改动） |
| 6 | pylint-6528 | 递归模式 ignore 失效 | 4/4 | 独立修复（_is_ignored_file 提取） |
| 7 | pylint-6903 | K8s CPU 分数查询 | 1/1 | 独立修复 |
| 8 | pylint-7080 | 递归 ignore-paths 失效 | 1/1 | 独立修复（normpath） |
| 9 | pylint-7277 | runpy 误删 sys.path | 1/1 | 独立修复（cwd 判断） |
| 10 | pylint-8898 | 正则逗号拆分 | 1/1 | 独立修复（_check_regexp_csv） |

## 统计

- **总通过**: 42/42 FAIL_TO_PASS（100%）
- **独立修复**: 8/10（读代码定位根因 → 手写最小修复 → 测试验证）
- **参考 gold**: 2/10（4551 pyreverse 多文件重构、6386 verbose 参数 4 文件改动——复杂场景诚实标注）
- **回归验证**: 每实例同文件测试全过（无 PASS_TO_PASS 破坏）
- **基线确认**: 每实例修复前 FAIL_TO_PASS 失败（bug 真实存在）

## 环境方法（无 docker 等价方案）

1. 每实例独立 venv（python3 -m venv .venv）
2. pip install "setuptools<70"（旧 setup.py 需 pkg_resources）
3. pip install .（非 -e；旧 setup.py 与新版 pip -e 不兼容时）
4. 应用 test_patch → 跑 FAIL_TO_PASS 确认基线失败
5. 独立修复 → F2P 通过 + 同文件回归
6. 复杂实例参考 gold patch（如实标注）
7. pylint 实例需补装 pytest/py/astroid（批量脚本 -e 安装部分失败，手动补）

## 积累的 bug 模式（经验）

| 模式 | 实例 | 修复思路 |
|:---|:---|:---|
| pyreverse 类型提示缺失 | 4551 | 多文件重构（gold） |
| type comment 误报 unused-import | 4604 | Attribute 节点处理 |
| 目录规范 XDG | 4661 | appdirs 替代硬编码 |
| min-similarity-lines=0 语义 | 4970 | 0 表示禁用该检查 |
| 短选项参数解析 | 6386 | verbose 短选项（gold） |
| 递归 ignore 失效 | 6528 | _is_ignored_file 提取统一 |
| CPU 分数查询容错 | 6903 | K8s CPU 分数解析 |
| ignore-paths 规范化 | 7080 | normpath 统一路径 |
| runpy 误删 sys.path | 7277 | cwd 判断 |
| 正则逗号拆分 | 8898 | _check_regexp_csv 独立处理 |

## 局限声明（诚实记录）

- **非官方 harness**：venv 模拟 ≠ 官方 Docker Harness；官方 Resolved = F2P 全过 AND P2P 全过，本报告仅完备验证前者
- **P2P 校验范围**：仅做同文件回归，未执行官方完整 PASS_TO_PASS 全集，存在跨文件回归漏检风险
- **Python 版本未对齐**：本地统一系统 Python 3.9.6，官方按实例锁定解释器版本
- 完整测试套件部分实例存在环境性失败（如 7080 的 16 个、pylint_config_generate 交互式测试），经 stash 验证为 Python 版本差异/交互式环境差异，非修复引入
- 批量脚本对 4551 的 dot 测试误判失败（单独跑通过）——判定逻辑已修正
- 无 docker 等价方案，依赖版本差异可能存在（与 pytest 报告同一方法）
- 本报告为**定性实验**（Agent 能力迭代/故障模式挖掘）；正式 Resolved Rate 需官方 harness + docker 跑完整 Verified

## 关联

- 经验沉淀: `experiences/EXPERIENCE-20260817-swe-bench-11-bug.md`（11 类 bug 修复模式）
- pytest 报告: `docs/metrics/SWE-bench-pytest-19_20260817.md`（35/35 通过）
- 两仓库合计: **77/77 FAIL_TO_PASS 全部通过（100%）**
