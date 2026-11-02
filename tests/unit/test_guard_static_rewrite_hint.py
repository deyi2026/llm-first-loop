"""阻断回执「可复制等价姿势」的回归锁（RULE-AI-36 回执侧，2026-11-02）.

背景（实测）：here-doc / 管道直连解释器在**良性载荷**下已被静态源转换自动
改写并执行；但载荷含进程派生、受保护动作或敏感读时转换被拒，回执原先只剩
「走 escalation_request」一句，调用方拿不到合法姿势，每轮试错白花一次交互。

`static_rewrite_hint` 只产出文本：不放行、不改判定、不返回任何信号。

这里锁两件事：
1. 建议文本包含「先落盘、再执行」两步，并内嵌真实载荷（不是空模板）；
2. 建议出来的命令本身不会再被**同一条**规则拦——否则建议等于废纸。

纪律：灾难形态一律运行时拼装（LL=双尖括号），源码不落会命中守卫正则的
连续子串。
"""

from __future__ import annotations

from llm_loop.tools.safety import (
    _CONVERT_HEREDOC_RULE,
    _CONVERT_PIPE_RULE,
    CatastrophicGuard,
)

LL = chr(60) * 2  # here-doc 引导符
PP = chr(124)  # 管道符
_BLOCKED_BODY = "import subprocess\nprint(subprocess.run(['echo', 'x']))"
_HINT_HEADER = "可复制的等价姿势"
_HINT_FOOTER = "\n注："


def _here_doc(body: str, interp: str = "python3", delim: str = "PY") -> str:
    return f"{interp} {LL}'{delim}'\n{body}\n{delim}"


def _suggested_block(hint: str) -> str:
    """切出回执建议里的可执行命令块（去首行标题与尾部注解）."""
    head = hint.index(_HINT_HEADER)
    body_start = hint.index("\n", head) + 1
    return hint[body_start : hint.index(_HINT_FOOTER)]


def test_heredoc_hint_embeds_real_payload_and_two_steps() -> None:
    hint = CatastrophicGuard().static_rewrite_hint(_here_doc(_BLOCKED_BODY))
    assert f"cat > /tmp/lfl_rewrite.py {LL}'LFL_EOF'" in hint
    assert "python3 -I /tmp/lfl_rewrite.py" in hint
    assert "import subprocess" in hint  # 真实载荷内嵌，可直接改一行就走
    assert "review_admission" in hint  # 受保护动作的合法出口写清


def test_hint_is_empty_outside_rewritable_shapes() -> None:
    guard = CatastrophicGuard()
    assert guard.static_rewrite_hint("ls -la") == ""
    assert guard.static_rewrite_hint("") == ""


def test_suggested_commands_do_not_retrigger_same_rule() -> None:
    guard = CatastrophicGuard()
    command = _here_doc(_BLOCKED_BODY)
    blocked = guard.guard("execute_command", {"command": command})
    assert blocked is not None and blocked.blocked
    assert blocked.rule == _CONVERT_HEREDOC_RULE
    suggestion = _suggested_block(guard.static_rewrite_hint(command))
    again = guard.guard("execute_command", {"command": suggestion})
    assert again is None or again.rule != _CONVERT_HEREDOC_RULE


def test_pipe_shaped_block_also_gets_a_hint() -> None:
    guard = CatastrophicGuard()
    command = f"cat payload.txt {PP} python3 -"
    blocked = guard.guard("execute_command", {"command": command})
    assert blocked is not None and blocked.blocked
    assert blocked.rule == _CONVERT_PIPE_RULE
    hint = guard.static_rewrite_hint(command)
    assert _HINT_HEADER in hint
    again = guard.guard(
        "execute_command", {"command": _suggested_block(hint)}
    )
    assert again is None or again.rule != _CONVERT_PIPE_RULE
