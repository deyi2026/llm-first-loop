---
title: "工作区 PYTHONPATH 指向 .releases 发布快照会导致\"修复无效\"的假阴性"
scenario: "在 llm-first-loop 仓库改完 src/ 后跑 pytest/import 做验证，结果显示新逻辑\"完全没生效\"，一度以为自己改错了文件或编辑失败。"
root_cause: "该工作区 shell 预设 PYTHONPATH 指向 .releases/<HEAD>/ 不可变发布快照，且其优先级高于 .venv/lib/python*/site-packages/ 里指向 src 的 .pth。不覆盖时所有 python import 与 pytest 导入的都是发布快照，旧代码无本次改动，表现为\"改了什么都没效果\"。"
solution: 改 src/ 后必须显式 PYTHONPATH=<repo>/src 绑定工作树，不能依赖默认环境。判定方法：先打印 llm_loop.feedback.validator.__file__ 和 inspect.getsource(被改函数) 确认导���版本，而不是直接相信失败结果。
evidence: 实测 __file__ 指向 /Users/yyj/Project/llm-first-loop-mirror/.releases/99069aae6/src/llm_loop/feedback/validator.py；加 PYTHONPATH=<repo>/src 后同一断言行为改变，测试 116 passed。
tags: [pythonpath, releases, 测试环境, 假阴性, module-resolution]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-13T22:01:17.714116+08:00"
updated_at: "2026-10-13T22:01:17.714116+08:00"
supersedes: [EXPERIENCE-20261012-公开分发快照的终检必须在导出后的树上执行-不能用原工作区测试结果替代, EXPERIENCE-20260821-pythonpath-src]
---