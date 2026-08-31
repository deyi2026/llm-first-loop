"""R8.24-A 模型契约瘦身硬门测试（A-G1/G2/G3/G4 + 常驻红灯断言）.

对应设计包: docs/r824/R8.24-A-model-contract-slimming.md §4.1
- A-G1: system prompt 中"任务开始/规则存疑必读 ai_rules"类指令 chars=0
- A-G2: 11 类运维主题在 lite（中/英）与 system prompt 中 chars=0（full SoT 豁免——超集留档）
- A-G3: 方法层①~⑥在 universal prompt 与 lite 中 chars=0
- A-G4: SYSTEM_PROMPT_EXTRA 自由文本通道 = 0；bundle 通道三态（未配置/合法/非法）
- 常驻断言（§7.1 风险 4）: lite 文件被 prompt 引用即红灯（防 playbook 定位漂移）
- v7 反例自证: 以 .backup/ai_rules.lite.v7.md 旧版验证断言有效性（旧版必"红"）
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]

# A-G1: 必读类指令主题（system prompt 快照 chars=0）
_G1_BANNED_IN_PROMPT = [
    "必读",
    "任务开始",
    "规则存疑",
    "rules_version",
    "重读",
    "read_file(full=true)",
    "以该文件为准",
]

# A-G2: 11 类运维主题（lite 中英 + system prompt chars=0；full SoT 豁免）
_G2_BANNED_TOPICS = {
    "每轮自查": ["每轮自查"],
    "动作链闭环": ["动作链"],
    "回答报工具名": ["回答提本轮工具名", "回答报工具名"],
    "[[memory]] 格式": ["[[memory]]"],
    "cache 纪律": ["规则改动批量低频", "缓存纪律", "batch rule"],
    "长输出分段": ["段标 1/N", "分段输出"],
    "DSH/CodeArts/interop 手册": ["dsh_task", "CodeArts", "data/interop"],
    "经验前置": ["调工具前查最短路径", "经验前置"],
    "模型切换 checklist": ["切必带 reason", "模型切换手册"],
    "中断恢复模型职责": ["中断恢复", "会话重启"],
    "Goal/checkpoint 通用纪律": ["checkpoint", "有界推进"],
}

# A-G3: 方法层①~⑥主题（universal prompt 与 lite chars=0）
_G3_METHOD_TOPICS = [
    "状态追踪",
    "前置自问",
    "假设先行",
    "增量推理",
    "结论固化",
    "工具轮思考链",
]


def _read(path: str) -> str:
    return (_ROOT / path).read_text(encoding="utf-8")


def _build_prompt() -> str:
    import sys

    sys.path.insert(0, str(_ROOT / "src"))
    from llm_loop.core.prompt import build_system_prompt

    return build_system_prompt()


def _lite_contents() -> list[tuple[str, str]]:
    return [
        ("docs/ai_rules.lite.md", _read("docs/ai_rules.lite.md")),
        ("docs/ai_rules.lite.en.md", _read("docs/ai_rules.lite.en.md")),
    ]


# ---------- A-G1: system prompt 必读类指令 chars=0 ----------


def test_g1_prompt_has_no_mandatory_read_directives(monkeypatch):
    monkeypatch.delenv("SYSTEM_PROMPT_EXTRA", raising=False)
    monkeypatch.delenv("LFL_SYSTEM_EXTRA_BUNDLE", raising=False)
    prompt = _build_prompt()
    for topic in _G1_BANNED_IN_PROMPT:
        assert topic not in prompt, f"A-G1 失败: system prompt 含必读类指令主题 {topic!r}"


def test_g1_prompt_has_no_operational_topics(monkeypatch):
    """A-G2 的 system prompt 分量: 11 类运维主题在 prompt 中 chars=0."""
    monkeypatch.delenv("SYSTEM_PROMPT_EXTRA", raising=False)
    monkeypatch.delenv("LFL_SYSTEM_EXTRA_BUNDLE", raising=False)
    prompt = _build_prompt()
    for topic, words in _G2_BANNED_TOPICS.items():
        for w in words:
            assert w not in prompt, f"A-G2(prompt) 失败: 主题 {topic!r} 残留 {w!r}"


# ---------- A-G2: lite 规则资产运维主题 chars=0（full SoT 豁免）----------


def test_g2_lite_has_no_operational_topics():
    for name, content in _lite_contents():
        for topic, words in _G2_BANNED_TOPICS.items():
            for w in words:
                assert w not in content, f"A-G2 失败: {name} 主题 {topic!r} 残留 {w!r}"


def test_g2_lite_retained_rules_present():
    """v8 保留集在场（1/2/3/6/7/12/21 + 灾难安全）——防过度删除回归."""
    zh = _read("docs/ai_rules.lite.md")
    for kw in [
        "1诚实",
        "2参数自主",
        "3停滞调整",
        "6演进/自评",
        "7工具优先",
        "12身份声明",
        "21程序反馈语义",
        "灾难性安全",
    ]:
        assert kw in zh, f"lite v8 保留条目缺失: {kw!r}"


# ---------- A-G3: 方法层①~⑥ chars=0 ----------


def test_g3_method_layer_removed_from_prompt_and_lite(monkeypatch):
    monkeypatch.delenv("SYSTEM_PROMPT_EXTRA", raising=False)
    monkeypatch.delenv("LFL_SYSTEM_EXTRA_BUNDLE", raising=False)
    prompt = _build_prompt()
    for name, content in _lite_contents():
        for topic in _G3_METHOD_TOPICS:
            assert topic not in content, f"A-G3 失败: {name} 方法层主题 {topic!r} 残留"
    for topic in _G3_METHOD_TOPICS:
        assert topic not in prompt, f"A-G3 失败: system prompt 方法层主题 {topic!r} 残留"


def test_g3_method_layer_landed_in_skill():
    """方法层①~⑥ 迁入 skill 且内容在场（下沉落点存在性）."""
    skill = _read("skills/long-task-research/SKILL.md")
    for topic in _G3_METHOD_TOPICS:
        assert topic in skill, f"方法层主题 {topic!r} 未落 skill"


# ---------- 常驻红灯断言（§7.1 风险 4）----------


def test_standing_lite_never_referenced_by_prompt(monkeypatch):
    """lite 文件被 prompt 引用即红灯——playbook 定位漂移防护（常驻 CI）."""
    monkeypatch.delenv("SYSTEM_PROMPT_EXTRA", raising=False)
    monkeypatch.delenv("LFL_SYSTEM_EXTRA_BUNDLE", raising=False)
    prompt = _build_prompt()
    assert "ai_rules.lite" not in prompt, "红灯: lite 被 system prompt 引用（playbook 定位漂移）"


def test_standing_prompt_source_has_no_lite_reference():
    """prompt.py 源码层也禁止引用 lite（防经代码路径回渗；docstring 文档性提及豁免）."""
    import sys

    sys.path.insert(0, str(_ROOT / "src"))
    from llm_loop.core import prompt as prompt_mod

    assert "ai_rules.lite" not in prompt_mod._BASE_PROMPT
    assert "SYSTEM_PROMPT_EXTRA" not in prompt_mod._BASE_PROMPT


# ---------- A-G4: SYSTEM_PROMPT_EXTRA / bundle 三态 ----------


def test_g4_free_text_env_channel_removed(monkeypatch):
    """自由文本 SYSTEM_PROMPT_EXTRA 注入 chars=0（通道已删除）."""
    import sys

    sys.path.insert(0, str(_ROOT / "src"))
    from llm_loop.core.prompt import build_system_prompt

    monkeypatch.setenv("SYSTEM_PROMPT_EXTRA", "## 附加规则\n必须使用简体中文回答。")
    monkeypatch.delenv("LFL_SYSTEM_EXTRA_BUNDLE", raising=False)
    prompt = build_system_prompt()
    assert "必须使用简体中文回答" not in prompt, "A-G4 失败: 自由文本通道仍生效"
    assert "## 附加规则" not in prompt


def test_g4_unconfigured_bundle_prompt_equals_base(monkeypatch):
    """bundle 未配置时 system prompt 与 _BASE_PROMPT 逐字节一致（缓存前缀不漂移）."""
    import sys

    sys.path.insert(0, str(_ROOT / "src"))
    from llm_loop.core import prompt as prompt_mod

    monkeypatch.delenv("SYSTEM_PROMPT_EXTRA", raising=False)
    monkeypatch.delenv("LFL_SYSTEM_EXTRA_BUNDLE", raising=False)
    assert prompt_mod.build_system_prompt() == prompt_mod._BASE_PROMPT


def _make_bundle(tmp_path: Path, body: str, version: str = "1.0.0") -> Path:
    d = tmp_path / "bundle"
    d.mkdir()
    target = d / "policy.md"
    target.write_text(body, encoding="utf-8")
    manifest = {
        "version": version,
        "files": [{"path": "policy.md", "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}],
    }
    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return d


def test_g4_valid_bundle_injected_verbatim(monkeypatch, tmp_path):
    """合法 bundle（manifest/hash 齐备）注入成功且内容逐字节一致."""
    import sys

    sys.path.insert(0, str(_ROOT / "src"))
    from llm_loop.core import prompt as prompt_mod

    body = "## operator policy\nbundle-only line"
    monkeypatch.setenv("LFL_SYSTEM_EXTRA_BUNDLE", str(_make_bundle(tmp_path, body)))
    monkeypatch.delenv("SYSTEM_PROMPT_EXTRA", raising=False)
    prompt = prompt_mod.build_system_prompt()
    assert prompt.startswith(prompt_mod._BASE_PROMPT)
    assert prompt.count("\n\n" + body) == 1, "bundle 内容应原样追加一次"
    assert prompt.endswith(body)


def test_g4_invalid_bundle_rejected_with_warning(monkeypatch, tmp_path, caplog):
    """manifest 校验失败（hash 不匹配）拒绝注入 + 告警留痕."""
    import sys

    sys.path.insert(0, str(_ROOT / "src"))
    from llm_loop.core import prompt as prompt_mod

    d = tmp_path / "bad_bundle"
    d.mkdir()
    (d / "policy.md").write_text("tampered body", encoding="utf-8")
    manifest = {
        "version": "1.0.0",
        "files": [{"path": "policy.md", "sha256": "0" * 64}],
    }
    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setenv("LFL_SYSTEM_EXTRA_BUNDLE", str(d))
    monkeypatch.delenv("SYSTEM_PROMPT_EXTRA", raising=False)
    with caplog.at_level(logging.WARNING, logger="llm_loop.core.prompt"):
        prompt = prompt_mod.build_system_prompt()
    assert prompt == prompt_mod._BASE_PROMPT, "非法 bundle 必须拒绝注入（fail-closed）"
    assert any("拒绝注入" in r.message for r in caplog.records), "校验失败须落告警留痕"


def test_g4_oversize_bundle_rejected(monkeypatch, tmp_path):
    """超出大小上限拒绝注入."""
    import sys

    sys.path.insert(0, str(_ROOT / "src"))
    from llm_loop.core import prompt as prompt_mod

    d = tmp_path / "big_bundle"
    d.mkdir()
    blob = "x" * (prompt_mod._BUNDLE_MAX_BYTES + 1)
    target = d / "policy.md"
    target.write_text(blob, encoding="utf-8")
    manifest = {
        "version": "1.0.0",
        "files": [
            {"path": "policy.md", "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
        ],
    }
    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setenv("LFL_SYSTEM_EXTRA_BUNDLE", str(d))
    monkeypatch.delenv("SYSTEM_PROMPT_EXTRA", raising=False)
    assert prompt_mod.build_system_prompt() == prompt_mod._BASE_PROMPT


# ---------- v7 反例自证（断言有效性证明）----------


def test_v7_backup_would_fail_assertions():
    """以 .backup/ai_rules.lite.v7.md 作反例：旧版必含被禁主题（证明断言有效）."""
    v7 = _read(".backup/ai_rules.lite.v7.md")
    hits = [
        w
        for words in _G2_BANNED_TOPICS.values()
        for w in words
        if w in v7
    ]
    assert len(hits) >= 8, f"v7 反例失效: 旧版应大量命中被禁主题，实际仅 {len(hits)}: {hits}"
    method_hits = [t for t in _G3_METHOD_TOPICS if t in v7]
    assert len(method_hits) == 6, f"v7 反例失效: 方法层应全部在场，实际 {method_hits}"


# ---------- rules_version 联动（A-2.3 复核）----------


def test_rules_version_reflects_v8():
    """lite 头部 version=8 且 _rules_version() 解析一致（缓存失效联动的前置）."""
    import sys

    sys.path.insert(0, str(_ROOT / "src"))
    from llm_loop.introspection.status import _rules_version

    lite = _read("docs/ai_rules.lite.md")
    m = re.search(r"version=(\d+)", lite.splitlines()[0])
    assert m and m.group(1) == "8", "lite 头部应为 version=8"
    assert _rules_version() == "8", "_rules_version() 应反映 v8"