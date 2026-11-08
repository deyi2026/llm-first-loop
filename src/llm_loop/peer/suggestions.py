"""reason_code → 建议动作（原文来自 docs/schemas/lfl.peer.v1/reason-codes.json）。

生成物：由 scripts 侧一次性脚本生成，测试断言键集合与 JSON 完全一致；
改文案请改 JSON 后重新生成，不要在 Python 侧手改（避免两处漂移）。
"""

from __future__ import annotations

REASON_SUGGESTIONS: dict[str, str] = {
    'artifact_digest_mismatch': '产物 sha256 与回执不符。视为 failed，不要使用该产物。',
    'artifact_missing': '声明的产物不存在。视为 failed；检查执行端产物目录。',
    'audit_unavailable': '审计写入失败（磁盘满/只读挂载）。不得无审计执行；先清理磁盘或修复挂载。',
    'blocked_timeout': 'blocked 状态超期转 failed。需人决策的任务不应进无人值守队列。',
    'cancelled_by_grant_revocation': '因租约撤销而取消。',
    'cancelled_by_operator': '被真人取消。',
    'command_not_allowed': '命令不在白名单。改用已授权命令；不得拼接绕过。',
    'crashed': '执行进程异常退出。检查 unknown_outcome 是否适用；幂等任务可按同 effect_id 重查状态。',
    'desktop_target_not_grounded': '点击坐标未来自本端采集帧。先用 desktop 采集取得目标，再以采集帧坐标派单。',
    'execution_not_authorized': '任务未获人工执行授权（被拒绝，或停在等待确认态而没有有效票据）。不要重试同一提交；请人在本机确认，或由真人调整授权范围。',
    'executor_internal_error': '受控端内部错误。读 reason_code 之外的审计记录定位；不要假定任务未执行。',
    'executor_unhealthy': '受控端健康度不满足执行条件（水位/依赖故障）。先看 manifest.health 与 limits.audit_watermark_pct。',
    'grant_exhausted': '租约任务数已用满。需要真人重新签发；不得自动续期。',
    'grant_expired': '租约已过期。需要真人在受控端重新签发；不得自动续期。',
    'grant_issuer_not_human': '签发者不是真人 ingress。租约只能由真人在受控端签发；定时任务/子代理/peer 通道不得代签（RULE-AI-14）。改由真人在受控端执行签发。',
    'grant_not_found': 'grant_id 不存在。用 peer_list 读取当前有效租约。',
    'grant_revoked': '租约已被撤销。停止派单；已入队任务应转为 cancelled。',
    'grant_unbounded': '缺少 expires_at 或 max_tasks_total。租约必须同时有期限与次数上限；补全后重新签发。',
    'idempotency_conflict': '同一 effect_id 的 kind/params 与既有记录不一致。换新 effect_id，不要复用旧键改语义。',
    'pair_fingerprint_mismatch': '短指纹与 offer 不一致。立即停止配对：可能是 SSH 主机密钥已被替换或双方拿的不是同一次 offer。重新走 PAIR-2..PAIR-4，不要重试 confirm。',
    'pair_nonce_expired': '配对 nonce 已过期或已使用。offer 有效期 300s 且一次性；重新执行 PAIR-2 生成新 offer。',
    'params_schema_invalid': 'params 不符合该 kind 的 schema。按 peer_list 返回的 params_schema_hint 修正后重提（新 effect_id）。',
    'path_outside_allowed_paths': '路径越出 allowed_paths。改用授权范围内的路径；不得请求扩大范围（那需要真人重新签发）。',
    'peer_bad_signature': '签名校验失败。核对共享密钥/公钥是否一致。不要重试同一请求；先排查密钥来源。',
    'peer_not_paired': '尚未完成配对。先跑 §5.7 配对 check-list 的 PAIR-1..PAIR-6。',
    'peer_replay_detected': 'nonce 已使用过。用新 nonce 重建请求；若同一 effect_id，属正常的幂等重放，应返回原记录而非该错误。',
    'peer_stale_signature': '时间戳超出 ±300s 窗口。校时（chrony/systemd-timesyncd）后重新签名；不得为绕开而放宽窗口。',
    'peer_transport_unavailable': '连接不可达。检查 SSH -L 隧道是否存活、受控端 8903 是否监听 loopback。',
    'peer_unknown_node': 'node_id 未登记。核对 data/peer/nodes 白名单，或重新执行 §5.7 配对。不要重试同一请求。',
    'policy_desktop_type_not_allowed': '首版禁止文本键入（D11）。改用 click，或转为有人在场并升级 L3 授权域。',
    'policy_task_kind_not_allowed': 'kind 不在 PeerGrant.allowed_kinds。先调用 peer_list 读取实际可用 kind，不要猜。',
    'quota_concurrency_exceeded': '超过 max_concurrency。等待在跑任务收敛后再提交，不要提高并发。',
    'requires_supervised_execution': '该 kind 非幂等且无可回滚快照，无人值守白名单不接受。改为有人在场模式，或改用具幂等性的 kind。',
    'sandbox_denied': '闸4 沙盒拒绝（write_scope/bwrap）。这是独立于闸3 的第二道拒绝，属预期双保险；不要尝试绕开。',
    'supervision_channel_unavailable': '监督通道不可用（目录不可写或属主不是当前用户）。修复 data 目录权限/属主后再试；期间控制端不应看到需要监督的 kind 被宣告。',
    'supervision_ticket_consumed': '票据已被使用。每次执行都需要一次新的现场确认；不要复用旧确认。',
    'supervision_ticket_expired': '票据已过 TTL。请人在本机重新确认；不要让服务端自动续期。',
    'supervision_ticket_mismatch': '票据绑定的参数摘要与任务不一致（参数可能被改过）。拒绝执行，核对提交内容后重新确认。',
    'supervision_ticket_missing': '任务停在等待确认态且没有有效票据。在本机 TTY 执行 scripts/peer_operator.py confirm <task_id>（用与服务端相同的 --data-dir/--node-id/--write-root）；不要用 HTTP 自助批准。',
    'supervision_timeout': '等待人工确认超过 TTL。任务未执行、无副作用；需要重新提交（新 effect_id），不要让服务端自动放行。',
    'task_not_found': '任务不存在或不属于当前节点。核对 task_id 与 node_id；不要用猜测的 id 重试。',
    'timeout': '超过 deadline_s。先查任务实际副作用是否已发生，再决定是否以新 effect_id 重提。',
    'unknown_outcome': '执行中崩溃且已可能产生副作用。不得自动重试；需人核对现场后决定。',
    'unsupported_display_protocol': '受控端为 Wayland 或未报告显示协议。L3 不可用；改走 CLI 路径。',
}
