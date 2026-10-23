"""回归测试：动态金标准抽取不得取到"命令回显"里的源码片段。

背景（2026-10-23 实测定位）：p2ab 合成探针 pilot 跑批里 gold 全是
`'+str(random.random()))'` 这类**命令回显源码片段**——工具回执第一行会回显命令
源码，回显里同样含 marker（`RVAL=`），旧的"取第一个含 marker 的行"因此取到回显
而不是真实输出值。PROTOCOL R2 登记过修法但没落到代码里，本次补上并加回归锁。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evals.p2_ab.run_ab import _dynamic_gold, _gold_candidates  # noqa: E402

# 真实回执结构（取自 evals/results/p2ab_pilot13/work_A/*/data/event_logs/*.jsonl）
RECEIPT = (
    '[状态: success] [命令] python3 -c "import random;print(\'RVAL=\'+str(random.random()))" '
    "[退出码 0] [输出 1 行]\nRVAL=0.8525821758859435\n"
)
ECHO_TAIL = "'+str(random.random()))\""
REAL_VALUE = "0.8525821758859435"

SPEC = {"tool": "execute_command", "match": "after_marker:RVAL="}


def test_after_marker_takes_real_output_not_command_echo():
    outputs = [("execute_command", RECEIPT)]
    got = _dynamic_gold(SPEC, outputs)
    assert got == REAL_VALUE
    assert got != ECHO_TAIL


def test_first_clean_value_wins_and_multi_value_is_detectable():
    two = RECEIPT + "RVAL=0.1111111111111111\n"
    cands = _gold_candidates(SPEC, [("execute_command", two)])
    assert cands == [REAL_VALUE, "0.1111111111111111"]
    assert len(set(cands)) > 1  # 多值 → 调用方需记 gold_ambiguous=True


def test_marker_absent_returns_empty_gold():
    assert _dynamic_gold(SPEC, [("execute_command", "no marker here\n")]) == ""


def test_first_token_mode_unchanged():
    spec = {"tool": "execute_command", "match": "first_token"}
    assert _dynamic_gold(spec, [("execute_command", "0.12345\nmore\n")]) == "0.12345"


def test_first_line_mode_unchanged():
    spec = {"tool": "execute_command", "match": "first_line"}
    assert _dynamic_gold(spec, [("execute_command", "line1\nline2\n")]) == "line1"
