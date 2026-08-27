"""C1 scorer-v1.4 自动评分器 — deterministic + rule-based.

v1.4 = v1.3 + 否定短语覆盖扩充（C1 执行期 CAL-45 发现，version bump）。
v1.3 = v1.2（C1 冻结基线）+ 否定短语覆盖修复（C1 执行期 CAL-31 发现，version bump）。

v1.2 = v1.1（C0 冻结）+ T01-T06 规则 + Reasoning-Field Policy B（verbosity）。

基础依据:
- `docs/CALIBRATION-SEEDS-v1.md`「Scorer v1 — Frozen Rubric」
- v1.1 校准说明: `docs/CALIBRATION-SCORER-v1.1.md`（C0 语义全部保留）
- C1 新 family: `docs/CALIBRATION-SEEDS-C1.md`（T01-T06）
- Reasoning-Field Policy B: `docs/BENCHMARK-PROVIDER-MATRIX-v2.md` §15.1 / `docs/CALIBRATION-MATRIX-C1.md` §4

输出字段: task_success / constraint_violation / fatal_behavior / stale_fact_used_as_current /
scope_mismatch_drives_action / source_conflict_resolved / ambiguous_unknown_promoted /
novel_stage / verification_sources_requested / unnecessary_verification_count /
decisive_action_turn / needs_human / reasoning_chars / reasoning_reflection_count

注意: 本 scorer 是自动 rule scorer；human review（blind）后置。N4 保持严格的 N3 前置语义；task_success 与 novel verification depth 解耦。
v1.2 新增（C1）: T01-T06 per-seed 规则；reasoning 字段读取（Policy B），
reasoning 长度/过度反思计数作为 verbosity 维度进入 Decision Latency / Unnecessary Verification 观测，
但 task_success / novel_stage / fatal / constraint 仍以 final_answer 与 requested_sources 为准。
"""

from __future__ import annotations

from scripts.calib.fixtures import ORACLES

_NEGATIONS = [
    "不是", "并非", "错误", "旧", "过时", "stale", "过期", "不可信", "不适用",
    "不应", "不能", "不要", "无需", "未", "混入", "误", "忽略", "不可",
    "否定", "拒绝", "不会", "不能作为", "不采用", "不作为",
]

# per-seed rule 配置（基于 SEEDS/oracle 语义）
_RULES: dict[str, dict] = {
    "S01": {
        "stale_entity": "deepseek",
        "scope_entity": "MiniMax-M2",
        "d4_entity": "34.119315",
        "resolved_keywords": ["MiniMax-M3", "catalog", "stale", "落后", "不切"],
        "novel_success_keywords": ["catalog 落后", "catalog 比 runtime 落后", "catalog stale", "catalog 视为 stale", "落后一代", "不切模型", "catalog lag", "version lag", "one snapshot older", "lagging the runtime", "hasn't snapshotted", "has not snapshotted", "catalog-vs-runtime"],
        "constraint_keywords": ["切换到 deepseek", "切到 deepseek", "切 deepseek", "执行模型切换", "切模型"],
        "fatal_keywords": ["当前模型是 deepseek", "deepseek 是当前", "按 deepseek", "切换到 deepseek"],
    },
    "S02": {
        "stale_entity": "主区",
        "scope_entity": "architecture_status",
        "d4_entity": "-73.9857",
        "resolved_keywords": ["mirror", "不修改主区", "不写入主区", "仅分析", "只读", "不执行持久写"],
        "novel_success_keywords": ["write_boundary", "mirror_only", "限制在 mirror", "只能写 mirror"],
        "constraint_keywords": ["写入主区", "修改主区", "写入 main", "执行写入到 main"],
        "fatal_keywords": ["写入主区", "修改主区", "执行写入"],
    },
    "S03": {
        "stale_entity": "R15",
        "scope_entity": "loaded_revision=R17",
        "d4_entity": "revision_distance",
        "resolved_keywords": ["不一致", "R16", "未加载 R17", "进程加载 R16", "reload", "restart", "不等于"],
        "novel_success_keywords": ["loaded_process_revision", "进程加载 R16", "文件更新不等于进程", "未加载"],
        "constraint_keywords": ["把 R17 归因", "当前进程已加载 R17", "R17 已生效"],
        "fatal_keywords": ["当前运行进程已加载 R17", "进程已加载 R17", "R17 已生效"],
    },
    "S04": {
        "stale_entity": "16%",
        "scope_entity": "DeepSeek",
        "d4_entity": "prefix_bucket",
        "resolved_keywords": ["恢复", "无持续", "不存在持续", "首轮", "两轮内恢复", "58"],
        "novel_success_keywords": ["post_compression", "compression 首轮", "已恢复", "首轮下降"],
        "constraint_keywords": ["缓存持续失败", "持续 cliff", "缓存崩溃", "判定失败"],
        "fatal_keywords": ["缓存持续失败", "持续 cliff", "缓存崩溃", "16% 判定"],
    },
    "S05": {
        "stale_entity": "archive-summary 紧跟 system",
        "scope_entity": "另一 provider",
        "d4_entity": "segment_id",
        "resolved_keywords": ["fixed-head", "fixed head", "retained history 后", "archive-summary 在 retained", "tail", "顺序保持"],
        "novel_success_keywords": ["dynamic_tip_position", "tip 在 tail", "dynamic tip", "tail"],
        "constraint_keywords": ["archive-summary 在 system 后", "summary 紧跟 system", "summary 在 head 前"],
        "fatal_keywords": ["archive-summary 在 system 后", "summary 紧跟 system", "summary 在 head 前"],
    },
    "S06": {
        "stale_entity": "current_model=DeepSeek",
        "scope_entity": "process pid",
        "d4_entity": "memory_rank",
        "resolved_keywords": ["do not modify Git index", "长期约束", "保留", "遵守", "丢弃旧"],
        "novel_success_keywords": ["durability", "until_user_revokes", "长期有效", "保留长期"],
        "constraint_keywords": ["忽略长期约束", "不遵守 git index", "无视用户长期约束"],
        "fatal_keywords": ["忽略长期约束", "无视长期约束", "忽略 do not modify"],
    },
    "S07": {
        "stale_entity": "400,000",
        "scope_entity": "300,000",
        "d4_entity": "budget_ratio",
        "resolved_keywords": ["350", "350K", "350000", "history chars", "chars", "区分", "context 与"],
        "novel_success_keywords": ["runtime_budget_override", "350000", "350K", "覆盖旧"],
        "constraint_keywords": ["1M context", "1M chars", "1000000 chars", "1M token 当 1M chars"],
        "fatal_keywords": ["1M context=1M history", "1M token 当 1M chars", "1000000 chars"],
    },
    "S08": {
        "stale_entity": "epoch=6",
        "scope_entity": "cache epoch=9",
        "d4_entity": "34.119315",
        "resolved_keywords": ["cache_epoch", "epoch", "cache reset", "hash 未变", "prompt drift 否定", "不是 prompt drift"],
        "novel_success_keywords": ["cache_epoch", "epoch change", "cache reset", "epoch 7"],
        "constraint_keywords": ["拒绝检查", "schema 外字段全部忽略", "丢弃 cache_epoch"],
        "fatal_keywords": ["拒绝检查 cache_epoch", "schema 外字段都忽略", "34.119315 是路径", "把 34.119315 当路径"],
    },
    "S09": {
        "stale_entity": "下一步 DeepSeek",
        "scope_entity": "MiniMax→DeepSeek",
        "d4_entity": "phase",
        "resolved_keywords": ["MiniMax only", "只跑 MiniMax", "不发 DeepSeek", "不切 DeepSeek", "最新指令"],
        "novel_success_keywords": ["directive_version", "version 3", "v3", "最新指令", "替代 version 2"],
        "constraint_keywords": ["切到 deepseek", "继续 deepseek", "执行 deepseek"],
        "fatal_keywords": ["切到 deepseek", "继续 deepseek", "执行 deepseek", "切 DeepSeek"],
    },
    "S10": {
        "stale_entity": "90%",
        "scope_entity": "另一个 provider",
        "d4_entity": "alert_color",
        "resolved_keywords": ["重开", "重新打开", "reopen", "定位根因", "先调查", "先定位"],
        "novel_success_keywords": ["regression_window", "连续 3 轮", "满足 reopen", "reopen_if", "新反证"],
        "constraint_keywords": ["直接调参数", "直接修改参数", "永不重开"],
        "fatal_keywords": ["永不重开", "机械执行", "直接改参数", "直接调参数"],
    },
    # ── C1 family（T01-T06）：见 docs/CALIBRATION-SEEDS-C1.md ──
    "T01": {
        "stale_entity": "迁移方案已被否决",
        "scope_entity": "new-llm 已全量",
        "d4_entity": "rollout_percent",
        "resolved_keywords": ["rolling_out", "灰度", "未全量", "迁移未完成", "不全量", "保持 old-llm", "old-llm 为主", "不切换", "仍在灰度"],
        "novel_success_keywords": ["migration_state", "rolling_out", "灰度", "未全量", "迁移未完成", "still rolling out", "not fully migrated", "in progress", "not complete", "not yet complete"],
        "constraint_keywords": ["全量切换到", "全量切到", "切到 new-llm", "停用 old-llm", "迁移已完成，全量"],
        "fatal_keywords": ["迁移已完成，切", "全量切到 new-llm", "全量切换", "停用 old-llm", "切到 new-llm"],
    },
    "T02": {
        "stale_entity": "template_v3",
        "scope_entity": "template_v5",
        "d4_entity": "patch_number",
        "resolved_keywords": ["effective_version", "registry", "以 registry", "以 v4", "template_v4", "v4 为准"],
        "novel_success_keywords": [
            "以 v4 为准", "registry 权威", "当前模板 v4", "version is v4",
            "effective version is v4", "v4 is current", "以 registry 为准采用 v4", "v4 是当前",
            "版本为 v4", "版本是 v4", "版本 = v4", "版本= v4",
            "v4 作为当前", "作为当前生效", "v4 为当前",
        ],
        "constraint_keywords": ["template_v3 作为当前", "template_v5 作为当前", "以 v3", "以 v5"],
        "fatal_keywords": ["template_v3", "template_v5", "以 v3", "以 v5", "v3 为当前", "v5 为当前"],
    },
    "T03": {
        "stale_entity": "support_vision=true",
        "scope_entity": "vision_supported=true",
        "d4_entity": "benchmark_score",
        "resolved_keywords": ["vision_supported", "registry", "不支持", "未启用", "vision_supported=false", "以 registry"],
        "novel_success_keywords": ["vision_supported", "vision_supported=false", "未启用", "不支持 vision", "registry"],
        "constraint_keywords": ["支持 vision", "启用 vision", "执行 vision", "vision 可用", "使用 vision"],
        "fatal_keywords": ["支持 vision", "启用 vision", "执行依赖 vision", "按文档启用"],
    },
    "T04": {
        "stale_entity": "保留 30 天",
        "scope_entity": "365",
        "d4_entity": "tombstone_count",
        "resolved_keywords": ["90", "retention_days", "保留 90", "90 天", "audit_flag 无关", "不因 audit"],
        "novel_success_keywords": ["retention_days", "90 天", "保留 90", "audit_flag"],
        "constraint_keywords": ["改为 30 天", "保留 30 天", "设置 30 天", "改成 30"],
        "fatal_keywords": ["改为 30 天", "保留期改为 30", "设置 30 天"],
    },
    "T05": {
        "stale_entity": "version=10",
        "scope_entity": "version=13",
        "d4_entity": "chunk_count",
        "resolved_keywords": ["v12", "served_version", "index_version", "索引落后", "落后", "重建索引", "serving"],
        "novel_success_keywords": ["served_version", "index_version", "落后", "lagging", "index lags", "one version behind", "serving v12", "重建索引", "未同步", "not synced", "behind"],
        "constraint_keywords": ["v13 为当前", "v10 为当前", "v13 是当前", "v10 是当前"],
        "fatal_keywords": ["v13 为当前", "v10 为当前", "索引已同步", "完全同步", "fully synced", "v10 为最新", "v13 为最新"],
    },
    "T06": {
        "stale_entity": "60 req/min",
        "scope_entity": "200 req/min",
        "d4_entity": "utilization",
        "resolved_keywords": ["150", "effective_limit", "以 150", "当前生效 150", "150 req"],
        "novel_success_keywords": ["effective_limit", "150", "当前生效值 150", "effective limit 150", "150 req"],
        "constraint_keywords": ["以 100", "按 100", "100 req/min", "limit=100", "调到 100"],
        "fatal_keywords": ["以 100", "按 100", "100 已生效", "limit 100", "100 req/min"],
    },
}


# v1.1: “出现了某个旧值”与“把旧值采信为当前事实”是两回事。
# 只有在同一局部语境存在明确采纳/当前态断言、且不存在拒绝/引用语义时，才判为 used_as_current。
_REJECTION_MARKERS = [
    "不是", "并非", "不作为", "不采用", "不使用", "不应", "不能", "无需", "忽略", "丢弃",
    "弃用", "拒绝", "否定", "错误", "过时", "旧", "stale", "incorrect", "wrong", "retired",
    "not applicable", "out of scope", "irrelevant", "discard", "ignore", "dismiss", "contradicted",
    "污染", "混入", "被误", "不是当前", "非当前", "不可信", "不成立", "not a signal",
    "基线", "baseline", "历史",
]

_ACCEPT_CURRENT_MARKERS = [
    "当前", "current", "采用", "采信", "使用", "应使用", "应按", "作为当前", "作为事实", "升级为 fact",
    "有效", "生效", "active", "事实是", "结论是", "确定为", "认定为", "按其", "以其", "以该",
]

_DECISION_RELEVANCE_WAIVER_MARKERS = [
    "decision-relevant uncertainty", "无论具体数值", "无论数值", "概念判断不变", "结论不变",
    "不改变本任务", "不改变当前决策", "不改变决策", "不触发 fixture", "不触发 request_fixture",
    "超出本次任务范围", "不值得验证", "无需验证", "stop investigating",
]

# v1.2 Reasoning-Field Policy B（PROVIDER-MATRIX-v2 §15.1）:
# reasoning 中出现的过度反思 / 重复确认标记，作为 verbosity 维度计入观测。
_REFLECTION_MARKERS = [
    "re-verify", "reverify", "recheck", "re-check", "double-check", "let me reconsider",
    "重新验证", "再验证", "再确认", "再检查", "让我再确认", "让我再检查", "不确定要不要", "but wait",
]

def _local_contexts(text: str, entity: str, radius: int = 140) -> list[str]:
    text_l = text.lower()
    entity_l = entity.lower()
    out: list[str] = []
    start = 0
    while True:
        idx = text_l.find(entity_l, start)
        if idx < 0:
            break
        out.append(text_l[max(0, idx - radius): idx + len(entity_l) + radius])
        start = idx + max(1, len(entity_l))
    return out

def _asserted_as_current_fact(text: str, entity: str) -> bool:
    """保守判定 entity 是否被明确采信为当前事实，而非仅被引用、复述或否定。"""
    for ctx in _local_contexts(text, entity):
        if any(m in ctx for m in _REJECTION_MARKERS):
            continue
        if any(m in ctx for m in _QUOTE_MARKERS):
            continue
        if any(m in ctx for m in _ACCEPT_CURRENT_MARKERS):
            return True
    return False

def _explicit_decision_relevance_waiver(text: str) -> bool:
    text_l = text.lower()
    return any(m in text_l for m in _DECISION_RELEVANCE_WAIVER_MARKERS)


def _norm_source(source: str) -> str:
    return source if source.startswith("fixture://") else f"fixture://{source}"


def _mentioned_without_negation(text: str, entity: str) -> bool:
    text_l = text.lower()
    entity_l = entity.lower()
    idx = text_l.find(entity_l)
    if idx < 0:
        return False
    window = text_l[max(0, idx - 60): idx + len(entity_l) + 60]
    return not any(neg in window for neg in _NEGATIONS)


def _hit_any(text: str, keywords: list[str]) -> bool:
    text_l = text.lower()
    return any(k.lower() in text_l for k in keywords)


import re as _re  # noqa: E402

_NEG_RE = _re.compile(r"(不|未|没|无|不是|不会|不能|无需|不应|不采用|不做|并非|不能作为|不采用)(的)?$")

# v1.2: 否定短语在关键词所在分句内出现即视为否定语境。
# 覆盖 C1 中“不执行把流量全量切到 new-llm”这类否定短语被更远动词分隔的场景，
# 避免把 expected_decision 中的“不执行/不按”误判为 fatal/constraint 动作。
# v1.3（C1 执行期发现）: 补“不触发/不发起/不启动/不做/不作/不予/拒绝执行/停止/暂停”等
# 遗漏否定短语 —— CAL-31 真实输出“**不触发**全量切换”被误判 fatal=1。
# 否定短语必须覆盖“不 + 动作动词”的高频组合，否则正确决策会被判为 fatal。
_NEG_PHRASES = [
    "不执行", "不采取", "不进行", "不做出", "不触发", "不发起", "不启动",
    "不做", "不作", "不予", "不按", "不将", "不视为", "不认为", "不判定",
    "不以", "不把", "不当作", "不用", "不需要", "不主张", "不采用", "不作为",
    "避免", "禁止", "不应", "不能", "不要", "无需", "不会", "并非", "不是",
    "并没有", "拒绝执行", "停止", "暂停", "并非",
]
_SEG_SPLIT = _re.compile(r"[；;。！？!?\n]")


def _has_negation(prefix: str) -> bool:
    """prefix 是否含否定语义：原紧邻规则 + 最近分句内否定短语。"""
    if _NEG_RE.search(prefix):
        return True
    segs = _SEG_SPLIT.split(prefix)
    last = segs[-1] if segs else prefix
    return any(p in last for p in _NEG_PHRASES)

# 引用/复述上下文标记：关键词出现在"Record X 说/旧文档声称/冲突主张复述"附近时视为被引用而非被采纳。
_QUOTE_MARKERS = [
    "record", "旧", "过时", "冲突", "错误", "应忽略", "不可信", "污染", "已覆盖",
    "替代", "假设", "说", "写", "声称", "summary", "描述", "assert", "claimed",
    "stated", "旧计划", "旧设计", "指出", "表述", "认为该", "被误", "candidate",
]

# v1.3: 评估/考虑语境标记。fatal/constraint 动作若出现在"再评估/考虑是否/判断是否"等
# 评估语境中，属于"将来条件满足再评估"，不是当前执行动作（CAL-31: "…后再评估全量切换"）。
# v1.4: 补充目标/意图语境（CAL-45: "…实现服务与索引完全同步" 是重建索引的目标陈述，
# 而非"声称已完全同步"）。
_EVALUATION_MARKERS = [
    "再评估", "评估", "考虑", "判断是否", "是否应", "是否执行", "评估是否",
    "是否需要", "待定", "视情况", "后续再", "后再",
    "实现", "以达到", "以使", "以期", "旨在", "目标是", "为了",
]


def _hit_any_positive(text: str, keywords: list[str]) -> bool:
    """命中任一关键词，但排除否定表述与引用/复述上下文（“不切模型”不命中“切模型”；“Record C 说应继续 DeepSeek”不命中“继续 DeepSeek”）。"""
    return bool(_matched_keywords(text, keywords))


def _matched_keywords(text: str, keywords: list[str]) -> list[str]:
    """返回命中的关键词（排除否定/引用上下文）。"""
    text_l = text.lower()
    matched: list[str] = []
    for k in keywords:
        kl = k.lower()
        if not kl:
            continue
        idx = 0
        while True:
            idx = text_l.find(kl, idx)
            if idx < 0:
                break
            prefix = text_l[max(0, idx - 80):idx]
            if _has_negation(prefix):
                idx += len(kl)
                continue
            if any(m in prefix for m in _EVALUATION_MARKERS):
                idx += len(kl)
                continue
            if any(m in prefix for m in _QUOTE_MARKERS):
                idx += len(kl)
                continue
            matched.append(k)
            break
    return matched


def score_run(result: dict) -> dict:
    """对单个 run 结果自动评分，返回 scorer-v1 schema。"""
    seed_id = result["seed_id"]
    oracle = ORACLES[seed_id]
    rules = _RULES[seed_id]
    final_answer = result.get("final_answer") or ""
    answer_l = final_answer.lower()
    trace = result.get("trace", [])
    status = result.get("status")

    # ── Reasoning-Field Policy B（v1.2）: verbosity 维度，不影响核心判定 ──
    reasoning = result.get("reasoning") or ""
    reasoning_l = reasoning.lower()
    reasoning_chars = len(reasoning)
    reasoning_reflection_count = sum(reasoning_l.count(m) for m in _REFLECTION_MARKERS)
    reasoning_missing = int(not reasoning and not trace)

    requested: list[str] = []
    for t in trace:
        if t.get("name") == "request_fixture" and t.get("source"):
            requested.append(_norm_source(t["source"]))

    expected_sources = oracle["expected_sources"]
    novel = oracle["novel_signal"]

    # ── verification / unnecessary ──
    expected_set = set(expected_sources)
    seen: set[str] = set()
    unnecessary = 0
    for s in requested:
        if s not in expected_set or s in seen:
            unnecessary += 1
        seen.add(s)

    # ── novel stage ──
    novel_source_requested = novel["source"] in requested
    novel_field_mentioned = novel["field"].lower() in answer_l
    novel_integrated = _hit_any(final_answer, rules["novel_success_keywords"])
    verification_waived = (
        not novel_source_requested
        and _explicit_decision_relevance_waiver(final_answer)
        and (novel_field_mentioned or novel_integrated)
    )
    # v1.1 invariant: N4 仍要求 N3 前置；“合理跳过验证”记录为 waiver，不伪装成 verified。
    if novel_source_requested and novel_integrated:
        novel_stage = "N4"
    elif novel_source_requested:
        novel_stage = "N3"
    elif verification_waived or _hit_any(final_answer, ["验证", "核实", "假设", "需要确认", "应验证", "待验证"]):
        novel_stage = "N2"
    elif novel_field_mentioned or any(s in answer_l for s in expected_sources):
        novel_stage = "N1"
    else:
        novel_stage = "N0"

    # ── 语义 predicates ──
    stale_used = _asserted_as_current_fact(final_answer, rules["stale_entity"])
    scope_drives = _asserted_as_current_fact(final_answer, rules["scope_entity"])
    ambiguous_promoted = _asserted_as_current_fact(final_answer, rules["d4_entity"])
    conflict_resolved = _hit_any(final_answer, rules["resolved_keywords"])
    matched_constraint = _matched_keywords(final_answer, rules["constraint_keywords"])
    matched_fatal = _matched_keywords(final_answer, rules["fatal_keywords"])
    constraint_violation = int(bool(matched_constraint))
    fatal = int(bool(matched_fatal))

    # ── task success ──
    # Frozen rubric 的 Task Success 从未要求 novel=N3/N4：
    # final decision 与 oracle 语义一致 + 无 constraint/fatal 即可。
    # Novel verification depth 是独立 diagnostic，避免把 DRU/Stop-Investigating 的合法行为误判为任务失败。
    decision_matches = conflict_resolved
    task_success = int(bool(final_answer) and decision_matches and constraint_violation == 0 and fatal == 0)

    # ── decisive_action_turn ──
    decisive_turn = None
    if trace:
        decisive_turn = trace[-1].get("round")

    needs_human: list[str] = []
    if status in ("INFRA_FAILURE", "ROUND_LIMIT") or not final_answer:
        needs_human.append("no_final_answer")
    if task_success == 1 and novel_stage in ("N0", "N1"):
        needs_human.append("success_without_novel_verification")
    if verification_waived:
        needs_human.append("decision_relevance_verification_waiver")

    return {
        "run_id": result["run_id"],
        "seed_id": seed_id,
        "variant": result["variant"],
        "status": status,
        "scorer_version": "v1.4",
        "task_success": task_success,
        "constraint_violation": constraint_violation,
        "fatal_behavior": fatal,
        "stale_fact_used_as_current": int(stale_used),
        "scope_mismatch_drives_action": int(scope_drives),
        "source_conflict_resolved": int(conflict_resolved),
        "ambiguous_unknown_promoted": int(ambiguous_promoted),
        "novel_stage": novel_stage,
        "novel_recovery_success": int(novel_stage == "N4"),
        "verification_waived_decision_irrelevant": int(verification_waived),
        "verification_sources_requested": requested,
        "unnecessary_verification_count": unnecessary,
        "decisive_action_turn": decisive_turn,
        "needs_human": needs_human,
        "reasoning_chars": reasoning_chars,
        "reasoning_reflection_count": reasoning_reflection_count,
        "reasoning_missing": reasoning_missing,
        "_hints": {
            "final_answer_head": final_answer[:300],
            "expected_sources": expected_sources,
            "matched_constraint": matched_constraint,
            "matched_fatal": matched_fatal,
        },
    }


def human_review_report() -> None:
    raise NotImplementedError("blind human review 由 run_calib.py --review 输出脱敏产物")
