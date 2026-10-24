"""spawn_subagent fs_isolation 诚实契约回归锁（安全建议书 2026-10-25 S2-5/P1-6 措辞分支）.

事实基线（2026-10-25 复核，HEAD 含提交 527fe6463）:
- requires.fs_isolation=true 在运行时**确有实现**（EVO-20261016-ac47e850）：
  runner.start()/run() 会 prepare_worktree 创建独立 git worktree、child 线程的
  current_workspace_root 指向隔离树、prepare 失败带 reason_code 拒绝且绝不降级
  共享工作区（src/llm_loop/subagent/runner.py + workspace/worktree_isolation.py，
  由 tests/unit/test_worktree_isolation.py 等覆盖）。
- 它是 best-effort 施工面隔离而**非安全沙箱**：child 的 execute_command 经
  绝对路径/跨目录操作仍可越界（建议书 S2-5）。

因此本文件锁定的契约不是"默认拒绝 fs_isolation"，而是**不虚假承诺**：
1. 声明透传：fs_isolation=true 必须原样传给 runner.start（校验通过≠执行生效）；
2. 回执诚实：带 worktree 的成功回执必须明示"非安全沙箱/绝对路径可越界"，
   不得让调用方误以为已获得安全隔离；
3. 描述诚实：工具描述与 schema 不得含"已隔离/隔离生效"类断言；
4. fail-closed：runner 拒绝（如 worktree 准备失败）→ FAILURE 原样透出，
   绝不伪造成功回执。

（注：曾有提案"默认拒绝 fs_isolation=true 并提示'运行时未实现'"——该前提与
当前代码不符，把"已实现"写成"未实现"才是虚假陈述，故未采纳；真正的残余
风险是"非安全沙箱"这一事实，必须显式告知调用方而非掩盖。）
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from llm_loop.core.message import ToolResultStatus
from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool


class RecordingRunner:
    """记录 start() 派生调用；不启动任何真实 child/provider/线程。"""

    def __init__(self, reply: dict | None = None) -> None:
        self.registry = SimpleNamespace(
            names=lambda: ["read_file", "execute_command", "wait"]
        )
        self.calls: list[dict] = []
        self._reply = dict(reply or {})

    def start(self, **kwargs):
        self.calls.append(kwargs)
        merged = {
            "accepted": True,
            "child_id": "child-test-0001",
            "state": "running",
            "depth": kwargs.get("depth", 0),
            "model": "",
        }
        merged.update(self._reply)
        return merged


def test_fs_isolation_true_forwarded_and_receipt_discloses_non_sandbox():
    """true → 透传给 runner；回执含 worktree 路径且明示非安全沙箱。"""
    wt = "/ws/repo/.worktrees/lfl-child-ab12cd34"
    runner = RecordingRunner(reply={"worktree": wt})
    tool = SpawnSubAgentTool(runner)
    res = tool.execute(task="隔离面施工", requires={"fs_isolation": True})
    assert res.status == ToolResultStatus.SUCCESS, res.content
    assert len(runner.calls) == 1
    assert runner.calls[0]["fs_isolation"] is True
    assert wt in res.content
    assert "非安全沙箱" in res.content
    assert "绝对路径" in res.content


def test_fs_isolation_default_or_false_no_isolation_claim():
    """缺省/显式 false → fs_isolation=False 传 runner；回执不出现隔离措辞。"""
    runner = RecordingRunner()
    tool = SpawnSubAgentTool(runner)
    res_default = tool.execute(task="普通子任务")
    assert res_default.status == ToolResultStatus.SUCCESS, res_default.content
    assert runner.calls[0]["fs_isolation"] is False
    assert "worktree=" not in res_default.content
    assert "隔离" not in res_default.content

    res_false = tool.execute(
        task="需要 fs 但不隔离",
        requires={"fs": True, "fs_isolation": False},
    )
    assert res_false.status == ToolResultStatus.SUCCESS, res_false.content
    assert runner.calls[1]["fs_isolation"] is False
    assert "隔离" not in res_false.content


def test_runner_refusal_is_failure_not_fake_success():
    """fail-closed：runner 拒绝（如 worktree 准备失败）→ FAILURE 原样透出。"""
    runner = RecordingRunner(
        reply={
            "accepted": False,
            "state": "refused",
            "detail": (
                "worktree 隔离准备失败（reason_code=DISK_LOW），child 未启动、"
                "未降级共享工作区"
            ),
        }
    )
    tool = SpawnSubAgentTool(runner)
    res = tool.execute(task="隔离子任务", requires={"fs_isolation": True})
    assert res.status == ToolResultStatus.FAILURE
    assert "DISK_LOW" in res.content
    assert "child 未启动" in res.content
    # 拒绝路径绝不输出成功回执形态
    assert "[状态: success]" not in res.content


def test_description_and_schema_make_no_isolation_promises():
    """描述/schema：无"已隔离/隔离生效"断言；非沙箱警示必须在场。"""
    schema_text = json.dumps(SpawnSubAgentTool.parameters, ensure_ascii=False)
    desc = SpawnSubAgentTool.description
    for text in (desc, schema_text):
        for forbidden in ("已隔离", "隔离生效", "隔离已生效"):
            assert forbidden not in text, f"虚假承诺措辞出现: {forbidden}"
    assert "非安全沙箱" in desc
    assert "非安全沙箱" in schema_text
    # 越界警示具体化：必须点名 execute_command 绝对路径可越界
    assert "绝对路径" in desc
    assert "绝对路径" in schema_text
