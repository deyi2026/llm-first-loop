# 提权闭环设计（EVO-20260923-c58a0bb1 配套 · 用户批准 2026-09-23）

## 背景

EVO-20260923-c58a0bb1（accepted）修正了 CatastrophicGuard 四条"按拼写拦截"
的过宽规则；用户同时新增要求: **确属必要**的被阻断操作应有人工提权通道，
经 web 端弹窗审批，且 AI 能收到审批反馈继续操作（此前 T5a 的审批回执需
用户手动转述，无闭环）。

## 闭环流程

    AI: execute_command(cmd) → [安全硬阻断]（提示 escalation_request）
    AI: escalation_request(command, justification)
      ├─ 前置复验: cmd 确实会被灾难层阻断（未被阻断 → 拒绝，防通道滥用）
      └─ 写 pending 请求（data/audit/escalation_requests.json）
    Web: 侧栏"🔓 提权"页 + 全局弹窗（5s 轮询 pending）
      ├─ 批准 → decide() 铸造一次性令牌（TTL 默认 10 分钟）
      └─ 拒绝 → 记录理由
    AI: escalation_wait(request_id) → 轮询接收决定（批准=令牌 / 拒绝=理由 / 超时=pending）
    AI: execute_command(command, escalation_token=<令牌>)
      └─ registry 灾难层 consume() 校验 → 通过则放行本次 + 审计

## 令牌纪律

- 绑定批准时的**精确命令文本**（SHA256），改动一字即废（不可移植）
- 绑定工具名；单次有效（approved→consumed 原子转换）
- 过期即废（expired 终态）；重复决定拒绝（仅 pending 可决，409）
- 令牌只经 AI 侧 escalation_wait 返回，**永不经 web 端点**（list/review 响应剥除）

## 边界纪律

- 提权只绕过**灾难性硬阻断层**；EXEC_MODE 分级、共享服务控制权
  （managed_service_guard）不受令牌影响，仍按各自规则独立裁决
- 未装配 escalation_store（参数 None）→ 纯 fail-closed 零回归
- 全量审计: escalation_log.jsonl（request_created/decided/token_consumed/
  token_expired）+ escalation_review_log.jsonl（web 审批操作）
- 并发: flock 跨进程 + 进程锁跨线程，临时文件 + os.replace 原子写

## 变更文件

- src/llm_loop/tools/escalation.py（新）: EscalationStore
- src/llm_loop/tools/builtin/escalation.py（新）: escalation_request / escalation_wait
- src/llm_loop/tools/registry.py: 灾难层令牌校验 + 阻断提示闭环引导
- src/llm_loop/tools/builtin/execute_command.py: schema 增 escalation_token
- src/llm_loop/factory.py: store 装配 + 工具注册
- src/llm_loop/web/routes.py + schemas.py: GET /api/v1/escalation/list、
  POST /api/v1/escalation/review
- webui: EscalationCenter.tsx（弹窗+面板）、Sidebar/stores/i18n/css 接入
- tests/unit/test_escalation.py（新）+ test_safety.py（EVO 修正回归）

## 验证

- 单测: 12 项闭环用例（生命周期/单次性/绑定/过期/防滥用/零回归）
- E2E: web TestClient 12 项断言（含令牌不出 web 通道、真实执行放行、复用拒绝）
