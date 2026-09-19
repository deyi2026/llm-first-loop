---
title: editable 安装可掩盖子进程 import 绑定回归——行为测试需显式断言绑定契约
scenario: P0-A.1 service_control 修复（efb676cb1）：验证 detached worker 控制器身份绑定不被目标 code_root 劫持
root_cause: site-packages editable .pth 使子进程 import 解析顺序与 PYTHONPATH 意图不一致，行为级测试的隐式假设（目标树无包则 import 失败）在该 venv 不成立
solution: 行为测试之外，用 monkeypatch spy 直接断言 spawn 构造 env 时的 python_src 参数等于控制器根；git push 遇 http2 RPC 错误用 HTTP/1.1 重试并用 ls-remote 验证
evidence: "execute_command RED 运行（4/5 红但身份测试过）：evidence://v1/b65bddcb8bf2b959477cc2662abae5403a9c8277dc1e5b50e378e057f6bbef9d；.venv editable pth 探测：evidence://v1/800f62f56d9c2d83c6a07cb5c2dded932724b68552f290c260ac6a604fb62cc2；修复提交 efb676cb1（含 spy 断言与 57/57 绿）：evidence://v1/a3ad6cab612d971457a6074906db0cff1d6a3dbab4549d45524366ef9d56bcb3"
tags: [testing, python-path, editable-install, service-control, git-push]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-19T00:23:37.915434+08:00"
updated_at: "2026-09-19T00:23:37.915434+08:00"
---

在 llm-first-loop 共享 worktree 环境里验证“子进程 import 绑定”类行为（如 service-control detached worker 的 PYTHONPATH 控制器身份）时，行为级测试可能因 .venv 的 __editable__ 安装而假绿：`python -m pkg.mod` 子进程即使 PYTHONPATH 指向不含该包的目标树，也能经 site-packages .pth 回退到 editable 根（本例 .venv __editable__.llm_first_loop-0.6.8.pth → 镜像 src）。证据：RED 阶段 test_detached_worker_uses_current_control_code_for_pre_p0a_target 意外通过（其余 4 测试正常红）；.venv site-packages 存在 editable pth。修法：对被测绑定契约加显式断言（monkeypatch spy 捕获 spawn 传入的 python_src 并断言等于 _control_code_root()/"src"），使回归在任何 venv 状态下都红。附带事实：推送 GitHub 偶发 http2 framing layer error 时，`git -c http.version=HTTP/1.1 push` 重试成功；push 回执自相矛盾时以 `git ls-remote` 的 ref 实际状态为准。