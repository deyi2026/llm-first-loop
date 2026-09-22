"""EVO-20260920-213965a1 案1/案2: pending 投影跨会话可见化.

- 案2: wake 降级为 notify 后，下一会话投影列出 sid/ts/reason，
  而不是零可见（incident: 12:50 grant 随 owner 死亡 → 12:55 到点降级
  无人消费）。
- 案1: 控制面自核验判 failed 的 restart 动作进入投影（unhealthy 可见）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from llm_loop.factory import (
    _scan_degraded_wake_notify,
    _scan_failed_service_actions,
)
from llm_loop.runtime.service_control import ManagedServiceDeploymentStore


def _write_notify(data_dir: Path, name: str, payload: dict) -> None:
    inbox = data_dir / "interop" / "lfl_to_dsh" / "pending"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_scan_degraded_wake_notify_lists_sid_ts_reason(tmp_path: Path) -> None:
    _write_notify(
        tmp_path,
        "20260920-sched-20260920-125500-abc.json",
        {
            "from": "lfl-scheduler",
            "to": "lfl",
            "topic": "notify",
            "ref": "sched-abc",
            "ts": "2026-09-20T12:55:00+00:00",
            "body": "[定时提醒] do X",
            "status": "pending",
            "wake_degraded_reason": "grant_lost_owner_dead",
        },
    )
    # 普通提醒（无降级原因）走既有回显消费路径，不进本投影。
    _write_notify(
        tmp_path,
        "20260920-sched-20260920-130000-plain.json",
        {
            "from": "lfl-scheduler",
            "topic": "notify",
            "ref": "sched-plain",
            "ts": "2026-09-20T13:00:00+00:00",
            "body": "[定时提醒] plain",
            "status": "pending",
        },
    )
    items = _scan_degraded_wake_notify(tmp_path)
    assert len(items) == 1
    assert items[0]["sid"] == "sched-abc"
    assert items[0]["reason"] == "grant_lost_owner_dead"
    assert items[0]["ts"] == "2026-09-20T12:55:00+00:00"


def test_scan_degraded_wake_notify_fail_open_missing_dir(tmp_path: Path) -> None:
    assert _scan_degraded_wake_notify(tmp_path) == []


def test_scan_failed_service_actions_recent_failed_only(tmp_path: Path) -> None:
    store = ManagedServiceDeploymentStore(tmp_path)
    store.actions_dir.mkdir(parents=True, exist_ok=True)

    def _action(action_id: str, status: str, updated: datetime) -> None:
        (store.actions_dir / f"{action_id}.json").write_text(
            json.dumps(
                {
                    "action_id": action_id,
                    "action": "restart",
                    "target": "feishu",
                    "status": status,
                    "deployment_generation": 53,
                    "detail": "restart_mirror rc=0 but verify failed; verify=unhealthy",
                    "updated_at": updated.isoformat(),
                }
            ),
            encoding="utf-8",
        )

    now = datetime.now(UTC)
    _action("svc-fresh-failed", "failed", now)
    _action("svc-old-failed", "failed", now - timedelta(hours=25))
    _action("svc-succeeded", "succeeded", now)
    items = _scan_failed_service_actions(tmp_path)
    assert [i["action_id"] for i in items] == ["svc-fresh-failed"]
    assert items[0]["target"] == "feishu"
    assert items[0]["generation"] == 53
    assert "verify=unhealthy" in items[0]["detail"]


def test_scan_failed_service_actions_fail_open_missing_dir(tmp_path: Path) -> None:
    assert _scan_failed_service_actions(tmp_path) == []


def _publish_desired(store: ManagedServiceDeploymentStore, generation: int) -> None:
    from llm_loop.runtime.service_control import ManagedServiceDeployment

    current = store.read()
    cur = current.generation if current is not None else 0
    for gen in range(cur + 1, generation + 1):  # CAS 要求逐代 +1
        deployment = ManagedServiceDeployment(
            schema="managed-service-deployment/v1",
            deployment_id=f"deploy-{gen}",
            generation=gen,
            git_head="b" * 40,
            code_root="/tmp/code",
            runtime_root="/tmp/runtime",
            webui_artifact_sha256="c" * 64,
        )
        store.compare_and_swap(deployment, expected_generation=gen - 1)


def test_scan_failed_service_actions_filters_superseded_generation(
    tmp_path: Path,
) -> None:
    """R5: desired 代已前进 → 旧代失败动作不再占活跃投影（只读过滤）."""
    store = ManagedServiceDeploymentStore(tmp_path)
    store.actions_dir.mkdir(parents=True, exist_ok=True)
    _publish_desired(store, 55)
    now = datetime.now(UTC)

    def _action(action_id: str, status: str, generation: int) -> None:
        (store.actions_dir / f"{action_id}.json").write_text(
            json.dumps(
                {
                    "action_id": action_id,
                    "action": "restart",
                    "target": "feishu",
                    "status": status,
                    "deployment_generation": generation,
                    "detail": "verify=unhealthy",
                    "updated_at": now.isoformat(),
                }
            ),
            encoding="utf-8",
        )

    _action("svc-gen53-failed", "failed", 53)  # P8: 旧代失败 → 噪声，过滤
    _action("svc-gen55-failed", "failed", 55)  # 当前代失败 → 真信号，保留
    items = _scan_failed_service_actions(tmp_path)
    assert [i["action_id"] for i in items] == ["svc-gen55-failed"]


def test_scan_failed_service_actions_same_generation_visible(tmp_path: Path) -> None:
    """R5 边界: 失败动作与 desired 同代 → 未被取代，仍进投影."""
    store = ManagedServiceDeploymentStore(tmp_path)
    store.actions_dir.mkdir(parents=True, exist_ok=True)
    _publish_desired(store, 53)
    now = datetime.now(UTC)
    (store.actions_dir / "svc-53-failed.json").write_text(
        json.dumps(
            {
                "action_id": "svc-53-failed",
                "action": "restart",
                "target": "web",
                "status": "failed",
                "deployment_generation": 53,
                "detail": "verify=unhealthy",
                "updated_at": now.isoformat(),
            }
        ),
        encoding="utf-8",
    )
    items = _scan_failed_service_actions(tmp_path)
    assert [i["action_id"] for i in items] == ["svc-53-failed"]
