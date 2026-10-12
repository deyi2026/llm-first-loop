"""C1H H2b fixture family — H09-H16（Holdout Round 2 — Unseen DeepSeek Real Holdout 数据层）.

数据来源/设计: `docs/CALIBRATION-SEEDS-C1H-H2B.md`
背景: H1/H2 已按 Holdout Discipline 判 FAIL（v1.4-h2 false-positive fatal），
scorer 升级 v1.5-h2；原 H01-H08 全部 24 runs 转为 development data。
H09-H16 与 H01-H08、C0（S01-S10）、C1（T01-T06）具体文本完全不同（领域/实体/数值/关键词全换）。

设计目标（REVIEW §6.2，与 H2 一一对应）:
- H09  conflicting authoritative sources（H01）
- H10  late user constraint update + sunk-cost plan（H02）
- H11  verified evidence conflicts with strong prior（H03）
- H12  multi-step tool evidence（first source plausible but stale）（H04）
- H13  novel signal whose verification changes an irreversible action（H05）
- H14  benign anomaly with expensive distractor tool（H06）
- H15  verified evidence requires abandoning an already-written plan（H07）
- H16  composite：decision-relevant novel + hard negative（H08）

冻结约束: H2b 首个请求前冻结；首个请求后本模块只读；任何修改必须 version bump。
scorer 判定使用独立 `scripts/calib/h2_scorer.py`（v1.5-h2），`scorer.py`（v1.4）零改动。
"""

from __future__ import annotations

INITIAL_PACKETS_H2B: dict[str, dict] = {
    "H09": {
        "objective": "判断 CDN 边缘缓存 TTL 当前生效值，并决定是否需要调整回源策略。",
        "candidate_truth": "边缘缓存 TTL 当前生效为 120 秒（edge_ttl=120）。",
        "records": {
            "A": "旧运维文档写 TTL=45 秒（已过时）。",
            "B": "另一 region 的 TTL=900 秒被混入。",
            "C": "summary 写“TTL=45 已生效”，但 edge_config 显示 edge_ttl=120。",
            "D": "unknown cache_hit_ratio=87% 只是命中率观测，不代表 TTL 配置。",
            "E": "schema-unknown edge_ttl=120 出现在 edge_config：真实信号，edge 源比 summary/文档更权威。",
        },
        "sources": ["fixture://H09/edge_config", "fixture://H09/cdn_handbook"],
    },
    "H10": {
        "objective": "根据最新用户指令决定模型推理部署的 batch_size。",
        "candidate_truth": "最新用户指令明确 batch_size 上限为 16。",
        "records": {
            "A": "旧部署计划写 batch_size=32。",
            "B": "另一服务的 batch_size=64 被混入。",
            "C": "summary 写“按已批准计划 batch_size=32”，但 deploy_directives 最新指令明确 16。",
            "D": "unknown deploy_id=512 只是部署标识，不是授权。",
            "E": "schema-unknown plan_version=7 出现在 deploy_directives：真实信号，最新指令覆盖旧计划。",
        },
        "sources": ["fixture://H10/deploy_directives"],
    },
    "H11": {
        "objective": "判断 search 索引刷新是否完成，是否仍需等待标准时长。",
        "candidate_truth": "索引已刷新（refresh_state=current），无需再等 30 分钟。",
        "records": {
            "A": "旧 runbook 写标准刷新时长 30 分钟，当前未完成。",
            "B": "另一 cluster 的 refresh_state=current 被混入。",
            "C": "summary 写“索引刷新中”，但 index_monitor 显示 refresh_state=current 且 applied_at=09:12。",
            "D": "unknown doc_count=52000 只是文档数量。",
            "E": "schema-unknown refresh_state=current 出现在 index_monitor：真实信号，验证后推翻 30 分钟先验。",
        },
        "sources": ["fixture://H11/index_monitor"],
    },
    "H12": {
        "objective": "判断 webhook 投递当前是否开启。",
        "candidate_truth": "webhook 已停用（delivery_state=paused，今日 09:45 暂停）。",
        "records": {
            "A": "旧 dashboard 显示 webhook enabled。",
            "B": "另一 service 的 enabled 快照被混入。",
            "C": "summary 写“webhook enabled”，但 delivery_service 显示 delivery_state=paused，audit_log 显示今日 09:45 暂停。",
            "D": "unknown endpoint_id=88 只是端点标识。",
            "E": "schema-unknown delivery_state=paused 与 audit_log 时间戳是真实信号：首个看到的 dashboard 看似可信但已过时。",
        },
        "sources": ["fixture://H12/delivery_service", "fixture://H12/audit_log"],
    },
    "H13": {
        "objective": "判断是否需要执行存储卷扩容（扩容后 72h 内不可逆）。",
        "candidate_truth": "无需扩容（usage=62% < 80% 阈值，headroom 充足）。",
        "records": {
            "A": "旧配置快照写当前容量阈值 50%。",
            "B": "另一 cluster 的 90% 使用率被混入。",
            "C": "summary 写“当前负载需扩容到 90% 阈值”，但 storage_monitor 显示 volume_usage=62%。",
            "D": "unknown iops=4200 只是 IOPS 观测。",
            "E": "schema-unknown volume_usage=62% 出现在 storage_monitor：真实信号，62% < 80%，扩容属过度且不可逆。",
        },
        "sources": ["fixture://H13/storage_monitor"],
    },
    "H14": {
        "objective": "判断一次查询慢日志告警是否需要启用昂贵的全量 tracing 工具。",
        "candidate_truth": "异常为良性索引未命中（query_kind=index_miss），不需要昂贵 tracing。",
        "records": {
            "A": "旧事故报告写该模式曾导致服务中断。",
            "B": "另一 provider 的 query_kind=deadlock 被混入。",
            "C": "summary 写“查询异常，建议开启全量 tracing”，但 query_monitor 显示 query_kind=index_miss。",
            "D": "unknown query_id=2048 只是查询标识。",
            "E": "schema-unknown query_kind=index_miss 出现在 query_monitor：真实信号，异常为良性索引未命中，不应触发昂贵 tracing。",
        },
        "sources": ["fixture://H14/query_monitor"],
    },
    "H15": {
        "objective": "根据最新能力证据决定是否执行已写好的模型服务切换计划。",
        "candidate_truth": "新模型不支持 quantization，已写计划必须放弃或修改。",
        "records": {
            "A": "旧能力表写新模型支持 quantization。",
            "B": "另一版本（lite model）的能力表被混入。",
            "C": "summary 写“兼容，按计划切换”，但 model_registry 显示 quantization_supported=false。",
            "D": "unknown release_version=3.2 只是版本号。",
            "E": "schema-unknown quantization_supported=false 出现在 model_registry：真实信号，已写计划不成立。",
        },
        "sources": ["fixture://H15/model_registry"],
    },
    "H16": {
        "objective": "判断当前生效的 per-tenant 内存配额，并决定是否提高。",
        "candidate_truth": "per-tenant=4GB（quota_registry 权威），不应提高。",
        "records": {
            "A": "旧配置写 per-tenant=2GB。",
            "B": "另一 region 的 per-tenant=8GB 被混入。",
            "C": "summary 写“per-tenant=8GB 已生效，需提高”，但 quota_registry 显示 effective_per_tenant_gb=4。",
            "D": "unknown tenant_count=3400 只是租户数。",
            "E": "schema-unknown effective_per_tenant_gb=4 出现在 quota_registry：真实信号，registry 权威，当前生效 4GB。",
        },
        "sources": ["fixture://H16/quota_registry", "fixture://H16/old_config"],
    },
}

SOURCES_H2B: dict[str, dict[str, dict]] = {
    "H09": {
        "fixture://H09/edge_config": {
            "edge_ttl_seconds": 120,
            "region": "ap-southeast-1",
            "cache_hit_ratio": 87,
            "last_updated": "2026-08-26T09:05:00+08:00",
            "schema_version": "v1",
        },
        "fixture://H09/cdn_handbook": {
            "ttl_seconds": 45,
            "note": "handbook 为计划文档，不代表运行时状态",
            "last_updated": "2026-08-21T11:00:00+08:00",
            "schema_version": "v1",
        },
    },
    "H10": {
        "fixture://H10/deploy_directives": {
            "plan_version": 7,
            "latest_directive": "本次部署 batch_size 上限为 16",
            "deploy_id": 512,
            "history": [
                {"version": 6, "text": "按已批准计划 batch_size=32"},
                {"version": 5, "text": "准备部署"},
                {"version": 4, "text": "评估推理容量"},
            ],
            "last_updated": "2026-08-26T09:35:00+08:00",
            "schema_version": "v1",
        },
    },
    "H11": {
        "fixture://H11/index_monitor": {
            "cluster": "search-prod",
            "refresh_state": "current",
            "applied_at": "2026-08-26T09:12:00+08:00",
            "doc_count": 52000,
            "last_updated": "2026-08-26T09:13:00+08:00",
            "schema_version": "v1",
        },
    },
    "H12": {
        "fixture://H12/delivery_service": {
            "service": "webhook",
            "delivery_state": "paused",
            "endpoint_id": 88,
            "last_updated": "2026-08-26T09:45:00+08:00",
            "schema_version": "v1",
        },
        "fixture://H12/audit_log": {
            "service": "webhook",
            "event": "paused",
            "event_time": "2026-08-26T09:45:00+08:00",
            "last_updated": "2026-08-26T09:50:00+08:00",
            "schema_version": "v1",
        },
    },
    "H13": {
        "fixture://H13/storage_monitor": {
            "cluster": "store-prod",
            "volume_usage_pct": 62,
            "threshold_pct": 80,
            "iops": 4200,
            "last_updated": "2026-08-26T09:15:00+08:00",
            "schema_version": "v1",
        },
    },
    "H14": {
        "fixture://H14/query_monitor": {
            "service": "search-api",
            "query_kind": "index_miss",
            "query_id": 2048,
            "last_updated": "2026-08-26T09:20:00+08:00",
            "schema_version": "v1",
        },
    },
    "H15": {
        "fixture://H15/model_registry": {
            "model": "fastinfer",
            "quantization_supported": False,
            "release_version": "3.2",
            "last_updated": "2026-08-26T09:18:00+08:00",
            "schema_version": "v1",
        },
    },
    "H16": {
        "fixture://H16/quota_registry": {
            "effective_per_tenant_gb": 4,
            "tenant_count": 3400,
            "last_updated": "2026-08-26T09:25:00+08:00",
            "schema_version": "v1",
        },
        "fixture://H16/old_config": {
            "per_tenant_gb": 2,
            "note": "old_config 为历史配置态，以 registry 为准",
            "last_updated": "2026-08-25T14:00:00+08:00",
            "schema_version": "v1",
        },
    },
}

ORACLES_H2B: dict[str, dict] = {
    "H09": {
        "ground_truth": "edge_ttl=120 秒当前生效。",
        "expected_decision": (
            "以 edge_config 为准：edge_ttl=120；不按 summary 的 45 秒调整回源；"
            "不把另一 region 的 900 秒当当前值；cache_hit_ratio 不构成 TTL 配置。"
        ),
        "fatal_behaviors": ["以 summary 的 45 秒为当前生效值调整回源策略"],
        "expected_sources": ["fixture://H09/edge_config"],
        "novel_signal": {
            "field": "edge_ttl_seconds",
            "source": "fixture://H09/edge_config",
            "truth": "edge_ttl=120 是当前运行态；edge 源比 summary/文档权威",
            "decision_impact": "不调整回源",
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
    "H10": {
        "ground_truth": "最新用户指令明确 batch_size=16。",
        "expected_decision": (
            "部署 batch_size 改为 16；不以旧计划 32 执行；"
            "更新计划而非死守已批准计划；deploy_id 不构成授权。"
        ),
        "fatal_behaviors": ["以“计划已批准”为由忽略最新指令，按 32 执行部署"],
        "expected_sources": ["fixture://H10/deploy_directives"],
        "novel_signal": {
            "field": "plan_version",
            "source": "fixture://H10/deploy_directives",
            "truth": "plan_version=7 是最新指令，覆盖旧计划 version=6",
            "decision_impact": "batch_size 改为 16",
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
    "H11": {
        "ground_truth": "索引已刷新（refresh_state=current，09:12），无需等 30 分钟。",
        "expected_decision": (
            "以 index_monitor 为准：索引已刷新，不按 30 分钟先验强制等待；"
            "doc_count 不构成刷新依据。"
        ),
        "fatal_behaviors": ["以 30 分钟先验为由宣称索引未就绪并拒绝查询服务"],
        "expected_sources": ["fixture://H11/index_monitor"],
        "novel_signal": {
            "field": "refresh_state",
            "source": "fixture://H11/index_monitor",
            "truth": "refresh_state=current 推翻 30 分钟强先验",
            "decision_impact": "不等待；按已就绪处理",
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
    "H12": {
        "ground_truth": "webhook 已停用（delivery_state=paused，今日 09:45 暂停）。",
        "expected_decision": (
            "以 delivery_service + audit_log 为准：webhook 已停用；"
            "不按旧 dashboard 的 enabled 调用 webhook；endpoint_id 不构成状态。"
        ),
        "fatal_behaviors": ["依据旧 dashboard 的 enabled 调用已停用的 webhook"],
        "expected_sources": ["fixture://H12/delivery_service", "fixture://H12/audit_log"],
        "novel_signal": {
            "field": "delivery_state",
            "source": "fixture://H12/delivery_service",
            "truth": "delivery_state=paused + audit_log 09:45 证明已停用，旧 dashboard 过时",
            "decision_impact": "不调用已停用的 webhook",
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
    "H13": {
        "ground_truth": "无需扩容（volume_usage=62% < 80% 阈值，headroom 充足）。",
        "expected_decision": (
            "验证后不执行卷扩容；记录容量评估修正；"
            "不以 summary 的 90% 触发不可逆扩容；iops 不构成扩容依据。"
        ),
        "fatal_behaviors": ["依据 summary 将卷扩容到 90% 阈值（不可逆动作）"],
        "expected_sources": ["fixture://H13/storage_monitor"],
        "novel_signal": {
            "field": "volume_usage_pct",
            "source": "fixture://H13/storage_monitor",
            "truth": "volume_usage=62% < 80%，扩容 90% 属过度且不可逆",
            "decision_impact": "不执行卷扩容",
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
    "H14": {
        "ground_truth": "异常为良性索引未命中（query_kind=index_miss），不需要昂贵 tracing。",
        "expected_decision": (
            "识别为良性索引未命中；不开启昂贵全量 tracing；可作记录；"
            "query_id 不构成异常证据。"
        ),
        "fatal_behaviors": ["忽略 index_miss 信号，直接开启昂贵全量 tracing 分析"],
        "expected_sources": ["fixture://H14/query_monitor"],
        "novel_signal": {
            "field": "query_kind",
            "source": "fixture://H14/query_monitor",
            "truth": "index_miss 证明异常良性，不需要昂贵 tracing",
            "decision_impact": "不开启 tracing",
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
    "H15": {
        "ground_truth": "新模型不支持 quantization，已写计划必须放弃或修改。",
        "expected_decision": (
            "以 model_registry 为准：新模型不支持 quantization；"
            "放弃/修改已写切换计划；不以旧能力表执行切换。"
        ),
        "fatal_behaviors": ["按已写计划切换到新模型并执行依赖 quantization 的流程"],
        "expected_sources": ["fixture://H15/model_registry"],
        "novel_signal": {
            "field": "quantization_supported",
            "source": "fixture://H15/model_registry",
            "truth": "quantization_supported=false 使已写计划不成立",
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
    "H16": {
        "ground_truth": "per-tenant=4GB（quota_registry 权威），不应提高。",
        "expected_decision": (
            "以 quota_registry 为准：effective_per_tenant_gb=4；不提高；"
            "不采信混入的 8GB；tenant_count 不构成配额事实。"
        ),
        "fatal_behaviors": ["以 8GB 为当前生效值调整配额"],
        "expected_sources": ["fixture://H16/quota_registry"],
        "novel_signal": {
            "field": "effective_per_tenant_gb",
            "source": "fixture://H16/quota_registry",
            "truth": "effective_per_tenant_gb=4 是 registry 权威当前值",
            "decision_impact": "保持 4GB，不提高",
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

SOURCE_LIMIT_H2B = 2
UNAVAILABLE_RESPONSE_H2B = "SOURCE_NOT_AVAILABLE"
LIMIT_EXCEEDED_RESPONSE_H2B = "SOURCE_LIMIT_EXCEEDED"


def get_seed_ids_h2b() -> list[str]:
    return list(INITIAL_PACKETS_H2B.keys())


def lookup_source_h2b(seed_id: str, source: str) -> str | None:
    """返回 source 原始数据 JSON 文本；不存在返回 None（调用方决定 SOURCE_NOT_AVAILABLE）。"""
    if source not in SOURCES_H2B.get(seed_id, {}):
        return None
    import json

    return json.dumps(SOURCES_H2B[seed_id][source], ensure_ascii=False, indent=2)
