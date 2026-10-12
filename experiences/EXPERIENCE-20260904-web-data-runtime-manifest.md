---
title: 镜像区临时起 web 实例验证：勿与主服务共用 data/（runtime manifest 覆盖致主服务重启）
scenario: 在镜像工作区（主服务 8903 常驻运行中）需要验证 web 层中间件/路由行为（如 Origin 白名单补丁）时，想当然起第二个 web 实例换端口验证
root_cause: "write_runtime_manifest(\"web\") 写共享 data/runtime_manifest.json，临时实例 pid 覆盖主服务记录；工具超时清理连带杀进程组，主服务被自动重启"
solution: ① 中间件级进程内验证：直接构造 _OriginGuardMiddleware + dummy ASGI app，手工 scope dict 调用（零端口/零进程/零文件副作用）；② 对主服务无损探测：POST 到 GET-only 端点（如 /health，路由层必 405），403=中间件拦截、405=放行；③ 确需真实实例：DATA_DIR 独立临时目录（/tmp 范式）+ 短超时后台 + 立即按 pid 清理
evidence: "execute_command 回执：8904 日志含 MCP fail-open + POST /health 405/403 混合记录；architecture_status 显示 web pid 56425(23:14启动)→62305(07:32启动)发生重启；/tmp/verify_asgi_mw.py 与主服务 curl 验证全部通过"
tags: [web, runtime-manifest, 临时实例, 验证策略, data目录冲突, 事故复盘]
source: {}
status: active
created_at: "2026-09-04T07:39:23.280348+08:00"
updated_at: "2026-09-04T07:39:23.280348+08:00"
---

## 事故复盘（2026-09-04）

**时间线**：为验证 Origin 白名单补丁，`WEB_PORT=8904 nohup .venv/bin/python -m llm_loop.web &` 起临时实例 → execute_command 60s 超时 → 清理机制杀进程 → 主服务（8903，原 pid 56425）被连带重启（→ pid 62305）→ 用户侧 web 端短暂不可达。

**根因**：
1. `main()` 里 `write_runtime_manifest("web")` 写共享 `data/runtime_manifest.json`，临时实例 pid 覆盖主服务记录；
2. 临时实例与主服务同 CWD、同 data/，任何 manifest/锁/心跳文件都互踩；
3. 超时清理按进程组杀，nohup+& 不隔离。

**替代方案（本次事后重验全部通过）**：
1. 中间件级：`_OriginGuardMiddleware(dummy_asgi_app)` + 手工构造 scope/headers，asyncio.run 直接调用——真实中间件对象、零端口零进程零文件；
2. 服务级：对运行中主服务 POST 到 GET-only 端点（/health，必 405）带不同 Origin 头——403=中间件拦截、405=放行到路由层，完全无损；
3. 若必须真实独立实例：`DATA_DIR=/tmp/xxx`（对齐 COG_RUNTIME 测试的 /tmp/cog_test 范式）+ 独立日志目录，避免共享 data/。