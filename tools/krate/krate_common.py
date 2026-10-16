"""K-Rate shared constants: scorer prompt, thresholds, aggregation math.
All numbers here are the single source of truth for scoring + disposition gates."""
import hashlib, json

# --- scorer endpoint defaults ---
SCORER_PORT = "8091"          # 27B-Instant-MLX-8bit (verified better calibration than 0.8B)
SCORER_PATH = "/v1/systemone"

# --- usefulness levels (verified against 6 bench cases incl. placebo/no-evidence) ---
LEVELS = [
    "0 无帮助: 条目与任务不对题,或使用后无效果",
    "1 轻微帮助: 仅个别细节被参考,整体路径不受其影响",
    "2 中等帮助: 部分思路被采纳,需较大改造后起作用",
    "3 显著帮助: 主要路径按条目执行,明显减少试错",
    "4 决定性帮助: 条目直接命中问题,照做即解决",
]

# --- evidence-sufficiency bands (from hard-case F: 27B gave p=0.335 conf=0.000) ---
SUFF_INSUFFICIENT = 0.35   # below  -> event scores NOTHING, only counted
SUFF_BORDERLINE   = 0.65   # between -> scores at half weight

# --- aggregation prior (Bayesian shrinkage: one lucky 4 must not top the index) ---
PRIOR_MU = 2.0
PRIOR_K  = 2.0

# --- evidence_level weights (self-report bias control: settlement field, not invented) ---
EV_WEIGHT = {"model_declared": 0.6, "observation_linked": 1.0, "independently_evaluated": 1.2}

# --- age decay: none for 30d, then linear to max 0.6 ---
DECAY_FREE_DAYS = 30
DECAY_MAX = 0.6

# --- disposition gates (numeric standard; script only SUGGESTS, model executes via native tools) ---
GATE_QUALIFY   = {"composite_min": 3.0, "n_valid_min": 3, "recent_days": 30}
GATE_DEMOTE    = {"n_valid_min": 3, "e_shrunk_max": 1.5}
GATE_INVALIDATE_HINDERED = 2
GATE_REFINE_ZERO_RATIO   = 0.70
GATE_STALE_DAYS = 45
GATE_RECEIPT_BAD_RATIO   = 0.60


def questions():
    return {
        "usefulness": {"type": "score", "criteria": LEVELS,
                       "instructions": "该知识条目在此任务中的实际帮助程度是哪一档?"},
        "evidence_sufficient": {"type": "noul",
            "criteria": {"true": "state 里的信息足以可靠判断帮助程度",
                         "false": "信息不足,任何具体档位都是猜测"},
            "instructions": "当前 state 提供的证据是否足以支撑判断?"},
    }


def prompt_hash() -> str:
    blob = json.dumps({"levels": LEVELS, "questions": questions()}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def event_class(p_suff: float) -> str:
    if p_suff < SUFF_INSUFFICIENT:
        return "insufficient"
    if p_suff < SUFF_BORDERLINE:
        return "borderline"
    return "valid"


def event_weight(ev_level: str, cls: str) -> float:
    w = EV_WEIGHT.get(ev_level or "model_declared", 0.6)
    return w * (0.5 if cls == "borderline" else 1.0)


def shrinkage(pairs) -> float:
    """pairs: [(weight, expected_score)] -> Bayesian-shrunk mean toward PRIOR_MU."""
    sw = sum(w for w, _ in pairs)
    if sw <= 0:
        return PRIOR_MU
    return (PRIOR_K * PRIOR_MU + sum(w * e for w, e in pairs)) / (PRIOR_K + sw)


def age_decay(age_days: float) -> float:
    if age_days <= DECAY_FREE_DAYS:
        return 0.0
    return min(DECAY_MAX, 0.02 * (age_days - DECAY_FREE_DAYS))
