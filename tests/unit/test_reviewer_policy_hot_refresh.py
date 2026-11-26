"""Reviewer policy hot refresh: the real HostReviewAdmission on the refresh_config path.

Pins the boundaries a naive "swap the global tuple" would break:

* an accepted review keeps the candidates it was accepted under -- a retry never
  drifts to a model that was not part of its own policy;
* a regular refresh only affects new reviews; an explicit revocation or a real
  policy drift fails in-flight reviews closed by the existing rule;
* an invalid refresh is a diagnostic, not a block: the last effective chain keeps
  serving new reviews;
* unconfigured / revoked never falls back to any model, including the session's.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from llm_loop.core.run_context import current_model_label, current_session_id
from llm_loop.llm.model_roles import reviewer_models_configured
from llm_loop.tools import review_host_admission as rha
from llm_loop.tools.review_host_admission import HostReviewAdmission
from tests.unit.test_review_host_admission import _repo
from tests.unit.test_review_model_config import RecordingRunner

CHAIN_A = "glm/glm-5.3-flash"
CHAIN_AB = "glm/glm-5.3-flash,deepseek/deepseek-v4-flash"
CHAIN_BC = "deepseek/deepseek-v4-flash,minimax/MiniMax-M3.1-Flash"
INVALID = "bad/model,,other/model"


class MultiRunner(RecordingRunner):
    """Fake runner that keeps several reviewer children apart (new + in-flight)."""

    def __init__(self) -> None:
        super().__init__()
        self.children: dict[str, dict[str, str]] = {}

    def start(self, task: str, **kwargs):  # noqa: ANN001, ANN201
        result = super().start(task, **kwargs)
        if result.get("accepted"):
            child_id = f"child-{len(self.models)}"
            result["child_id"] = child_id
            self.children[child_id] = {
                "model": str(kwargs["model"]), "state": "running", "answer": "",
                # 审查权威在 runner.start 前后以 current_session_id 绑定 parent：按子代理记录。
                "parent": str(current_session_id.get() or ""),
            }
        return result

    def review_terminal_current(self, child_id: str, parent_id: str):  # noqa: ANN201
        row = self.children.get(child_id)
        if row is None or row["state"] != "completed" or parent_id != row["parent"]:
            return None
        return {
            "child_id": child_id, "parent_id": parent_id, "state": row["state"],
            "generation": "gen-1", "review_isolated": True,
            "final_answer": row["answer"], "observed_model": row["model"],
        }

    def result_current(self, child_id: str, wait_seconds=0):  # noqa: ANN201
        row = self.children[child_id]
        completed = row["state"] == "completed"
        result = SimpleNamespace(final_answer=row["answer"], outcome=row["state"])
        return True, "ok", {
            "child_id": child_id, "parent_id": row["parent"], "state": row["state"],
            "result_id": "result-verified" if completed else "",
            "generation": "gen-1", "result": result,
            "local_active": not completed,
        }

    def settle_pass(self, child_id: str, receipt: dict) -> None:
        self.children[child_id].update(
            state="completed",
            answer=f"VERDICT: PASS\nP0=0 P1=0 P2=0\nSHA256: {receipt['candidate_sha256']}",
        )


def _chain(raw: str) -> tuple[str, ...]:
    return tuple(raw.split(","))


def _digest_of(raw: str) -> str:
    return HostReviewAdmission(reviewer_models_raw=raw)._policy_digest


def _host(raw: str, runner: MultiRunner) -> HostReviewAdmission:
    host = HostReviewAdmission(reviewer_models_raw=raw)
    host.attach_runner(runner)
    return host


def _start(host: HostReviewAdmission, runner: MultiRunner, repo: Path, parent: str = "author-1") -> dict:
    return host.start(parent, "full_test", workdir=str(repo), command="pytest -q")


# ── 1. 有效刷新：只有新审查消费新候选 ───────────────────────────────────────────


def test_valid_refresh_is_consumed_by_the_next_start(tmp_path) -> None:  # noqa: ANN001
    repo = _repo(tmp_path)
    runner = MultiRunner()
    host = _host(CHAIN_AB, runner)
    before = host._policy_digest

    result = host.refresh_reviewer_models(CHAIN_BC)

    assert result["applied"] is True and result["changed"] is True and result["revoked"] is False
    assert result["previous_models"] == list(_chain(CHAIN_AB))
    assert result["models"] == list(_chain(CHAIN_BC))
    assert "热更新" in result["note"]
    assert host._policy_digest != before
    assert host._reviewer_model_error == ""

    receipt = _start(host, runner, repo)
    assert receipt["accepted"] is True
    assert receipt["reviewer_model"] == "deepseek/deepseek-v4-flash"
    assert receipt["review_budget"]["models"] == list(_chain(CHAIN_BC))
    row = host._records[receipt["child_id"]]
    assert row.reviewer_models == _chain(CHAIN_BC)
    assert row.policy_digest == host._policy_digest


# ── 2. 无效刷新：诊断与阻断分离 ─────────────────────────────────────────────────


def test_invalid_refresh_is_diagnostic_only_and_keeps_in_flight_review_usable(tmp_path) -> None:  # noqa: ANN001
    repo = _repo(tmp_path)
    runner = MultiRunner()
    host = _host(CHAIN_AB, runner)
    inflight = _start(host, runner, repo, parent="author-1")
    digest = host._policy_digest

    result = host.refresh_reviewer_models(INVALID)

    assert result["applied"] is False and result["changed"] is False
    assert "无效" in result["note"] and "保留上次有效候选" in result["note"]
    # 有效策略原样保留；error 只是诊断。
    assert host._reviewer_models == _chain(CHAIN_AB)
    assert host._reviewer_model_error == "reviewer_models_invalid"
    assert host._policy_digest == digest

    # (a) 诊断不得阻断新审查，且仍用保留的有效链。
    fresh = _start(host, runner, repo, parent="author-2")
    assert fresh["accepted"] is True
    assert fresh["reviewer_model"] == "glm/glm-5.3-flash"

    # (b) 在途审查照常签发并可消费。
    runner.settle_pass(inflight["child_id"], inflight)
    assert host.poll("author-1", inflight["child_id"])["qualification"] == "PASS"
    row = host._records[inflight["child_id"]]
    assert host._consume("author-1", "full_test", row.target, row.sha).allowed is True

    # (c) 之后的有效刷新清掉诊断，有效策略不变。
    assert host.refresh_reviewer_models(CHAIN_AB)["reviewer_model_error"] == ""
    assert host._policy_digest == digest


def test_invalid_refresh_without_any_effective_chain_still_refuses(tmp_path) -> None:  # noqa: ANN001
    repo = _repo(tmp_path)
    runner = MultiRunner()
    host = _host("", runner)
    assert host.refresh_reviewer_models(INVALID)["applied"] is False
    refused = _start(host, runner, repo)
    assert refused == {"accepted": False, "reason": "reviewer_models_invalid"}
    assert runner.models == []


# ── 3. 明确撤销 / 策略漂移：既有 fail-closed 语义 ───────────────────────────────


def test_explicit_revocation_refuses_new_reviews_and_fails_in_flight_closed(tmp_path) -> None:  # noqa: ANN001
    repo = _repo(tmp_path)
    runner = MultiRunner()
    host = _host(CHAIN_AB, runner)
    inflight = _start(host, runner, repo)
    digest = host._policy_digest

    result = host.refresh_reviewer_models("")

    assert result["revoked"] is True and result["applied"] is True and result["changed"] is True
    assert host._reviewer_models == () and host._policy_digest != digest
    # 新审查一律拒绝，不回退任何模型。
    refused = _start(host, runner, repo, parent="author-2")
    assert refused == {"accepted": False, "reason": "reviewer_models_unconfigured"}
    assert runner.models == ["glm/glm-5.3-flash"]
    # 在途审查：不重试、不签发。
    assert host._respawn_reviewer("author-1", inflight["child_id"], "reviewer_rate_limited", 240) is None
    runner.settle_pass(inflight["child_id"], inflight)
    polled = host.poll("author-1", inflight["child_id"])
    assert polled["qualification"] == "DENIED" and polled["reason"] == "review_policy_changed"
    assert runner.models == ["glm/glm-5.3-flash"]


def test_policy_drift_fails_in_flight_closed_and_blocks_retry(tmp_path) -> None:  # noqa: ANN001
    repo = _repo(tmp_path)
    runner = MultiRunner()
    host = _host(CHAIN_AB, runner)
    inflight = _start(host, runner, repo)

    assert host.refresh_reviewer_models(CHAIN_BC)["changed"] is True

    # 旧审查的重试：不预占名额、不 spawn（冻结策略已不是当前策略）。
    assert host._respawn_reviewer("author-1", inflight["child_id"], "reviewer_rate_limited", 240) is None
    assert host._records[inflight["child_id"]].attempts == 0
    assert runner.models == ["glm/glm-5.3-flash"]
    runner.settle_pass(inflight["child_id"], inflight)
    assert host.poll("author-1", inflight["child_id"])["reason"] == "review_policy_changed"
    # 新审查用新候选链。
    fresh = _start(host, runner, repo, parent="author-2")
    assert fresh["reviewer_model"] == "deepseek/deepseek-v4-flash"


def test_grant_issued_before_drift_is_not_consumable_after_it(tmp_path) -> None:  # noqa: ANN001
    repo = _repo(tmp_path)
    runner = MultiRunner()
    host = _host(CHAIN_AB, runner)
    issued = _start(host, runner, repo)
    runner.settle_pass(issued["child_id"], issued)
    assert host.poll("author-1", issued["child_id"])["qualification"] == "PASS"
    row = host._records[issued["child_id"]]

    host.refresh_reviewer_models(CHAIN_BC)

    denied = host._consume("author-1", "full_test", row.target, row.sha)
    assert denied.allowed is False and "策略" in denied.reason
    assert row.granted is True and row.consumed is False


def test_identical_refresh_leaves_in_flight_review_untouched(tmp_path) -> None:  # noqa: ANN001
    repo = _repo(tmp_path)
    runner = MultiRunner()
    host = _host(CHAIN_AB, runner)
    inflight = _start(host, runner, repo)
    digest = host._policy_digest

    result = host.refresh_reviewer_models(" glm/glm-5.3-flash , deepseek/deepseek-v4-flash ")

    assert result["changed"] is False and "未变" in result["note"]
    assert host._policy_digest == digest
    runner.settle_pass(inflight["child_id"], inflight)
    assert host.poll("author-1", inflight["child_id"])["qualification"] == "PASS"
    row = host._records[inflight["child_id"]]
    assert host._consume("author-1", "full_test", row.target, row.sha).allowed is True
    # 同一冻结链上的异步重试照常推进。
    again = _start(host, runner, repo, parent="author-2")
    retry = host._respawn_reviewer("author-2", again["child_id"], "reviewer_rate_limited", 240)
    assert retry is not None
    assert retry["auto_retry"]["model"] == "deepseek/deepseek-v4-flash"


# ── 4. 重试只读被接纳时冻结的链 ─────────────────────────────────────────────────


def test_retry_advances_on_the_chain_frozen_at_admission_not_the_live_tuple(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """只换全局 tuple 的朴素热更新会让在途重试漂移；冻结链把它钉住。"""
    repo = _repo(tmp_path)
    runner = MultiRunner()
    host = _host(CHAIN_AB, runner)
    runner.refusals = ["429 rate limit"]
    monkeypatch.setattr(rha.time, "sleep", lambda _: None)
    issued = _start(host, runner, repo)
    assert issued["reviewer_model"] == "deepseek/deepseek-v4-flash"  # 首个候选被限流后回落

    # 模拟「只换实时链、不动 digest」：deepseek 在新实时链里排第一，其后是 minimax。
    host._reviewer_models = _chain(CHAIN_BC)
    retry = host._respawn_reviewer("author-1", issued["child_id"], "reviewer_rate_limited", 240)

    assert retry is not None
    # 冻结链 [glm, deepseek] 上 deepseek 已是链尾：有界重试同一模型，绝不漂到 minimax。
    assert retry["auto_retry"]["model"] == "deepseek/deepseek-v4-flash"
    assert runner.models == [
        "glm/glm-5.3-flash", "deepseek/deepseek-v4-flash", "deepseek/deepseek-v4-flash",
    ]
    row = host._records[issued["child_id"]]
    assert row.reviewer_models == _chain(CHAIN_AB)
    assert row.reviewer_model == "deepseek/deepseek-v4-flash"


def test_record_without_frozen_chain_is_never_retried(tmp_path) -> None:  # noqa: ANN001
    from dataclasses import replace

    repo = _repo(tmp_path)
    runner = MultiRunner()
    host = _host(CHAIN_AB, runner)
    issued = _start(host, runner, repo)
    host._records[issued["child_id"]] = replace(
        host._records[issued["child_id"]], reviewer_models=(),
    )
    assert host._respawn_reviewer("author-1", issued["child_id"], "reviewer_rate_limited", 240) is None
    assert runner.models == ["glm/glm-5.3-flash"]


# ── 5. start 准备期间发生刷新 ───────────────────────────────────────────────────


def test_start_refuses_when_effective_policy_changes_during_preparation(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    repo = _repo(tmp_path)
    runner = MultiRunner()
    host = _host(CHAIN_AB, runner)
    prepared = host._input_budget

    def refreshed_during_preparation(task, reviewer_models=None):  # noqa: ANN001, ANN202
        host.refresh_reviewer_models(CHAIN_BC)  # 刷新落在锁外的准备阶段
        return prepared(task, reviewer_models)

    monkeypatch.setattr(host, "_input_budget", refreshed_during_preparation)
    receipt = _start(host, runner, repo)

    # 材料是按旧候选定价的：不按已不是当前的链 spawn，如实拒绝。
    assert receipt["accepted"] is False and receipt["reason"] == "review_policy_changed"
    assert runner.models == [] and host._records == {}
    # 调用方重新 start 即落在当前策略上。
    monkeypatch.setattr(host, "_input_budget", prepared)
    again = _start(host, runner, repo)
    assert again["reviewer_model"] == "deepseek/deepseek-v4-flash"


def test_start_proceeds_when_only_the_diagnostic_changes_during_preparation(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    repo = _repo(tmp_path)
    runner = MultiRunner()
    host = _host(CHAIN_AB, runner)
    prepared = host._input_budget

    def invalid_during_preparation(task, reviewer_models=None):  # noqa: ANN001, ANN202
        host.refresh_reviewer_models(INVALID)  # 诊断性刷新：有效策略不变
        return prepared(task, reviewer_models)

    monkeypatch.setattr(host, "_input_budget", invalid_during_preparation)
    receipt = _start(host, runner, repo)

    assert receipt["accepted"] is True
    assert receipt["reviewer_model"] == "glm/glm-5.3-flash"
    assert host._reviewer_model_error == "reviewer_models_invalid"


# ── 6. 新旧并发 ────────────────────────────────────────────────────────────────


def test_concurrent_refresh_and_start_never_mix_identities(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    repo = _repo(tmp_path)
    runner = MultiRunner()
    host = _host(CHAIN_AB, runner)
    prepared = host._input_budget

    def slow_prepare(task, reviewer_models=None):  # noqa: ANN001, ANN202
        time.sleep(0.002)  # 材料冻结与预算定价在锁外：给并发 refresh 留出真实窗口
        return prepared(task, reviewer_models)

    monkeypatch.setattr(host, "_input_budget", slow_prepare)
    stop = threading.Event()
    errors: list[str] = []
    receipts: list[dict] = []

    def refresher() -> None:
        flip = True
        while not stop.is_set():
            try:
                host.refresh_reviewer_models(CHAIN_BC if flip else CHAIN_AB)
            except Exception as exc:  # noqa: BLE001 — 记录而非中断，断言在主线程
                errors.append(f"refresh: {exc}")
            flip = not flip
            time.sleep(0.001)

    def starter() -> None:
        try:
            for _ in range(4):
                receipts.append(
                    host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"start: {exc}")

    threads = [threading.Thread(target=refresher)] + [
        threading.Thread(target=starter) for _ in range(6)
    ]
    for thread in threads:
        thread.start()
    for thread in threads[1:]:
        thread.join()
    stop.set()
    threads[0].join()

    assert not errors, errors
    assert len(receipts) == 24
    for receipt in receipts:
        assert receipt["accepted"] or receipt["reason"] == "review_policy_changed", receipt
    digests = {CHAIN_AB: _digest_of(CHAIN_AB), CHAIN_BC: _digest_of(CHAIN_BC)}
    accepted = [receipt for receipt in receipts if receipt["accepted"]]
    assert accepted, "并发窗口内没有任何审查被接纳，测试没有覆盖到竞态"
    for receipt in accepted:
        row = host._records[receipt["child_id"]]
        chain = ",".join(row.reviewer_models)
        assert chain in digests
        # 同一条记录的候选链与 digest 永远配套：不会出现「旧身份 + 新策略」。
        assert row.policy_digest == digests[chain]
        # 实际派发的身份来自这条记录自己的冻结链。
        assert row.reviewer_model in row.reviewer_models
        assert receipt["reviewer_model"] == row.reviewer_model
        assert runner.children[receipt["child_id"]]["model"] == row.reviewer_model
    current = ",".join(host._reviewer_models)
    assert host._policy_digest == digests[current]


# ── 7. 不回退任何模型（含父会话当前模型）；审计只观测不设闸 ───────────────────


def test_unconfigured_and_invalid_never_fall_back_to_the_session_model(tmp_path) -> None:  # noqa: ANN001
    repo = _repo(tmp_path)
    runner = MultiRunner()
    host = _host("", runner)
    token = current_model_label.set("glm/glm-5.4")  # 父会话（开发）模型
    try:
        assert _start(host, runner, repo)["reason"] == "reviewer_models_unconfigured"
        assert host.refresh_reviewer_models(INVALID)["models"] == []
        assert _start(host, runner, repo)["reason"] == "reviewer_models_invalid"
        assert host.refresh_reviewer_models(CHAIN_A)["applied"] is True
        assert _start(host, runner, repo)["reviewer_model"] == "glm/glm-5.3-flash"
        assert host.refresh_reviewer_models("")["revoked"] is True
        assert _start(host, runner, repo)["reason"] == "reviewer_models_unconfigured"
    finally:
        current_model_label.reset(token)
    assert runner.models == ["glm/glm-5.3-flash"]


def test_refresh_is_audited_but_never_gated_by_the_audit_write(tmp_path) -> None:  # noqa: ANN001
    class Store:
        enabled = True

        def __init__(self) -> None:
            self.rows: list[tuple[str, str, dict]] = []

        def append(self, parent, event_type, payload):  # noqa: ANN001, ANN202
            self.rows.append((parent, event_type, payload))
            return object()

    class Broken(Store):
        def append(self, *args):  # noqa: ANN002, ANN202
            raise OSError("disk full")

    host = HostReviewAdmission(reviewer_models_raw=CHAIN_AB)
    store = Store()
    host.attach_event_store(store)
    token = current_session_id.set("operator-session")
    try:
        result = host.refresh_reviewer_models(CHAIN_BC)
    finally:
        current_session_id.reset(token)
    parent, event_type, payload = store.rows[-1]
    assert (parent, event_type) == ("operator-session", "review_admission_reviewer_policy_refreshed")
    assert payload["changed"] is result["changed"] is True
    assert payload["policy_digest"] == host._policy_digest
    assert "note" not in payload

    host.attach_event_store(Broken())
    assert host.refresh_reviewer_models(CHAIN_AB)["changed"] is True
    assert host._reviewer_models == _chain(CHAIN_AB)


# ── 8. 真实生产入口：build_engine / refresh_config 执行器 ──────────────────────

_PROVIDERS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY",
        "models": {
            "deepseek-v4-flash": {"context": 1000000, "thinking": True, "cost_tier": "low"},
            "deepseek-v4-pro": {"context": 1000000, "thinking": True, "cost_tier": "high"},
        },
        "default_model": "deepseek-v4-flash",
    },
    "minimax": {
        "base_url": "https://api.minimax.chat/v1",
        "api_key_env": "MINIMAX_API_KEY",
        "models": {"MiniMax-M3": {"context": 1000000, "thinking": False, "cost_tier": "mid"}},
        "default_model": "MiniMax-M3",
    },
}


class _FakeLLM:
    timeout_s = 60.0
    thinking_mode = True
    reasoning_effort = "high"
    thinking_supported = True
    model = "deepseek-v4-flash"
    max_tokens = None
    wire_protocol = "openai"

    def chat(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise NotImplementedError


class _Engine:
    """install_refresh_executor 所需的最小 engine（真实 CorrectionContext + 真实 pool）。"""

    def __init__(self, pool) -> None:  # noqa: ANN001
        from llm_loop.introspection.corrections import CorrectionContext

        self.correction_ctx = CorrectionContext()
        self.correction_ctx.model_pool = pool


def _executor_env(monkeypatch, data_dir: Path) -> None:
    """refresh 执行器内 load_settings() 所需的最小 env（隔离 data_dir、假凭据）。"""
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("MODEL_PROVIDERS", "")
    monkeypatch.setenv("LLM_WIRE_PROTOCOL", "openai")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("LLM_MODEL", "deepseek-v4-flash")


def _pool(tmp_path: Path, monkeypatch):  # noqa: ANN001, ANN202
    from llm_loop.config import Settings
    from llm_loop.llm.pool import ModelClientPool
    from llm_loop.llm.providers import load_registry

    (tmp_path / "providers.json").write_text(json.dumps(_PROVIDERS), encoding="utf-8")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")
    monkeypatch.setenv("MINIMAX_API_KEY", "test-minimax-key")
    settings = Settings(
        llm_api_key="test-key",
        llm_base_url="https://api.deepseek.com/v1",
        llm_model="deepseek-v4-flash",
        data_dir=str(tmp_path),
        model_providers_raw="",
        model_fallbacks_raw="",
        self_inspection_enabled=False,
        extract_enabled=False,
    )
    return ModelClientPool(
        registry=load_registry(settings),
        default_client=_FakeLLM(),  # type: ignore[arg-type]
        model_fallbacks_raw="",
    )


def _managed_dotenv(monkeypatch, dotenv: Path) -> None:
    monkeypatch.setenv("LFL_ENV_FILE", str(dotenv))
    monkeypatch.delenv("LFL_RUNTIME_ROOT", raising=False)
    monkeypatch.delenv("LFL_REVIEWER_MODELS", raising=False)
    monkeypatch.delenv("LFL_MODEL_ROLES", raising=False)


def test_real_engine_refresh_config_hot_updates_reviewer_without_restart(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """真实生产装配：build_engine → refresh_config 工具 → HostReviewAdmission.start 消费新候选。"""
    from llm_loop.config import Settings
    from llm_loop.core.message import ToolResultStatus
    from llm_loop.factory import build_engine

    dotenv = tmp_path / ".env"
    dotenv.write_text("LFL_REVIEWER_MODELS=deepseek/deepseek-v4-flash\n", encoding="utf-8")
    _managed_dotenv(monkeypatch, dotenv)
    # 进程里只剩启动时的副本；运营者之后只改文件、不重启。
    monkeypatch.setenv("LFL_REVIEWER_MODELS", "deepseek/deepseek-v4-flash")
    _executor_env(monkeypatch, tmp_path)
    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        self_inspection_enabled=True,
        extract_enabled=False,
        reviewer_models_raw="deepseek/deepseek-v4-flash",
    )
    engine = build_engine(settings)
    authority = engine.host_review_admission
    assert authority is engine.registry._review_admission
    assert authority._reviewer_models == ("deepseek/deepseek-v4-flash",)
    runner = MultiRunner()
    authority.attach_runner(runner)  # 不触网：只换子代理执行器，审查权威仍是生产装配出的实例
    repo = _repo(tmp_path)

    def refresh() -> str:
        result = engine.corrections.execute("refresh_config", {})
        assert result.status == ToolResultStatus.SUCCESS
        return result.content

    # 1) 运营者改文件：无需重启，下一次 start 用新候选。
    dotenv.write_text(
        "LFL_REVIEWER_MODELS=minimax/MiniMax-M3.1-Flash,deepseek/deepseek-v4-flash\n",
        encoding="utf-8",
    )
    assert "审查员候选已热更新" in refresh()
    assert authority._reviewer_models == ("minimax/MiniMax-M3.1-Flash", "deepseek/deepseek-v4-flash")
    issued = authority.start("operator", "full_test", workdir=str(repo), command="pytest -q")
    assert issued["accepted"] is True
    assert issued["reviewer_model"] == "minimax/MiniMax-M3.1-Flash"

    # 2) 非法配置：不应用、保留有效链、不阻断新审查（诊断与阻断分离）。
    dotenv.write_text("LFL_REVIEWER_MODELS=bad/model,,other/model\n", encoding="utf-8")
    assert "审查员候选配置无效，未应用" in refresh()
    assert authority._reviewer_model_error == "reviewer_models_invalid"
    assert authority._reviewer_models == ("minimax/MiniMax-M3.1-Flash", "deepseek/deepseek-v4-flash")
    again = authority.start("operator", "full_test", workdir=str(repo), command="pytest -q")
    assert again["accepted"] is True
    assert again["reviewer_model"] == "minimax/MiniMax-M3.1-Flash"
    runner.settle_pass(issued["child_id"], issued)
    assert authority.poll("operator", issued["child_id"])["qualification"] == "PASS"

    # 3) 明确撤销：新审查拒绝，不回退任何模型。
    dotenv.write_text("LFL_REVIEWER_MODELS=\n", encoding="utf-8")
    assert "审查员候选已被运营者撤销" in refresh()
    refused = authority.start("operator", "full_test", workdir=str(repo), command="pytest -q")
    assert refused == {"accepted": False, "reason": "reviewer_models_unconfigured"}
    assert runner.models == ["minimax/MiniMax-M3.1-Flash", "minimax/MiniMax-M3.1-Flash"]


def test_refresh_config_execution_role_change_leaves_reviewer_policy_untouched(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """Reviewer 独立性：execution 角色热更新不波及 reviewer 解析与在途审查资格。"""
    from llm_loop.introspection.providers_registry_reload import install_refresh_executor

    pool = _pool(tmp_path, monkeypatch)
    _executor_env(monkeypatch, tmp_path)
    dotenv = tmp_path / ".env"
    _managed_dotenv(monkeypatch, dotenv)

    def write_roles(execution: str, reviewer: str) -> None:
        dotenv.write_text(
            "LFL_REVIEWER_MODELS=\nLFL_MODEL_ROLES="
            + json.dumps({"execution": [execution], "reviewer": [reviewer]})
            + "\n",
            encoding="utf-8",
        )

    startup = json.dumps({"execution": ["deepseek/deepseek-v4-flash"], "reviewer": ["minimax/MiniMax-M3"]})
    runner = MultiRunner()
    host = _host(reviewer_models_configured(startup, ""), runner)
    assert host._reviewer_models == ("minimax/MiniMax-M3",)
    repo = _repo(tmp_path)
    inflight = _start(host, runner, repo)
    digest = host._policy_digest
    engine = _Engine(pool)
    engine.host_review_admission = host
    install_refresh_executor(engine)

    write_roles("deepseek/deepseek-v4-flash", "minimax/MiniMax-M3")
    msg = engine.correction_ctx.refresh_executor()
    assert "审查员候选已核验未变（minimax/MiniMax-M3）" in msg
    assert pool.role_candidates("execution") == ["deepseek/deepseek-v4-flash"]

    # 只改 execution 角色：reviewer 解析与在途审查资格都不受影响。
    write_roles("deepseek/deepseek-v4-pro", "minimax/MiniMax-M3")
    msg = engine.correction_ctx.refresh_executor()
    assert pool.role_candidates("execution") == ["deepseek/deepseek-v4-pro"]
    assert "审查员候选已核验未变（minimax/MiniMax-M3）" in msg
    assert host._policy_digest == digest
    runner.settle_pass(inflight["child_id"], inflight)
    assert host.poll("author-1", inflight["child_id"])["qualification"] == "PASS"
    row = host._records[inflight["child_id"]]
    assert host._consume("author-1", "full_test", row.target, row.sha).allowed is True

    # 只改 reviewer 角色：execution 路由不变，审查员策略热更新。
    write_roles("deepseek/deepseek-v4-pro", "deepseek/deepseek-v4-pro")
    msg = engine.correction_ctx.refresh_executor()
    assert pool.role_candidates("execution") == ["deepseek/deepseek-v4-pro"]
    assert "审查员候选已热更新：minimax/MiniMax-M3 → deepseek/deepseek-v4-pro" in msg
    assert host._reviewer_models == ("deepseek/deepseek-v4-pro",)


def test_refresh_config_unreadable_or_invalid_config_keeps_last_effective_chain(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    from llm_loop.introspection.providers_registry_reload import install_refresh_executor

    pool = _pool(tmp_path, monkeypatch)
    _executor_env(monkeypatch, tmp_path)
    dotenv = tmp_path / ".env"
    _managed_dotenv(monkeypatch, dotenv)
    dotenv.write_text("LFL_REVIEWER_MODELS=deepseek/deepseek-v4-flash\n", encoding="utf-8")
    runner = MultiRunner()
    host = _host("deepseek/deepseek-v4-flash", runner)
    engine = _Engine(pool)
    engine.host_review_admission = host
    install_refresh_executor(engine)
    repo = _repo(tmp_path)
    chain = ("deepseek/deepseek-v4-flash",)

    # 角色映射本身非法：绝不能被当成「撤销审查员」。
    dotenv.write_text("LFL_REVIEWER_MODELS=\nLFL_MODEL_ROLES='{invalid'\n", encoding="utf-8")
    msg = engine.correction_ctx.refresh_executor()
    assert "模型角色配置未应用" in msg
    assert "审查员候选配置未刷新（保留上次有效候选）：model_roles_invalid_json" in msg
    assert host._reviewer_models == chain

    # 遗留变量非法：不应用，仅诊断，新审查照常。
    dotenv.write_text("LFL_REVIEWER_MODELS=bad/model,,x/y\n", encoding="utf-8")
    msg = engine.correction_ctx.refresh_executor()
    assert "审查员候选配置无效，未应用（reviewer_models_invalid）" in msg
    assert host._reviewer_models == chain
    assert host._reviewer_model_error == "reviewer_models_invalid"
    assert _start(host, runner, repo)["accepted"] is True

    # 受管 dotenv 不可读：保留上次有效候选。
    dotenv.unlink()
    msg = engine.correction_ctx.refresh_executor()
    assert "审查员候选配置未刷新（保留上次有效候选）：model_roles_config_unreadable" in msg
    assert host._reviewer_models == chain


def test_refresh_config_without_reviewer_wiring_reports_nothing(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    from llm_loop.introspection.providers_registry_reload import install_refresh_executor

    pool = _pool(tmp_path, monkeypatch)
    _executor_env(monkeypatch, tmp_path)
    monkeypatch.setenv("LFL_REVIEWER_MODELS", "glm/glm-5.3-flash")
    engine = _Engine(pool)
    install_refresh_executor(engine)

    assert "审查员" not in engine.correction_ctx.refresh_executor()
