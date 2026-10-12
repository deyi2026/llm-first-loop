# SWE-bench Verified 官方 Harness 评测报告（sympy 27 实例）

> 日期: 2026-08-18 | 评测: swebench 4.1.0 官方 harness + OrbStack Docker（linux/amd64 模拟）
> 数据: SWE-bench Verified (princeton-nlp/SWE-bench_Verified) sympy 子集 27 实例
> 选样: patch 最小 15 个（277-505 字符）+ 中等 12 个（1007-1427 字符）
> **结果: 27/27 Resolved（100%）**

## 评测配置

- 数据集: /tmp/swe_local/sympy27/test（本地 Dataset，F2P/P2P 正则解析 numpy repr）
- predictions: data/swe_results/sympy_27_predictions.jsonl（15 + 12 合并）
- 运行: swebench harness，max_workers=3，报告 llm-first-loop.swe-sympy-27b.json
- 环境: OrbStack Docker + Rosetta（swebench 镜像 x86_64，pull 加 platform=linux/x86_64）

## 结果明细（27/27 全 resolved）

### 轻量子集 15 个（patch 277-505）
| 实例 | Bug | F2P |
|:---|:---|:---|
| sympy-22914 | PythonCodePrinter 缺 Min/Max | 1/1 |
| sympy-23950 | Contains.as_set 返回自身 | 1/1 |
| sympy-13757 | Poly 左乘不评估 | 1/1 |
| sympy-23534 | symbols 递归丢 cls | 1/1 |
| sympy-19040 | factor 丢 y-1 因子 | 1/1 |
| sympy-15875 | is_zero 复数判断 | 1/1 |
| sympy-14711 | 向量加 0 报错 | 1/1 |
| sympy-17139 | cos(x)**I 崩溃 | 2/2 |
| sympy-20428 | clear_denoms 零判断 | 1/1 |
| sympy-19637 | kernS 未赋值 | 1/1 |
| sympy-16886 | 摩斯码 "1" 错误 | 1/1 |
| sympy-15349 | 旋转矩阵公式 | 1/1 |
| sympy-13647 | col_insert 索引 | 1/1 |
| sympy-15809 | Min/Max 空参 | 2/2 |
| sympy-12096 | evalf 不递归 | 1/1 |

### 中等子集 12 个（patch 1007-1427）
| 实例 | Bug | F2P |
|:---|:---|:---|
| sympy-21379 | Mod PolynomialError | 1/1 |
| sympy-21930 | secondquant latex 花括号 | 6/6 |
| sympy-21847 | itermonomials 度数 | 1/1 |
| sympy-13031 | sparse 空矩阵堆叠 | ⚠️ 环境限制* |
| sympy-18698 | sqf_list 因子合并 | 1/1 |
| sympy-24661 | parse_expr 关系运算 | 1/1 |
| sympy-19783 | Dagger Identity 简化 | 2/2 |
| sympy-23413 | HNF 行处理 | 1/1 |
| sympy-12419 | Identity _entry | 1/1 |
| sympy-13798 | mul_symbol 自定义 | 1/1 |
| sympy-22456 | String Atom 继承 | 1/1 |
| sympy-17318 | sqrtdenest IndexError | 1/1 |

*13031 在 mac venv 有环境限制（SparseMatrix.zeros(0,n) 老代码不支持），官方容器中 F2P 通过

## 关键过程

1. **venv 近似验证**（前置）: 轻量 17/17 F2P + 中等 17/18（13031 环境限制），全部独立修复
2. **官方 harness 首跑 15/27**（假失败）: 数据格式坑——sympy F2P/P2P 是 numpy array repr（`['a' 'b' 'c']` 空格分隔），ast.literal_eval 静默解析成单个拼接串 → harness 找不到测试 → 假失败
3. **数据修复**（正则提取）: `re.findall(r"'([^']*)'", v)` → 27/27 全 resolved

## 结论

- **27/27 官方 Resolved（100%）**——docker 全量 F2P/P2P 严格判定
- 全部独立修复（无 gold 参考）
- 诚实声明: 选样为 patch ≤1427 字符的子集（偏简单），不代表 sympy 全 75 实例难度；更大 patch（8000+）未覆盖
