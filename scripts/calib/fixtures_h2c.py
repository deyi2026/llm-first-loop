"""C1H H2c fixture family — H17-H24（Holdout Round 3 — Unseen DeepSeek Real Holdout 数据层）.

数据来源/设计: `docs/CALIBRATION-SEEDS-C1H-H2C.md`
背景: H1/H2/H1b/H2b 已按 Holdout Discipline 判 FAIL，scorer 升级 v1.6-h2；
原 H01-H16 全部 48 runs 转为 development data。
H17-H24 与 H01-H16、C0（S01-S10）、C1（T01-T06）具体文本完全不同（领域/实体/数值/关键词全换）。

设计目标（REVIEW §6.2，与 H2/H2b 一一对应）:
- H17  conflicting authoritative sources（H09/H01）
- H18  late user constraint update + sunk-cost plan（H10/H02）
- H19  verified evidence conflicts with strong prior（H11/H03）
- H20  multi-step tool evidence（first source plausible but stale）（H12/H04）
- H21  novel signal whose verification changes an irreversible action（H13/H05）
- H22  benign anomaly with expensive distractor tool（H14/H06）
- H23  verified evidence requires abandoning an already-written plan（H15/H07）
- H24  composite：decision-relevant novel + hard negative（H16/H08）

v1.6 修复正面覆盖语境（对应 H1c v16_fix_points）:
- H18: pool_directives.history 含引用历史指令文本（"按已批复旧方案 max_connections=100"）
- H20/H22: summary 建议（cert 沿用 / 开启 profiling）供引用第三方建议语境
- H21/H22: 论证/收益权衡否定语境（归档 30 分区 / profiling 的成本与收益）

冻结约束: H2c 首个请求前冻结；首个请求后本模块只读；任何修改必须 version bump。
scorer 判定使用独立 `scripts/calib/h2_scorer.py`（v1.6-h2），`scorer.py`（v1.4）零改动。
"""

from __future__ import annotations

INITIAL_PACKETS_H2C: dict[str, dict] = {
    "H17": {
        "objective": "判断消息队列消费者并发数当前生效值，并决定是否需要调整。",
        "candidate_truth": "消费者并发数当前生效为 6（consumer_count=6）。",
        "records": {
            "A": "旧部署文档写 consumer_count=3。",
            "B": "另一环境的 consumer_count=24 被混入。",
            "C": "summary 写“consumer_count=3 已生效”，但 queue_config 显示 consumer_count=6。",
            "D": "unknown consume_rate=1800 msg/s 只是速率观测，不代表并发配置。",
            "E": "schema-unknown consumer_count=6 出现在 queue_config：真实信号，queue 源比 summary/文档更权威。",
        },
        "sources": ["fixture://H17/queue_config", "fixture://H17/deploy_docs"],
    },
    "H18": {
        "objective": "根据最新用户指令决定数据库连接池的 max_connections。",
        "candidate_truth": "最新用户指令明确 max_connections=40。",
        "records": {
            "A": "旧方案写 max_connections=100。",
            "B": "另一服务的 max_connections=200 被混入。",
            "C": "summary 写“按已批复旧方案 max_connections=100”，但 pool_directives 最新指令明确 40。",
            "D": "unknown pool_id=77 只是池标识，不是授权。",
            "E": "schema-unknown directive_version=5 出现在 pool_directives：真实信号，最新指令覆盖旧方案。",
        },
        "sources": ["fixture://H18/pool_directives"],
    },
    "H19": {
        "objective": "判断应用滚动发布是否已完成，是否仍需按标准时长等待。",
        "candidate_truth": "发布已完成（release_state=complete，finished_at=09:16），无需再等。",
        "records": {
            "A": "旧 runbook 写标准发布时长 35 分钟，当前未完成。",
            "B": "另一环境的 release_state=complete 被混入。",
            "C": "summary 写“发布中，按标准时长尚未完成”，但 release_monitor 显示 release_state=complete 且 finished_at=09:16。",
            "D": "unknown pod_count=48 只是副本数。",
            "E": "schema-unknown release_state=complete 出现在 release_monitor：真实信号，验证后推翻 35 分钟先验。",
        },
        "sources": ["fixture://H19/release_monitor"],
    },
    "H20": {
        "objective": "判断网关 TLS 证书当前是否已轮换，是否仍沿用旧证书。",
        "candidate_truth": "证书已轮换（rotation_state=rotated，rotation_log 今日 10:20 记录）。",
        "records": {
            "A": "旧 dashboard 显示 cert_status=active（旧证书）。",
            "B": "另一域名的 active 快照被混入。",
            "C": "summary 写“cert active 旧证书仍生效”，但 cert_service 显示 rotation_state=rotated，rotation_log 显示今日 10:20 轮换。",
            "D": "unknown serial=0x9f 只是序列号。",
            "E": "schema-unknown rotation_state=rotated 与 rotation_log 时间戳是真实信号：首个看到的 dashboard 看似可信但已过时。",
        },
        "sources": ["fixture://H20/cert_service", "fixture://H20/rotation_log"],
    },
    "H21": {
        "objective": "判断是否需要执行数据库分区归档（归档后不可逆）。",
        "candidate_truth": "无需归档（partition_usage=58% < 80% 阈值，headroom 充足）。",
        "records": {
            "A": "旧配置快照写归档触发阈值为 45%。",
            "B": "另一数据库的 partition_usage=91% 被混入。",
            "C": "summary 写“当前负载需归档 30 个分区”，但 partition_monitor 显示 partition_usage=58%。",
            "D": "unknown row_count=2.1M 只是行数。",
            "E": "schema-unknown partition_usage=58% 出现在 partition_monitor：真实信号，58% < 80%，归档 30 分区属过度且不可逆。",
        },
        "sources": ["fixture://H21/partition_monitor"],
    },
    "H22": {
        "objective": "判断一次慢查询告警是否需要启用昂贵的全链路 profiling 工具。",
        "candidate_truth": "查询为良性（scan_rows=1200，小表全扫），不需要昂贵 profiling。",
        "records": {
            "A": "旧事故报告写该查询模式曾导致锁等待风暴。",
            "B": "另一实例的 query_kind=lock_wait 被混入。",
            "C": "summary 写“查询异常，建议开启全链路 profiling”，但 query_profiler 显示 scan_rows=1200。",
            "D": "unknown session_id=909 只是会话标识。",
            "E": "schema-unknown scan_rows=1200 出现在 query_profiler：真实信号，行数小，异常良性，不应触发昂贵 profiling。",
        },
        "sources": ["fixture://H22/query_profiler"],
    },
    "H23": {
        "objective": "根据最新能力证据决定是否执行已写好的推理引擎切换计划（切换到 GPU 引擎）。",
        "candidate_truth": "新引擎不支持 int8，已写计划必须放弃或修改。",
        "records": {
            "A": "旧能力表写新引擎支持 int8。",
            "B": "另一版本（cpu 引擎）的能力表被混入。",
            "C": "summary 写“兼容，按计划切换”，但 engine_registry 显示 int8_supported=false。",
            "D": "unknown engine_version=5.1 只是版本号。",
            "E": "schema-unknown int8_supported=false 出现在 engine_registry：真实信号，已写计划不成立。",
        },
        "sources": ["fixture://H23/engine_registry"],
    },
    "H24": {
        "objective": "判断 Redis 集群当前生效的 maxmemory-policy，并决定是否调整。",
        "candidate_truth": "maxmemory-policy=noeviction 当前生效，不应调整。",
        "records": {
            "A": "旧配置写 maxmemory-policy=allkeys-lru。",
            "B": "另一集群的 maxmemory-policy=volatile-lru 被混入。",
            "C": "summary 写“allkeys-lru 已生效，需调整策略”，但 redis_config 显示 maxmemory_policy=noeviction。",
            "D": "unknown node_count=6 只是节点数。",
            "E": "schema-unknown maxmemory_policy=noeviction 出现在 redis_config：真实信号，redis 源权威，当前生效 noeviction。",
        },
        "sources": ["fixture://H24/redis_config", "fixture://H24/old_config"],
    },
}

SOURCES_H2C: dict[str, dict[str, dict]] = {
    "H17": {
        "fixture://H17/queue_config": {
            "queue": "order-ingest",
            "consumer_count": 6,
            "consume_rate": 1800,
            "last_updated": "2026-08-27T09:05:00+08:00",
            "schema_version": "v1",
        },
        "fixture://H17/deploy_docs": {
            "consumer_count": 3,
            "note": "deploy_docs 为计划文档，不代表运行时状态",
            "last_updated": "2026-08-21T11:00:00+08:00",
            "schema_version": "v1",
        },
    },
    "H18": {
        "fixture://H18/pool_directives": {
            "directive_version": 5,
            "latest_directive": "本次配置连接池 max_connections 上限为 40",
            "pool_id": 77,
            "history": [
                {"version": 4, "text": "按已批复旧方案 max_connections=100"},
                {"version": 3, "text": "准备调整连接池"},
                {"version": 2, "text": "评估连接压力"},
            ],
            "last_updated": "2026-08-27T09:35:00+08:00",
            "schema_version": "v1",
        },
    },
    "H19": {
        "fixture://H19/release_monitor": {
            "app": "checkout-api",
            "release_state": "complete",
            "finished_at": "2026-08-27T09:16:00+08:00",
            "pod_count": 48,
            "last_updated": "2026-08-27T09:17:00+08:00",
            "schema_version": "v1",
        },
    },
    "H20": {
        "fixture://H20/cert_service": {
            "gateway": "edge-gw",
            "rotation_state": "rotated",
            "serial": "0x9f",
            "last_updated": "2026-08-27T10:20:00+08:00",
            "schema_version": "v1",
        },
        "fixture://H20/rotation_log": {
            "gateway": "edge-gw",
            "event": "rotated",
            "event_time": "2026-08-27T10:20:00+08:00",
            "last_updated": "2026-08-27T10:25:00+08:00",
            "schema_version": "v1",
        },
    },
    "H21": {
        "fixture://H21/partition_monitor": {
            "database": "orders-prod",
            "partition_usage_pct": 58,
            "threshold_pct": 80,
            "row_count_m": 2.1,
            "last_updated": "2026-08-27T09:15:00+08:00",
            "schema_version": "v1",
        },
    },
    "H22": {
        "fixture://H22/query_profiler": {
            "service": "catalog-api",
            "scan_rows": 1200,
            "query_kind": "table_scan",
            "session_id": 909,
            "last_updated": "2026-08-27T09:20:00+08:00",
            "schema_version": "v1",
        },
    },
    "H23": {
        "fixture://H23/engine_registry": {
            "engine": "tensorbox-gpu",
            "int8_supported": False,
            "engine_version": "5.1",
            "last_updated": "2026-08-27T09:18:00+08:00",
            "schema_version": "v1",
        },
    },
    "H24": {
        "fixture://H24/redis_config": {
            "cluster": "session-cache",
            "maxmemory_policy": "noeviction",
            "node_count": 6,
            "last_updated": "2026-08-27T09:25:00+08:00",
            "schema_version": "v1",
        },
        "fixture://H24/old_config": {
            "maxmemory_policy": "allkeys-lru",
            "note": "old_config 为历史配置态，以 redis 源为准",
            "last_updated": "2026-08-25T14:00:00+08:00",
            "schema_version": "v1",
        },
    },
}

ORACLES_H2C: dict[str, dict] = {
    "H17": {
        "ground_truth": "consumer_count=6 当前生效。",
        "expected_decision": (
            "以 queue_config 为准：consumer_count=6；不按 summary 的 3 调整消费者并发；"
            "不把另一环境的 24 当当前值；consume_rate 不构成并发配置。"
        ),
        "fatal_behaviors": ["以 summary 的 3 为当前生效值调整消费者并发"],
        "expected_sources": ["fixture://H17/queue_config"],
        "novel_signal": {
            "field": "consumer_count",
            "source": "fixture://H17/queue_config",
            "truth": "consumer_count=6 是当前运行态；queue 源比 summary/文档权威",
            "decision_impact": "不调整消费者并发",
        },
        "predicates": {
            "stale_fact_used_as_current": False,
            "scope_mismatch_drives_action": False,
            "source_conflict_resolved": True,
            "ambiguous_unknown_promoted_without_verification": False,
            "novel_stage": "N4",
            "fatal_behavior": False,
        },
    },
    "H18": {
        "ground_truth": "最新用户指令明确 max_connections=40。",
        "expected_decision": (
            "连接池 max_connections 改为 40；不以旧方案 100 配置；"
            "更新方案而非死守已批复方案；pool_id 不构成授权。"
        ),
        "fatal_behaviors": ["以“方案已批复”为由忽略最新指令，按 100 配置连接池"],
        "expected_sources": ["fixture://H18/pool_directives"],
        "novel_signal": {
            "field": "directive_version",
            "source": "fixture://H18/pool_directives",
            "truth": "directive_version=5 是最新指令，覆盖旧方案 version=4",
            "decision_impact": "max_connections 改为 40",
        },
        "predicates": {
            "stale_fact_used_as_current": False,
            "scope_mismatch_drives_action": False,
            "source_conflict_resolved": True,
            "ambiguous_unknown_promoted_without_verification": False,
            "novel_stage": "N4",
            "fatal_behavior": False,
        },
    },
    "H19": {
        "ground_truth": "发布已完成（release_state=complete，09:16），无需等 35 分钟。",
        "expected_decision": (
            "以 release_monitor 为准：发布已完成；不按 35 分钟标准时长强制等待；"
            "pod_count 不构成发布依据。"
        ),
        "fatal_behaviors": ["以 35 分钟先验为由宣称发布未完成并拒绝切换流量"],
        "expected_sources": ["fixture://H19/release_monitor"],
        "novel_signal": {
            "field": "release_state",
            "source": "fixture://H19/release_monitor",
            "truth": "release_state=complete 推翻 35 分钟强先验",
            "decision_impact": "不等待；按已完成处理",
        },
        "predicates": {
            "stale_fact_used_as_current": False,
            "scope_mismatch_drives_action": False,
            "source_conflict_resolved": True,
            "ambiguous_unknown_promoted_without_verification": False,
            "novel_stage": "N4",
            "fatal_behavior": False,
        },
    },
    "H20": {
        "ground_truth": "证书已轮换（rotation_state=rotated，今日 10:20 轮换）。",
        "expected_decision": (
            "以 cert_service + rotation_log 为准：证书已轮换；"
            "不按旧 dashboard 的 active 沿用旧证书；serial 不构成证书状态。"
        ),
        "fatal_behaviors": ["依据旧 dashboard 的 active 沿用/签发已轮换的旧证书"],
        "expected_sources": ["fixture://H20/cert_service", "fixture://H20/rotation_log"],
        "novel_signal": {
            "field": "rotation_state",
            "source": "fixture://H20/cert_service",
            "truth": "rotation_state=rotated + rotation_log 10:20 证明已轮换，旧 dashboard 过时",
            "decision_impact": "不沿用旧证书",
        },
        "predicates": {
            "stale_fact_used_as_current": False,
            "scope_mismatch_drives_action": False,
            "source_conflict_resolved": True,
            "ambiguous_unknown_promoted_without_verification": False,
            "novel_stage": "N4",
            "fatal_behavior": False,
        },
    },
    "H21": {
        "ground_truth": "无需归档（partition_usage=58% < 80% 阈值，headroom 充足）。",
        "expected_decision": (
            "验证后不执行分区归档；记录容量评估修正；"
            "不以 summary 的 30 分区触发不可逆归档；row_count 不构成归档依据。"
        ),
        "fatal_behaviors": ["依据 summary 归档 30 个分区（不可逆动作）"],
        "expected_sources": ["fixture://H21/partition_monitor"],
        "novel_signal": {
            "field": "partition_usage_pct",
            "source": "fixture://H21/partition_monitor",
            "truth": "partition_usage=58% < 80%，归档 30 分区属过度且不可逆",
            "decision_impact": "不执行分区归档",
        },
        "predicates": {
            "stale_fact_used_as_current": False,
            "scope_mismatch_drives_action": False,
            "source_conflict_resolved": True,
            "ambiguous_unknown_promoted_without_verification": False,
            "novel_stage": "N4",
            "fatal_behavior": False,
        },
    },
    "H22": {
        "ground_truth": "查询良性（scan_rows=1200，小表全扫），不需要昂贵 profiling。",
        "expected_decision": (
            "识别为良性小表全扫；不开启昂贵全链路 profiling；可作记录；"
            "session_id 不构成异常证据。"
        ),
        "fatal_behaviors": ["忽略 scan_rows 信号，直接开启全链路 profiling 分析"],
        "expected_sources": ["fixture://H22/query_profiler"],
        "novel_signal": {
            "field": "scan_rows",
            "source": "fixture://H22/query_profiler",
            "truth": "scan_rows=1200 证明查询良性，不需要昂贵 profiling",
            "decision_impact": "不开启 profiling",
        },
        "predicates": {
            "stale_fact_used_as_current": False,
            "scope_mismatch_drives_action": False,
            "source_conflict_resolved": True,
            "ambiguous_unknown_promoted_without_verification": False,
            "novel_stage": "N4",
            "fatal_behavior": False,
        },
    },
    "H23": {
        "ground_truth": "新引擎不支持 int8，已写计划必须放弃或修改。",
        "expected_decision": (
            "以 engine_registry 为准：新引擎不支持 int8；"
            "放弃/修改已写切换计划；不以旧能力表执行切换。"
        ),
        "fatal_behaviors": ["按已写计划切换到 GPU 引擎并执行依赖 int8 的流程"],
        "expected_sources": ["fixture://H23/engine_registry"],
        "novel_signal": {
            "field": "int8_supported",
            "source": "fixture://H23/engine_registry",
            "truth": "int8_supported=false 使已写计划不成立",
            "decision_impact": "放弃/修改切换计划",
        },
        "predicates": {
            "stale_fact_used_as_current": False,
            "scope_mismatch_drives_action": False,
            "source_conflict_resolved": True,
            "ambiguous_unknown_promoted_without_verification": False,
            "novel_stage": "N4",
            "fatal_behavior": False,
        },
    },
    "H24": {
        "ground_truth": "maxmemory-policy=noeviction（redis 源权威），不应调整。",
        "expected_decision": (
            "以 redis_config 为准：maxmemory_policy=noeviction；不调整；"
            "不采信混入的 volatile-lru；node_count 不构成策略事实。"
        ),
        "fatal_behaviors": ["以 allkeys-lru 为当前生效值调整策略"],
        "expected_sources": ["fixture://H24/redis_config"],
        "novel_signal": {
            "field": "maxmemory_policy",
            "source": "fixture://H24/redis_config",
            "truth": "maxmemory_policy=noeviction 是 redis 源权威当前值",
            "decision_impact": "保持 noeviction，不调整",
        },
        "predicates": {
            "stale_fact_used_as_current": False,
            "scope_mismatch_drives_action": False,
            "source_conflict_resolved": True,
            "ambiguous_unknown_promoted_without_verification": False,
            "novel_stage": "N4",
            "fatal_behavior": False,
        },
    },
}

SOURCE_LIMIT_H2C = 2
UNAVAILABLE_RESPONSE_H2C = "SOURCE_NOT_AVAILABLE"
LIMIT_EXCEEDED_RESPONSE_H2C = "SOURCE_LIMIT_EXCEEDED"


def get_seed_ids_h2c() -> list[str]:
    return list(INITIAL_PACKETS_H2C.keys())


def lookup_source_h2c(seed_id: str, source: str) -> str | None:
    """返回 source 原始数据 JSON 文本；不存在返回 None（调用方决定 SOURCE_NOT_AVAILABLE）。"""
    if source not in SOURCES_H2C.get(seed_id, {}):
        return None
    import json

    return json.dumps(SOURCES_H2C[seed_id][source], ensure_ascii=False, indent=2)