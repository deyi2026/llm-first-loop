---
method_id: inert-diff-gate-rerun-failure-is-environment-22e7ade258b1
name: inert-diff-gate-rerun-failure-is-environment
description: 重跑一个已被声明通过的验证 gate（pytest/lint/build）时，若失败发生在收集/导入阶段，且被审 diff 已核实为零代码路径触碰（仅 docs/回执类文件），先把失败归类为解释器/环境不匹配而非树回归：读缺失模块名，一次性定位项目固定解释器（repo 根 .venv、uv/pyproject 在场则 uv run）重跑并逐项比对原通过数字。不做全盘解释器枚举、不调查树。与 method-root-cause 互补：那是真回归的假设-实验流程，本方法是惰性 diff 场景下的快速分类短路，可省 2-3 次诊断调用并避免把环境问题误记为审查 P 发现。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:4d4ac6a0-34d8-458a-9e7d-7c6f99d0c65a:0:16309e4a59e75b8a06ab
evidence_refs: learning:learn:c5a17ead6327
created_at: 2026-10-17T07:00:17.672333+08:00
updated_at: 2026-10-17T07:00:17.672333+08:00
---
## Trigger
在全新 shell/系统默认解释器下重跑一个此前被声明为通过（有回执或任务陈述数字）的验证命令，结果在 collection/import 阶段报 ERROR（exit 2 类）；同时被审分支的改动文件清单已核实全为非代码文件（docs/receipts 等），不可能影响被收集的测试模块。

## Discriminator
失败时刻已同时持有三个事实即可定案：(1) 错误类别是 collection-time ERROR（如 ModuleNotFoundError），不是 assertion FAILURE；(2) 已验证的 diff 文件清单与失败测试文件零代码交叉（docs-only ⇒ 分支不可能造成该失败）；(3) 同一树上存在近期通过声明（如 47 passed/exit0）。三者并存时，唯一自洽解释是当前解释器缺依赖/环境不匹配。

## Short path
- 读失败输出首行错误类与缺失模块名，确认是 import/collection ERROR 而非断言失败
- 对照此前已核实的 diff 文件清单，判断被审改动是否可能触及失败测试（docs-only ⇒ 不可能）
- 一次性探测项目固定解释器：repo 根 .venv/bin/python 或 uv.lock/pyproject 在场时用 uv run；不枚举系统其它 venv
- 用固定解释器原样重跑同一命令，与原声明数字逐项比对（如 47 passed / exit0）
- 一致即判环境问题并关闭，将『系统解释器缺依赖』记为环境备注而非审查发现

## Stop conditions
- 固定解释器下重跑结果与原通过声明逐项一致 → 判定为环境不匹配，停止调查
- 固定解释器下仍失败，或失败为断言/逻辑类、或失败测试确与被改文件相关 → 本方法失效，转入正常回归调查流程
- 已找到并验证一个与声明一致的运行环境后，不再尝试其它解释器或重复诊断运行

## Verification
- 固定解释器重跑输出与任务陈述/旧回执中的通过数字完全一致（测试数、exit code）
- 原 collection 错误（缺失模块导入）在固定解释器下消失
- diff 清单复核确认与失败测试文件零代码路径交叉

## Counterexamples
- 失败是断言失败且测试覆盖被审分支改动的文件 → 真回归，换解释器只会掩盖问题
- 该树从未有过通过记录（无 prior passing claim 可作判别事实）→ 不能用本分类短路
- collection 错误源自被审分支新增的 conftest.py/依赖声明 → 失败与 diff 因果相关，非纯环境
- 任务本身就是环境迁移/修复（venv 是被审对象）→ 环境失败正是目标事实，须完整调查
