"""T47: AI 规则一致性校验（FR-AUD-DOC-02，2026-08-20 P2 重构版）.

P2 架构（docs/ARCHITECTURE-cache-stable-rules.md）:
- prompt.py = L0 稳定核心（身份/协议硬约束/信息通道/必读指令），前缀几乎永不变。
- 规则移出前缀，存 docs/ai_rules.lite.md（版本化，AI 经 read_file(full=true) 按需读取）。
- 详细 SoT docs/ai_rules.md 为 lite 的超集（人工/演进参考）。

机械层校验（自动化）:
1. L0 prompt 含必读指令（lite 引用 + full=true）与协议硬约束关键词；
2. lite 文件（中/英）存在，中文 lite < 3000 字符（默认 read_file 不截断），头部含 version=N；
3. lite 的约束编号与关键动作词在详细 SoT（ai_rules.md）中可找到对应（超集防漂移）。

语义层（浓缩不失真）不伪装自动化——由 code_review + 每版人工抽查承担。
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]

# L0 稳定核心必须包含的元素（协议硬约束 + 必读指令 + 通道声明）
_L0_REQUIRED = [
    "reasoning_content",  # M20 思考链回传（协议硬约束）
    "tool_call_id",  # 声明↔回执配对
    "不静默",  # 不静默吞错/降级
    "ai_rules.lite.md",  # 必读指令指向规则文件
    "read_file(full=true)",  # 防截断读取
    "architecture_status",  # 通道声明（架构事实）
]

# lite 约束编号 → SoT 关键动作词（lite 浓缩自 SoT，动作词必须在 SoT 存在）
_LITE_TO_SOT_KEYWORDS = {
    "1": "诚实",  # RULE-AI-01
    "2": "参数",  # RULE-AI-02
    "3": "停滞",  # RULE-AI-03
    "4": "程序异常",  # RULE-AI-04
    "5": "[[memory]]",  # RULE-AI-05
    "6": "submit_evolution",  # RULE-AI-06
    "7": "工具优先",  # RULE-AI-07
    "8": "adjust_strategy",  # RULE-AI-08
    "9": "model_catalog",  # RULE-AI-09
    "10": "每轮",  # RULE-AI-10
    "11": "head",  # RULE-AI-11（自截断禁令）
    "12": "身份",  # RULE-AI-12
    "13": "dsh_task",  # RULE-AI-13
    "14": "interop",  # RULE-AI-14
    "15": "codearts_dispatch",  # RULE-AI-15
    "16": "缓存",  # RULE-AI-16
    "17": "分段",  # RULE-AI-17
    "18": "经验",  # RULE-AI-18
    "19": "内容消费",  # RULE-AI-19（2026-08-20 对齐 DSH 交互范式）
}


def _read(path: str) -> str:
    return (_ROOT / path).read_text(encoding="utf-8")


def test_l0_prompt_has_required_elements():
    """L0 稳定核心必含: 协议硬约束 + 必读指令 + 通道声明."""
    prompt = _read("src/llm_loop/core/prompt.py")
    for kw in _L0_REQUIRED:
        assert kw in prompt, f"prompt.py L0 缺关键元素: {kw}"


def test_l0_prompt_rules_moved_out():
    """规则细节已移出前缀（L0 不含具体规则正文，前缀可稳定）."""
    prompt = _read("src/llm_loop/core/prompt.py")
    for banned in ["RULE-AI-03", "停滞自主调整", "截断提炼与轮次耗尽", "工具轮思考链最短化"]:
        assert banned not in prompt, f"L0 不应再含规则细节: {banned}"


def test_lite_file_exists_and_within_read_limit():
    """lite 文件存在；中文 lite < 3000 字符（默认 read_file 不截断）."""
    for name in ["docs/ai_rules.lite.md", "docs/ai_rules.lite.en.md"]:
        p = _ROOT / name
        assert p.exists(), f"{name} 缺失"
        content = p.read_text(encoding="utf-8")
        assert "version=" in content.splitlines()[0], f"{name} 首行缺 version 标记"
    zh = _read("docs/ai_rules.lite.md")
    assert len(zh) < 3000, f"中文 lite {len(zh)} 字符 ≥3000（默认 read_file 会截断）"


def test_lite_is_superset_checked_against_sot():
    """lite 约束编号与关键动作词在详细 SoT（ai_rules.md）中可找到（防浓缩漂移）."""
    sot = _read("docs/ai_rules.md")
    lite = _read("docs/ai_rules.lite.md")
    # 约束编号 1-18 在 lite 中逐条存在
    for n in _LITE_TO_SOT_KEYWORDS:
        assert re.search(rf"^{n}[^\d]", lite, re.M), f"lite 缺约束 {n}"
    # 每个动作词在 SoT 存在（lite 是 SoT 的浓缩，动作词必须来源于 SoT）
    for n, kw in _LITE_TO_SOT_KEYWORDS.items():
        assert kw in sot, f"SoT(ai_rules.md) 缺 lite 约束 {n} 的动作词: {kw}"


def test_lite_version_matches_snapshot_reader():
    """lite 头部 version 与 architecture_status 读取逻辑一致（version=N 可提取）."""
    import sys

    sys.path.insert(0, str(_ROOT / "src"))
    from llm_loop.introspection.status import _rules_version

    lite = _read("docs/ai_rules.lite.md")
    header = lite.splitlines()[0]
    m = re.search(r"version=(\d+)", header)
    assert m, "lite 首行 version 格式: version=N"
    assert _rules_version() == m.group(1), (
        f"_rules_version()={_rules_version()!r} 与 lite 版本 {m.group(1)} 不一致"
    )
