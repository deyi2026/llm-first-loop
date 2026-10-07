"""svc_deploy N1（tasks 8.1 / T1）与事故回归（tasks 8.3 / T3）。

覆盖：
- AC-1  绑定核验拒绝 → 回执携带指向 publish 的可执行下一步（含入口名与参数名）
- AC-2  8 类 binding problem 逐类映射；未登记类别保留事实 + 显式「无预设下一步」
- AC-3  下一步位于接收者可见范围（独立结构化字段，不依赖 reason_ref）
- AC-4  提示中的入口在既有 CLI / 工具 action 契约中真实存在
- AC-5  提示与新增字段无凭证、无私有绝对路径、无端口/端点
- AC-6  被拒后零副作用（动作集合 / desired / 工作树逐字节不变）
- AC-7  与 gate_classification 的 identity_conflict 一致：binding 类只给 publish
- AC-21 回执 schema 向后兼容（旧记录缺 next_step 可反序列化与展示）
- AC-19 事故最小重演（E1 未 publish 前进 HEAD → 拒绝 + 下一步；E3 publish 后重试成功）
- INV-2 绑定核验不减弱（原文逐字不变）
- INV-3 提示零副作用 / INV-5 展示预算可见 / INV-6 提示确定性
- INV-7 无私有路径落盘 / INV-8 无未验证命令 / INV-12 回执 schema 兼容

本文件为纯新增；不修改任何既有测试文件，也不放宽既有断言。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import llm_loop.runtime.service_control as sc
from llm_loop.runtime.admission_barrier import AdmissionBarrierRegistry
from llm_loop.runtime.service_control import (
    NEXT_STEP_KIND_GENERATION_CONFLICT,
    BindingProblem,
    BindingProblemKind,
    ManagedServiceDeployment,
    ManagedServiceDeploymentStore,
    ServiceControlAction,
    binding_next_steps,
    decode_next_steps,
    encode_next_steps,
)
from llm_loop.tools.builtin.service_control import ServiceControlTool

# --------------------------------------------------------------------------
# 契约表：problem kind → 期望的 exit_action（AC-2 / AC-7 / INV-8）
# --------------------------------------------------------------------------
_STEP_CONTRACT: dict[str, str] = {
    BindingProblemKind.GIT_HEAD_MISMATCH: "publish",
    BindingProblemKind.CODE_ROOT_MISMATCH: "publish",
    BindingProblemKind.RUNTIME_ROOT_MISMATCH: "publish",
    BindingProblemKind.WEBUI_ARTIFACT_MISMATCH: "publish",
    BindingProblemKind.WEBUI_ARTIFACT_UNAVAILABLE: "publish",
    NEXT_STEP_KIND_GENERATION_CONFLICT: "publish",
    BindingProblemKind.TRACKED_WORKTREE_DIRTY: "",
    BindingProblemKind.GIT_HEAD_UNAVAILABLE: "",
    BindingProblemKind.GIT_STATUS_UNAVAILABLE: "",
}

# R3：提示只陈述事实与既有入口，不含完成裁决 / 训诫语。
_FORBIDDEN_NOTE_WORDS = ("必须", "禁止", "应当", "已完成", "succeeded", "should")

# INV-7：私有绝对路径与凭证特征（提示里出现的路径必须是占位符）。
_PRIVATE_PATH_RE = re.compile(r"(/(?:Users|home|private|tmp|var|root)/)|(?:[A-Za-z]:\\\\)")
_SECRET_RE = re.compile(r"(token|secret|password|credential|api[_-]?key)", re.IGNORECASE)

_RESTART_SCRIPT = (
    "#!/usr/bin/env bash\n"
    "set -euo pipefail\n"
    'printf \'%s\\n\' "${LFL_RESTART_ACTION_ID:-}" > "$LFL_RESTART_RUNTIME_ROOT/executed_action_id.txt"\n'
    'mkdir -p "$LFL_RESTART_RUNTIME_ROOT/data/runtime"\n'
    'head=$(git -C "$LFL_RESTART_CODE_ROOT" rev-parse HEAD)\n'
    'started=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)\n'
    'svcs="${1:-all}"\n'
    'if [ "$svcs" = "all" ]; then svcs="web feishu learning"; fi\n'
    "for svc in $svcs; do\n"
    '  printf \'{"pid": 1, "git_head": "%s", "started_at": "%s"}\\n\' "$head" "$started"'
    ' > "$LFL_RESTART_RUNTIME_ROOT/data/runtime/runtime_manifest.$svc.json"\n'
    "done\n"
)


@pytest.fixture()
def fast_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sc, "_REQUESTER_EXIT_POLL_S", 0.02)
    monkeypatch.setattr(sc, "_REQUESTER_EXIT_TIMEOUT_S", 0.3)
    monkeypatch.setattr(sc, "_IDLE_POLL_S", 0.02)
    monkeypatch.setattr(sc, "_IDLE_TIMEOUT_S", 0.3)
    monkeypatch.setattr(sc, "_STALE_WAITING_MARGIN_S", 0.0)
    monkeypatch.setattr(sc, "_VERIFY_POLL_S", 0.02)
    monkeypatch.setattr(sc, "_VERIFY_TIMEOUT_S", 0.3)


def _make_repo(root: Path) -> Path:
    """真实 git worktree + webui/dist + restart_mirror.sh 夹具。"""
    (root / "webui" / "dist").mkdir(parents=True, exist_ok=True)
    (root / "webui" / "dist" / "index.html").write_text("<html>v1</html>\n", encoding="utf-8")
    (root / ".gitignore").write_text("webui/dist/\ndata/\n", encoding="utf-8")
    (root / "app.py").write_text("print('v1')\n", encoding="utf-8")
    script = root / "scripts" / "restart_mirror.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(_RESTART_SCRIPT, encoding="utf-8")
    script.chmod(0o755)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "svc@test.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "svc-test"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
    return root


def _advance_head(root: Path, name: str = "next.txt") -> str:
    """未 publish 的情况下把物理 HEAD 前进一步（E1 的成因）。"""
    (root / name).write_text("advance\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", name], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", f"advance {name}"], check=True)
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _json_lines(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.startswith("{")]


def _plain_deployment(tmp_path: Path, generation: int = 1) -> ManagedServiceDeployment:
    code_root = tmp_path / "code"
    runtime_root = tmp_path / "runtime-root"
    code_root.mkdir(parents=True, exist_ok=True)
    runtime_root.mkdir(parents=True, exist_ok=True)
    return ManagedServiceDeployment(
        schema=sc._DEPLOYMENT_SCHEMA,
        deployment_id=f"deploy-{generation}",
        generation=generation,
        git_head="a" * 40,
        code_root=str(code_root.resolve()),
        runtime_root=str(runtime_root.resolve()),
        webui_artifact_sha256="b" * 64,
    )


def _snapshot(path: Path) -> dict[str, bytes]:
    return {
        str(item.relative_to(path)): item.read_bytes()
        for item in sorted(path.rglob("*"))
        if item.is_file()
    }


# --------------------------------------------------------------------------
# AC-2 / INV-8：事实源与映射表完整性
# --------------------------------------------------------------------------


def test_binding_problem_kind_enum_is_closed_and_exactly_eight() -> None:
    assert len(BindingProblemKind.ALL) == 8
    assert BindingProblemKind.ALL == frozenset(
        {
            "code_root_mismatch",
            "runtime_root_mismatch",
            "git_head_unavailable",
            "git_head_mismatch",
            "tracked_worktree_dirty",
            "git_status_unavailable",
            "webui_artifact_unavailable",
            "webui_artifact_mismatch",
        }
    )


def test_mapping_table_covers_every_kind_and_cas_conflict() -> None:
    assert set(sc._NEXT_STEP_BY_KIND) >= BindingProblemKind.ALL
    assert NEXT_STEP_KIND_GENERATION_CONFLICT in sc._NEXT_STEP_BY_KIND
    for key, step in sc._NEXT_STEP_BY_KIND.items():
        assert step.problem_kind == key


@pytest.mark.parametrize("kind", sorted(_STEP_CONTRACT))
def test_each_kind_maps_to_its_declared_next_step(kind: str) -> None:
    steps = binding_next_steps([kind])
    assert len(steps) == 1
    step = steps[0]
    assert step.problem_kind == kind
    assert step.exit_action == _STEP_CONTRACT[kind]
    assert step.note.strip()
    if step.exit_action:
        assert "--code-root" in step.argv_hint
        assert "--runtime-root" in step.argv_hint
    else:
        assert step.argv_hint == ""


@pytest.mark.parametrize("kind", sorted(_STEP_CONTRACT))
def test_notes_are_bounded_and_contain_no_verdict_words(kind: str) -> None:
    step = sc._NEXT_STEP_BY_KIND[kind]
    assert len(step.note) <= 120
    for word in _FORBIDDEN_NOTE_WORDS:
        assert word not in step.note


def test_binding_kinds_only_offer_publish_never_override_or_adopt() -> None:
    """AC-7：与 gate_classification 的 identity_conflict（须重新 publish）一致。"""
    for kind in BindingProblemKind.ALL:
        step = sc._NEXT_STEP_BY_KIND[kind]
        assert step.exit_action in {"publish", ""}
        assert "override" not in step.argv_hint
        assert "adopt" not in step.note


def test_all_exit_actions_are_real_cli_and_tool_contract_entries(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-4 / INV-8：提示里的入口必须在既有契约中真实存在。"""
    declared = {step.exit_action for step in sc._NEXT_STEP_BY_KIND.values() if step.exit_action}
    assert declared <= {"publish", "update", "restart"}

    tool_actions = set(ServiceControlTool.parameters["properties"]["action"]["enum"])
    assert declared <= tool_actions

    for subcommand in sorted(declared):
        with pytest.raises(SystemExit):
            sc.main([subcommand])
        err = capsys.readouterr().err
        # 已知子命令报「缺少必填参数」；未知子命令报 invalid choice。
        assert "invalid choice" not in err, subcommand


def test_unknown_subcommand_is_reported_as_invalid_choice(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        sc.main(["definitely-not-a-subcommand"])
    assert "invalid choice" in capsys.readouterr().err


# --------------------------------------------------------------------------
# AC-2 兜底 / AC-5 / INV-6 / INV-7
# --------------------------------------------------------------------------


def test_argvt_hint_is_placeholder_only_and_has_no_private_paths() -> None:
    for step in sc._NEXT_STEP_BY_KIND.values():
        if not step.argv_hint:
            continue
        tokens = step.argv_hint.split()
        for index, token in enumerate(tokens):
            if token.startswith("--"):
                value = tokens[index + 1]
                assert value.startswith("<") and value.endswith(">"), step.argv_hint
        assert not _PRIVATE_PATH_RE.search(step.argv_hint), step.argv_hint
        assert not _SECRET_RE.search(step.argv_hint), step.argv_hint


@pytest.mark.parametrize("raw_kind", ["future_kind", "brand_new_binding_problem"])
def test_unregistered_kind_keeps_fact_and_marks_no_preset_step(raw_kind: str) -> None:
    steps = binding_next_steps([raw_kind])
    assert len(steps) == 1
    assert steps[0].problem_kind == raw_kind
    assert steps[0].exit_action == ""
    assert steps[0].argv_hint == ""
    assert steps[0].note == sc._NEXT_STEP_UNREGISTERED_NOTE


def test_blank_kind_yields_no_step_at_all() -> None:
    """空类别不是「问题」，映射层不臆造条目（不猜、不编）。"""
    assert binding_next_steps([""]) == ()
    assert binding_next_steps([]) == ()


def test_binding_problem_object_keeps_verbatim_text_when_mapped() -> None:
    """AC-2 / INV-2：映射只读结构化类别，事实原文不被改写。"""
    problem = BindingProblem(
        kind=BindingProblemKind.GIT_HEAD_MISMATCH,
        text="git_head mismatch desired=aaa actual=bbb",
        desired="aaa",
        actual="bbb",
    )
    steps = binding_next_steps([problem])
    assert len(steps) == 1
    assert steps[0].problem_kind == BindingProblemKind.GIT_HEAD_MISMATCH
    assert problem.text == "git_head mismatch desired=aaa actual=bbb"


def test_unregistered_kind_is_appended_after_registered_ones() -> None:
    steps = binding_next_steps(
        ["future_kind", BindingProblemKind.GIT_HEAD_MISMATCH, "future_kind"]
    )
    assert [step.problem_kind for step in steps] == [
        BindingProblemKind.GIT_HEAD_MISMATCH,
        "future_kind",
    ]


def test_next_steps_are_deterministic_across_calls_and_input_order() -> None:
    forward = [
        BindingProblemKind.GIT_HEAD_MISMATCH,
        BindingProblemKind.CODE_ROOT_MISMATCH,
        NEXT_STEP_KIND_GENERATION_CONFLICT,
    ]
    reversed_input = list(reversed(forward))
    first = encode_next_steps(binding_next_steps(forward))
    second = encode_next_steps(binding_next_steps(forward))
    third = encode_next_steps(binding_next_steps(reversed_input))
    assert first == second == third


def test_repeated_kinds_are_deduplicated_within_one_output() -> None:
    steps = binding_next_steps(
        [
            BindingProblemKind.GIT_HEAD_MISMATCH,
            BindingProblemKind.GIT_HEAD_MISMATCH,
            BindingProblemKind.GIT_HEAD_MISMATCH,
        ]
    )
    assert [step.problem_kind for step in steps] == [BindingProblemKind.GIT_HEAD_MISMATCH]


def test_next_step_payload_has_no_secret_path_or_region_endpoint() -> None:
    """AC-5 / AC-24 / INV-7：无凭证、无私有绝对路径、无主区端口与端点。"""
    payload = json.dumps(
        sc._next_steps_view(
            sorted(BindingProblemKind.ALL) + [NEXT_STEP_KIND_GENERATION_CONFLICT]
        ),
        ensure_ascii=False,
    )
    assert not _PRIVATE_PATH_RE.search(payload)
    assert not _SECRET_RE.search(payload)
    assert "8902" not in payload
    assert "/health" not in payload


# --------------------------------------------------------------------------
# AC-21 / INV-6 / INV-12：编解码与诚实降级
# --------------------------------------------------------------------------


def test_encode_empty_sequence_is_empty_string() -> None:
    assert encode_next_steps(()) == ""
    assert decode_next_steps("") == []


def test_encode_decode_roundtrip_preserves_all_four_keys() -> None:
    steps = binding_next_steps(
        [BindingProblemKind.GIT_HEAD_MISMATCH, BindingProblemKind.TRACKED_WORKTREE_DIRTY]
    )
    decoded = decode_next_steps(encode_next_steps(steps))
    assert len(decoded) == len(steps)
    for item, step in zip(decoded, steps):
        assert item == {
            "problem_kind": step.problem_kind,
            "exit_action": step.exit_action,
            "argv_hint": step.argv_hint,
            "note": step.note,
        }


@pytest.mark.parametrize(
    "corrupt",
    [
        "not-json-at-all",
        "{}",
        '{"problem_kind": "x"}',
        "[1, 2, 3]",
        '[{"problem_kind": "x"}, 5]',
        '"just a string"',
        "42",
    ],
)
def test_decode_honestly_degrades_on_corrupt_input(corrupt: str) -> None:
    assert decode_next_steps(corrupt) == []


def test_decode_normalizes_partial_object_to_four_keys() -> None:
    decoded = decode_next_steps('[{"problem_kind": "git_head_mismatch"}]')
    assert decoded == [
        {
            "problem_kind": "git_head_mismatch",
            "exit_action": "",
            "argv_hint": "",
            "note": "",
        }
    ]


def test_action_schema_stays_v1_and_next_step_is_optional() -> None:
    assert sc._ACTION_SCHEMA == "service-control-action/v1"
    assert "next_step" in sc._ACTION_OPTIONAL_FIELDS
    assert "next_step" not in sc._ACTION_FIELDS


def test_legacy_action_record_without_next_step_deserializes(tmp_path: Path) -> None:
    """AC-21 / INV-12 / D6：旧形态记录（缺 next_step）可读、可展示、不报错。"""
    raw = {
        "schema": "service-control-action/v1",
        "action_id": "svc-legacy-0001",
        "action": "restart",
        "target": "feishu",
        "deployment_id": "deploy-legacy",
        "deployment_generation": 1,
        "requester_session_id": "session-legacy",
        "status": "failed",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:01+00:00",
        "detail": "legacy receipt without next_step",
    }
    action = ServiceControlAction.from_dict(raw)
    assert action.next_step == ""
    assert action.to_dict()["next_step"] == ""
    assert decode_next_steps(action.next_step) == []

    store = ManagedServiceDeploymentStore(tmp_path / "data")
    store.actions_dir.mkdir(parents=True, exist_ok=True)
    store.action_path("svc-legacy-0001").write_text(
        json.dumps(raw), encoding="utf-8"
    )
    reloaded = store.read_action("svc-legacy-0001")
    assert reloaded is not None
    assert reloaded.next_step == ""
    assert reloaded.detail == "legacy receipt without next_step"


def test_update_action_persists_next_step_and_keeps_it_when_omitted(
    tmp_path: Path,
) -> None:
    """INV-12：next_step 走既有 replace 白名单；未传 = 保持既有值（不静默清空）。"""
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    store.compare_and_swap(_plain_deployment(tmp_path), expected_generation=0)
    action = store.accept_restart(
        target="feishu", expected_generation=1, requester_session_id="session-a"
    )
    encoded = encode_next_steps(binding_next_steps([BindingProblemKind.GIT_HEAD_MISMATCH]))
    assert encoded

    updated = store.update_action(
        action.action_id, status="failed", detail="binding failed", next_step=encoded
    )
    assert updated.next_step == encoded

    again = store.update_action(action.action_id, status="failed", detail="binding failed again")
    assert again.next_step == encoded


# --------------------------------------------------------------------------
# AC-6 / INV-3：提示生成零副作用
# --------------------------------------------------------------------------


def test_next_step_generation_has_zero_side_effects(tmp_path: Path) -> None:
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    store.compare_and_swap(_plain_deployment(tmp_path), expected_generation=0)
    before = _snapshot(store.data_dir)

    for _ in range(3):
        view = sc._next_steps_view(
            [BindingProblemKind.GIT_HEAD_MISMATCH, BindingProblemKind.TRACKED_WORKTREE_DIRTY]
        )
        assert view
        encode_next_steps(binding_next_steps([BindingProblemKind.CODE_ROOT_MISMATCH]))
        decode_next_steps('[{"problem_kind": "bogus"}]')

    assert _snapshot(store.data_dir) == before
    assert store.read() is not None
    assert list(store.actions_dir.glob("*.json")) == []


# --------------------------------------------------------------------------
# INV-2：结构化事实源与既有 verify 原文逐字一致
# --------------------------------------------------------------------------


def test_structured_source_projects_to_verbatim_verify_text(tmp_path: Path) -> None:
    code = _make_repo(tmp_path / "feishu-code")
    deployment = sc.build_deployment(code_root=code, runtime_root=code, generation=1)
    # EVO-20261007-9c6eccf3: 漂移改测绑定树（release checkout）——开发树前移
    # 不再构成绑定漂移（这正是该 EVO 的目标语义）。
    bound = Path(deployment.code_root)
    assert sc.verify_deployment_binding(deployment, code_root=bound, runtime_root=code) == []

    _advance_head(bound)

    facts = sc._binding_problems_structured(deployment, code_root=bound, runtime_root=code)
    assert [fact.kind for fact in facts] == [BindingProblemKind.GIT_HEAD_MISMATCH]
    assert [fact.text for fact in facts] == sc.verify_deployment_binding(
        deployment, code_root=bound, runtime_root=code
    )
    assert "git_head mismatch desired=" in facts[0].text
    assert facts[0].desired == deployment.git_head


def test_structured_source_keeps_declared_problem_order(tmp_path: Path) -> None:
    code = _make_repo(tmp_path / "feishu-code")
    deployment = sc.build_deployment(code_root=code, runtime_root=code, generation=1)
    empty = tmp_path / "empty-root"
    empty.mkdir()

    facts = sc._binding_problems_structured(
        deployment, code_root=empty, runtime_root=empty, verify_webui=True
    )
    kinds = [fact.kind for fact in facts]
    assert kinds == [
        BindingProblemKind.CODE_ROOT_MISMATCH,
        BindingProblemKind.RUNTIME_ROOT_MISMATCH,
        BindingProblemKind.GIT_HEAD_UNAVAILABLE,
        BindingProblemKind.GIT_STATUS_UNAVAILABLE,
        BindingProblemKind.WEBUI_ARTIFACT_UNAVAILABLE,
    ]
    # 事实源与投影同序同文（INV-2：既有断言口径不变）。
    assert [fact.text for fact in facts] == sc.verify_deployment_binding(
        deployment, code_root=empty, runtime_root=empty, verify_webui=True
    )
    steps = binding_next_steps(facts)
    by_kind = {step.problem_kind: step.exit_action for step in steps}
    assert by_kind[BindingProblemKind.CODE_ROOT_MISMATCH] == "publish"
    assert by_kind[BindingProblemKind.RUNTIME_ROOT_MISMATCH] == "publish"
    assert by_kind[BindingProblemKind.WEBUI_ARTIFACT_UNAVAILABLE] == "publish"
    assert by_kind[BindingProblemKind.GIT_HEAD_UNAVAILABLE] == ""
    assert by_kind[BindingProblemKind.GIT_STATUS_UNAVAILABLE] == ""


# --------------------------------------------------------------------------
# AC-1 / AC-3 / AC-19：E1 → E3 最小事故重演（D1）
# --------------------------------------------------------------------------


def test_incident_e1_rejection_carries_publish_next_step_then_e3_retry_succeeds(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fast_waits: None,
) -> None:
    code = _make_repo(tmp_path / "feishu-code")
    data = code / "data"
    store = ManagedServiceDeploymentStore(data)
    store.compare_and_swap(
        sc.build_deployment(code_root=code, runtime_root=code, generation=1),
        expected_generation=0,
    )

    # --- E1：绑定树（release checkout）HEAD 前进但 desired 未 publish → restart 必须被拒 ---
    # （EVO-20261007-9c6eccf3: 开发树前移不再是漂移源；E1 成因改为绑定树分歧。）
    _advance_head(Path(store.read().code_root))
    rc = sc.main(
        [
            "restart",
            "--data-dir",
            str(data),
            "--target",
            "feishu",
            "--requester",
            "cli-test",
            # 终态断言 → 内联（GOAL-20261008-f143e051：默认 detach）。
            "--wait",
        ]
    )
    assert rc == 4

    accepted, final = _json_lines(capsys.readouterr().out)
    assert accepted["ok"] is True
    action_id = accepted["action_id"]
    assert final["ok"] is False
    assert final["status"] == "failed"
    # 拒绝事实原文逐字保留（INV-2 / AC-1）。
    assert final["detail"].startswith("deployment binding failed: git_head mismatch")

    # AC-3 / INV-5：下一步在接收者可见的独立结构化字段里，无需读 reason_ref。
    steps = final["next_step"]
    assert steps, "next_step 必须位于 CLI 终态 JSON（独立字段，不受 400 字符截断）"
    publish_steps = [step for step in steps if step["exit_action"] == "publish"]
    assert len(publish_steps) == 1
    assert publish_steps[0]["problem_kind"] == BindingProblemKind.GIT_HEAD_MISMATCH
    assert "--code-root" in publish_steps[0]["argv_hint"]
    assert "--runtime-root" in publish_steps[0]["argv_hint"]

    # AC-6 / INV-3：被拒后零副作用——动作仍为 failed（无新动作、无自动重试）。
    recorded = store.read_action(action_id)
    assert recorded is not None
    assert recorded.status == "failed"
    assert recorded.next_step == encode_next_steps(
        binding_next_steps([BindingProblemKind.GIT_HEAD_MISMATCH])
    )
    assert len(list(store.actions_dir.glob("*.json"))) == 1
    assert not (code / "executed_action_id.txt").exists()

    # INV-13：提示只陈述事实与既有入口，不是完成裁决。
    assert all("已完成" not in step["note"] for step in steps)
    assert all("succeeded" not in step["note"] for step in steps)

    # --- E3：publish 新 HEAD 后同一条 restart 成功 ---
    assert (
        sc.main(
            ["publish", "--code-root", str(code), "--runtime-root", str(code)]
        )
        == 0
    )
    published = _json_lines(capsys.readouterr().out)[0]
    assert published["generation"] == 2
    assert len(published["git_head"]) == 40

    rc = sc.main(
        [
            "restart",
            "--data-dir",
            str(data),
            "--target",
            "feishu",
            # 终态断言 → 内联（GOAL-20261008-f143e051：默认 detach）。
            "--wait",
        ]
    )
    assert rc == 0
    retry_accepted, retry_final = _json_lines(capsys.readouterr().out)
    assert retry_final["ok"] is True
    assert retry_final["status"] == "succeeded"
    assert retry_final["next_step"] == []
    assert retry_accepted["action_id"] != action_id
    assert (
        (code / "executed_action_id.txt").read_text(encoding="utf-8").strip()
        == retry_accepted["action_id"]
    )


# --------------------------------------------------------------------------
# AC-3：CLI verify 失败面同样带出可见下一步
# --------------------------------------------------------------------------


def test_cli_verify_failure_exposes_next_step_for_publish(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _make_repo(tmp_path / "feishu-code")
    data = code / "data"
    store = ManagedServiceDeploymentStore(data)
    store.compare_and_swap(
        sc.build_deployment(code_root=code, runtime_root=code, generation=1),
        expected_generation=0,
    )
    _advance_head(code)

    rc = sc.main(["verify", "--data-dir", str(data), "--code-root", str(code), "--runtime-root", str(code)])
    assert rc == 5
    payload = _json_lines(capsys.readouterr().err)[-1]
    assert payload["ok"] is False
    assert any("git_head mismatch" in item for item in payload["problems"])
    assert payload["next_step"][0]["exit_action"] == "publish"


def test_cli_publish_dirty_tree_is_structured_not_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-4：CLI publish 脏树 → 结构化原因 + 同源下一步（不再裸 traceback）。"""
    code = _make_repo(tmp_path / "feishu-code")
    (code / "app.py").write_text("print('dirty')\n", encoding="utf-8")

    rc = sc.main(["publish", "--code-root", str(code), "--runtime-root", str(code)])
    assert rc == 10
    payload = _json_lines(capsys.readouterr().err)[-1]
    assert payload["ok"] is False
    assert payload["error"] == "dirty_worktree"
    assert "tracked worktree must be clean" in payload["detail"]
    assert payload["next_step"][0]["problem_kind"] == BindingProblemKind.TRACKED_WORKTREE_DIRTY
    assert payload["next_step"][0]["exit_action"] == ""

def test_cli_publish_without_artifacts_reports_missing_and_next_step(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-4：产物缺失是模型可修复状态 → 回报缺哪一项 + 同源下一步。"""
    code = _make_repo(tmp_path / "feishu-code")
    shutil.rmtree(code / "webui" / "dist")

    rc = sc.main(["publish", "--code-root", str(code), "--runtime-root", str(code)])
    assert rc == 10
    payload = _json_lines(capsys.readouterr().err)[-1]
    assert payload["error"] == "artifact_missing"
    assert payload["missing"]
    assert (
        payload["next_step"][0]["problem_kind"]
        == BindingProblemKind.WEBUI_ARTIFACT_UNAVAILABLE
    )


# --------------------------------------------------------------------------
# 事实源补充类别与目标推导（AC-2 / AC-8 的缺省规则）
# --------------------------------------------------------------------------


def test_structured_source_flags_dirty_tracked_worktree(tmp_path: Path) -> None:
    code = _make_repo(tmp_path / "feishu-code")
    deployment = sc.build_deployment(code_root=code, runtime_root=code, generation=1)
    # EVO-20261007-9c6eccf3: 绑定树为 release checkout，脏树改测绑定树。
    bound = Path(deployment.code_root)
    (bound / "app.py").write_text("print('dirty')\n", encoding="utf-8")

    facts = sc._binding_problems_structured(deployment, code_root=bound, runtime_root=code)
    assert [fact.kind for fact in facts] == [BindingProblemKind.TRACKED_WORKTREE_DIRTY]
    assert facts[0].text == "code_root tracked worktree is dirty"
    assert [fact.text for fact in facts] == sc.verify_deployment_binding(
        deployment, code_root=bound, runtime_root=code
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("feishu-code", "feishu"),
        ("mirror-web", "web"),
        ("mirror-learning", "learning"),
        ("shared-root", "all"),
    ],
)
def test_restart_target_default_derivation(name: str, expected: str) -> None:
    assert sc._derive_restart_target_from_code_root(f"/srv/{name}") == expected


# --------------------------------------------------------------------------
# 工具面同族补齐（AC-2 / AC-4 / AC-11 / INV-8：禁止另写文案）
# --------------------------------------------------------------------------


def _tool(tmp_path: Path) -> tuple[ServiceControlTool, ManagedServiceDeploymentStore]:
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    return ServiceControlTool(store=store, worker_spawner=lambda _action_id: None), store


def test_tool_publish_dirty_tree_reuses_single_source_next_step(tmp_path: Path) -> None:
    code = _make_repo(tmp_path / "feishu-code")
    tool, _ = _tool(tmp_path)
    (code / "app.py").write_text("print('dirty')\n", encoding="utf-8")

    result = tool.execute(action="publish", code_root=str(code))
    assert result.status.value == "failure"
    assert "[service_control publish rejected]" in result.content
    assert "next_step:" in result.content
    note = sc._NEXT_STEP_BY_KIND[BindingProblemKind.TRACKED_WORKTREE_DIRTY].note
    assert note in result.content
    assert "tracked_worktree_dirty" in result.content


def test_tool_publish_missing_artifact_reuses_single_source_next_step(
    tmp_path: Path,
) -> None:
    code = _make_repo(tmp_path / "feishu-code")
    shutil.rmtree(code / "webui" / "dist")
    tool, _ = _tool(tmp_path)

    result = tool.execute(action="publish", code_root=str(code))
    assert result.status.value == "failure"
    assert "artifact_missing" in result.content
    note = sc._NEXT_STEP_BY_KIND[BindingProblemKind.WEBUI_ARTIFACT_UNAVAILABLE].note
    assert note in result.content


def test_tool_update_partial_reports_published_half_with_same_source_step(
    tmp_path: Path,
) -> None:
    code = _make_repo(tmp_path / "feishu-code")
    tool, store = _tool(tmp_path)

    AdmissionBarrierRegistry(store.data_dir).establish(
        "feishu", operation_id="svc-foreign-owner", reason="restart"
    )

    result = tool.execute(action="update", code_root=str(code), reason="deploy new build")
    assert result.status.value == "failure"
    assert "partial" in result.content
    assert "generation=1" in result.content
    assert "git_head=" in result.content
    assert "next_step:" in result.content
    conflict_note = sc._NEXT_STEP_BY_KIND[NEXT_STEP_KIND_GENERATION_CONFLICT].note
    assert conflict_note in result.content
    deployment = store.read()
    assert deployment is not None
    assert deployment.generation == 1

def test_tool_publish_empty_artifact_dir_maps_to_no_preset_step(tmp_path: Path) -> None:
    """产物目录存在但为空 → 走 binding 结构化分支，下一步同源（不另写文案）。"""
    code = _make_repo(tmp_path / "feishu-code")
    shutil.rmtree(code / "webui" / "dist")
    (code / "webui" / "dist").mkdir()
    tool, _ = _tool(tmp_path)

    result = tool.execute(action="publish", code_root=str(code))
    assert result.status.value == "failure"
    assert "next_step:" in result.content
    note = sc._NEXT_STEP_BY_KIND[BindingProblemKind.GIT_STATUS_UNAVAILABLE].note
    assert note in result.content


def test_tool_publish_non_repo_root_maps_to_error_fact_step(tmp_path: Path) -> None:
    """非 git 目录 + 产物齐备 → 非 ValueError 的失败面，仍追加同源事实行。"""
    code = tmp_path / "plain-code"
    (code / "webui" / "dist").mkdir(parents=True)
    (code / "webui" / "dist" / "index.html").write_text("<html/>\n", encoding="utf-8")
    tool, _ = _tool(tmp_path)

    result = tool.execute(action="publish", code_root=str(code))
    assert result.status.value == "failure"
    assert "next_step:" in result.content
    # CT-2/3：环境类失败映射 GIT_HEAD_UNAVAILABLE（封闭 kind），替代原裸串
    # publish_error 兜底——断言从"兜底裸串存在"升为"分类=特定 kind 且映射
    # note 完整呈现"，判定强度不降反升。
    note = sc._NEXT_STEP_BY_KIND[BindingProblemKind.GIT_HEAD_UNAVAILABLE].note
    assert note in result.content


def test_next_step_text_is_empty_for_empty_kind_list() -> None:
    from llm_loop.tools.builtin.service_control import _next_step_text

    assert _next_step_text([]) == ""