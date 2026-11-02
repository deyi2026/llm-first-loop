# 部署核验：演进建议来源会话链接（web gen 345 / git 913f2945a）

- 记录时间：2026-10-30 22:43 (+08:00)，session 31f2f5ae-5341-424f-9eb2-b63cb8de105f3
- 状态：**未生效 / 核验未完成**（本节不宣称成功）

## 1 已确立事实（含实测命令与输出）

1) publish gen345 已发布，desired git_head=913f2945a314060942e92f4606b5ee85c6fe3e6c（service_control status 回执）。
2) 首次 restart action svc-c3b59780cbc04dfca33e968ac7b5a14c 终态 failed：
   - updated_at=2026-10-30T22:35:37.331889+08:00
   - detail=target still busy after 900s: confirmed_busy: active run locks: 4
   - 归类：idle 门未满足（并发会话活跃），不是发布/代码缺陷。
3) run-lock 持有者审计（命令：find data/sessions -name "*.run.lock" -mmin -10；lsof；python3 fcntl 非阻塞共享锁探测）：
   - data/sessions 下 *.run.lock 共 2457 个，机械持有 5 个：31f2f5ae(本 run)、cab051cc-c0ca-4a09-b848-6d4a00ec0ffe、25e48ad9-7d56-4793-9a70-4c63d9502373、6e7b4358-a1b8-4e23-a99c-931d6e86bee2、831d550a-d9e7-4dc0-8324-20496745d212。
   - lsof 显示上述租约 FD 均由 PID 7472 持有；PID 7472=cwd 本仓库的 python3.13 宿主，LISTEN 127.0.0.1:8903。
   - 45 秒采样 session json：cab051cc、831d550a 文件持续增长（真实在跑）；25e48ad9、6e7b4358 当次静态但租约仍被持有。
   - 结论：这是并发活动会话造成的真实 idle 阻塞，不是陈旧/僵尸锁。
4) restart 前 runtime 身份：git_head=785e5a2e537239077dac8ef3169fa28690049853，restart_required=true（status 回执 reasons: live_git_head_mismatch）。
5) 判据②基线（restart 前）：
   curl -s -o /dev/null -w http=%{http_code} "http://127.0.0.1:8903/api/v1/evolution/session-locator?session_id=31f2f5ae-5341-424f-9eb2-b3cb8de105f3"
   → http=404, body={"detail":"Not Found"}（新端点在旧 runtime 不存在，必须重启后复验）。
6) 判据③基线（restart 前）：
   - GET / → 307, location: /ui/v2/
   - GET /ui/v2/ → 200, 1405 bytes, 引用 assets/index-YVEKHGVY.js、assets/index-BNbBDZdW.css
   - webui/dist/.lfl-webui-source.json: source_sha256=ebd564da132db6c9304cd07836ee3356b2209a1a13fe79df82fdbf1533e956b6, tracked_files=143（与构建指纹 ebd564da132db6c9 一致）。
   注：根路径 307 是既有设计（重定向到 /ui/v2/），判据③按 /ui/v2/ 与 assets 引用一致性核验。

## 2 本次处置（失败处置流程：等空闲后重发一次 restart）

- 22:42:12 重发 restart target=web expected_generation=345
  → action_id=svc-3b9c73a002364a9c93c1056ffd9ae924（受理回执，受理不等于完成）
- 22:42:23 读 action 文件：status=waiting_for_requester_exit，worker_pid=71051。
- 语义说明：该 worker 两阶段等待——先等 requester 会话（31f2f5ae，即本 run）租约释放，再等目标无机械持有 run lock；第二阶段超时 900s。
- **未使用 override(gate=waiting_for_idle)**：强推会打断 4 个并发活动会话的在飞 run，超出当前授权范围。

## 3 待完成核验（restart 成功后在后续会话执行，三判据全为真才算生效）

1) service_control(action=status, target=web) 中 action_id=svc-3b9c73a002364a9c93c1056ffd9ae924 为 succeeded，且 web 段 runtime_git_head 前缀=913f2945a、runtime_generation=345、restart_required=false。
2) curl -s -w "%{http_code}" "http://127.0.0.1:8903/api/v1/evolution/session-locator?session_id=31f2f5ae-5341-424f-9eb2-b3cb8de105f3" → 200 且 available=true。
3) curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8903/ui/v2/ → 200；assets 引用与 webui/dist 当前构建一致（source_sha256=ebd564da132db6c9）。

## 4 结论

- 判据 1/2/3 均未核验通过：本次仍未生效。
- GOAL-20261030-3b54af7a 不闭环；TASK-3b54af7a-005 保持 in_progress。
- 若重发的 action 再次 failed（预期原因仍是 active run locks），下一步：读 action 回执 closure（verify_acknowledge）→ 待人空闲窗口重排，或经人明确授权后 override。

## 5 第三次 restart 请求（23:17，用户明确指令“重启吧”）

- 23:17 环境事实（本次实测）：
  - 递归探测 data/sessions/**/*.run.lock（python3 fcntl 非阻塞排他探测）：total 2459 / free 2458 / held 1，唯一持有者为本会话 31f2f5ae；22:43 记录的另外 4 个持有者已释放（对应 run 已结束）。
  - 目标代码快照存在且含本特性：.releases/913f2945a314060942e92f4606b5ee85c6fe3e6c 内 `session-locator|session_locator` 命中 7 处（src/llm_loop/web/routes.py、webui/src/components/sidebar/EvolutionPanel.tsx、webui/dist/assets/index-cjDKAFFV.js 等）。
  - data/runtime/managed_service_deployment.json：generation=345、git_head=913f2945a314060942e92f4606b5ee85c6fe3e6c、code_root=.releases/913f2945a...（重启从发布快照启动，与工作树 HEAD a07bb1c3 无关）。
  - restart 前 runtime 复测：GET /api/v1/evolution/session-locator?... → http=404；GET /ui/v2/ → http=200（旧 runtime 仍在跑，未生效）。
- 23:17 重发 restart target=web expected_generation=345
  → action_id=svc-d398da37d30d4104871dafc196d274bf（受理回执；受理≠完成，终态须异步核对）。
- 未使用 override：沿用官方两阶段等待（先等 requester 会话结束，再等目标空闲）；本 run 结束即释放自身租约，预计随后执行重启。
- 生效判据不变（见 §3 三判据）；其中判据 1) 的 action_id 以 svc-d398da37d30d4104871dafc196d274bf 为准。
- 本条记录时点仍为**未生效**，不宣称成功。

## 6 重启后核验结果（23:24–23:25，三判据执行）

- 核验时间：2026-10-30 23:24–23:25 (+08:00)；会话 31f2f5ae（restart 受理后的定时续跑）。
- action 终态：`svc-d398da37d30d4104871dafc196d274bf` status=**succeeded**（created 23:18:00，updated 23:18:46；detail: restart_mirror rc=0；identity generation=345、git_head=913f2945a314…；verify=confirmed_ok，`web[ok pid=94695 head=913f2945a314]`）。

判据 1) ✅ 已满足
- `service_control(action=status, target=web)` 回执：该 action=succeeded；web 段 live.git_head=`913f2945a314060942e92f4606b5ee85c6fe3e6c`、pid=94695、pid_alive=true、started_at=23:18:44、matches_desired_generation=true；stable.action_id=svc-d398…、stable.generation=**345**、lag_generations=0；**restart_required=false、reasons=[]**。
- 交叉核对：`GET /api/v1/services/status`（同 composer）web 段与上述一致；`data/runtime/runtime_manifest.web.json` git_head=913f2945a314…，`lsof -iTCP:8903` 监听者即 pid 94695。

判据 2) ✅ 已满足
- `GET /api/v1/evolution/session-locator?session_id=31f2f5ae-5341-424f-9eb2-b3cb8de105f3` → HTTP **200**，body `{"ok":true,"available":true,"session_id":"31f2f5ae-…","current":true,…}`（restart 前为 404）。

判据 3) ✅ 已满足
- `GET /ui/v2/` → HTTP **200**；index.html 引用 `assets/index-cjDKAFFV.js` + `assets/index-BNbBDZdW.css`，与 `webui/dist/index.html` 及 `.releases/913f2945a314060942e92f4606b5ee85c6fe3e6c/webui/dist/index.html` 的引用完全一致。
- 线上 `/ui/v2/assets/index-cjDKAFFV.js` sha256 与 `webui/dist/` 及 release dist 同名文件 **完全相同**（字节一致），且 bundle 内含 `session-locator` 调用。
- 来源绑定：`verify_webui_source_binding()` 对 release 代码根与工作树均通过，重算 source_sha256=`ebd564da132db6c9…`（143 文件，tracked 指纹一致）= `webui/dist/.lfl-webui-source.json` 记录值。

结论：**三判据全为真 → web restart 已生效**（gen 345 / git 913f2945a 已上线，特性可用）。GOAL 交付闭环，TASK-3b54af7a-005 → done。

- 已知边界（非本目标交付物）：wecom 服务仍运行在旧 head 785e5a2e（restart_required 由 wecom 段 lag 触发），本次未重启、未 override；如需同步另行授权。
