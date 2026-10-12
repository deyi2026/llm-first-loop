---
title: SWE-bench 官方 Harness 评测：model_patch 边界与依赖/作用域三坑
scenario: 用官方 SWE-bench harness（swebench + Docker/OrbStack）评测 Agent 修复结果时，venv 本地全过的 patch 在官方评测中失败的三种典型根因与规避方法。
root_cause: venv 本地验证与官方 harness 存在三个系统性 gap：测试文件边界、依赖声明、多进程作用域，均不在单进程同文件回归的覆盖范围内。
solution: 1) model_patch 边界：官方 test_patch 由数据集注入，model_patch 只允许改 src（业务代码），严禁含 tests/ 目录改动——一旦夹带直接判定失败。落地：Agent 导出 patch 前强制 `git checkout tests/` + 后处理过滤 tests/ 路径 diff。2) 依赖声明：代码新增 import 必须同步改 setup.cfg/pyproject 的依赖声明（官方流程 apply model_patch → pip install -e . → 跑测试，依赖缺失直接 F2P 失败）；本地手动 pip install 会掩盖此问题。3) 多进程作用域：重构提取函数时被移出作用域的局部变量，单进程测试不触发，官方 P2P 全集（含 multiprocessing 并行测试）才爆 NameError——提取函数时检查被删变量是否在其他调用路径被引用。4) 评测脚本注意：swebench run_instance 对镜像缺失返回 completed=False（不抛异常），架构降级逻辑须判断 completed 而非捕获异常；x86_64 镜像需 docker pull --platform linux/amd64 预拉（SDK pull 不带 platform 按 host 拉会 404）。
evidence: 2026-08-17 SWE-bench Verified 官方评测：pylint-4661 依赖缺失（补 setup.cfg appdirs 后 resolved）、pylint-6528 多进程 NameError（补 basename 后重跑）、6528 初版 patch 夹带测试改动被拒；pytest 19 实例 x86_64 镜像 pull 方式修正后 9/19 补测。
tags: [SWE-bench, 官方harness, model_patch, 依赖声明, 多进程作用域, Rosetta]
source: {}
status: active
created_at: "2026-08-17T09:56:17.427732+08:00"
updated_at: "2026-08-17T09:56:17.427732+08:00"
---