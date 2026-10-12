# RESULT: isolated_transport_open_failed 根因、修复与 Web-only 发布资格

- 日期: 2026-10-09 | 分支: feat/p1a-standard-packages | 基线: c79d1612a (含 14352cc6f 重启修复，未触碰)
- 范围: TaskBudget 隔离传输最后一个生产验收缺口；不新增开发阶段。

## 1. 事故事实（生产日志）

- `data/event_logs/481915ed-….jsonl` seq10-13：2026-10-09 14:14:59，web 会话（glm/glm-5.3）
  round 1 即败，`LLM HTTP 异常: isolated_transport_open_failed`，provider_total_ms≈1229，
  0 tokens，fail-closed（run.end run_incomplete=true）。
- `data/task_budget_admin_once/budget-7c99f….json`：grant profile =
  `web-glm-one-physical-attempt-v3`；唯一物理尝试 dispatch reservation
  `outcome=failure, phase=unknown`——CAS/防重放/一次尝试/fail-closed 记账全部按设计工作。

## 2. 根因（机制层，已证实）

1. **网络拓扑分叉**：本机 GLM 出网依赖 macOS 系统代理（Surge 127.0.0.1:6152，
   scutil --proxy 证实；shell/daemon 环境无 proxy 变量）。主客户端
   `client.py` 对远程 provider `trust_env=True`，httpx 经 urllib 读系统代理出网；
   隔离子进程 `trust_env=False + proxy=None`（v3 profile 强制）走直连。
   两条路径拓扑不同。14:14 直连路径快败（1229ms 含 spawn ≈ 数百 ms），
   同期主路径（走代理）正常；17:33 探测（纯 TCP/TLS，零 API 请求）直连与代理
   均通——触发条件为直连路径的瞬时/拓扑态（本机存在 5 个 utun 接口，Surge TUN 可变）。
2. **可诊断性缺失（确定性 bug）**：worker 把异常类名
   （`kind=type(exc).__name__`，如 ConnectError）随帧发回，父进程在
   `task_budget_process_transport.py` 抛错时**丢弃 kind**，只留笼统的
   `isolated_transport_open_failed`——生产上永远无法归因。已排除确定性帧编码
   bug（httpx 0.28.1 下 `http_version` 为 bytes，loopback 全 SSE 用例通过）。

## 3. 修复（保持 CAS/防重放/一次尝试/fail-closed 不变）

| 文件 | 变更 |
| --- | --- |
| resources/task_budget_transport_context.py | 新增 `qualify_loopback_provider_proxy`（严格 http:// 回环+显式端口，无凭据/路径/非回环一律无效）与授权 contextvar（`bind/active_authorized_provider_proxy`） |
| resources/task_budget_admin_once.py | `AdminOnceEventPlan.provider_proxy`（可选，默认 None）；`__post_init__` 校验不合格即 `admin_once_proxy_invalid`；`bind_admin_once_plan` 同时绑定授权 scope |
| resources/task_budget_dispatch.py | dispatch 守卫：`profile.proxy ∈ {None, 授权值}`，其余照旧拒绝 |
| resources/task_budget_process_transport.py | ① 父进程透传 worker 异常类名：`isolated_transport_open_failed:ConnectError` / `isolated_transport_worker_error:RemoteProtocolError`（白名单 `[A-Za-z0-9_.]{1,64}`，仅类型名，不携凭据/URL）；② v3 守卫同 dispatch 对齐 |
| web/task_budget_canary.py | admin-once 配置可选键 `provider_proxy`（严格校验，非法 fail-closed）；plan 携带；bind 时 profile.proxy=plan 值；signed 计划路径保持 proxy=None |
| scripts/task_budget_admin_once_setup.py | `--provider-proxy`（不合格直接拒绝生成配置） |

- worker 仍 `trust_env=False`：环境/系统代理发现依旧被禁止；唯一例外是
  operator 在 admin-once 配置里显式钉定的回环 http 代理（与主路径同等暴露面：
  TLS 端到端校验 origin，代理仅见 CONNECT 元数据）。
- 不含该键的既有配置行为与旧版完全一致（直接放行不受影响）。

## 4. 测试（全部 loopback，零 GLM 额度）

新增 25 例：
- `test_open_failure_surfaces_worker_exception_kind`（closed port → `…:ConnectError`）
- `test_midstream_worker_error_surfaces_exception_kind`（截断响应 → `…:RemoteProtocolError`）
- `test_explicit_loopback_proxy_carries_one_sse_attempt`（转发代理 e2e：worker 仅经
  显式代理出网，完整 SSE 往返成功，`connects` 断言仅命中 origin）
- v3 守卫矩阵：dispatch/transport 双侧接受授权值；无计划、值不匹配、dispatch 后
  重绑不同 profile 均拒绝（`positive_budget_requires_exclusive_verified_process` /
  `positive_transport_unqualified`），且不消耗物理尝试
- `AdminOnceEventPlan` 对 socks/https/远端/带凭据/路径/越界端口/非字符串 全部
  `admin_once_proxy_invalid`；operator 配置同等校验；bootstrap 测试断言
  plan→profile→授权 scope 传递且离开 bind 窗口即复位

附带修复（test-only）：web_cutover 3 例既有失败为环境锚定——本机 .env 携带真实
`LFL_TASK_BUDGET_WEB_CANARY_CONFIG`，`business_config_snapshot` 读 dotenv 绕过
`monkeypatch.delenv`，使 default-off 断言误触 `_deny`（HEAD stash 复跑同败，非本次
引入）。按 admin_once 测试既有手法补 `monkeypatch.setattr(business_config_snapshot)`
快照隔离后 web_cutover 9/9 全绿；task_budget 全族 286 passed / 0 failed。

## 5. 发布资格（Web-only）与待授权项

- 代码资格：针对性+相邻回归绿；重启链路零触碰（git diff --name-only 复核 NONE）。
- 上线路径（需用户授权）：publish 新代（Web-only）→ operator 以
  `--provider-proxy http://127.0.0.1:6152` 重发 canary 配置（可选；不发则维持直连）
  → 新 GLM-5.3 物理尝试授权后验收。真实 GLM 调用与生产 publish 未执行。
