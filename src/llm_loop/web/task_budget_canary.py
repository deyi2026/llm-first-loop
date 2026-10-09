"""The only opt-in Web -> signed TaskBudget cutover for ONE existing session.

Default OFF. The browser/message/model cannot select, issue, edit or expand a
budget. The human operator provisions the independent issuer + reviewer first;
this adapter then binds their signed proof to the existing Web worker Run.
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from Crypto.PublicKey import ECC
from fastapi import Request

from llm_loop.event_log.store import EventStore
from llm_loop.resources.task_budget_event_authority import (
    SignedWebEventPlan,
    bind_signed_web_event_plan,
)
from llm_loop.resources.task_budget_operator_mailbox import TrustedHumanApprovalBridge
from llm_loop.resources.task_budget_operator_proof import OperatorApprovalVerifier
from llm_loop.resources.task_budget_process_transport import (
    IsolatedTransportProfile,
    bind_isolated_provider_transport,
)
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError, TaskBudgetStore
from llm_loop.runtime.resolver import business_config_snapshot


@dataclass(frozen=True)
class WebTaskBudgetCanary:
    session_id: str
    plan: SignedWebEventPlan

    def bind(self) -> AbstractContextManager[None]:
        return bind_web_canary(self)


def _deny() -> NoReturn:
    raise TaskBudgetDeniedError("web_task_budget_canary_unqualified")


def _read_operator_config(path: Path) -> dict[str, Any]:
    if not path.is_absolute():
        _deny()
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid not in (0, os.geteuid())
            or metadata.st_mode & 0o077 or metadata.st_nlink != 1
            or metadata.st_size > 16384
        ):
            _deny()
        content = os.read(fd, 16385)
    finally:
        os.close(fd)
    if len(content) > 16384:
        _deny()
    try:
        result = json.loads(content)
    except (ValueError, UnicodeError):
        _deny()
    if not isinstance(result, dict) or set(result) != {
        "schema", "session_id", "workspace_root", "operator_uid", "issuer_uid",
        "web_group_gid", "mailbox_dir", "issuer_socket", "operator_key_id",
        "operator_public_key_pem", "operator_id", "budget_key_id",
        "budget_public_key_pem",
    } or result["schema"] != "web-task-budget-one-session/v1":
        _deny()
    return result


def _public_pem(raw: Any) -> bytes:
    if not isinstance(raw, str) or len(raw) > 2048:
        _deny()
    try:
        pem = raw.encode("ascii")
        key = ECC.import_key(pem)
        if key.curve != "Ed25519" or key.has_private():
            _deny()
        return pem
    except (ValueError, UnicodeError):
        _deny()


def load_operator_web_canary(engine: Any) -> WebTaskBudgetCanary | None:
    """The ONLY startup switch. Absent config => default OFF, no side effects."""
    config_path = business_config_snapshot("web").get(
        "LFL_TASK_BUDGET_WEB_CANARY_CONFIG", ""
    ).strip()
    if not config_path:
        return None
    config = _read_operator_config(Path(config_path))
    session_id = config["session_id"]
    if (
        not isinstance(session_id, str) or len(session_id) > 128
        or not engine.session.exists(session_id)
        or str(engine.workspace_root or "") != config["workspace_root"]
    ):
        _deny()
    web_uid, human_uid, issuer_uid, web_gid = (
        os.geteuid(), config["operator_uid"], config["issuer_uid"],
        config["web_group_gid"],
    )
    if (
        any(type(x) is not int or x <= 0 for x in (web_uid, human_uid, issuer_uid, web_gid))
        or len({web_uid, human_uid, issuer_uid}) != 3
        or web_gid not in os.getgroups()
    ):
        _deny()
    socket_path, mailbox = Path(config["issuer_socket"]), Path(config["mailbox_dir"])
    try:
        socket_stat, mailbox_stat = os.lstat(socket_path), os.lstat(mailbox)
        if (
            not socket_path.is_absolute() or not mailbox.is_absolute()
            or not stat.S_ISSOCK(socket_stat.st_mode)
            or socket_stat.st_uid != issuer_uid or socket_stat.st_gid != web_gid
            or socket_stat.st_mode & 0o777 != 0o660
            or not stat.S_ISDIR(mailbox_stat.st_mode)
            or mailbox_stat.st_uid != human_uid or mailbox_stat.st_gid != web_gid
            or mailbox_stat.st_mode & 0o7777 != 0o2750
        ):
            _deny()
    except OSError:
        _deny()
    if not isinstance(getattr(engine, "_event_store", None), EventStore):
        _deny()
    if not engine._event_store.enabled:
        _deny()
    runner = getattr(engine, "runner", None)
    if runner is None or runner.enabled is not True:
        _deny()
    operator_key_id, budget_key_id, operator_id = (
        config["operator_key_id"], config["budget_key_id"], config["operator_id"],
    )
    if any(not isinstance(x, str) or not x for x in (
        operator_key_id, budget_key_id, operator_id,
    )):
        _deny()
    verifier = OperatorApprovalVerifier(
        trusted_keys={operator_key_id: _public_pem(config["operator_public_key_pem"])},
        authorized_operators={operator_id: operator_key_id},
    )
    bridge = TrustedHumanApprovalBridge(
        mailbox_dir=mailbox, operator_uid=human_uid, web_uid=web_uid,
        web_group_gid=web_gid, workspace_root=Path(config["workspace_root"]),
        issuer_socket=socket_path, operator_verifier=verifier,
        is_cancelled=lambda: runner.is_cancelled(session_id),
        max_wait_seconds=30.0,
    )
    data_dir = Path(engine.settings.data_dir).expanduser().resolve()
    plan = SignedWebEventPlan(
        issue_for_event=bridge.issue_for_event,
        trusted_public_keys={budget_key_id: _public_pem(config["budget_public_key_pem"])},
        event_store=engine._event_store,
        budget_store=TaskBudgetStore(data_dir / "task_budget_web_canary"),
        allow_one_physical_attempt=True,
    )
    return WebTaskBudgetCanary(session_id=session_id, plan=plan)


def choose_signed_web_canary(
    request: Request, session_id: str, *, model: str | None,
    resume: bool, queued: bool, attachments: bool,
) -> WebTaskBudgetCanary | None:
    """Only the startup-pinned session can enter; no user request flag exists."""
    selected = getattr(request.app.state, "task_budget_web_canary", None)
    if selected is None or selected.session_id != session_id or resume:
        return None
    from llm_loop.web.auth import request_authenticated

    if (
        not request_authenticated(request)
        or queued or attachments or model != "glm/glm-5.3"
    ):
        _deny()
    return selected


@contextmanager
def bind_web_canary(canary: WebTaskBudgetCanary | None) -> Iterator[None]:
    """Both scopes MUST span each physical next(generator) in the worker."""
    if canary is None:
        yield
        return
    with bind_signed_web_event_plan(canary.plan), bind_isolated_provider_transport(
        IsolatedTransportProfile(verify=True, proxy=None)
    ):
        yield
