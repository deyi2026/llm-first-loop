"""`T-GATE-5`（五类证据分开与阶段门禁）+ `T-OPS-1/2/3`（交付边界）测试。

覆盖 RTM：EVD-01/02/03/04/05/06、OBS-06/07/09、PRF-01/08。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_loop.realtime.delivery_boundary import (
    RUNTIME_USER_STATE_FILES,
    CommitBoundaryError,
    CommitPlan,
    is_ignored,
    is_tracked,
    rollback_playbook,
)
from llm_loop.realtime.evidence_grading import EvidenceLevel
from llm_loop.realtime.evidence_report import (
    AcceptanceStatus,
    EvidenceClass,
    EvidenceEntry,
    EvidenceReport,
)

REPO = str(Path(__file__).resolve().parents[2])


class TestEvidenceClassesSeparated:
    def test_evidence_reported_by_class_separately(self):
        report = EvidenceReport()
        report.add(EvidenceEntry("unit", EvidenceClass.SIMULATED, EvidenceLevel.SERVICE_LEVEL, measured=True, met=True))
        report.add(EvidenceEntry("probe_c", EvidenceClass.REAL_PROVIDER, EvidenceLevel.SERVICE_LEVEL, measured=True, met=True))
        assert len(report.by_class(EvidenceClass.SIMULATED)) == 1
        assert len(report.by_class(EvidenceClass.REAL_PROVIDER)) == 1

    def test_missing_real_evidence_listed(self):
        report = EvidenceReport()
        report.add(EvidenceEntry("unit", EvidenceClass.SIMULATED, EvidenceLevel.SERVICE_LEVEL, measured=True, met=True))
        assert "real_device" in report.missing_real_evidence()
        assert "browser_link" not in report.missing_real_evidence()


class TestBrowserLinkAcceptance:
    def test_simulated_never_accepts(self):
        report = EvidenceReport()
        report.add(EvidenceEntry("sim", EvidenceClass.SIMULATED, EvidenceLevel.BROWSER_LINK, measured=True, met=True))
        assert report.acceptance_status("sim") is AcceptanceStatus.NOT_ACCEPTED

    def test_service_level_does_not_fill_browser_acceptance(self):
        report = EvidenceReport()
        report.add(EvidenceEntry("svc", EvidenceClass.REAL_PROVIDER, EvidenceLevel.SERVICE_LEVEL, measured=True, met=True))
        assert report.service_level_is_not_browser_acceptance() is True
        assert report.may_declare_pass() is False  # 禁止提前写 PASS

    def test_measured_not_met_reported_distinctly(self):
        report = EvidenceReport()
        report.add(EvidenceEntry("browser", EvidenceClass.REAL_DEVICE, EvidenceLevel.BROWSER_LINK, measured=True, met=False))
        assert report.acceptance_status("browser") is AcceptanceStatus.MEASURED_NOT_MET
        assert report.may_declare_pass() is False

    def test_pass_requires_measured_and_met_browser_evidence(self):
        report = EvidenceReport()
        report.add(EvidenceEntry("browser", EvidenceClass.REAL_DEVICE, EvidenceLevel.BROWSER_LINK, measured=True, met=True))
        assert report.may_declare_pass() is True

    def test_unmeasured_browser_entry_not_accepted(self):
        report = EvidenceReport()
        report.add(EvidenceEntry("browser", EvidenceClass.REAL_DEVICE, EvidenceLevel.BROWSER_LINK, measured=False, met=False))
        assert report.acceptance_status("browser") is AcceptanceStatus.NOT_ACCEPTED

    def test_to_dict_reports_grading(self):
        report = EvidenceReport()
        report.add(EvidenceEntry("probe_c", EvidenceClass.REAL_PROVIDER, EvidenceLevel.SERVICE_LEVEL, measured=True, met=True))
        data = report.to_dict()
        assert data["service_level"] == 1
        assert data["browser_link"] == 0
        assert data["may_declare_pass"] is False


class TestCommitBoundary:
    def test_broad_add_is_rejected(self):
        with pytest.raises(CommitBoundaryError):
            CommitPlan((".",))
        with pytest.raises(CommitBoundaryError):
            CommitPlan(("-A",))

    def test_runtime_file_is_rejected(self):
        with pytest.raises(CommitBoundaryError):
            CommitPlan((RUNTIME_USER_STATE_FILES[0],))

    def test_exact_paths_accepted(self):
        plan = CommitPlan(("src/llm_loop/realtime/media_usage.py", "tests/realtime/test_media_usage.py"))
        assert plan.is_exact() is True

    def test_glob_paths_not_exact(self):
        assert CommitPlan(("docs/*.md",)).is_exact() is False


class TestRuntimeFilesNotTracked:
    def test_runtime_user_state_files_are_ignored_and_untracked(self):
        for path in RUNTIME_USER_STATE_FILES:
            assert is_tracked(path, cwd=REPO) is False
            assert is_ignored(path, cwd=REPO) is True

    def test_delivery_documents_are_tracked_paths_not_runtime(self):
        # 交付文档属于可提交源码/文档路径，不属运行态
        for path in RUNTIME_USER_STATE_FILES:
            assert path not in (
                "docs/SPEC-20261023-realtime-multimodal-requirements-v1.md",
                "docs/DESIGN-20261023-realtime-multimodal-architecture.md",
                "docs/TASKS-20261023-realtime-multimodal-implementation.md",
            )


class TestRollbackBoundary:
    def test_playbook_keeps_task_facts(self):
        playbook = rollback_playbook()
        assert "disable_realtime_media_entrypoints" in playbook["steps"]
        assert "restore_text_only_entrypoint" in playbook["steps"]
        assert "task_facts" in playbook["must_preserve"]
        assert "do_not_interrupt_other_services" in playbook["steps"]
