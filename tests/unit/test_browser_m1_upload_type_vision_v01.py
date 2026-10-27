"""M1 (DESIGN-20261027) B1 upload / B2 type / B10 vision metadata.

B1: do=upload path policy (realpath -> allow_roots -> existence -> regular
file -> size -> count) enforced in Python before any CDP request; per-path
design-book error codes; DOM.setFileInputFiles + same-session event dispatch.
B2: do=type via Input.insertText after a fixed focus call (never this.value);
length+preview-only echo; >2000 rejected; empty text = explicit no-op.
B10: vision evidence receipts carry page_id/world_version/captured_at and an
explicit content_unchanged marker when the same sha is reused.

Negative cases call the real production code paths (adapter execute /
cdp actuator dispatch / tool execute) and assert the deterministic codes;
they are not read-the-code inferences (RULE-AI-35 discipline).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from llm_loop.browser.action import (
    BrowserActionAdapter,
    BrowserActionReceiptStore,
    BrowserDispatchResult,
)
from llm_loop.browser.cdp_action_host import (
    _ALLOWED,
    CdpBrowserMutationActuator,
    _MutationCdpSession,
)
from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore
from llm_loop.tools.builtin.browser_perceive import BrowserPerceiveTool
from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool
from llm_loop.tools.builtin.browser_semantic_operation import (
    BrowserSemanticOperationReceiptStore,
    BrowserSemanticOperationTool,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads(
    (ROOT / "tests/fixtures/smc_browser_perception_v01.json").read_text(encoding="utf-8")
)

_PNG_A = b"\x89PNG\r\n\x1a\n" + b"A" * 64
_PNG_B = b"\x89PNG\r\n\x1a\n" + b"B" * 64


def _attest_dedicated(url: str):  # noqa: ANN001, ANN202 - S3b test stub
    from llm_loop.browser.attestation import AttestationVerdict

    return AttestationVerdict(
        verdict="dedicated", user_data_dir="/tmp/attest-stub-profile",
        argv_sha256="stub" * 16, argv=(), detail="unit-test stub",
    )


def _raw_with_attachment_input() -> dict[str, Any]:
    raw = json.loads(json.dumps(FIXTURES["base"]))
    raw["dom"]["nodes"].append(
        {
            "physical_id": "n-attach",
            "parent_id": "n-root",
            "frame_token": None,
            "kind": "input",
            "attributes": {"role": "button", "name": "Attachment", "tag": "input"},
            "state": {"exists": True, "enabled": True, "visible": True, "editable": True},
        }
    )
    return raw


class _CaptureBackend:
    def __init__(self, captures: list[dict[str, Any]]) -> None:
        self.captures = [json.loads(json.dumps(item)) for item in captures]
        self.calls = 0

    def capture(self) -> dict[str, Any]:
        self.calls += 1
        if not self.captures:
            raise RuntimeError("no capture")
        if len(self.captures) == 1:
            return json.loads(json.dumps(self.captures[0]))
        return json.loads(json.dumps(self.captures.pop(0)))


class _Actuator:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def dispatch(self, **kwargs: Any) -> BrowserDispatchResult:
        self.calls.append(kwargs)
        return BrowserDispatchResult(
            acknowledged=True,
            boundary_events=(),
            completeness_reasons=("boundary_detector_non_exhaustive",),
        )


class _HookedCaptureBackend:
    """Capture backend whose per-call hook fires BEFORE the raw is returned.

    fix(P0-1) regression harness (review-M1 probe A2): the hook runs at the
    real temporal position between _validate and dispatch, deterministically
    reproducing the symlink swap window without any racing.
    """

    def __init__(self, raw: dict[str, Any], hook: Any = None) -> None:
        self._raw = json.loads(json.dumps(raw))
        self._hook = hook
        self.calls = 0

    def capture(self) -> dict[str, Any]:
        self.calls += 1
        if self._hook is not None:
            self._hook(self.calls)
        return json.loads(json.dumps(self._raw))


def _adapter_stack(tmp_path: Path, backend: Any = None):
    raw = _raw_with_attachment_input()
    perception = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "perception"))
    if backend is None:
        backend = _CaptureBackend([raw])
    actuator = _Actuator()
    action = BrowserActionAdapter(
        perception=perception,
        receipt_store=BrowserActionReceiptStore(tmp_path / "actions"),
        capture_backend=backend,
        actuator=actuator,
    )
    first = perception.snapshot("s1", raw)
    return first, backend, actuator, action


def _object_action(first: dict[str, Any], *, verb: str, args: dict[str, Any], action_id: str) -> dict[str, Any]:
    target = next(
        obj
        for obj in first["objects"]
        if obj.get("attributes", {}).get("name") == "Attachment"
    )
    return {
        "schema": "smc.semantic_action.v0.1",
        "domain": "browser",
        "scope_ref": target["scope_ref"],
        "action_id": action_id,
        "verb": verb,
        "target_id": target["id"],
        "args": args,
        "args_normalization": {"applied": False, "rule": None},
        "operation_class": "mutate",
        "idempotency_class": "unknown",
        "atomicity_class": "single_dispatch",
        "expected_version": first["snapshot"]["snapshot_id"],
        "version_scope": "object",
        "version_precondition": "required",
    }


def _tool_stack(tmp_path: Path):
    raw = _raw_with_attachment_input()
    perception = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "perception"))
    backend = _CaptureBackend([raw])
    actuator = _Actuator()
    action = BrowserActionAdapter(
        perception=perception,
        receipt_store=BrowserActionReceiptStore(tmp_path / "actions"),
        capture_backend=backend,
        actuator=actuator,
    )
    execute = BrowserSemanticExecuteTool(perception=perception, action_adapter=action, session_id_getter=lambda: "s1")
    operation = BrowserSemanticOperationTool(
        perception=perception,
        capture_backend=backend,
        semantic_execute=execute,
        receipt_store=BrowserSemanticOperationReceiptStore(tmp_path / "operation_receipts"),
        session_id_getter=lambda: "s1",
    )
    return operation, actuator


# ---------------------------------------------------------------------------
# A. B1 upload path policy at the adapter gate (real execute, zero dispatch).
# ---------------------------------------------------------------------------


def test_upload_rejects_etc_passwd_before_any_capture_or_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LFL_BROWSER_UPLOAD_ALLOW_ROOTS", str(tmp_path))
    first, backend, actuator, action = _adapter_stack(tmp_path)
    result = action.execute(
        "s1",
        _object_action(first, verb="upload", args={"paths": ["/etc/passwd"]}, action_id="act-up-1"),
    )
    assert result["status"] == "rejected"
    assert result["retry"]["reason"] == "path_not_allowed"
    assert actuator.calls == []  # no dispatch -> no CDP request
    assert backend.calls == 0  # rejected before even the pre-dispatch capture


def test_upload_rejects_symlink_escape_resolved_by_realpath(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    secret = tmp_path / "secret.bin"
    secret.write_bytes(b"private")
    link = workspace / "link.bin"
    link.symlink_to(secret)
    monkeypatch.setenv("LFL_BROWSER_UPLOAD_ALLOW_ROOTS", str(workspace))
    first, _, actuator, action = _adapter_stack(tmp_path)
    result = action.execute(
        "s1",
        _object_action(first, verb="upload", args={"paths": [str(link)]}, action_id="act-up-2"),
    )
    assert result["status"] == "rejected"
    assert result["retry"]["reason"] == "path_not_allowed"
    assert actuator.calls == []


def test_upload_rejects_directory_as_not_regular_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LFL_BROWSER_UPLOAD_ALLOW_ROOTS", str(tmp_path))
    (tmp_path / "subdir").mkdir()
    first, _, actuator, action = _adapter_stack(tmp_path)
    result = action.execute(
        "s1",
        _object_action(first, verb="upload", args={"paths": [str(tmp_path / "subdir")]}, action_id="act-up-3"),
    )
    assert result["status"] == "rejected"
    assert result["retry"]["reason"] == "not_regular_file"
    assert actuator.calls == []


def test_upload_rejects_fifo_as_not_regular_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A FIFO stands in for the non-regular file class (device nodes cannot be
    # created unprivileged); sockets/FIFOs/dirs all hit the same S_ISREG gate.
    monkeypatch.setenv("LFL_BROWSER_UPLOAD_ALLOW_ROOTS", str(tmp_path))
    fifo = tmp_path / "pipe.fifo"
    os.mkfifo(fifo)
    first, _, actuator, action = _adapter_stack(tmp_path)
    result = action.execute(
        "s1",
        _object_action(first, verb="upload", args={"paths": [str(fifo)]}, action_id="act-up-4"),
    )
    assert result["status"] == "rejected"
    assert result["retry"]["reason"] == "not_regular_file"
    assert actuator.calls == []


def test_upload_rejects_missing_path_inside_allowed_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LFL_BROWSER_UPLOAD_ALLOW_ROOTS", str(tmp_path))
    first, _, actuator, action = _adapter_stack(tmp_path)
    result = action.execute(
        "s1",
        _object_action(first, verb="upload", args={"paths": [str(tmp_path / "missing.bin")]}, action_id="act-up-5"),
    )
    assert result["status"] == "rejected"
    assert result["retry"]["reason"] == "path_not_found"
    assert actuator.calls == []


def test_upload_rejects_file_over_configured_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LFL_BROWSER_UPLOAD_ALLOW_ROOTS", str(tmp_path))
    monkeypatch.setenv("LFL_BROWSER_UPLOAD_MAX_FILE_BYTES", "1024")
    (tmp_path / "small.bin").write_bytes(b"x" * 2000)
    first, _, actuator, action = _adapter_stack(tmp_path)
    result = action.execute(
        "s1",
        _object_action(first, verb="upload", args={"paths": [str(tmp_path / "small.bin")]}, action_id="act-up-6"),
    )
    assert result["status"] == "rejected"
    assert result["retry"]["reason"] == "too_large"
    assert actuator.calls == []


def test_upload_rejects_100mb_default_limit_with_sparse_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LFL_BROWSER_UPLOAD_ALLOW_ROOTS", str(tmp_path))
    big = tmp_path / "big.bin"
    big.write_bytes(b"x")
    with open(big, "ab") as handle:
        handle.truncate(100 * 1024 * 1024 + 1)  # sparse: no real disk usage
    first, _, actuator, action = _adapter_stack(tmp_path)
    result = action.execute(
        "s1",
        _object_action(first, verb="upload", args={"paths": [str(big)]}, action_id="act-up-7"),
    )
    assert result["status"] == "rejected"
    assert result["retry"]["reason"] == "too_large"
    assert actuator.calls == []


def test_upload_rejects_nine_files_with_count_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LFL_BROWSER_UPLOAD_ALLOW_ROOTS", str(tmp_path))
    paths = []
    for index in range(9):
        item = tmp_path / f"f{index}.bin"
        item.write_bytes(b"x")
        paths.append(str(item))
    first, _, actuator, action = _adapter_stack(tmp_path)
    result = action.execute(
        "s1",
        _object_action(first, verb="upload", args={"paths": paths}, action_id="act-up-8"),
    )
    # per-file checks pass first; the 1..8 count bound is evaluated last
    assert result["status"] == "rejected"
    assert result["retry"]["reason"] == "paths_count_invalid"
    assert actuator.calls == []


def test_upload_accepts_workspace_files_and_dispatches_resolved_absolute_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LFL_BROWSER_UPLOAD_ALLOW_ROOTS", str(tmp_path))
    (tmp_path / "a.png").write_bytes(b"\x89PNG")
    (tmp_path / "b.txt").write_bytes(b"hello")
    first, _, actuator, action = _adapter_stack(tmp_path)
    result = action.execute(
        "s1",
        _object_action(
            first,
            verb="upload",
            args={"paths": [str(tmp_path / "a.png"), str(tmp_path / "b.txt")]},
            action_id="act-up-9",
        ),
    )
    assert result["status"] == "ok", result
    assert len(actuator.calls) == 1
    call = actuator.calls[0]
    assert call["verb"] == "upload"
    assert call["args"]["paths"] == [
        str(tmp_path / "a.png"),
        str(tmp_path / "b.txt"),
    ]  # canonical absolute realpath form (tmp_path is already resolved)
    assert call["physical_target"].startswith("dom:")


_SYSTEM_PASSWORD_FILE = os.sep + "etc" + os.sep + "passwd"


def test_upload_toctou_swap_after_validate_rejected_before_dispatch_and_no_dispatch_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # fix(P0-1) regression (review-M1 probe A2, deterministic — no racing):
    # a benign regular file passes _validate, then is swapped for a symlink to
    # the system password file inside the FIRST pre-dispatch capture (the real
    # temporal window between validate and dispatch). The pre-dispatch recheck
    # must reject: zero dispatch calls, zero dispatch.json, and no digest of
    # the swapped sensitive file anywhere under the action store.
    workspace = tmp_path / "ws"
    workspace.mkdir()
    swap = workspace / "swap.bin"
    swap.write_bytes(b"benign-bytes")
    monkeypatch.setenv("LFL_BROWSER_UPLOAD_ALLOW_ROOTS", str(workspace))

    def hook(call_number: int) -> None:
        if call_number == 1:  # inside the window: validate already passed
            swap.unlink()
            swap.symlink_to(_SYSTEM_PASSWORD_FILE)

    first, backend, actuator, action = _adapter_stack(
        tmp_path, backend=_HookedCaptureBackend(_raw_with_attachment_input(), hook)
    )
    result = action.execute(
        "s1",
        _object_action(first, verb="upload", args={"paths": [str(swap)]}, action_id="act-up-toctou-1"),
    )
    assert result["status"] == "rejected"
    assert result["retry"]["reason"] == "path_not_allowed"
    assert actuator.calls == []  # zero dispatch -> zero CDP upload request
    assert backend.calls == 1  # rejection happened AFTER the first capture, i.e. at the recheck, not at _validate
    actions_root = tmp_path / "actions"
    assert list(actions_root.rglob("dispatch.json")) == []  # zero dispatch.json
    # the swapped sensitive file's content digest must not be persisted anywhere
    secret_sha = hashlib.sha256(
        Path(_SYSTEM_PASSWORD_FILE).read_bytes()
    ).hexdigest()
    for persisted in actions_root.rglob("*"):
        if persisted.is_file():
            assert secret_sha not in persisted.read_text(encoding="utf-8", errors="ignore")


def test_upload_toctou_positive_control_benign_file_still_dispatches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Positive control for the recheck: the same hooked stack WITHOUT the swap
    # must keep the happy path intact (no false kills) — dispatch happens once
    # and dispatch.json carries the re-verified file's digest.
    workspace = tmp_path / "ws"
    workspace.mkdir()
    payload = b"benign-content-0123456789"
    benign = workspace / "benign.bin"
    benign.write_bytes(payload)
    monkeypatch.setenv("LFL_BROWSER_UPLOAD_ALLOW_ROOTS", str(workspace))

    first, backend, actuator, action = _adapter_stack(
        tmp_path, backend=_HookedCaptureBackend(_raw_with_attachment_input(), None)
    )
    result = action.execute(
        "s1",
        _object_action(first, verb="upload", args={"paths": [str(benign)]}, action_id="act-up-toctou-2"),
    )
    assert result["status"] == "ok", result
    assert len(actuator.calls) == 1
    assert actuator.calls[0]["args"]["paths"] == [str(benign)]
    dispatch_docs = list((tmp_path / "actions").rglob("dispatch.json"))
    assert len(dispatch_docs) == 1
    grounding = json.loads(dispatch_docs[0].read_text(encoding="utf-8"))
    assert grounding["args"]["files"] == [
        {
            "name": "benign.bin",
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    ]


# ---------------------------------------------------------------------------
# B. B2 type at the adapter gate.
# ---------------------------------------------------------------------------


def test_type_rejects_text_over_2000_characters(tmp_path: Path) -> None:
    first, backend, actuator, action = _adapter_stack(tmp_path)
    result = action.execute(
        "s1",
        _object_action(first, verb="type", args={"text": "x" * 2001}, action_id="act-ty-1"),
    )
    assert result["status"] == "rejected"
    assert result["retry"]["reason"] == "type_text_too_long"
    assert actuator.calls == []
    assert backend.calls == 0


def test_type_dispatches_and_empty_text_is_valid_noop(tmp_path: Path) -> None:
    first, _, actuator, action = _adapter_stack(tmp_path)
    ok = action.execute(
        "s1",
        _object_action(first, verb="type", args={"text": "HELLO"}, action_id="act-ty-2"),
    )
    assert ok["status"] == "ok"
    assert actuator.calls[0]["args"] == {"text": "HELLO"}

    empty = action.execute(
        "s1",
        _object_action(first, verb="type", args={"text": ""}, action_id="act-ty-3"),
    )
    # empty text is accepted (explicit no-op), not an error
    assert empty["status"] == "ok"
    assert actuator.calls[1]["args"] == {"text": ""}


# ---------------------------------------------------------------------------
# C. CDP actuator surface (FakeWs): exact protocol sequences.
# ---------------------------------------------------------------------------


class _UploadTypeWs:
    def __init__(self) -> None:
        self.pending: list[str] = []
        self.requests: list[dict[str, Any]] = []
        self.set_file_calls: list[dict[str, Any]] = []
        self.insert_text_calls: list[dict[str, Any]] = []

    def send(self, payload: str) -> None:
        req = json.loads(payload)
        self.requests.append(req)
        method = req["method"]
        if method == "DOM.resolveNode":
            result: dict[str, Any] = {"object": {"objectId": "obj-1"}}
        elif method == "Runtime.callFunctionOn":
            result = {"result": {"type": "undefined"}}
        elif method == "Page.enable":
            result = {}
        elif method == "DOM.setFileInputFiles":
            self.set_file_calls.append(req["params"])
            result = {}
        elif method == "Input.insertText":
            self.insert_text_calls.append(req["params"])
            result = {}
        else:
            raise AssertionError(method)
        self.pending.append(json.dumps({"id": req["id"], "result": result}))

    def recv(self, timeout: float | None = None) -> str:  # noqa: ARG002
        return self.pending.pop(0)

    def close(self) -> None:
        return None


def _cdp_host(ws: _UploadTypeWs) -> CdpBrowserMutationActuator:
    targets = [
        {
            "id": "target-1",
            "type": "page",
            "url": "http://127.0.0.1/a",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/target-1",
        }
    ]
    return CdpBrowserMutationActuator(
        "http://127.0.0.1:9222",
        target_id="target-1",
        http_get_json=lambda url: json.loads(json.dumps(targets)),
        ws_connect=lambda url: ws,
        attest_fn=_attest_dedicated,
    )


def test_upload_uses_backend_node_id_and_same_session_event_dispatch() -> None:
    ws = _UploadTypeWs()
    host = _cdp_host(ws)
    host.dispatch(verb="upload", physical_target="dom:7", args={"paths": ["/ws/a.png", "/ws/b.txt"]})
    methods = [req["method"] for req in ws.requests]
    assert methods == [
        "Page.enable",
        "DOM.resolveNode",
        "DOM.setFileInputFiles",
        "Runtime.callFunctionOn",
    ]
    assert ws.set_file_calls == [
        {"files": ["/ws/a.png", "/ws/b.txt"], "backendNodeId": 7}
    ]
    # the input/change dispatch rides the same session right after injection
    dispatch_call = next(
        req["params"]
        for req in ws.requests
        if req["method"] == "Runtime.callFunctionOn"
    )
    assert "dispatchEvent(new Event('input'" in dispatch_call["functionDeclaration"]
    assert "dispatchEvent(new Event('change'" in dispatch_call["functionDeclaration"]
    # paths are protocol data, never script content (NFR-2)
    assert "/ws/a.png" not in dispatch_call["functionDeclaration"]


def test_type_focuses_then_inserttext_with_text_as_protocol_param() -> None:
    ws = _UploadTypeWs()
    host = _cdp_host(ws)
    host.dispatch(verb="type", physical_target="dom:7", args={"text": "HELLO-世界-Secret"})
    methods = [req["method"] for req in ws.requests]
    assert methods == [
        "Page.enable",
        "DOM.resolveNode",
        "Runtime.callFunctionOn",
        "Input.insertText",
    ]
    focus_call = next(
        req["params"] for req in ws.requests if req["method"] == "Runtime.callFunctionOn"
    )
    assert focus_call["functionDeclaration"] == "function(){ this.focus(); }"
    assert ws.insert_text_calls == [{"text": "HELLO-世界-Secret"}]
    # no this.value assignment and no user text inside any script payload
    for req in ws.requests:
        if req["method"] == "Runtime.callFunctionOn":
            assert "this.value" not in req["params"]["functionDeclaration"]
            assert "HELLO" not in req["params"]["functionDeclaration"]


def test_type_empty_text_is_acknowledged_noop_on_cdp_layer() -> None:
    ws = _UploadTypeWs()
    host = _cdp_host(ws)
    result = host.dispatch(verb="type", physical_target="dom:7", args={"text": ""})
    assert result.acknowledged is True
    assert [req["method"] for req in ws.requests] == ["Page.enable", "DOM.resolveNode"]
    assert ws.insert_text_calls == []


def test_mutation_allowlist_gained_exactly_two_m1_methods() -> None:
    # 4 frozen pre-M1 methods + exactly the two M1 additions, nothing else.
    assert sorted(_ALLOWED) == [
        "DOM.resolveNode",
        "DOM.setFileInputFiles",
        "Input.insertText",
        "Page.enable",
        "Page.navigate",
        "Runtime.callFunctionOn",
    ]
    session = _MutationCdpSession(_UploadTypeWs())
    # M2 surface must still be rejected today (press_key/hover/dialog not shipped)
    for method in (
        "Input.dispatchKeyEvent",
        "Input.dispatchMouseEvent",
        "Page.handleJavaScriptDialog",
        "DOM.getDocument",
    ):
        with pytest.raises(PermissionError, match="mutation actuator surface"):
            session.send(method, {})


# ---------------------------------------------------------------------------
# D. Tool layer (browser_operate do=upload / do=type) model-facing receipts.
# ---------------------------------------------------------------------------


def test_operate_upload_receipt_carries_per_file_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LFL_BROWSER_UPLOAD_ALLOW_ROOTS", str(tmp_path))
    (tmp_path / "note.txt").write_bytes(b"hello world")
    tool, actuator = _tool_stack(tmp_path)
    result = tool.execute(
        do="upload",
        target={"kind": "input", "name": "Attachment"},
        paths=[str(tmp_path / "note.txt")],
    )
    assert result.status.value == "success"
    receipt = json.loads(result.content)
    assert receipt["status"] == "completed"
    assert receipt["upload_files"] == [
        {"ok": True, "name": "note.txt", "size": 11, "mime": "text/plain"}
    ]
    assert [call["verb"] for call in actuator.calls] == ["upload"]
    assert actuator.calls[0]["args"]["paths"] == [str(tmp_path / "note.txt")]


def test_operate_upload_etc_passwd_rejected_with_design_code_before_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LFL_BROWSER_UPLOAD_ALLOW_ROOTS", str(tmp_path))
    tool, actuator = _tool_stack(tmp_path)
    result = tool.execute(
        do="upload",
        target={"kind": "input", "name": "Attachment"},
        paths=["/etc/passwd"],
    )
    assert result.status.value == "failure"
    assert "path_not_allowed" in result.content
    assert actuator.calls == []


def test_operate_type_receipt_echoes_length_and_preview_only(
    tmp_path: Path,
) -> None:
    text = "ABCDEFGHIJKLMNOPQRST" + "uvwxyz-hidden-tail-0123456789"  # 49 chars
    tool, actuator = _tool_stack(tmp_path)
    result = tool.execute(
        do="type",
        target={"kind": "input", "name": "Attachment"},
        text=text,
    )
    assert result.status.value == "success"
    receipt = json.loads(result.content)
    assert receipt["type_echo"] == {"length": 49, "preview": "ABCDEFGHIJKLMNOPQRST"}
    # full text never appears on the model-facing compact receipt
    assert text not in result.content
    assert "uvwxyz-hidden-tail" not in result.content
    assert [call["verb"] for call in actuator.calls] == ["type"]
    assert actuator.calls[0]["args"] == {"text": text}


def test_operate_type_rejects_2001_chars_at_compile_time(tmp_path: Path) -> None:
    tool, actuator = _tool_stack(tmp_path)
    result = tool.execute(
        do="type",
        target={"kind": "input", "name": "Attachment"},
        text="x" * 2001,
    )
    assert result.status.value == "failure"
    assert "type_text_too_long" in result.content
    assert actuator.calls == []


def test_operate_type_empty_text_is_explicit_noop(tmp_path: Path) -> None:
    tool, actuator = _tool_stack(tmp_path)
    result = tool.execute(
        do="type",
        target={"kind": "input", "name": "Attachment"},
        text="",
    )
    assert result.status.value == "success"
    receipt = json.loads(result.content)
    assert receipt["type_echo"] == {"length": 0, "preview": ""}
    assert [call["verb"] for call in actuator.calls] == ["type"]
    assert actuator.calls[0]["args"] == {"text": ""}


# ---------------------------------------------------------------------------
# E. B10 vision evidence metadata + content_unchanged.
# ---------------------------------------------------------------------------


def test_store_vision_evidence_metadata_and_content_unchanged_marker(
    tmp_path: Path,
) -> None:
    adapter = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "p"))
    first = adapter.store_vision_evidence(
        "s1", _PNG_A, page_id="target-1", world_version="sha-a", captured_at="2026-10-27T12:00:00.000+00:00"
    )
    assert first["content_unchanged"] is False
    assert first["page_id"] == "target-1"
    assert first["world_version"] == "sha-a"
    assert first["captured_at"] == "2026-10-27T12:00:00.000+00:00"
    assert "content_same_as_ref" not in first

    again = adapter.store_vision_evidence("s1", _PNG_A, page_id="target-1", world_version="sha-a", captured_at="2026-10-27T12:00:01.000+00:00")
    # same bytes -> same content-addressed ref, reuse declared explicitly
    assert again["ref"] == first["ref"]
    assert again["content_unchanged"] is True
    assert again["content_same_as_ref"] == first["ref"]

    changed = adapter.store_vision_evidence("s1", _PNG_B, page_id="target-1", world_version="sha-b", captured_at="2026-10-27T12:00:02.000+00:00")
    assert changed["ref"] != first["ref"]
    assert changed["content_unchanged"] is False
    assert changed["sha256"] != first["sha256"]


class _VisionBackend:
    def __init__(self, vision: bytes) -> None:
        self.vision = vision
        self.bound_target_id = "target-9"

    def capture(self) -> dict[str, Any]:
        return json.loads(json.dumps(FIXTURES["base"]))

    def capture_vision_evidence(self) -> bytes:
        return self.vision


def test_perceive_vision_block_carries_page_and_world_metadata(tmp_path: Path) -> None:
    adapter = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "p"))
    tool = BrowserPerceiveTool(
        adapter=adapter, backend=_VisionBackend(_PNG_A), session_id_getter=lambda: "s1"
    )
    payload = json.loads(tool.execute(action="snapshot", vision="evidence").content)
    vision = payload["vision"]
    assert vision["status"] == "ok"
    assert vision["page_id"] == "target-9"
    assert vision["world_version"] == payload["snapshot"]["snapshot_id"]
    assert isinstance(vision["captured_at"], str) and vision["captured_at"].startswith("202")
    assert vision["content_unchanged"] is False
    assert "content_same_as_ref" not in vision
    # evidence-layer invariant retained: vision stays out of the snapshot body
    assert "vision" not in payload["snapshot"]

    # same pixels again -> same ref with an explicit unchanged marker
    payload2 = json.loads(tool.execute(action="snapshot", vision="evidence").content)
    vision2 = payload2["vision"]
    assert vision2["ref"] == vision["ref"]
    assert vision2["content_unchanged"] is True
    assert vision2["content_same_as_ref"] == vision["ref"]
    assert vision2["page_id"] == "target-9"
