---
method_id: locate-project-env-before-symptom-workarounds-f7dd29f1718b
name: locate-project-env-before-symptom-workarounds
description: 在项目仓库内，当用环境默认解释器跑命令出现依赖级失败（ModuleNotFoundError / PEP 668 externally-managed）时，先把『项目权威运行环境是什么』当作唯一先决未知量一次性解决（一次 ls 定位 .venv 等项目解释器），再用它重跑；而不是枚举症状级 workaround（--ignore 目录、grep 项目配置、向默认解释器 pip install）。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: session:d3e8d89f-0695-48ca-8061-5ba53bfe928c
created_at: 2026-09-09T17:09:46.364218+00:00
updated_at: 2026-09-09T17:09:46.364218+00:00
---
name: locate-project-env-before-symptom-workarounds
status: candidate
trigger:
  - 在项目仓库内用环境默认解释器（如系统 python3）执行 pytest/脚本，出现依赖级失败：ModuleNotFoundError 或 PEP 668 externally-managed 提示
  - 正要为『让默认环境跑通』而做 workaround：给 pytest 加 --ignore、grep Makefile/pyproject/pytest.ini 找排除配置、pip install 到默认解释器
discriminator:
  - 失败签名是『环境不匹配』而非代码断言失败：import 错误 / externally-managed 报错文本本身就是证据——默认解释器不是项目开发环境
  - 仓库测试/源码确实 import 这些第三方依赖，且（本会话或仓库历史）该测试集曾整体跑通 ⇒ 一个已配好的解释器必然存在于本地某处
short_path:
  - 第一步只解决一个未知量：项目权威解释器在哪——一条命令探测 .venv/venv/.venv/bin/python（或看 CI/脚本如何调用 pytest）
  - 用该解释器重跑受影响测试，读真实失败，区分实现 bug 与测试契约过时
  - 按失败证据做最小修复（改实现或适配测试），重跑至绿
  - 用同一解释器后台跑全量并定时回收结果，不在等待期做无关枚举
branch_on_evidence:
  - observation: 探测到项目 venv
    next: 全程改用该解释器，撤销所有默认环境 workaround（ignore/安装/配置考古）
  - observation: 仓库确无 venv 且无跑通先例
    next: 此时才按项目规范配环境（venv/pipx/--user），而不是先装进系统解释器
  - observation: 失败是 AssertionError 而非 import/环境错误
    next: 转向代码与契约调试，不要怀疑解释器
stop_conditions:
  - 已确认权威解释器，且目标测试集（含原先因缺依赖而失败的模块）在该解释器下可收集并通过，无需 ignore 或安装
verification:
  - 换用项目解释器后，原『环境性失败』的测试不再需要任何排除或安装即通过
anti_patterns:
  - 见缺依赖就 pip install 到环境默认解释器（PEP 668 下必败，且两次重试同一动作）
  - 用 --ignore/目录排除把一个环境问题切分成多个小 workaround（ignore → grep 错误 → grep 配置 → install）
counterexamples:
  - 容器/CI 中系统解释器即项目预配环境：ModuleNotFoundError 说明依赖真缺失，安装才是正确下一步
  - 失败与解释器无关（纯断言/逻辑失败）：应先调试代码，不应先查环境
  - 一次性 stdlib 用途（如 ast 语法检查）：用系统解释器无妨，不必先找 venv
programizable:
  - 执行前置检查：cwd 存在 .venv/bin/python 且命令含 python/pip/pytest → 提示替换为 venv 解释器；检测 PEP 668/ModuleNotFoundError 错误签名 → 路由到『定位项目环境』分支而非 install
model_owned:
  - 判断失败属于环境不匹配还是真实缺陷；判断权威环境候选（venv/uv/poetry/容器）
why_shorter: 把『多个症状级 workaround（ignore、grep 配置、install×2）』收敛为对一个先决未知量的单次探测，之后所有命令天然用对解释器。
