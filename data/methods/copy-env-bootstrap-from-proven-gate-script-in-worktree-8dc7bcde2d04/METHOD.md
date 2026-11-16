---
method_id: copy-env-bootstrap-from-proven-gate-script-in-worktree-8dc7bcde2d04
name: copy-env-bootstrap-from-proven-gate-script-in-worktree
description: 在隔离 git worktree 中要跑仓库自身测试/门禁时，不要猜 .venv/bin/python、也不要用系统解释器试错（老版本直接 ImportError）；任务上下文若已表明某入口脚本（如 CI gate）本机真实跑通过，其 bootstrap 就是现成环境答案：一次只读，逐字复制其解释器回退链（本树 .venv→主 worktree .venv）与 PYTHONPATH 前置本树 src 的锚定——后者避免 editable 安装锚定主区 src 而静默测错代码树。对禁改脚本只复制解析行，不执行其副作用。
aliases: worktree 里没有 .venv 怎么跑测试, 隔离工作树该用哪个 python, 从 CI 脚本头部抄解释器路径, 老系统 python 跑仓库测试直接 ImportError, 防止 editable 安装静默测到主区代码, 跑门前先读门禁脚本的环境段
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a43dc767-17c2-429a-82f3-1dd9d4aa5558:50:b639c85eaa6caf03fbc4
evidence_refs: learning:learn:6162b4fa22b3
created_at: 2026-11-15T21:37:47.598529+08:00
updated_at: 2026-11-15T21:37:47.598529+08:00
---
## Trigger
在隔离 worktree/检出中需要运行该仓库的测试/门禁/lint，且任务文本或上下文已给出一个本机已真实执行成功过的仓库入口脚本（有退出码/日志为证，如 ci_gate.sh）

## Discriminator
『入口脚本已在本机跑通』意味着其 bootstrap 已编码本机可用的解释器解析与路径锚定（worktree 常无自有 .venv，脚本内含主 worktree 回退与 PYTHONPATH=本树 src 的防测错树注释）；该事实把『环境是什么』从多次探测缩成一次只读

## Short path
- 冻结核验（HEAD/clean）与最小补丁照常落地
- 发起第一条测试/检查命令前，只读已跑通入口脚本的 bootstrap（约前 40 行）——未知量：本树权威解释器与路径锚定是什么
- 逐字复用其 PY 解析：本树 .venv 优先，缺失则回退 git worktree list 找主树 .venv
- 同样前置 PYTHONPATH=本树/src，防止 editable 安装静默测到主区旧代码树
- 用该环境跑定向 pytest/ruff/pyright；staged 口径守卫在 git add 后复跑

## Stop conditions
- 已取得与入口脚本一致的解释器路径与 PYTHONPATH 锚定，并按其完成定向验证
- 脚本 bootstrap 不存在、不可读或委托给沙箱内缺失的包装器 → provenance 边断裂，回退常规环境发现（pyproject/环境标记/which 探测）

## Verification
- 比对实际使用的解释器与脚本解析出的 PY 一致（本树 .venv 或主树回退）
- 确认 PYTHONPATH 指向本隔离树 src；守卫按 staged 口径在 git add 后复跑仍绿

## Counterexamples
- 仓库没有已知跑通过的入口脚本（无 gate/Makefile 或从未在本机执行）→ 无可复制的权威解析，走通用项目环境定位
- 入口脚本的环境装配含被禁副作用（regen 基线/跑全量/改门禁）→ 只读复制解析行，绝不执行脚本
- worktree 自带完整 .venv（每树自给装配）→ 惯例路径即可，多读一次只是廉价降级
- 任务明确禁止读取该脚本（罕见）→ 放弃此边直接探测
