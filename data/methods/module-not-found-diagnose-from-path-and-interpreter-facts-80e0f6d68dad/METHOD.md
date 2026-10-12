---
method_id: module-not-found-diagnose-from-path-and-interpreter-facts-80e0f6d68dad
name: module-not-found-diagnose-from-path-and-interpreter-facts
description: 用户贴出 python -m X 报 ModuleNotFoundError 时，判别事实已在报错行与一次包定位里：包存在于非 cwd 前缀（如 src/X/），且报错解释器不是项目 venv。据此直接给出 PYTHONPATH/venv 修复，并用一次真实 import 验证。反模式：为诊断导入失败去通读目标模块源码（本集读了 1286 行并多段重读）、stat 已被搜索结果否证的根级路径、在导入问题闭环前展开下游子命令机制与部署状态检查——模块内容不影响 import 解析，路径布局与解释器选择才影响。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5adf278f-405b-44db-95e5-3d3b94e1b8d9:869:8a2bc6d1313097e9eee3
evidence_refs: learning:learn:726c00a5370d
created_at: 2026-09-19T12:18:55.626719+00:00
updated_at: 2026-09-19T12:18:55.626719+00:00
---
## Trigger
用户报告 `python -m <pkg>.<mod> ...` 或 import 报 `ModuleNotFoundError: No module named '<pkg>'`，且贴出的命令/traceback 暴露了解释器路径与 shell cwd（prompt 所在目录）。

## Discriminator
最早一次包定位（search/ls）命中 src/<pkg>/...（包存在但不在 cwd 下），同时报错首行解释器为系统/homebrew python 而非 .venv/bin/python——这两条在读任何模块源码之前就把候选缩到『src-layout + 未走 venv/PYTHONPATH』这一种解释。

## Short path
- 从报错提取未知量『包 X 是否存在、在哪个前缀』，做一次 search/ls 定位（如命中 src/X/）。
- 把包前缀与用户 prompt 的 cwd 对照：包在 cwd 外前缀即说明 python -m 的 sys.path 不含它，根因判定为布局/解释器问题而非代码问题。
- 核对解释器：检查项目 .venv 是否存在、其 editable pth 是否指向该 src；确认用户所用解释器未安装该包。
- 最小验证两种修复：`PYTHONPATH=<repo>/src <python> -c 'import X'` 与 `.venv/bin/python -c 'import X'` 各跑一次。
- 输出根因与修复命令后停止；下游子命令前置条件（部署状态等）若要顺带核对，作为导入闭环后的增量单独进行。

## Stop conditions
- 任一推荐调用方式下 `import X` 实际 rc=0，导入问题闭环，不再读模块源码。
- 包定位返回空或包名拼写不同 -> 切换到『安装/改名』分支，布局诊断终止。
- traceback 显示失败发生在模块内部某行的 import（依赖缺失）-> 本方法不适用，转读模块依赖清单。

## Verification
- 验证必须是真实 import（python -c 'import X'）跑在与推荐给用户相同的解释器/PYTHONPATH 组合下，而非阅读模块源码。
- 确认推荐解释器满足包声明（如 pyproject 的 requires-python）。

## Counterexamples
- 报错是模块内部依赖缺失（ImportError 指向模块内某行）而非顶层解析失败——此时读模块源码/依赖清单才相关。
- 包就在仓库根且 venv 正确却仍失败——属于解释器版本或 site-packages 问题，布局判别不适用。
- X 在磁盘上不存在（拼错、子模块未拉取）——首次定位为空即转入不同分支。
