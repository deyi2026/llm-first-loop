"""EVO-20261101-66eac12e 回归：grill_me 必须消费 design 正文并标注 mode."""

from __future__ import annotations

from llm_loop.introspection.tools_skills import run_grill_me

DESIGN_A = (
    "## 2.3 缓存失效\n"
    "TTL=300s，命中率目标 0.85；失效时回源到 store_alpha。\n"
    "## 4.1 回滚\n"
    "回滚窗口 10 分钟，超过则人工介入。"
)
DESIGN_B = (
    "## 7.2 队列背压\n"
    "inflight_limit=64，积压超 1000 条时阻塞生产者 pipeline_beta。\n"
    "## 8.4 观测\n"
    "延迟 p99 必须低于 120ms。"
)
DESIGN_FLAT = "就是一个想法，没有结构也没有数字。"


def _run(design: str) -> str:
    result = run_grill_me(object(), object(), {"design": design, "depth": 2})
    return result.content


def _anchor_lines(text: str) -> list[str]:
    head = text.split("## 🔍 定点追问")
    if len(head) < 2:
        return []
    body = head[1].split("## 🎯")[0]
    return [line for line in body.splitlines() if line.startswith("- 〔")]


def test_anchored_mode_is_labelled_with_anchor_count() -> None:
    text = _run(DESIGN_A)
    assert "**mode**: design_anchored" in text
    assert "anchors=" in text


def test_questions_quote_design_identifiers() -> None:
    text = _run(DESIGN_A)
    anchors = _anchor_lines(text)
    assert anchors, text
    joined = "\n".join(anchors)
    assert ("2.3" in joined) or ("store_alpha" in joined) or ("0.85" in joined)


def test_different_designs_yield_different_questions() -> None:
    first = set(_anchor_lines(_run(DESIGN_A)))
    second = set(_anchor_lines(_run(DESIGN_B)))
    assert first and second
    assert first != second
    assert not (first & second)


def test_unstructured_design_declares_template_only() -> None:
    text = _run(DESIGN_FLAT)
    assert "**mode**: template_only" in text
    assert "与本次 design 的具体内容无关" in text
    assert _anchor_lines(text) == []
