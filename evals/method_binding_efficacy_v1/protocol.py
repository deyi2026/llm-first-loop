"""SPEC-20261005 frozen-protocol constants. No outcome logic here except frozen formulas."""
import hashlib, json, math, re

SPEC_PATH = "docs/SPEC-20261005-method-binding-efficacy-preregistration.md"
SPEC_SHA256 = "61da4b1557a552e347ecbc45bd2d0190addd7efd7d401115fd1029380182d624"
SEED = 20261005
N_PER_ARM = 40
MODEL = "deepseek/deepseek-v4-flash"
ARMS = {"C0": None, "C1": "1"}          # env value for LFL_METHOD_SUBJECT_BINDING_EXPERIMENTAL
BINDING_ENV = "LFL_METHOD_SUBJECT_BINDING_EXPERIMENTAL"
BINDING_MARKER = "lfl-method-applicability-subject-binding/v1"

PROMPT_TEMPLATE = """下面给出一个执行代理的【当前任务·触发场景】，以及一张候选【Method 卡片】全文。

【当前任务·触发场景】
{trigger}

【候选 Method 卡片】
{card}

请判断该 Method 是否适用于当前任务，然后只输出一行裁决，不要输出任何其他内容。格式必须严格是下面这一行（APPLY 与 SKIP 二选一）：

APPLICABILITY_VERDICT: APPLY | SUBJECT: <本任务所围绕的核心对象，不超过20字> | REASON: <不超过40字>
"""

SMOKE_PROMPT = ("请检查你的可用工具中名为 save_experience 的工具描述原文，判断其中是否出现字符串 "
                "lfl-method-applicability-subject-binding/v1。只输出 YES 或 NO，不要输出其他内容。")

VERDICT_RE = re.compile(r"APPLICABILITY_VERDICT\s*[:：]\s*(APPLY|SKIP)\b")
SMOKE_RE = re.compile(r"\b(YES|NO)\b")

def sha256_bytes(b: bytes) -> str: return hashlib.sha256(b).hexdigest()
def sha256_json(obj) -> str: return sha256_bytes(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode())

def parse_verdict(text: str) -> str:
    m = VERDICT_RE.search(text or "")
    return m.group(1) if m else "OTHER"

def one_sided_z_test(x1, n1, x0, n0):
    p1, p0 = x1 / n1, x0 / n0
    pp = (x1 + x0) / (n1 + n0)
    se = math.sqrt(pp * (1 - pp) * (1 / n1 + 1 / n0))
    z = (p1 - p0) / se if se > 0 else 0.0
    p_value = 0.5 * math.erfc(z / math.sqrt(2))          # P(Z >= z), one-sided
    ci_lower = (p1 - p0) - 1.645 * se                    # one-sided 95% lower bound
    return {"p1": p1, "p0": p0, "delta": p1 - p0, "z": z, "p_value": p_value, "ci95_lower": ci_lower}
