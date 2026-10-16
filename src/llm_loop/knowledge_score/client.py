"""独立打分器 HTTP 客户端（StartLux-Decision /v1/systemone 协议）.

协议参考 tmp/startlux/bench_scoring.py 与 bench_hard.py（6 例真实验证通过，
本模块不修改 bench 脚本，只照抄协议常量）：

- 请求: POST {"state": ..., "questions": {"usefulness": score(5档),
          "evidence_sufficient": noul}, "return_details": true}
- 响应: {"answers": {"usefulness": {"probabilities": {"0".."4": p},
          "confidence": c}, "evidence_sufficient": {"noul": p}},
          "timing_ms": {...}, "model": "27B-Instant-MLX-8bit"}

严格校验（畸形响应抛 typed 异常，不猜默认值、不静默修补）：
- probabilities 键 "0".."4" 齐全、各值 ∈ [0,1]、和 ≈ 1（容差 0.05，浮点归一化余量）
- confidence / noul ∈ [0,1]

端点从环境变量 LFL_INDEPENDENT_SCORER_URL 读取，默认
http://127.0.0.1:8091/v1/systemone；单例耗时 ~0.6-0.8s，超时默认 120s。
"""

from __future__ import annotations

import http.client
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field

DEFAULT_SCORER_URL = "http://127.0.0.1:8091/v1/systemone"
DEFAULT_TIMEOUT_S = 120.0

# 5 档 criteria——与 tmp/startlux/bench_scoring.py LEVELS 逐字一致（协议常量，勿改文案）
LEVELS = [
    "无帮助: 条目与任务不对题,或使用后无效果",
    "轻微帮助: 仅个别细节被参考,整体路径不受其影响",
    "中等帮助: 部分思路被采纳,需较大改造后起作用",
    "显著帮助: 主要路径按条目执行,明显减少试错",
    "决定性帮助: 条目直接命中问题,照做即解决",
]

LEVEL_LABELS = ("无帮助", "轻微帮助", "中等帮助", "显著帮助", "决定性帮助")

USEFULNESS_QUESTION = {
    "type": "score",
    "criteria": LEVELS,
    "instructions": "该经验条目在此任务中的实际帮助程度是哪一档?",
}

# 证据充分性 noul 问题——文案与 bench_hard.py（F_no_evidence 校准例）一致
EVIDENCE_SUFFICIENT_QUESTION = {
    "type": "noul",
    "criteria": {
        "true": "state 里的信息足以可靠判断帮助程度",
        "false": "信息不足,任何具体档位都是猜测",
    },
    "instructions": "当前 state 提供的证据是否足以支撑判断?",
}

_SUM_TOLERANCE = 0.05


class ScorerError(Exception):
    """独立打分器调用失败（基类）。"""


class ScorerTransportError(ScorerError):
    """网络/超时/HTTP 层失败。"""


class ScorerResponseError(ScorerError):
    """响应结构或数值校验失败（缺键/概率和异常/越界）。"""


@dataclass(frozen=True)
class ScoreResult:
    """一次独立打分的机械解析结果（不含采纳判定）。"""

    probabilities: dict[str, float]
    expected: float
    top_level: int
    top_label: str
    confidence: float
    p_evidence_sufficient: float
    model: str = ""
    timing_ms: dict = field(default_factory=dict)


def build_request_body(state: str) -> dict:
    """按 bench 协议构造 /v1/systemone 请求体。"""
    return {
        "state": str(state or ""),
        "questions": {
            "usefulness": USEFULNESS_QUESTION,
            "evidence_sufficient": EVIDENCE_SUFFICIENT_QUESTION,
        },
        "return_details": True,
    }


def _unit_interval(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScorerResponseError(f"{what} 不是数值: {value!r}")
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise ScorerResponseError(f"{what} 超出 [0,1]: {number}")
    return number


def parse_response(payload: object) -> ScoreResult:
    """严格解析并校验打分响应；畸形输入抛 ScorerResponseError。"""
    if not isinstance(payload, dict):
        raise ScorerResponseError("响应不是 JSON object")
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        raise ScorerResponseError("响应缺少 answers 对象")
    usefulness = answers.get("usefulness")
    if not isinstance(usefulness, dict):
        raise ScorerResponseError("响应缺少 answers.usefulness")
    evidence = answers.get("evidence_sufficient")
    if not isinstance(evidence, dict):
        raise ScorerResponseError("响应缺少 answers.evidence_sufficient")

    raw_probs = usefulness.get("probabilities")
    if not isinstance(raw_probs, dict):
        raise ScorerResponseError("usefulness 缺少 probabilities")
    probabilities: dict[str, float] = {}
    for level in ("0", "1", "2", "3", "4"):
        if level not in raw_probs:
            raise ScorerResponseError(f"probabilities 缺少档位 {level!r}")
        probabilities[level] = _unit_interval(
            raw_probs[level], f"probabilities[{level!r}]"
        )
    total = sum(probabilities.values())
    if abs(total - 1.0) > _SUM_TOLERANCE:
        raise ScorerResponseError(f"probabilities 概率和 {total:.4f} 不 ≈1")

    if "confidence" not in usefulness:
        raise ScorerResponseError("usefulness 缺少 confidence")
    confidence = _unit_interval(usefulness["confidence"], "confidence")
    if "noul" not in evidence:
        raise ScorerResponseError("evidence_sufficient 缺少 noul")
    p_evidence = _unit_interval(evidence["noul"], "evidence_sufficient.noul")

    expected = sum(int(k) * v for k, v in probabilities.items())
    top_level = max(probabilities, key=probabilities.get)  # type: ignore[arg-type]
    top_level_int = int(top_level)
    timing = payload.get("timing_ms")
    return ScoreResult(
        probabilities=probabilities,
        expected=expected,
        top_level=top_level_int,
        top_label=LEVEL_LABELS[top_level_int],
        confidence=confidence,
        p_evidence_sufficient=p_evidence,
        model=str(payload.get("model") or ""),
        timing_ms=timing if isinstance(timing, dict) else {},
    )


def resolve_endpoint(endpoint: str | None = None) -> str:
    """端点解析：显式参数 > 环境变量 LFL_INDEPENDENT_SCORER_URL > 默认值。

    键用字面量（非 SCORER_URL_ENV 变量）：runtime env 守卫按机械可恢复键记账，
    字面量使签名可审计（read|LFL_INDEPENDENT_SCORER_URL）。
    """
    if endpoint:
        return str(endpoint)
    return os.environ.get("LFL_INDEPENDENT_SCORER_URL", "").strip() or DEFAULT_SCORER_URL


def _urlopen(req, timeout):  # 测试注入点（monkeypatch 本属性即可全 mock）
    return urllib.request.urlopen(req, timeout=timeout)


def score_state(
    state: str,
    *,
    endpoint: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> ScoreResult:
    """对单个 state 发起一次独立打分（阻塞 ~0.6-0.8s）。"""
    url = resolve_endpoint(endpoint)
    body = build_request_body(state)
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with _urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise ScorerTransportError(f"打分器 HTTP 错误 {exc.code}: {exc.reason}") from exc
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        http.client.HTTPException,  # P2-1: IncompleteRead 等读体中断（非 OSError）
    ) as exc:
        raise ScorerTransportError(f"打分器传输失败: {exc}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScorerResponseError(f"打分器返回非 JSON 响应: {exc}") from exc
    return parse_response(payload)
