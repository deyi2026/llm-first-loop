---
title: proc_version 单测失败常因环境变量 LFL_WORKSPACE_ROOT 指向干净 worktree，非代码回归
scenario: "tests/unit/test_proc_version.py::test_workspace_dirty_clean_and_dirty 失败（自建 tmp 仓库 + untracked 文件后断言 dirty=True 得 False）。根因：当前运行环境导出 LFL_WORKSPACE_ROOT 指向干净 worktree，proc_version._git_command 优先 -C 该路径，覆盖测试的 chdir。"
root_cause: ""
solution: 跑测试基线用 env -u LFL_WORKSPACE_ROOT .venv/bin/python -m pytest ...（exit 0 全绿）。判定与代码改动无关时先复现环境依赖：echo $LFL_WORKSPACE_ROOT 并用 env -u 复跑单测确认。
evidence: "evidence://v1/ea8323d36f0a9e4936de982f853637421d1c565a78bd1ebdc7c5646eae25d953 evidence://v1/eaa93a66115aa4888eb49838d990a622ccc2197c56ab577baf34b8b5056d7"
tags: [workspace, tests, environment, verified]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-16T16:16:29.797258+08:00"
updated_at: "2026-09-16T16:16:29.797258+08:00"
---