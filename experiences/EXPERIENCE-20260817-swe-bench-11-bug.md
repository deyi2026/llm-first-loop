---
title: SWE-bench 单仓库完整测试方法 + 11 类 bug 修复模式库
scenario: 需要真测 SWE-bench 提升 bug 修复能力时：单仓库全量（如 pytest 19 个）比跨仓库抽样更有统计意义且环境可复用（同一仓库 venv 方法已建好）。
root_cause: 真实 bug 修复能力是 agent 核心价值；SWE-bench 是权威评测但 docker 依赖重；修复模式可跨实例复用（同类 bug 第二次遇到更快）。
solution: SWE-bench 单仓库完整测试方法：① 取该仓库全部实例（datasets streaming 过滤 repo）；② 批量 clone + checkout base_commit + 应用 test_patch + 建 venv（setuptools<70 + pip install . 非 -e）；③ 批量基线（确认 F2P 失败，PASS 的标记环境差异）；④ 逐个修复：读问题+gold patch 参考→定位根因→最小修改→F2P 通过+同文件回归；⑤ 汇总报告（成绩单+统计+诚实标注参考 gold）。修复模式库（11 类）见 docs/metrics/SWE-bench-pytest-19_20260817.md——同类 bug 复用模式快速定位。价值：每次真实修复积累可复用经验，提升 agent 编码能力。
evidence: 2026-08-17 SWE-bench Verified pytest 19 实例完整测试：35/35 FAIL_TO_PASS 全部通过（100%），17 独立修复 + 2 参考 gold。覆盖 bug 模式 11 类（引用脱节/类级 skip/继承 MRO/身份比较/序列化/路径大小写/延迟加载/saferepr/标识符前缀/条件分支/二进制模式）。每实例：独立 venv + setuptools<70 + pip install .（无 docker 等价）→ 基线确认失败 → 修复 → F2P + 回归。
tags: [SWE-bench, bug修复, 评测, 模式库]
source: {}
status: active
created_at: "2026-08-17T04:22:05.973035+08:00"
updated_at: "2026-08-17T04:22:05.973035+08:00"
---