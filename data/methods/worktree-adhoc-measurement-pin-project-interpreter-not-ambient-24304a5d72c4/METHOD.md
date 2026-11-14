---
method_id: worktree-adhoc-measurement-pin-project-interpreter-not-ambient-24304a5d72c4
name: worktree-adhoc-measurement-pin-project-interpreter-not-ambient
description: git worktree 内用环境默认解释器对仓库自身源码做临时测量（AST 行数、compile、复跑测试）出现 parse 期 SyntaxError 或 cwd 相对 .venv 缺失时：第一未知量是『项目权威解释器在哪』——worktree 不携带未跟踪 env，要到主 checkout 根（git worktree list）取；且错误仅在源码的现代语法（如 PEP 701 嵌套引号 f-string）上发生时，属于测量工具语言级别不足，应在报告中归类为审查环境限制而非被审源码缺陷。是『先定位项目环境再对症』类方法在 worktree+解释器语言级别不匹配场景的扩展，非同义重复。
aliases: worktree 里跑 python 报语法错误, venv 不在 worktree 里去哪找, AST 数函数行数该用哪个解释器, PEP 701 嵌套引号 python 3.9 解析失败, 审查时源码 SyntaxError 算不算缺陷
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d324e1a9-2f27-4e42-aaf3-680d2917311c:0:bb8265e6515099d25375
evidence_refs: learning:learn:ff1067d97cff
created_at: 2026-11-14T09:45:29.649478+08:00
updated_at: 2026-11-14T09:45:29.649478+08:00
---
## Trigger
在 git worktree 中对仓库源码做临时静态/语义测量或复跑项目测试时，环境默认 python 在解析阶段报 SyntaxError（如 PEP 701 嵌套引号 f-string），或按 cwd 相对路径找不到 .venv/bin/python

## Discriminator
traceback 的 stdlib 路径直接暴露当前解释器版本（如 …/Python3.framework/Versions/3.9/ast.py），而报错行使用的是项目源码的现代语法 ⇒ 测量工具语言级别不足而非被审源码缺陷；同时 worktree 不含未跟踪的 venv，项目解释器在主 checkout 根（git worktree list 可得，本例为 python3.13）

## Short path
- 测量前先解析唯一先决未知量：项目被门禁/CI 运行在哪个解释器下（pyproject requires-python、CI 配置、主 checkout 的 .venv）
- worktree 内不猜 cwd 相对 .venv；用 git worktree list 定位主 checkout 根，取其环境解释器
- 在报告中把 parse 失败明确归类为审查环境限制，不得计为被审对象的源码缺陷
- 用项目解释器重跑同一测量脚本，测得数值与守卫基线/父侧报告交叉对账后再出数

## Stop conditions
- 项目解释器完成全部目标文件解析且数值可与基线对账 → 停止环境排查，回到审查本体
- 确认源码在项目自身声明的最低语言版本下也无法解析 → 转为真实缺陷上报，不再换解释器

## Verification
- 定位到的解释器 --version 与 pyproject/CI 声明的 Python 版本一致
- 同一 AST/compile 测量脚本在该解释器下解析全部目标文件无 SyntaxError
- 独立测得的函数行数/结构数值与守卫登记值或父侧报告可交叉核对

## Counterexamples
- 项目声明兼容旧解释器且 CI 就用旧版本跑 → SyntaxError 是真实兼容性缺陷，必须上报而非换解释器掩盖
- 非 worktree 的普通 checkout（cwd 即项目根）→ 相对 .venv 通常有效，直接使用即可，无需先做 worktree 定位
- 主 checkout 也没有可复用 env 的外部只读场景 → 按任务书降级为 INCOMPLETE/局限披露，不应拉长环境试错
