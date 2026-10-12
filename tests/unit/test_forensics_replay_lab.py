"""T6 取证闭环测试（tasks 1.9，design §2.4 T6，spec 5.1.1-2a/3a 验收）.

固化 P0 硬门判据（决策 D5）：
- replay_lab 对 E1 滥用形态复现成功回执（四条件逐项断言）
- 根因报告与实证证据一致性核对（时间耦合 + 内容同构 + 复现三证据齐备
  方可解锁修复合入——本测试为机检硬门）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_FORENSICS_DIR = _PROJECT_ROOT / "scripts" / "forensics"
if str(_FORENSICS_DIR) not in sys.path:
    sys.path.insert(0, str(_FORENSICS_DIR))

from build_report import build_forensics_report  # noqa: E402
from replay_lab import (  # noqa: E402
    content_has_trace_signature,
    replay_candidate_path,
)

FIXTURE_DIR = _PROJECT_ROOT / "tests" / "fixtures" / "trace_leak"


def _load_leak_sample(name: str = "leak-280-msg.jsonl") -> str:
    ev = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    return str(ev["payload"]["content"])


@pytest.fixture(scope="module")
def leak_sample() -> str:
    return _load_leak_sample()


@pytest.fixture(scope="module")
def root_cause_report(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """用仓库内脱敏 fixture 重建取证输入，不依赖本机运行态 event_logs/out。"""
    root = tmp_path_factory.mktemp("forensics-report")
    event_dir = root / "data" / "event_logs"
    out_dir = root / "scripts" / "forensics" / "out"
    event_dir.mkdir(parents=True)
    out_dir.mkdir(parents=True)

    event_rows: list[dict] = []
    for name in (
        "incident-context-279.jsonl",
        "leak-280-msg.jsonl",
        "isomorphic-replay-pair.jsonl",
        "leak-290-msg.jsonl",
    ):
        for line in (FIXTURE_DIR / name).read_text(encoding="utf-8").splitlines():
            if line.strip():
                event_rows.append(json.loads(line))
    event_rows.sort(key=lambda row: int((row.get("payload") or {}).get("index", -1)))
    incident = event_dir / "004976ea-5a23-4ae9-9f16-83b18767720a.jsonl"
    incident.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in event_rows) + "\n",
        encoding="utf-8",
    )

    sample = _load_leak_sample()
    for candidate in ("e1_abuse", "interop_legacy_tail", "err1210_defer_residual"):
        receipt = replay_candidate_path(candidate, sample, repo_root=_PROJECT_ROOT).to_dict()
        (out_dir / f"replay-{candidate}.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    return build_forensics_report(root)


class TestReplayLabVerdict:
    """replay_candidate_path 四条件回执断言（spec 5.1.1-2a）。"""

    def test_e1_abuse_reproduces_all_four_conditions(self, leak_sample: str) -> None:
        verdict = replay_candidate_path("e1_abuse", leak_sample, repo_root=_PROJECT_ROOT)
        assert verdict.reproduced is True
        # 四条件逐项（design §2.1.3-P0 判定口径）
        assert verdict.conditions["persisted_role_user"] is True
        assert verdict.conditions["program_origin_false"] is True
        assert verdict.conditions["trace_signature_hit"] is True
        assert verdict.conditions["not_via_feishu_web"] is True

    def test_e1_abuse_snapshot_matches_incident_identity(self, leak_sample: str) -> None:
        """落盘消息身份快照与实证 #280 一致（role/origin/program_origin/指纹）。"""
        verdict = replay_candidate_path("e1_abuse", leak_sample, repo_root=_PROJECT_ROOT)
        snap = verdict.persisted_snapshot
        assert len(snap) == 1
        entry = snap[0]
        assert entry["role"] == "user"
        assert entry["origin_layer"] == "user_instruction"
        assert entry["program_origin"] is False

    def test_interop_legacy_tail_falsified(self, leak_sample: str) -> None:
        """interop 历史版本 tail 链路零落盘 → 证伪（版本差异审计交叉印证）。"""
        verdict = replay_candidate_path(
            "interop_legacy_tail", leak_sample, repo_root=_PROJECT_ROOT
        )
        assert verdict.reproduced is False
        assert verdict.conditions["persisted_role_user"] is False

    def test_err1210_defer_residual_falsified(self, leak_sample: str) -> None:
        """err1210 defer 残留重放零落盘 → 证伪。"""
        verdict = replay_candidate_path(
            "err1210_defer_residual", leak_sample, repo_root=_PROJECT_ROOT
        )
        assert verdict.reproduced is False
        assert verdict.conditions["persisted_role_user"] is False

    def test_unknown_candidate_rejected(self, leak_sample: str) -> None:
        with pytest.raises(ValueError):
            replay_candidate_path("no_such_path", leak_sample)

    def test_scenarios_isolated(self, leak_sample: str) -> None:
        """三类剧本相互隔离：e1 落盘态不影响另两类剧本的空落盘判定。"""
        e1 = replay_candidate_path("e1_abuse", leak_sample, repo_root=_PROJECT_ROOT)
        it = replay_candidate_path("interop_legacy_tail", leak_sample, repo_root=_PROJECT_ROOT)
        assert e1.reproduced is True and it.reproduced is False


class TestTraceSignature:
    """轨迹特征判定（#280/#290 结构模板）。"""

    def test_leak_fixture_hits_signature(self, leak_sample: str) -> None:
        assert content_has_trace_signature(leak_sample) is True

    def test_normal_user_text_no_hit(self) -> None:
        assert content_has_trace_signature("检查上下文情况，是否有注入污染影响？") is False
        assert content_has_trace_signature("帮我看一下这个报错：ValueError: bad arg") is False


class TestHardGateEvidence:
    """硬门判据机检：三证据齐备方可解锁修复合入（决策 D5 / spec 5.1.1-3a）。"""

    def test_report_four_evidence_complete(self, root_cause_report: dict) -> None:
        fe = root_cause_report["four_evidence"]
        for kind in ("static_scan", "time_coupling", "content_isomorphism", "replay"):
            assert kind in fe and fe[kind].get("finding"), f"缺证据: {kind}"
        assert root_cause_report["evidence_complete_for_hard_gate"] is True

    def test_report_confidence_upgraded_to_confirmed(self, root_cause_report: dict) -> None:
        assert "确证" in root_cause_report["confidence"]

    def test_time_coupling_present(self, root_cause_report: dict) -> None:
        rows = root_cause_report["time_coupling_table"]
        assert any("#280 泄漏注入" in r["event"] for r in rows)
        assert any("#290 二次注入" in r["event"] for r in rows)

    def test_content_isomorphism_byte_identical(self, root_cause_report: dict) -> None:
        iso = root_cause_report["content_isomorphism"]
        assert iso["leak_pair_byte_identical"] is True
        assert iso["metadata_form_matches_e1"] is True

    def test_replay_receipt_confirmed(self, root_cause_report: dict) -> None:
        replays = root_cause_report["replay_receipts"]
        assert any(r.get("reproduced") for r in replays), "至少一条通路被复现实验证实"
