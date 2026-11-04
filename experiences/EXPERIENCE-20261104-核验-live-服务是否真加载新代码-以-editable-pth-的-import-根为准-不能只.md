---
title: 核验 live 服务是否真加载新代码：以 editable .pth 的 import 根为准，不能只看 deployment code_root / status.git_head
scenario: "managed service 部署（service_control publish+restart）后，需要确认运行中的进程确实加载了新提交的代码。status 回执给出 deployment.code_root=.releases/<sha> 与 services.<name>.git_head=<sha>、matches_desired_generation=true、guard_code_drift=current，容易据此直接宣称\"新代码已生效\"。"
root_cause: "服务以 `.venv/bin/python -m llm_loop.runtime.launch <svc>` 启动，而 `llm_loop` 的实际 import 根由 .venv 里 editable install 的 .pth 决定（本例 __editable__.llm_first_loop-0.6.37.pth 内容为 runtime_root/src），不是 deployment.code_root 指向的 .releases/<sha>/src。两者可以指向不同目录：若 release 与 runtime_root 的 src 分叉，status 仍会报 release 的 head 与 desired 匹配，而进程跑的是 runtime_root/src 的旧/脏代码。status 的 git_head 与 matches_desired_generation 都只证明\"manifest 记录态\"，不证明\"进程导入态\"。"
solution: "三步核验：(1) 读 .venv/lib/python*/site-packages/__editable__*.pth 得到真实 import 根；(2) 在该根执行 git rev-parse HEAD，与 status 的 desired head（及 deployment.git_head）对比，相等才继续；(3) 在该根执行 git status --porcelain -- src/（须为空）与 git diff --stat HEAD -- <关键文件>（须为空），并用 git show HEAD:<file> | grep <新符号> 确认符号已进提交而非仅在工作树。三者全过才可声称 live 加载了新代码。附带：lsof -a -p <pid> -d cwd 只能看 cwd，看不到 import 根，不足以作判据；release 目录内是否出现 __pycache__ 也不可靠（可能来自离线执行）。"
evidence: ".pth 内容实测为 <workspace>/src；runtime_root git HEAD=94323293323d8b13d048744ed5de475518b83db1 与 deployment.git_head 相同；git status --porcelain -- src/ docs/ 为空；git diff --stat HEAD -- src/llm_loop/desktop/operate.py src/llm_loop/tools/builtin/desktop_operate.py 为空；git show HEAD:src/.../desktop_operate.py | grep -c stale_breaks = 4；四个服务 pid 69143/69588/69827/70305 命令行均为 .venv/bin/python -m llm_loop.runtime.launch，lsof cwd=运行时无需 release 路径。"
tags: [deployment, verification, editable-install, code-root, service_control]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-04T15:05:29.137155+08:00"
updated_at: "2026-11-04T15:05:29.137155+08:00"
supersedes: [EXPERIENCE-20261101-代码时效判断-对照基准要按部署形态推导-不能取-manifest-环境里的-workspace-ro]
---