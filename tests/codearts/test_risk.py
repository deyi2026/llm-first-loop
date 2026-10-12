"""风险分类器单元测试（design.md §2.2.2.7）."""

from __future__ import annotations

from llm_loop.codearts.models import DispatchTask, RiskLevel
from llm_loop.codearts.risk import PatternRiskClassifier
from llm_loop.tools.safety import CatastrophicGuard


def _make_task(desc: str) -> DispatchTask:
    return DispatchTask(task_description=desc, trace_id="t1")


def test_normal_task():
    guard = CatastrophicGuard(audit_dir=None)
    classifier = PatternRiskClassifier(guard)
    risk = classifier.classify(_make_task("运行单元测试并报告结果"))
    assert risk.level == RiskLevel.NORMAL
    assert risk.local_blocked is False


def test_catastrophic_production_deploy():
    guard = CatastrophicGuard(audit_dir=None)
    classifier = PatternRiskClassifier(guard)
    risk = classifier.classify(_make_task("production deploy 到生产环境"))
    assert risk.level == RiskLevel.CATASTROPHIC


def test_catastrophic_force_push():
    guard = CatastrophicGuard(audit_dir=None)
    classifier = PatternRiskClassifier(guard)
    risk = classifier.classify(_make_task("git push --force 到主分支"))
    assert risk.level == RiskLevel.CATASTROPHIC


def test_catastrophic_terraform_destroy():
    guard = CatastrophicGuard(audit_dir=None)
    classifier = PatternRiskClassifier(guard)
    risk = classifier.classify(_make_task("terraform destroy 销毁环境"))
    assert risk.level == RiskLevel.CATASTROPHIC


def test_local_blocked_rm_rf():
    guard = CatastrophicGuard(audit_dir=None)
    classifier = PatternRiskClassifier(guard)
    risk = classifier.classify(_make_task("rm -rf /"))
    assert risk.local_blocked is True
    assert risk.level == RiskLevel.CATASTROPHIC


def test_local_blocked_mkfs():
    guard = CatastrophicGuard(audit_dir=None)
    classifier = PatternRiskClassifier(guard)
    risk = classifier.classify(_make_task("mkfs.ext4 /dev/sda1"))
    assert risk.local_blocked is True


def test_credential_not_in_assessment():
    guard = CatastrophicGuard(audit_dir=None)
    classifier = PatternRiskClassifier(guard)
    risk = classifier.classify(_make_task("normal task"))
    assert "ak" not in risk.reason.lower()
    assert "sk" not in risk.reason.lower()
    assert "token" not in risk.reason.lower()
