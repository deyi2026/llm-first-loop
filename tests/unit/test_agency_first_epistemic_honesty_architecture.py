from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "docs" / "DESIGN-20260903-llm-agency-first-repair-optimization.md"


def _design() -> str:
    return DESIGN.read_text(encoding="utf-8")


def test_agency_first_architecture_defines_epistemic_honesty() -> None:
    text = _design()

    assert "R6 认识论诚实" in text
    assert "## 1.5 认识论诚实" in text
    assert "当前可核事实" in text
    assert "训练先验不是证据" in text
    assert "未核验 / 当前证据不足 / 推断 / 存在不确定性" in text
    assert "证据对象、版本、时间和运行层必须支持所声称的结论" in text
    assert "不能单独证明运行中的 Web 已加载该版本" in text
    assert "执行完成以真实成功回执" in text


def test_epistemic_honesty_is_provider_agnostic_without_new_semantic_gate() -> None:
    text = _design()

    assert "Provider-agnostic" in text
    for model_family in ("Ornith", "Qwen", "GLM", "MiniMax", "DeepSeek"):
        assert model_family in text

    assert "Provider adapter 只处理 wire protocol" in text
    assert "不得为云端强模型绕过当前事实诚实" in text
    assert "不得为本地模型另建一套程序替它判断的语义控制面" in text

    # 诚实是证据纪律，不是恢复新的 program authority / 固定核验仪式。
    assert "所有回答一律强制工具调用" in text
    assert "所有当前事实固定查 N 个来源" in text
    assert "模型仍自主判断什么证据足够" in text
    assert "不得把整份架构文档重新注入普通 prompt" in text


def test_architecture_and_rule_sot_are_explicitly_linked() -> None:
    text = _design()

    assert "RULE-AI-01" in text
    assert "docs/ai_rules.md" in text
    assert "src/llm_loop/core/prompt.py" in text
