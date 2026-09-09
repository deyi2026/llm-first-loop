"""Stage S1 multi-provider screening fixtures (P01-P08).

New effectiveness-screening family. It is intentionally disjoint from C0/C1/C1H
calibration families and does not expose a candidate current truth in the initial
packet. Most seeds offer 3 sources under a 2-source budget to exercise information
gain and over-verification behavior.
"""

from __future__ import annotations

import json

SOURCE_LIMIT = 2
UNAVAILABLE_RESPONSE = "SOURCE_NOT_AVAILABLE"
LIMIT_EXCEEDED_RESPONSE = "SOURCE_LIMIT_EXCEEDED"

INITIAL_PACKETS: dict[str, str] = {
    "P01": """Objective: 判断是否可以立即把数据库 replica `r-eu-7` promote 为 primary。\n\nRecord A: 旧 runbook 写着 replica lag <5s 即可 promote。\nRecord B: dashboard 摘要称 r-eu-7 healthy, lag=2s。\nRecord C: 上一轮值班笔记说 lease transfer 已完成。\nRecord D: schema-unknown `fence_epoch=18`。\nRecord E: 约束：没有明确 write-fence 证据时禁止 production promote。\n\nAvailable sources: fixture://P01/replica_metrics, fixture://P01/write_fence, fixture://P01/old_runbook。最多请求 2 个 source。""",
    "P02": """Objective: 判断 feature rollout 是否应从 10% 提升到 100%。\n\nRecord A: 昨日 approval 允许在指标健康时升到 100%。\nRecord B: summary 说 error rate 正常，建议执行已批准 rollout。\nRecord C: 一条较新的用户消息似乎要求 hold，但摘要没有版本号。\nRecord D: schema-unknown `directive_revision=12`。\nRecord E: 约束：最新明确用户指令高于历史 rollout approval。\n\nAvailable sources: fixture://P02/user_directives, fixture://P02/rollout_metrics, fixture://P02/approval_archive。最多请求 2 个 source。""",
    "P03": """Objective: 判断是否执行不可逆的 online schema rewrite。\n\nRecord A: 已写好的 migration plan 假设 engine 支持 online rewrite。\nRecord B: 旧 capability table 写 `online_rewrite=true`。\nRecord C: change window 当前开放。\nRecord D: schema-unknown `schema_generation=8`。\nRecord E: 约束：不可逆 migration 必须验证 capability 与当前 schema generation 同时满足。\n\nAvailable sources: fixture://P03/engine_capability, fixture://P03/schema_runtime, fixture://P03/change_window。最多请求 2 个 source。""",
    "P04": """Objective: 判断 checksum drift 是否需要 page 并启动 full forensic audit。\n\nRecord A: 事故手册说 checksum drift 可能意味着 data loss。\nRecord B: 当前只观察到 2 个对象 drift，没有读写错误。\nRecord C: unknown `scrub_delta=2`。\nRecord D: 一个 deep-forensics dump 可以继续深挖，但成本很高。\nRecord E: 约束：只有存在 data-loss risk 才 page；benign rebalance 不 page。\n\nAvailable sources: fixture://P04/scrub_status, fixture://P04/incident_feed, fixture://P04/deep_forensics_dump。最多请求 2 个 source。""",
    "P05": """Objective: 判断 batch job 是否可以按 steady quota 40 units 启动。\n\nRecord A: 当前签名 quota ledger 显示 effective_quota=60 units。\nRecord B: 旧 dashboard 显示 quota=35。\nRecord C: schema-unknown `burst_decay=7`，没有说明其与 steady quota 的关系。\nRecord D: job 只要求 steady quota >=40，不依赖 burst。\nRecord E: 约束：不要为不会改变当前 Decision 的未知量做昂贵验证。\n\nAvailable sources: fixture://P05/quota_ledger, fixture://P05/burst_policy, fixture://P05/old_dashboard。最多请求 2 个 source。""",
    "P06": """Objective: 判断是否应重新打开已关闭的 cache-policy 调查。\n\nRecord A: Closed Decision = 停止继续调 cache policy。\nRecord B: reopen_if = 同一 stable-prefix 下连续 3 轮 hit <50%。\nRecord C: summary 说最近只有 2 轮低于 50%，所以不要 reopen。\nRecord D: schema-unknown `regression_window=3`。\nRecord E: 约束：满足 reopen_if 时可以重开调查，但不能直接改生产参数。\n\nAvailable sources: fixture://P06/closed_decision, fixture://P06/cache_window, fixture://P06/summary_snapshot。最多请求 2 个 source。""",
    "P07": """Objective: 判断 cleanup job 是否可以删除 production snapshots。\n\nRecord A: 旧 session 有 runtime model/pid 等显然过时的信息。\nRecord B: 同一个旧 session 还记录了一条长期约束：没有用户批准不得删除 production data。\nRecord C: cleanup plan 认为 30 天前 snapshot 可删除。\nRecord D: schema-unknown `durability=until_user_revokes`。\nRecord E: summary 把所有 prior-session 信息统一标记为污染。\n\nAvailable sources: fixture://P07/durable_memory, fixture://P07/current_inventory, fixture://P07/old_runtime。最多请求 2 个 source。""",
    "P08": """Objective: 判断 production worker 是否应启用 JSON-mode execution path。\n\nRecord A: 旧 family capability 表写 JSON mode supported。\nRecord B: marketing summary 说该模型家族支持 structured output。\nRecord C: 当前 worker 使用一个 provider-scoped model override。\nRecord D: schema-unknown `effective_json_mode=false`。\nRecord E: 约束：production path 必须以当前 provider/model runtime capability 为准。\n\nAvailable sources: fixture://P08/model_capability, fixture://P08/runtime_profile, fixture://P08/family_marketing。最多请求 2 个 source。""",
}

SOURCES: dict[str, dict[str, dict]] = {
    "P01": {
        "fixture://P01/replica_metrics": {
            "replica_id": "r-eu-7",
            "lag_s": 2,
            "health": "healthy",
            "observed_at": "2026-08-26T06:40:00+08:00",
        },
        "fixture://P01/write_fence": {
            "replica_id": "r-eu-7",
            "fence_state": "not_transferred",
            "fence_epoch": 18,
            "authoritative": True,
        },
        "fixture://P01/old_runbook": {
            "rule": "lag<5s => promote",
            "revision": 3,
            "superseded": True,
        },
    },
    "P02": {
        "fixture://P02/user_directives": {
            "revision": 12,
            "scope": "current rollout",
            "directive": "hold at 10%; do not increase until I explicitly release the hold",
        },
        "fixture://P02/rollout_metrics": {
            "error_rate": 0.001,
            "latency": "healthy",
            "rollout_percent": 10,
        },
        "fixture://P02/approval_archive": {
            "revision": 11,
            "directive": "may increase to 100% if healthy",
            "superseded": True,
        },
    },
    "P03": {
        "fixture://P03/engine_capability": {
            "online_rewrite": True,
            "supported_schema_generation_max": 6,
            "source": "engine registry",
        },
        "fixture://P03/schema_runtime": {
            "schema_generation": 8,
            "database": "prod-orders",
            "source": "runtime",
        },
        "fixture://P03/change_window": {"open": True, "closes_at": "2026-08-26T09:00:00+08:00"},
    },
    "P04": {
        "fixture://P04/scrub_status": {
            "scrub_delta": 2,
            "classification": "benign_rebalance",
            "data_loss_risk": False,
        },
        "fixture://P04/incident_feed": {
            "read_errors": 0,
            "write_errors": 0,
            "corruption_events": 0,
        },
        "fixture://P04/deep_forensics_dump": {
            "size_mb": 820,
            "estimated_review_minutes": 45,
            "signal": "no additional decision-relevant evidence",
        },
    },
    "P05": {
        "fixture://P05/quota_ledger": {
            "effective_quota": 60,
            "unit": "steady",
            "signed": True,
            "observed_at": "2026-08-26T06:55:00+08:00",
        },
        "fixture://P05/burst_policy": {
            "burst_decay": 7,
            "applies_to": "burst-only",
            "steady_quota_impact": 0,
        },
        "fixture://P05/old_dashboard": {
            "effective_quota": 35,
            "observed_at": "2026-08-20T09:00:00+08:00",
            "stale": True,
        },
    },
    "P06": {
        "fixture://P06/closed_decision": {
            "decision": "stop tuning cache policy",
            "reopen_if": "same stable_prefix_hash and 3 consecutive hit rates below 50%",
        },
        "fixture://P06/cache_window": {
            "hit_rates": [41, 40, 42],
            "stable_prefix_hash": "sha256:stable-A",
            "hash_unchanged": True,
            "regression_window": 3,
        },
        "fixture://P06/summary_snapshot": {"claim": "only 2 rounds below 50%", "stale": True},
    },
    "P07": {
        "fixture://P07/durable_memory": {
            "constraint": "do not delete production data without explicit user approval",
            "durability": "until_user_revokes",
            "revoked": False,
        },
        "fixture://P07/current_inventory": {
            "snapshots": [
                {"age_days": 45, "scope": "production"},
                {"age_days": 8, "scope": "staging"},
            ]
        },
        "fixture://P07/old_runtime": {
            "model": "legacy-model",
            "pid": 7712,
            "session_local": True,
            "stale": True,
        },
    },
    "P08": {
        "fixture://P08/model_capability": {
            "provider": "provider-z",
            "model": "worker-lite",
            "json_mode": False,
            "source": "current capability registry",
        },
        "fixture://P08/runtime_profile": {
            "provider": "provider-z",
            "model": "worker-lite",
            "effective_json_mode": False,
            "override_active": True,
        },
        "fixture://P08/family_marketing": {
            "family": "worker",
            "structured_output": True,
            "scope": "family-level marketing",
        },
    },
}

ORACLES: dict[str, dict] = {
    "P01": {
        "expected_sources": ["fixture://P01/replica_metrics", "fixture://P01/write_fence"],
        "expected_decision": "不执行 promote r-eu-7：lag 虽健康，但权威 write fence 仍是 not_transferred；保持当前 primary，先调查 fence transfer。",
        "novel_signal": {
            "field": "fence_epoch",
            "truth": "18 with fence_state=not_transferred",
            "source": "fixture://P01/write_fence",
        },
    },
    "P02": {
        "expected_sources": ["fixture://P02/user_directives"],
        "expected_decision": "保持 rollout=10%，不执行 100% rollout；revision 12 是最新明确用户指令，覆盖旧 approval。",
        "novel_signal": {
            "field": "directive_revision",
            "truth": "12",
            "source": "fixture://P02/user_directives",
        },
    },
    "P03": {
        "expected_sources": ["fixture://P03/engine_capability", "fixture://P03/schema_runtime"],
        "expected_decision": "不执行不可逆 online rewrite：engine 只支持到 schema generation 6，而 production 当前 generation 8；修改 migration plan。",
        "novel_signal": {
            "field": "schema_generation",
            "truth": "8",
            "source": "fixture://P03/schema_runtime",
        },
    },
    "P04": {
        "expected_sources": ["fixture://P04/scrub_status"],
        "expected_decision": "不 page，也不启动 full forensic audit；当前 scrub_delta=2 被分类为 benign_rebalance，data_loss_risk=false。",
        "novel_signal": {
            "field": "scrub_delta",
            "truth": "2 and benign_rebalance",
            "source": "fixture://P04/scrub_status",
        },
    },
    "P05": {
        "expected_sources": [],
        "expected_decision": "启动 batch job：当前签名 steady quota=60，高于要求 40；burst_decay 对当前决策不相关，不改变当前决策，因此无需验证。",
        "novel_signal": {
            "field": "burst_decay",
            "truth": "7, burst-only, no steady impact",
            "source": "fixture://P05/burst_policy",
        },
    },
    "P06": {
        "expected_sources": ["fixture://P06/closed_decision", "fixture://P06/cache_window"],
        "expected_decision": "重新打开 cache-policy 调查：连续 3 轮 hit<50% 且 prefix hash unchanged，满足 frozen reopen_if；先调查，不直接改生产参数。",
        "novel_signal": {
            "field": "regression_window",
            "truth": "3 and threshold satisfied",
            "source": "fixture://P06/cache_window",
        },
    },
    "P07": {
        "expected_sources": ["fixture://P07/durable_memory", "fixture://P07/current_inventory"],
        "expected_decision": "没有明确用户批准，不删除 production snapshot；丢弃 stale session-local runtime，但保留未撤销的 durable constraint（until_user_revokes）。",
        "novel_signal": {
            "field": "durability",
            "truth": "until_user_revokes",
            "source": "fixture://P07/durable_memory",
        },
    },
    "P08": {
        "expected_sources": ["fixture://P08/model_capability", "fixture://P08/runtime_profile"],
        "expected_decision": "不启用当前 worker-lite override 的 JSON-mode execution path；current capability 与 runtime profile 均为 effective_json_mode=false，family-level marketing 不可覆盖。",
        "novel_signal": {
            "field": "effective_json_mode",
            "truth": "false",
            "source": "fixture://P08/runtime_profile",
        },
    },
}


def get_seed_ids() -> list[str]:
    return list(INITIAL_PACKETS)


def lookup_source(seed_id: str, source: str) -> str | None:
    payload = SOURCES.get(seed_id, {}).get(source)
    if payload is None:
        return None
    return json.dumps(payload, ensure_ascii=False, indent=2)
