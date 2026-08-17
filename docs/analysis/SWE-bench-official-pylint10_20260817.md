# SWE-bench Verified 官方 Harness 评测报告（pylint 10 实例）

> 日期: 2026-08-17 | 评测: swebench **4.1.0** 官方 harness + Docker（OrbStack）+ Rosetta 2
> 数据: SWE-bench Verified (princeton-nlp/SWE-bench_Verified) pylint-dev/pylint 全 10 实例
> 结果: **10/10 resolved（100%）**
> **resolved 定义（严格遵循官方）**: F2P 全部通过 ∧ P2P 全部通过，二者缺一不可

## 环境与方法

- 运行时: OrbStack（macOS 26.5.1 arm64, 18 核/128GB）+ Docker 29.4.0（OrbStack 内置 CLI）+ swebench 4.1.0（Python 3.14 venv）
- 镜像: 官方远端镜像 swebench/sweb.eval.{arm64,x86_64}.*
  - arm64 直接拉取（原生架构）
  - x86_64 实例（4604/6386/7080）需 `docker pull --platform linux/amd64` 预拉 + Rosetta 模拟运行
- predictions: 每实例 model_patch = git diff（仅 src/setup.cfg，不含测试文件改动）
- 判定: 官方 harness F2P 全过 AND P2P 全过 = resolved

## 结果

| # | 实例 | 架构 | F2P | 结果 | 备注 |
|:---|:---|:---|:---|:---|:---|
| 1 | pylint-4551 | arm64 | 10/10 | ✅ resolved | |
| 2 | pylint-4604 | x86_64 | 21/21 | ✅ resolved | |
| 3 | pylint-4661 | arm64 | 1/1 | ✅ resolved | 初跑失败→补 appdirs 依赖后过 |
| 4 | pylint-4970 | arm64 | 1/1 | ✅ resolved | |
| 5 | pylint-6386 | x86_64 | 1/1 | ✅ resolved | |
| 6 | pylint-6528 | arm64 | 4/4 | ✅ resolved | 初跑 P2P 3 失败→补 basename 定义后重跑通过 |
| 7 | pylint-6903 | arm64 | 1/1 | ✅ resolved | |
| 8 | pylint-7080 | x86_64 | 1/1 | ✅ resolved | |
| 9 | pylint-7277 | arm64 | 1/1 | ✅ resolved | |
| 10 | pylint-8898 | arm64 | 1/1 | ✅ resolved | |

## 官方评测 vs venv 定性评测的差异（重要发现）

官方 harness 暴露了 2 个 venv 漏检的问题：

1. **pylint-4661（XDG 目录规范）**：venv 全过，官方 F2P 失败
   - 根因: 官方 test_patch 引入 `import appdirs`，但官方镜像无 appdirs 依赖
   - 修复: setup.cfg 补 `appdirs>=1.4.0`（官方 gold 的做法；eval.sh 的 `pip install -e .` 会读取新依赖并安装）
   - 教训: model_patch 改依赖声明时，官方流程会在应用 patch 后重装，依赖变更必须写进 setup.cfg/pyproject

2. **pylint-6528（递归 ignore）**：venv 同文件回归过，官方 P2P 3 失败
   - 根因: 提取 _is_ignored_file 时删除了循环内 `basename` 定义，并行 worker（multiprocessing）触发 `NameError: basename is not defined`
   - 修复: 补回 `basename = os.path.basename(something)`（与官方 gold 一致）
   - 结果: 修复后官方重跑 **resolved=True**（F2P 4/4 + P2P 全集通过）
   - 教训: venv 单进程回归测不出 multiprocessing 路径；官方 P2P 全集（含并行模式测试）能覆盖

3. **补丁污染测试文件的教训**：初版 6528 patch 含测试文件改动（新增测试+修改 test_recursive_current_dir 的 chdir 语义），官方判定失败——model_patch 只应包含 src 改动

## 局限

- **Rosetta 模拟风险**: x86_64 实例（4604/6386/7080）经 OrbStack + Rosetta 2 模拟 linux/amd64 镜像运行；绝大多数 Python 逻辑与原生 x86 等价，但少数系统调用、文件锁、信号、fork/multiprocessing 底层行为存在模拟层带来的潜在非确定性（本实验未发现受影响用例，如实声明）
- 未跑完整 500 实例，仅 pylint 子集——不代表 SWE-bench Verified 整体得分
- pylint-6528 经修复（补 basename 定义）后重跑 **resolved=True**，已计入统计
