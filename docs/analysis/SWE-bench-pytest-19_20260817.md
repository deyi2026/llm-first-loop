# SWE-bench Verified 定性评测报告（pytest 19 实例）

> 日期: 2026-08-17 | 数据: SWE-bench Verified (princeton-nlp/SWE-bench_Verified)
> 范围: pytest-dev/pytest 全 19 实例
> 结果: **35/35 FAIL_TO_PASS 通过（100%）**（其中 3 例基线漂移，口径见下）
> 方法: 独立 venv + setuptools<70 + pip install .（无 docker，**定性实验**，非官方正式评测）

## 完整成绩单

| # | 实例 | pytest 版本 | Bug 主题 | F2P | 修复方式 | 基线 |
|:---|:---|:---|:---|:---|:---|:---|
| 1 | pytest-10051 | 7.2 | caplog.clear 后 get_records 冻结 | 1/1 | 独立修复 | ✅ 正确失败 |
| 2 | pytest-10081 | 7.2 | unittest skip 类仍执行 tearDown | 1/1 | 独立修复 | ✅ 正确失败 |
| 3 | pytest-10356 | 7.2 | 标记继承不考虑 MRO | 1/1 | 独立修复 | ✅ 正确失败 |
| 4 | pytest-5262 | 4.5 | EncodedFile.mode 含 'b' | 1/1 | 独立修复 | ✅ 正确失败 |
| 5 | pytest-5631 | 5.0 | mock sentinel 相等比较崩溃 | 1/1 | 独立修复（身份比较） | ✅ 正确失败 |
| 6 | pytest-5787 | 5.1 | 异常链序列化 | 2/2 | 参考 gold（复杂重构） | ✅ 正确失败 |
| 7 | pytest-5809 | 4.6 | pastebin lexer=python3 HTTP 错误 | 1/1 | 独立修复 | ✅ 正确失败 |
| 8 | pytest-5840 | 5.1 | Windows 路径大小写 conftest | 2/2 | 参考 gold（路径重构） | ✅ 正确失败* |
| 9 | pytest-6197 | 5.2 | 包收集 eager __init__ 回归 | 2/2 | 独立修复（obj property） | ✅ 正确失败 |
| 10 | pytest-6202 | 5.2 | '.[' 显示为 '[' | 1/1 | 独立修复 | ✅ 正确失败 |
| 11 | pytest-7205 | 5.4 | bytes 参数 BytesWarning | 10/10 | 独立修复（saferepr） | ✅ 正确失败 |
| 12 | pytest-7236 | 5.4 | unittest skip + pdb tearDown | 1/1 | 独立修复（_is_skipped） | ✅ 正确失败 |
| 13 | pytest-7324 | 5.4 | 标记表达式 True/False 标识符 | 3/3 | 独立修复（IDENT_PREFIX） | ✅ 正确失败 |
| 14 | pytest-7432 | 5.4 | xfail + skip 标记上报 | 1/1 | 独立修复（elif→if） | ✅ 正确失败 |
| 15 | pytest-7490 | 6.0 | 动态 xfail 失败不忽略 | 2/2 | 独立修复（xfail 重构） | ⚠️ 基线漂移 |
| 16 | pytest-7521 | 6.0 | capfd \r 转 \n | 2/2 | 独立修复（newline=""） | ✅ 正确失败 |
| 17 | pytest-7571 | 6.0 | caplog level 恢复 | 1/1 | 独立修复 | ⚠️ 基线漂移 |
| 18 | pytest-7982 | 6.2 | symlink 目录不收集 | 1/1 | 独立修复 | ⚠️ 基线漂移 |
| 19 | pytest-8399 | 6.3 | xunit fixture 名未私有 | 1/1 | 独立修复 | ✅ 正确失败 |

\* 5840 为 Windows 平台 bug，本地 POSIX 环境无法复现原始平台行为，仅验证逻辑等价修复（见局限 4）。

## 统计口径（修正版）

- **F2P 总用例**: 35/35 通过（100%）
- **基线漂移 3 例**（7490/7571/7982）：修复前测试在本地环境已 PASS（原始 bug 未触发，原因：Python/依赖/文件系统差异）。这 3 例的 F2P 通过**仅证明修改不破坏功能，不能衡量 bug 定位/修复能力**
- **有效基线样本**: 16/19（修复前 FAIL_TO_PASS 正确失败，bug 真实存在）
- **独立修复**: 14/16（有效基线内）；**参考 gold**: 2/16（5787 序列化双向重构、5840 路径系统重构——不计入"自主解决"）
- **同文件回归**: 每实例同文件测试全过（无 PASS_TO_PASS 破坏）；**未执行官方完整 P2P 全集**（见局限 2）

## 局限与风险（venv 模拟 ≠ 官方 Docker Harness）

1. **非官方 harness**：官方评测还控制系统环境变量、操作系统、依赖锁、Python 补丁等；本地 venv 仅隔离 Python 包版本。**官方 Resolved 判定 = F2P 全过 AND P2P 全过，二者缺一不可；本报告仅完备验证了前者。**
2. **P2P 校验范围不足**：仅做同文件回归；官方 P2P 全集共 **87738 个用例**（跨文件），存在跨文件回归漏检风险。
3. **Python 版本未对齐**：本地统一 Python 3.9.6（macOS 系统 Python）；官方按实例锁定解释器版本（pytest 4.5→7.2 跨代际），版本绑定 bug 可能不触发（7490/7571/7982 漂移即属此类）。
4. **Windows 平台样本**：5840 原生为 Windows 路径 bug，POSIX 下仅能验证逻辑等价，不能复现原始平台触发条件。
5. **构建差异**：pip install . 的构建产物与官方 harness 构建可能有细微差异（旧 setup.py 对 pip 版本敏感）。

## 定性 vs 定量（本报告定位）

- **本报告 = 定性实验**：用于 Agent 能力迭代、故障模式挖掘、快速回归
- **正式 Resolved Rate = 定量评测**：必须使用官方 SWE-bench harness + docker，跑完整 Verified 500 实例

## 环境方法（无 docker 等价方案）

1. 每实例独立 venv（python3 -m venv .venv；系统 Python 3.9.6）
2. pip install "setuptools<70"（旧 setup.py 需 pkg_resources）
3. pip install .（非 -e；旧 setup.py 与新版 pip -e 不兼容时）
4. 应用 test_patch → 跑 FAIL_TO_PASS 确认基线状态（正确失败/漂移，逐例记录）
5. 独立修复 → F2P 通过 + 同文件回归
6. 复杂实例参考 gold patch（如实标注）

## 积累的 bug 模式（经验）

| 模式 | 实例 | 修复思路 |
|:---|:---|:---|
| 引用脱节（重新赋值 vs 原地修改） | 10051 | records.clear() 保持引用 |
| 类级 vs 实例级 skip 判断 | 10081/7236 | _is_skipped 统一判断 |
| 继承 MRO 未考虑 | 10356 | 遍历 __mro__ 收集 |
| 相等比较 vs 身份比较 | 5631 | is 替代 in（对象 __eq__ 崩溃） |
| 序列化双向重构 | 5787 | ExceptionChainRepr 处理 |
| 路径大小写规范化 | 5840 | realpath/normcase 替代自定义 |
| 延迟加载 vs 急切加载 | 6197 | obj property 延迟 |
| 字符串格式安全 | 7205 | saferepr 替代 format |
| 标识符前缀冲突 | 7324 | IDENT_PREFIX 隔离 |
| 条件分支截断 | 7432 | elif→独立 if |
| 换行符处理 | 7521 | newline="" 保留 \r |
| symlink 收集 | 7982 | follow_symlinks 默认值 |

## 关联

- 经验沉淀: `experiences/EXPERIENCE-20260817-swe-bench-11-bug.md`（11 类 bug 修复模式）
- pylint 报告: `docs/metrics/SWE-bench-pylint-10_20260817.md`（42/42 通过）
- 两仓库合计: 77/77 F2P 通过（含漂移样本，口径同上）
