---
title: service_control 重启预检哈希 webui/dist，不是 src/llm_loop/web/static
scenario: LFL mirror 常驻服务换新 code_root worktree 后经 service_control(action=restart) 上线，第一次返回 rc=1 detail=webui_artifact_preflight_failed；当时已把旧 worktree 的 src/llm_loop/web/static 复制到新 worktree 但仍被拒
root_cause: dist 复用目标歧义：运行静态目录与部署预检产物目录是两条不同路径，且预检失败 detail 不含期望路径信息
solution: 复用目标是 code_root/webui/dist（63 文件，copytree 前后两侧树哈希相等），不是 src/llm_loop/web/static；随后用旧线代码跑 _tree_sha256 验证新 worktree/webui/dist == 部署记录 webui_artifact_sha256（143498c3...）再重试 restart，rc=0，gen5 上线
evidence: "data/runtime/service-control-actions/svc-c8b879de515841d99f2b0f716e8e980f.json (status=failed, detail=webui_artifact_preflight_failed); data/runtime/service-control-actions/svc-18d63b5af6bf461c8db8e5ca322d817e.json (status=succeeded, restart_mirror rc=0); data/restart-receipt.json (ts=2026-09-17T20:34:41+08:00, web_pid=99738, feishu_pid=99852, git_head=43a772ea); 官方 _tree_sha256(new/webui/dist)=143498c3...==记录值"
tags: [service-control, restart, deployment, worktree, webui-dist, preflight]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-17T20:36:39.408463+08:00"
updated_at: "2026-09-17T20:36:39.408463+08:00"
---

service_control restart 拒绝时 detail 仅 "webui_artifact_preflight_failed"，根因是预检哈希对象为 code_root/webui/dist（src/llm_loop/runtime/service_control.py 的 _tree_sha256(code / "webui" / "dist")），与运行服务的静态目录 src/llm_loop/web/static 是两处。fresh git worktree 只有源码，webui/dist 为构建产物，必须从旧部署 worktree 逐字节复用（copytree + 两侧树哈希相等断言）。验证哈希要用官方算法：PYTHONPATH=<旧线>/src python -c "from llm_loop.runtime.service_control import _tree_sha256; ..."，自造哈希算法与记录值不等不代表复用失败。附带发现：factory.py:1486 注释"默认关闭（LEARNING_PLANE_ENABLED）"已过时，config.py:869 实际默认 "1"。