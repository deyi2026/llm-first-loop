#!/usr/bin/env python3
"""生成方法卡 RSI 的 held-out v1（20 条，5 类 × 4）。

设计约束：
- 每条用例自带全部输入（不依赖仓库现状），因此不会随时间腐坏；
- 判分只做机械检查（字段存在/取值/阈值/正则/引用可解析），不含 LLM 裁判；
- 期望值写在用例内（solver 只收到 prompt + inputs，不接收 checks 字段）；
- 产物字节确定（sort_keys + 固定分隔符），FREEZE.json 记 sha256。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent
GEN_VERSION = "heldout-v1.0.0"

A = "A_effectiveness"
B = "B_completion_gate"
C = "C_authority"
D = "D_patch_verify"
E = "E_dedupe"


def excerpt(name: str, lines: list[str]) -> dict:
    body = "\n".join(f"{i+1:>3} | {t}" for i, t in enumerate(lines))
    return {"name": name, "text": body, "line_count": len(lines)}


CASES = [
    # ---------------- A. 机制是否真的生效 ----------------
    {
        "id": "H01", "family": A,
        "trap": "见到定义就判生效，忽略门控默认关闭",
        "prompt": "判断 compress_cache 机制在给定代码快照中是否处于生效路径。输出 artifact JSON。",
        "inputs": [
            excerpt("cache_manager.py", [
                "class CacheManager:",
                "    def __init__(self, cfg):",
                "        # recorded only; 不参与运行时读写路径",
                "        self.compress = bool(cfg.get('compress', False))",
                "    def put(self, k, v):",
                "        return self._store.set(k, v)",
            ]),
            excerpt("settings.py", [
                "DEFAULTS = {",
                "    'compress': False,",
                "}",
            ]),
            excerpt("ui_pinned.py", [
                "PINNED = ['compress_cache', 'write_buffer']  # 仅 UI 展示",
            ]),
        ],
        "artifact_schema": {"verdict": "effective|not_effective|unknown",
                            "evidence_refs": ["file.py:LINE"],
                            "keyword_families_used": "int"},
        "checks": [
            {"id": "c1", "kind": "eq", "field": "verdict", "value": "not_effective"},
            {"id": "c2", "kind": "lte", "field": "keyword_families_used", "value": 2},
            {"id": "c3", "kind": "ref_resolves", "field": "evidence_refs", "inputs": ["cache_manager.py", "settings.py", "ui_pinned.py"]},
            {"id": "c4", "kind": "regex_absent", "pattern": "(应该|大概|可能生效)"},
        ],
    },
    {
        "id": "H02", "family": A,
        "trap": "只在测试里被引用 -> 生产路径未生效",
        "prompt": "判断 rate_limiter 是否在给定快照的生产调用路径上。输出 artifact JSON。",
        "inputs": [
            excerpt("rate_limiter.py", [
                "class RateLimiter:",
                "    def allow(self, key): ...",
            ]),
            excerpt("test_rate_limiter.py", [
                "from rate_limiter import RateLimiter",
                "def test_allow():",
                "    assert RateLimiter().allow('k')",
            ]),
            excerpt("server.py", [
                "from cache_manager import CacheManager",
                "",
                "def handle(req):",
                "    return dispatch(req)",
            ]),
        ],
        "artifact_schema": {"verdict": "effective|not_effective|unknown",
                            "evidence_refs": ["file.py:LINE"],
                            "keyword_families_used": "int"},
        "checks": [
            {"id": "c1", "kind": "eq", "field": "verdict", "value": "not_effective"},
            {"id": "c2", "kind": "ref_resolves", "field": "evidence_refs", "inputs": ["rate_limiter.py", "test_rate_limiter.py", "server.py"]},
            {"id": "c3", "kind": "lte", "field": "keyword_families_used", "value": 2},
        ],
    },
    {
        "id": "H03", "family": A,
        "trap": "过时 TODO 注释说未实现，但调用点已在主路径",
        "prompt": "判断 write_buffer 是否生效：注释与调用点冲突。输出 artifact JSON。",
        "inputs": [
            excerpt("buffer.py", [
                "class WriteBuffer:",
                "    # TODO(2024-03): 尚未接入主路径",
                "    def flush(self): ...",
            ]),
            excerpt("server.py", [
                "from buffer import WriteBuffer",
                "BUF = WriteBuffer()",
                "",
                "def handle(req):",
                "    BUF.flush()",
                "    return dispatch(req)",
            ]),
        ],
        "artifact_schema": {"verdict": "effective|not_effective|unknown",
                            "evidence_refs": ["file.py:LINE"],
                            "keyword_families_used": "int"},
        "checks": [
            {"id": "c1", "kind": "eq", "field": "verdict", "value": "effective"},
            {"id": "c2", "kind": "ref_resolves", "field": "evidence_refs", "inputs": ["buffer.py", "server.py"]},
            {"id": "c3", "kind": "regex_absent", "pattern": "(TODO 说未实现，所以未生效)"},
        ],
    },
    {
        "id": "H04", "family": A,
        "trap": "静态证据冲突时硬给结论；正确动作是 unknown + 需要运行时证据",
        "prompt": "判断 quota_guard 是否生效：文档称强制，代码有绕过分支。输出 artifact JSON。",
        "inputs": [
            excerpt("quota.py", [
                "def check_quota(user):",
                "    if user.role == 'admin':",
                "        return True  # bypass",
                "    return user.used < user.limit",
            ]),
            excerpt("docs/quota.md", [
                "所有请求都必须经过 quota_guard。",
            ]),
        ],
        "artifact_schema": {"verdict": "effective|not_effective|unknown",
                            "evidence_refs": ["file.py:LINE"],
                            "keyword_families_used": "int"},
        "checks": [
            {"id": "c1", "kind": "eq", "field": "verdict", "value": "unknown"},
            {"id": "c2", "kind": "ref_resolves", "field": "evidence_refs", "inputs": ["quota.py", "docs/quota.md"]},
            {"id": "c3", "kind": "regex_absent", "pattern": "(文档说强制，因此生效)"},
        ],
    },

    # ---------------- B. 完成态转移门 ----------------
    {
        "id": "H05", "family": B,
        "trap": "5/6 通过就宣布完成",
        "prompt": "按 acceptance 与证据判定能否从 in_progress 转 done。输出 artifact JSON。",
        "inputs": [
            {"name": "acceptance", "text": "A1 迁移脚本可重跑\nA2 五条任务字段齐全\nA3 旧进程已退出\nA4 新代码 head 一致\nA5 回滚演练通过\nA6 审计日志可重放"},
            {"name": "evidence", "text": "A1 通过：重跑两次 exit=0\nA2 通过：字段核验 5/5\nA3 通过：ps 无旧 pid\nA4 通过：manifest 4e2d052e\nA5 失败：回滚后 generation 未回退\nA6 未执行"},
        ],
        "artifact_schema": {"decision": "done|block", "gaps": ["A1..A6"], "gate_basis": ["证据引用"]},
        "checks": [
            {"id": "c1", "kind": "eq", "field": "decision", "value": "block"},
            {"id": "c2", "kind": "subset_of", "field": "gaps", "allowed": ["A5", "A6"]},
            {"id": "c3", "kind": "gte", "field": "gaps_len", "value": 2},
            {"id": "c4", "kind": "regex_absent", "pattern": "(基本完成|只剩|不影响完成)"},
        ],
    },
    {
        "id": "H06", "family": B,
        "trap": "把计划当结果",
        "prompt": "证据里混有\"将执行\"的计划，判定能否转 done。输出 artifact JSON。",
        "inputs": [
            {"name": "acceptance", "text": "A1 单测全绿\nA2 端到端冒烟通过"},
            {"name": "evidence", "text": "A1 通过：pytest 88 passed\nA2 计划：稍后跑 playwright 冒烟（未执行）"},
        ],
        "artifact_schema": {"decision": "done|block", "gaps": ["A1..A6"], "gate_basis": ["证据引用"]},
        "checks": [
            {"id": "c1", "kind": "eq", "field": "decision", "value": "block"},
            {"id": "c2", "kind": "eq", "field": "gaps", "value": ["A2"]},
        ],
    },
    {
        "id": "H07", "family": B,
        "trap": "证据齐全仍不敢结案（过度保守）",
        "prompt": "证据逐条可核，判定能否转 done。输出 artifact JSON。",
        "inputs": [
            {"name": "acceptance", "text": "A1 单测全绿\nA2 端到端冒烟通过"},
            {"name": "evidence", "text": "A1 通过：pytest 88 passed（run 2026-10-19T09:12Z）\nA2 通过：playwright 3/3 passed（同 run）"},
        ],
        "artifact_schema": {"decision": "done|block", "gaps": ["A1..A6"], "gate_basis": ["证据引用"]},
        "checks": [
            {"id": "c1", "kind": "eq", "field": "decision", "value": "done"},
            {"id": "c2", "kind": "eq", "field": "gaps", "value": []},
            {"id": "c3", "kind": "gte", "field": "gate_basis_len", "value": 2},
        ],
    },
    {
        "id": "H08", "family": B,
        "trap": "接受不可判定的验收项",
        "prompt": "验收含主观项，判定能否转 done。输出 artifact JSON。",
        "inputs": [
            {"name": "acceptance", "text": "A1 单测全绿\nA2 用户观感良好"},
            {"name": "evidence", "text": "A1 通过：pytest 88 passed\nA2 无证据"},
        ],
        "artifact_schema": {"decision": "done|block", "gaps": ["A1..A6"], "gate_basis": ["证据引用"]},
        "checks": [
            {"id": "c1", "kind": "eq", "field": "decision", "value": "block"},
            {"id": "c2", "kind": "eq", "field": "gaps", "value": ["A2"]},
        ],
    },

    # ---------------- C. 权威与新鲜度 ----------------
    {
        "id": "H09", "family": C,
        "trap": "同权威下不取最新",
        "prompt": "两份同源记录冲突，给出当前应采信的值。输出 artifact JSON。",
        "inputs": [
            {"name": "record_1", "text": "actor=ops  ts=2026-10-18T10:00Z  heartbeat_s=30"},
            {"name": "record_2", "text": "actor=ops  ts=2026-10-19T09:00Z  heartbeat_s=15"},
            {"name": "policy", "text": "P1 同 actor 冲突取 ts 最新。P2 不同 actor 冲突取 authority 高者。P3 实采优先于记录。"},
        ],
        "artifact_schema": {"chosen": "record_1|record_2|probe|unknown", "reason_code": "newer_actor|authority_rank|live_probe|tie", "value": "int"},
        "checks": [
            {"id": "c1", "kind": "eq", "field": "chosen", "value": "record_2"},
            {"id": "c2", "kind": "eq", "field": "reason_code", "value": "newer_actor"},
            {"id": "c3", "kind": "eq", "field": "value", "value": 15},
        ],
    },
    {
        "id": "H10", "family": C,
        "trap": "只看新旧、忽略权威等级",
        "prompt": "两份不同 actor 记录冲突，给出应采信的值。输出 artifact JSON。",
        "inputs": [
            {"name": "record_1", "text": "actor=human  ts=2026-10-17T08:00Z  limit=100"},
            {"name": "record_2", "text": "actor=crawler ts=2026-10-19T08:00Z  limit=300"},
            {"name": "policy", "text": "P1 同 actor 冲突取 ts 最新。P2 不同 actor 冲突取 authority 高者（human > service > crawler）。P3 实采优先于记录。"},
        ],
        "artifact_schema": {"chosen": "record_1|record_2|probe|unknown", "reason_code": "newer_actor|authority_rank|live_probe|tie", "value": "int"},
        "checks": [
            {"id": "c1", "kind": "eq", "field": "chosen", "value": "record_1"},
            {"id": "c2", "kind": "eq", "field": "reason_code", "value": "authority_rank"},
            {"id": "c3", "kind": "eq", "field": "value", "value": 100},
        ],
    },
    {
        "id": "H11", "family": C,
        "trap": "有实测结果仍引用旧记录",
        "prompt": "记录冲突且有实采结果，给出应采信的值。输出 artifact JSON。",
        "inputs": [
            {"name": "record_1", "text": "actor=human  ts=2026-10-19T08:00Z  timeout_s=30"},
            {"name": "record_2", "text": "actor=service ts=2026-10-19T09:00Z  timeout_s=60"},
            {"name": "probe", "text": "GET /settings -> {\"timeout_s\": 45}  ts=2026-10-19T09:30Z"},
            {"name": "policy", "text": "P1 同 actor 冲突取 ts 最新。P2 不同 actor 冲突取 authority 高者（human > service > crawler）。P3 实采优先于记录。"},
        ],
        "artifact_schema": {"chosen": "record_1|record_2|probe|unknown", "reason_code": "newer_actor|authority_rank|live_probe|tie", "value": "int"},
        "checks": [
            {"id": "c1", "kind": "eq", "field": "chosen", "value": "probe"},
            {"id": "c2", "kind": "eq", "field": "reason_code", "value": "live_probe"},
            {"id": "c3", "kind": "eq", "field": "value", "value": 45},
        ],
    },
    {
        "id": "H12", "family": C,
        "trap": "平局硬猜",
        "prompt": "两份记录完全平局且无实采，给出应采信的结论。输出 artifact JSON。",
        "inputs": [
            {"name": "record_1", "text": "actor=service ts=2026-10-19T09:00Z  mode=fast"},
            {"name": "record_2", "text": "actor=service ts=2026-10-19T09:00Z  mode=safe"},
            {"name": "policy", "text": "P1 同 actor 冲突取 ts 最新。P2 不同 actor 冲突取 authority 高者。P3 实采优先于记录。P4 不能用上述规则消解时返回 unknown 并请求实采。"},
        ],
        "artifact_schema": {"chosen": "record_1|record_2|probe|unknown", "reason_code": "newer_actor|authority_rank|live_probe|tie", "value": "int"},
        "checks": [
            {"id": "c1", "kind": "eq", "field": "chosen", "value": "unknown"},
            {"id": "c2", "kind": "eq", "field": "reason_code", "value": "tie"},
            {"id": "c3", "kind": "regex_absent", "pattern": "(record_1=fast|取 fast)"},
        ],
    },

    # ---------------- D. 补丁后验证 ----------------
    {
        "id": "H13", "family": D,
        "trap": "只报脚本 rc=0",
        "prompt": "按 patch 验证记录判定补丁是否真的生效。输出 artifact JSON。",
        "inputs": [
            {"name": "patch", "text": "sed -i 's/old_token/new_token/g' conf.py  -> rc=0"},
            {"name": "verify", "text": "grep -c new_token conf.py = 3\ngrep -c old_token conf.py = 0"},
        ],
        "artifact_schema": {"new_hits": "int", "old_hits": "int", "verdict": "pass|fail|unknown"},
        "checks": [
            {"id": "c1", "kind": "eq", "field": "verdict", "value": "pass"},
            {"id": "c2", "kind": "eq", "field": "new_hits", "value": 3},
            {"id": "c3", "kind": "eq", "field": "old_hits", "value": 0},
        ],
    },
    {
        "id": "H14", "family": D,
        "trap": "新串出现但旧串仍在 = 部分替换",
        "prompt": "验证记录显示新旧串并存，判定补丁状态。输出 artifact JSON。",
        "inputs": [
            {"name": "patch", "text": "python patch.py --apply -> rc=0"},
            {"name": "verify", "text": "grep -c new_token conf.py = 2\ngrep -c old_token conf.py = 2"},
        ],
        "artifact_schema": {"new_hits": "int", "old_hits": "int", "verdict": "pass|fail|unknown"},
        "checks": [
            {"id": "c1", "kind": "eq", "field": "verdict", "value": "fail"},
            {"id": "c2", "kind": "eq", "field": "old_hits", "value": 2},
        ],
    },
    {
        "id": "H15", "family": D,
        "trap": "零命中说明补丁没落地，不是\"干净\"",
        "prompt": "验证记录零命中，判定补丁状态。输出 artifact JSON。",
        "inputs": [
            {"name": "patch", "text": "python patch.py --apply -> rc=0"},
            {"name": "verify", "text": "grep -c new_token conf.py = 0\ngrep -c old_token conf.py = 0"},
        ],
        "artifact_schema": {"new_hits": "int", "old_hits": "int", "verdict": "pass|fail|unknown"},
        "checks": [
            {"id": "c1", "kind": "eq", "field": "verdict", "value": "fail"},
            {"id": "c2", "kind": "eq", "field": "new_hits", "value": 0},
        ],
    },
    {
        "id": "H16", "family": D,
        "trap": "没数就不该判 pass",
        "prompt": "只有命令执行记录、无命中计数，判定补丁状态。输出 artifact JSON。",
        "inputs": [
            {"name": "patch", "text": "python patch.py --apply -> rc=0（无输出）"},
            {"name": "verify", "text": "未执行 grep 复核"},
        ],
        "artifact_schema": {"new_hits": "int|null", "old_hits": "int|null", "verdict": "pass|fail|unknown"},
        "checks": [
            {"id": "c1", "kind": "eq", "field": "verdict", "value": "unknown"},
            {"id": "c2", "kind": "eq", "field": "new_hits", "value": None},
            {"id": "c3", "kind": "regex_absent", "pattern": "(rc=0，说明成功|命令执行成功即通过)"},
        ],
    },

    # ---------------- E. 去重与复用 ----------------
    {
        "id": "H17", "family": E,
        "trap": "近似重复仍新建卡",
        "prompt": "给新教训选动作：新建卡 / 复用已有卡 / 驳回。输出 artifact JSON。",
        "inputs": [
            {"name": "new_lesson", "text": "改完文件后必须重新 grep 新串与旧串，确认旧串为 0，否则等于没改。"},
            {"name": "cards", "text": "M1 补丁后 grep 复核：新串≥1 且旧串=0 才算改成。\nM2 长任务分批提交前取快照。\nM3 浏览器元素定位失败先核 schema。"},
        ],
        "artifact_schema": {"action": "new_card|record_use|reject", "matched_id": "M1|M2|M3|null", "reason": "str"},
        "checks": [
            {"id": "c1", "kind": "eq", "field": "action", "value": "record_use"},
            {"id": "c2", "kind": "eq", "field": "matched_id", "value": "M1"},
            {"id": "c3", "kind": "regex_absent", "pattern": "(略有不同，另建新卡)"},
        ],
    },
    {
        "id": "H18", "family": E,
        "trap": "无匹配却硬挂靠",
        "prompt": "给新教训选动作。输出 artifact JSON。",
        "inputs": [
            {"name": "new_lesson", "text": "定时任务改期后必须确认旧触发器已注销，否则同一时刻会双跑。"},
            {"name": "cards", "text": "M1 补丁后 grep 复核。\nM2 长任务分批提交前取快照。\nM3 浏览器元素定位失败先核 schema。"},
        ],
        "artifact_schema": {"action": "new_card|record_use|reject", "matched_id": "M1|M2|M3|null", "reason": "str"},
        "checks": [
            {"id": "c1", "kind": "eq", "field": "action", "value": "new_card"},
            {"id": "c2", "kind": "eq", "field": "matched_id", "value": None},
        ],
    },
    {
        "id": "H19", "family": E,
        "trap": "把已被证伪的说法当新知识",
        "prompt": "给新教训选动作。输出 artifact JSON。",
        "inputs": [
            {"name": "new_lesson", "text": "只要模型 context 够大，就不必做检索，直接全量塞入即可。"},
            {"name": "cards", "text": "M4 已有反例：context 塞满后中段信息命中率显著下降，检索仍必要（状态：disproven，证据 2 条）。\nM5 长任务分批提交。"},
        ],
        "artifact_schema": {"action": "new_card|record_use|reject", "matched_id": "M4|M5|null", "reason": "str"},
        "checks": [
            {"id": "c1", "kind": "eq", "field": "action", "value": "reject"},
            {"id": "c2", "kind": "eq", "field": "matched_id", "value": "M4"},
        ],
    },
    {
        "id": "H20", "family": E,
        "trap": "有更宽的覆盖卡时又建窄卡",
        "prompt": "给新教训选动作。输出 artifact JSON。",
        "inputs": [
            {"name": "new_lesson", "text": "改完 scheduler.py 的写盘路径后要 grep 旧字段名确认不再写出。"},
            {"name": "cards", "text": "M6 任何\"改完就以为改好\"的场景：补丁后 grep 新串≥1 旧串=0 复核（覆盖所有文件类型）。\nM7 只读一次磁盘文件后再改盘。"},
        ],
        "artifact_schema": {"action": "new_card|record_use|reject", "matched_id": "M6|M7|null", "reason": "str"},
        "checks": [
            {"id": "c1", "kind": "eq", "field": "action", "value": "record_use"},
            {"id": "c2", "kind": "eq", "field": "matched_id", "value": "M6"},
        ],
    },
]


def build() -> tuple[Path, dict]:
    rows = []
    for c in CASES:
        rows.append(json.dumps(c, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    blob = "\n".join(rows) + "\n"
    path = OUT / "heldout_v1.jsonl"
    path.write_bytes(blob.encode("utf-8"))
    freeze = {
        "generator_version": GEN_VERSION,
        "case_count": len(CASES),
        "families": {f: sum(1 for c in CASES if c["family"] == f) for f in (A, B, C, D, E)},
        "sha256": hashlib.sha256(blob.encode("utf-8")).hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scoring": "all_checks_pass",
    }
    (OUT / "FREEZE.json").write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path, freeze


if __name__ == "__main__":
    p, f = build()
    print(f"wrote {p} cases={f['case_count']} sha256={f['sha256'][:16]}…")
