"""S1-08 与 L3 协助收件箱的集成（RULE-AI-35：应拦输入必须实测被拦）.

机检第 8 条从「数据源缺失只能 skip」变为可判定，是本集成的唯一目的：
- 收件箱为空（数据源可用）→ pass；
- 存在 need=block 的未决请求 → fail + help_blocking。
"""

import json
import pathlib

from llm_loop.introspection.help_inbox import HelpInbox
from llm_loop.introspection.tools_merge_queue import run_lane_gate_check


class _Host:
    """最小 RegistryHost 替身：只提供 tools_merge_queue 实际读取的属性。"""

    def __init__(self, data_dir: pathlib.Path, root: pathlib.Path) -> None:
        self.audit_dir = str(data_dir / "audit")
        self.ctx = None
        self.workspace_root = str(root)


def _checks(tmp_path: pathlib.Path, with_block: bool) -> dict[str, dict]:
    data = tmp_path / "data"
    (data / "audit").mkdir(parents=True)
    if with_block:
        HelpInbox(data).post(
            topic="需要确认接口契约", body="lane x 改了 provider 接口", need="block",
            from_session="sess-A",
        )
    txt = run_lane_gate_check(
        None, _Host(data, tmp_path), {"evidence": {"lane": {}, "main": {}}}
    ).content
    payload = json.loads(txt.split("\n", 1)[1])
    return {c["check_id"]: c for c in payload["gate"]["checks"]}


def test_s1_08_passes_when_inbox_has_no_blocking_request(tmp_path):
    assert _checks(tmp_path, False)["s1_08"]["verdict"] == "pass"


def test_s1_08_blocks_on_pending_block_request(tmp_path):
    c = _checks(tmp_path, True)["s1_08"]
    assert c["verdict"] == "fail"
    assert c["reason_code"] == "help_blocking"
