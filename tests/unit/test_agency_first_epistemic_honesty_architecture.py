from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "docs" / "DESIGN-20260903-llm-agency-first-repair-optimization.md"


def _design() -> str:
    return DESIGN.read_text(encoding="utf-8")


def test_agency_first_architecture_defines_epistemic_honesty() -> None:
    text = _design()

    assert "R9 Prefix Stability as a Mechanical Resource Boundary" in text
    assert "R8 Runtime Identity Boundary" in text
    assert "R7 诚实感官/连续性继续有效" in text
    assert "## 1.5 认识论诚实" in text
    assert "当前可核事实" in text
    assert "训练先验不是证据" in text
    assert "未核验 / 当前证据不足 / 推断 / 存在不确定性" in text
    assert "证据对象、版本、时间和运行层必须支持所声称的结论" in text
    assert "不能单独证明运行中的 Web 已加载该版本" in text
    assert "执行完成以真实成功回执" in text
    assert "## 1.6 诚实感官的四个机械推论" in text
    assert "失败回执是事实，不是修复计划" in text
    assert "默认模型视图应限定当前 session" in text
    assert "active continuity 不得归零" in text
    assert "Working-set 收敛是表示/资源机制" in text
    assert "不得恢复隐藏 reasoning" in text
    assert "禁止恢复已被实测否决的“每轮一暴露就重写旧前缀”方案" in text
    assert "## 1.7 运维沙箱不是 LFL Runtime 身份" in text
    assert "这些值不得因为一次 restart/deploy 动作而无意变成" in text
    assert "不能用 operator 的临时沙箱替代这些 LFL 安全机制" in text
    assert "DSH_HOME=<mirror>/data/dsh-home" in text
    assert "## 1.8 Provider Prefix 稳定是机械表示职责" in text
    assert "Stable Compaction Frontier" in text
    assert "事件重放与当前进程不能拥有两套不同的 compaction 世界" in text
    assert "soft result count" in text
    assert "不新增第二套 coalescer" in text
    assert "healthy comparable hit" in text
    assert "structural warmup" in text


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
    assert "不得把安装依赖、切换工具/模型、重试、修改任务方案等策略" in text


def test_architecture_and_rule_sot_are_explicitly_linked() -> None:
    text = _design()

    assert "RULE-AI-01" in text
    assert "docs/ai_rules.md" in text
    assert "src/llm_loop/core/prompt.py" in text
