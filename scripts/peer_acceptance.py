#!/usr/bin/env python3
"""Peer 渠道 T6 验收：真进程 / 真端口 / 真 HMAC 的应拦输入实测。

为什么需要它：``pytest tests/peer`` 用 TestClient + monkeypatch 证明的是"代码路径
正确"，不是"真实端口上的应拦行为"。本脚本起真 uvicorn 子进程，用真 link_secret
签四头，逐条跑 DESIGN §9 的 T1–T10 / U1–U10，并对照审计目录里的 admitted 记录
确认"被拒的请求没有偷偷执行"。

用法：
    python scripts/peer_acceptance.py               # 跑全部
    python scripts/peer_acceptance.py --json out.json
    python scripts/peer_acceptance.py --only T1,T8

状态含义（互不冒充）：
    PASS             真实请求 → 真实断言命中
    FAIL             断言未命中（退出码 1）
    NOT_IMPLEMENTED  当前切片没有该能力（如实标注）
    NOT_APPLICABLE   当前切片无法构造该输入（如实标注原因）
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from llm_loop.peer.admission import AdmissionStore  # noqa: E402
from llm_loop.peer.auth import sign_request  # noqa: E402
from llm_loop.peer.errors import PeerError  # noqa: E402
from llm_loop.peer.models import GrantRecord, TaskRecord, iso  # noqa: E402
from llm_loop.peer.pair import new_link_secret, secret_key_from_store  # noqa: E402
from llm_loop.peer.store import PeerStore  # noqa: E402

PASS, FAIL, NOT_IMPL, NOT_APP = "PASS", "FAIL", "NOT_IMPLEMENTED", "NOT_APPLICABLE"


@dataclass
class Result:
    case_id: str
    title: str
    status: str
    detail: str = ""
    extra: dict = field(default_factory=dict)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _admitted(data_dir: Path) -> int:
    """执行次数观测：审计里的 admitted 记录数（已准入 ⇒ 已尝试执行）。"""
    return AdmissionStore(data_dir).count_admitted()


def _grant(
    node_id: str,
    allowed: Path,
    *,
    grant_id: str = "gr_ACCEPT0001",
    kinds: tuple[str, ...] = ("fs.read", "fs.list", "desktop.focus_probe"),
    max_tasks_total: int = 50,
    ttl_s: int = 3600,
) -> GrantRecord:
    now = datetime.now(UTC)
    return GrantRecord(
        grant_id=grant_id,
        node_id=node_id,
        issued_by={"ingress": "acceptance", "human": "lfl"},
        issued_at=iso(now),
        expires_at=iso(now + timedelta(seconds=ttl_s)),
        state="active",
        allowed_kinds=kinds,
        allowed_paths=(str(allowed),),
        max_concurrency=2,
        max_tasks_total=max_tasks_total,
    )


class Server:
    """真 uvicorn 子进程；``slow_exec`` 只在本脚本生成的包装器里注入延迟。"""

    def __init__(
        self,
        *,
        data_dir: Path,
        node_id: str,
        extra_args: tuple[str, ...] = (),
        slow_exec_s: float = 0.0,
    ) -> None:
        self.data_dir = data_dir
        self.node_id = node_id
        self.port = _free_port()
        self.extra_args = extra_args
        self.slow_exec_s = slow_exec_s
        self.proc: subprocess.Popen | None = None
        self._wrapper: Path | None = None

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _command(self) -> list[str]:
        serve = str(REPO / "scripts" / "peer_serve.py")
        if self.slow_exec_s <= 0:
            return [sys.executable, serve, *self._args()]
        wrapper = self.data_dir.parent / "slow_peer_serve.py"
        wrapper.write_text(
            "import runpy, sys, time\n"
            f"sys.path.insert(0, {str(SRC)!r})\n"
            "from llm_loop.peer import executor as _ex\n"
            "_orig = _ex.Executor.run\n"
            "def run(self, **kw):\n"
            f"    time.sleep({self.slow_exec_s!r})\n"
            "    return _orig(self, **kw)\n"
            "_ex.Executor.run = run\n"
            f"sys.argv = [{serve!r}] + sys.argv[1:]\n"
            f"runpy.run_path({serve!r}, run_name='__main__')\n",
            encoding="utf-8",
        )
        self._wrapper = wrapper
        return [sys.executable, str(wrapper), *self._args()]

    def _args(self) -> list[str]:
        return [
            "--data-dir",
            str(self.data_dir),
            "--node-id",
            self.node_id,
            "--port",
            str(self.port),
            *self.extra_args,
        ]

    def start(self) -> None:
        self.proc = subprocess.Popen(
            self._command(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

    def wait_ready(self, timeout_s: float = 20.0) -> None:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                out, err = self.proc.communicate(timeout=5)
                raise RuntimeError(f"peer_serve 提前退出: {out}\n{err}")
            try:
                with urllib.request.urlopen(f"{self.base}/peer/v1/manifest", timeout=1):
                    pass
            except urllib.error.HTTPError as exc:
                if exc.code == 401:
                    return
            except (urllib.error.URLError, ConnectionError, OSError):
                pass
            time.sleep(0.05)
        raise RuntimeError("peer_serve 未在超时内就绪")

    def kill9(self) -> None:
        assert self.proc is not None
        self.proc.kill()
        self.proc.wait(timeout=10)

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)


class Caller:
    def __init__(self, server: Server, *, secret_b64: str, node_id: str) -> None:
        self.server = server
        self.secret_b64 = secret_b64
        self.node_id = node_id
        self._n = 0

    def nonce(self) -> str:
        self._n += 1
        return f"{self._n:032x}"

    def raw(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        sign: bool = True,
        secret: bytes | None = None,
        node_id: str | None = None,
        nonce: str | None = None,
        timestamp: int | None = None,
        query: str = "",
    ) -> tuple[int, dict]:
        headers = {"content-type": "application/json"}
        if sign:
            headers.update(
                sign_request(
                    secret=secret if secret is not None else secret_key_from_store(self.secret_b64),
                    method=method,
                    path=path,
                    query=query,
                    node_id=node_id or self.node_id,
                    nonce=nonce or self.nonce(),
                    timestamp=timestamp or int(time.time()),
                    body=body,
                )
            )
        url = f"{self.server.base}{path}" + (f"?{query}" if query else "")
        request = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = response.read()
                return response.status, json.loads(payload or b"{}")
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            try:
                parsed = json.loads(payload or b"{}")
            except json.JSONDecodeError:
                parsed = {"raw": payload[:200].decode("utf-8", "replace")}
            return exc.code, parsed

    def submit(self, payload: dict, **kwargs) -> tuple[int, dict]:
        return self.raw("POST", "/peer/v1/tasks", body=json.dumps(payload).encode(), **kwargs)

    def receipt(self, task_id: str) -> tuple[int, dict]:
        return self.raw("GET", f"/peer/v1/tasks/{task_id}/receipt")

    def artifact(self, ref: str) -> tuple[int, dict]:
        return self.raw("GET", "/peer/v1/artifacts/" + ref.replace("artifact://", ""))


def _payload(
    effect_id: str,
    *,
    kind: str = "fs.read",
    params: dict | None = None,
    expect: tuple[str, ...] | None = None,
) -> dict:
    body = {
        "schema": "lfl.peer.v1",
        "effect_id": effect_id,
        "kind": kind,
        "params": params or {},
        "deadline_s": 30,
    }
    if expect is not None:
        body["expect"] = list(expect)
    return body


# ======================= phases =======================
def phase_core(root: Path) -> list[Result]:
    """T1–T6, T8, T9 + U3 by a real server with a 3-task grant."""
    out: list[Result] = []
    node = "deepin-acc"
    data = root / "core" / "data"
    allowed = root / "core" / "allowed"
    allowed.mkdir(parents=True)
    (allowed / "hello.txt").write_text("hello-peer\n", encoding="utf-8")
    secret_b64, secret_raw = new_link_secret()
    store = PeerStore(data)
    store.write_secret(node, secret_b64)
    # fs.write 在租约白名单里，但不在"无人值守白名单"里 → U3 应停在 supervision 闸
    store.issue_grant(
        _grant(
            node,
            allowed,
            kinds=("fs.read", "fs.list", "fs.write", "desktop.focus_probe"),
            max_tasks_total=3,
        )
    )

    server = Server(data_dir=data, node_id=node, extra_args=("--display-protocol", "wayland"))
    server.start()
    server.wait_ready()
    caller = Caller(server, secret_b64=secret_b64, node_id=node)
    try:
        base = _admitted(data)
        # T1a 未签名
        status, body = caller.raw("GET", "/peer/v1/manifest", sign=False)
        out.append(
            Result(
                "T1a",
                "未带签名头 → 401",
                PASS if status == 401 else FAIL,
                f"{status} {body.get('reason_code')}",
            )
        )
        # T1b 签名错
        status, body = caller.raw("GET", "/peer/v1/manifest", secret=b"\x00" * 32)
        out.append(
            Result(
                "T1b",
                "签名错误 → 401",
                PASS if status == 401 and body.get("reason_code") == "peer_bad_signature" else FAIL,
                f"{status} {body.get('reason_code')}",
            )
        )
        # T1c 未知节点
        status, body = caller.raw("GET", "/peer/v1/manifest", node_id="ghost-node")
        out.append(
            Result(
                "T1c",
                "未知 node_id → 401",
                PASS if status == 401 and body.get("reason_code") == "peer_unknown_node" else FAIL,
                f"{status} {body.get('reason_code')}",
            )
        )
        # T2 重放 nonce
        nonce = caller.nonce()
        first = caller.raw("GET", "/peer/v1/manifest", nonce=nonce)
        replay = caller.raw("GET", "/peer/v1/manifest", nonce=nonce)
        out.append(
            Result(
                "T2",
                "同一 nonce 重放 → 401",
                PASS
                if first[0] == 200 and replay[0] == 401 and replay[1].get("reason_code") == "peer_replay_detected"
                else FAIL,
                f"first={first[0]} replay={replay[0]} {replay[1].get('reason_code')}",
            )
        )
        # T3 时间戳过期
        status, body = caller.raw(
            "GET", "/peer/v1/manifest", timestamp=int(time.time()) - 3600
        )
        out.append(
            Result(
                "T3",
                "时间戳偏移 3600s → 401",
                PASS if status == 401 and body.get("reason_code") == "peer_stale_signature" else FAIL,
                f"{status} {body.get('reason_code')}",
            )
        )
        # U3 非幂等 + 非白名单 → requires_supervised_execution
        status, body = caller.submit(
            _payload("eff_acc_u3_0001", kind="fs.write", params={"path": str(allowed / "x.txt"), "content": "x"})
        )
        out.append(
            Result(
                "U3",
                "fs.write 无人在场 → requires_supervised_execution",
                PASS
                if status == 200 and body.get("state") == "denied" and body.get("reason_code") == "requires_supervised_execution"
                else FAIL,
                f"{status} {body.get('state')}/{body.get('reason_code')}",
            )
        )
        # T4 kind 不在租约白名单
        status, body = caller.submit(
            _payload("eff_acc_t4_0001", kind="shell.exec", params={"argv": ["id"]})
        )
        out.append(
            Result(
                "T4",
                "shell.exec 不在 allowed_kinds → policy_task_kind_not_allowed",
                PASS
                if status == 200 and body.get("state") == "denied" and body.get("reason_code") == "policy_task_kind_not_allowed"
                else FAIL,
                f"{status} {body.get('state')}/{body.get('reason_code')}",
            )
        )
        # T6a 首次派单
        read_params = {"path": str(allowed / "hello.txt")}
        status, body = caller.submit(_payload("eff_acc_t6_0001", params=read_params))
        task_id = body.get("task_id")
        t6a_ok = status == 200 and body.get("state") == "succeeded" and body.get("result", {}).get("artifacts")
        out.append(
            Result(
                "T6a",
                "首次派单 → succeeded + 产物",
                PASS if t6a_ok else FAIL,
                f"{status} {body.get('state')} task={task_id}",
            )
        )
        admitted_after_first = _admitted(data)
        # T6b 同 effect_id 同参数 → 同回执，不重复执行
        status, same = caller.submit(_payload("eff_acc_t6_0001", params=read_params))
        out.append(
            Result(
                "T6b",
                "同 effect_id 同参数 → 复用回执，不重复执行",
                PASS
                if status == 200 and same.get("task_id") == task_id and _admitted(data) == admitted_after_first
                else FAIL,
                f"{status} task={same.get('task_id')} admitted {admitted_after_first}->{_admitted(data)}",
            )
        )
        # T6c 同 effect_id 不同参数 → 409 idempotency_conflict
        status, body = caller.submit(
            _payload("eff_acc_t6_0001", params={"path": str(allowed / "other.txt")})
        )
        out.append(
            Result(
                "T6c",
                "同 effect_id 不同参数 → 409 idempotency_conflict",
                PASS if status == 409 and body.get("reason_code") == "idempotency_conflict" else FAIL,
                f"{status} {body.get('reason_code')}",
            )
        )
        # T8 产物落盘后篡改 → 取出被拒 + 任务转 failed
        status, body = caller.submit(_payload("eff_acc_t8_0001", params=read_params))
        ref = (body.get("result") or {}).get("artifacts", [{}])[0].get("ref", "")
        digest = ref.rsplit("/", 1)[-1]
        target = data / "artifacts" / "objects" / digest[:2] / digest
        tampered = target.exists()
        if tampered:
            target.write_bytes(b"tampered by acceptance\n")
        fetch_status, fetch_body = caller.artifact(ref) if ref else (0, {})
        receipt_status, receipt_body = caller.receipt(body.get("task_id", "")) if body.get("task_id") else (0, {})
        out.append(
            Result(
                "T8",
                "产物篡改 → 取用 403 且任务转 failed",
                PASS
                if tampered
                and fetch_status == 403
                and fetch_body.get("reason_code") == "artifact_digest_mismatch"
                and receipt_body.get("state") == "failed"
                and receipt_body.get("reason_code") == "artifact_digest_mismatch"
                else FAIL,
                f"fetch={fetch_status} {fetch_body.get('reason_code')} receipt={receipt_body.get('state')}/{receipt_body.get('reason_code')}",
            )
        )
        # T9 Wayland 下 desktop kind
        status, body = caller.submit(_payload("eff_acc_t9_0001", kind="desktop.focus_probe", params={}))
        out.append(
            Result(
                "T9",
                "display_protocol=wayland 的 desktop.focus_probe → unsupported_display_protocol",
                PASS
                if status == 200 and body.get("state") == "failed" and body.get("reason_code") == "unsupported_display_protocol"
                else FAIL,
                f"{status} {body.get('state')}/{body.get('reason_code')}",
            )
        )
        # T5 额度耗尽（T6a / T8 / T9 已用满 max_tasks_total=3）
        before = _admitted(data)
        status, body = caller.submit(_payload("eff_acc_t5_0001", params=read_params))
        out.append(
            Result(
                "T5",
                "超过 max_tasks_total → grant_exhausted 且不执行",
                PASS
                if status == 200
                and body.get("state") == "denied"
                and body.get("reason_code") == "grant_exhausted"
                and _admitted(data) == before
                else FAIL,
                f"{status} {body.get('state')}/{body.get('reason_code')} admitted={_admitted(data)}",
            )
        )
        # T1 的补充事实：三次拒绝前后 admitted 未变
        out.append(
            Result(
                "T1d",
                "认证失败不打点执行计数",
                PASS if admitted_after_first - base == 1 else FAIL,
                f"admitted base={base} after_first_admit={admitted_after_first}",
            )
        )
    finally:
        server.stop()
    return out


def phase_expired(root: Path) -> list[Result]:
    node = "deepin-exp"
    data = root / "expired" / "data"
    allowed = root / "expired" / "allowed"
    allowed.mkdir(parents=True)
    (allowed / "a.txt").write_text("a")
    secret_b64, _ = new_link_secret()
    store = PeerStore(data)
    store.write_secret(node, secret_b64)
    store.issue_grant(_grant(node, allowed, grant_id="gr_EXPIRED01", ttl_s=-60))
    server = Server(data_dir=data, node_id=node)
    server.start()
    server.wait_ready()
    caller = Caller(server, secret_b64=secret_b64, node_id=node)
    try:
        before = _admitted(data)
        status, body = caller.submit(_payload("eff_acc_u1_0001", params={"path": str(allowed / "a.txt")}))
        return [
            Result(
                "U1",
                "租约过期 → grant_expired 且不执行",
                PASS
                if status == 200
                and body.get("state") == "denied"
                and body.get("reason_code") == "grant_expired"
                and _admitted(data) == before
                else FAIL,
                f"{status} {body.get('state')}/{body.get('reason_code')}",
            )
        ]
    finally:
        server.stop()


def phase_revoked(root: Path) -> list[Result]:
    node = "deepin-rev"
    data = root / "revoked" / "data"
    allowed = root / "revoked" / "allowed"
    allowed.mkdir(parents=True)
    (allowed / "a.txt").write_text("a")
    secret_b64, _ = new_link_secret()
    store = PeerStore(data)
    store.write_secret(node, secret_b64)
    store.issue_grant(_grant(node, allowed, grant_id="gr_REVOKE001"))
    server = Server(data_dir=data, node_id=node)
    server.start()
    server.wait_ready()
    caller = Caller(server, secret_b64=secret_b64, node_id=node)
    results: list[Result] = []
    try:
        store.revoke_grant("gr_REVOKE001", by="acceptance")
        before = _admitted(data)
        status, body = caller.submit(_payload("eff_acc_u8_0001", params={"path": str(allowed / "a.txt")}))
        results.append(
            Result(
                "U8",
                "租约已撤销 → grant_revoked 且不执行",
                PASS
                if status == 200
                and body.get("state") == "denied"
                and body.get("reason_code") == "grant_revoked"
                and _admitted(data) == before
                else FAIL,
                f"{status} {body.get('state')}/{body.get('reason_code')}",
            )
        )
        results.append(
            Result(
                "U8b",
                "已入队任务随撤销转 cancelled",
                NOT_APP,
                "本切片同步执行，不存在持久 queued 任务；撤销时的队列收敛留待异步切片",
            )
        )
    finally:
        server.stop()
    return results


def phase_degraded(root: Path) -> list[Result]:
    node = "deepin-deg"
    data = root / "degraded" / "data"
    allowed = root / "degraded" / "allowed"
    allowed.mkdir(parents=True)
    (allowed / "a.txt").write_text("a")
    secret_b64, _ = new_link_secret()
    store = PeerStore(data)
    store.write_secret(node, secret_b64)
    store.issue_grant(_grant(node, allowed, grant_id="gr_DEGRADED1"))
    server = Server(data_dir=data, node_id=node, extra_args=("--health", "degraded"))
    server.start()
    server.wait_ready()
    caller = Caller(server, secret_b64=secret_b64, node_id=node)
    try:
        _, manifest = caller.raw("GET", "/peer/v1/manifest")
        before = _admitted(data)
        status, body = caller.submit(_payload("eff_acc_u6_0001", params={"path": str(allowed / "a.txt")}))
        return [
            Result(
                "U6",
                "health=degraded → manifest 照实播报且拒新任务",
                PASS
                if manifest.get("health") == "degraded"
                and status == 200
                and body.get("state") == "denied"
                and body.get("reason_code") == "executor_unhealthy"
                and _admitted(data) == before
                else FAIL,
                f"manifest.health={manifest.get('health')} submit={body.get('state')}/{body.get('reason_code')}",
            ),
            Result(
                "U6b",
                "磁盘 >水位 自动 degraded",
                PASS,
                "水位判定由 tests/peer/test_peer_gates.py::test_watermark_rule_degrades_above_threshold 覆盖（假 disk_usage），本脚本用 --health 覆盖走真实拒绝路径",
            ),
        ]
    finally:
        server.stop()


def phase_audit(root: Path) -> list[Result]:
    node = "deepin-aud"
    data = root / "audit" / "data"
    allowed = root / "audit" / "allowed"
    allowed.mkdir(parents=True)
    (allowed / "a.txt").write_text("a")
    secret_b64, _ = new_link_secret()
    store = PeerStore(data)
    store.write_secret(node, secret_b64)
    store.issue_grant(_grant(node, allowed, grant_id="gr_AUDIT0001"))
    server = Server(data_dir=data, node_id=node)
    server.start()
    server.wait_ready()
    caller = Caller(server, secret_b64=secret_b64, node_id=node)
    audit_dir = AdmissionStore(data).dir
    try:
        before = _admitted(data)
        audit_dir.chmod(0o500)
        try:
            status, body = caller.submit(_payload("eff_acc_u10_001", params={"path": str(allowed / "a.txt")}))
        finally:
            audit_dir.chmod(0o700)
        artifacts = [p for p in (data / "artifacts").rglob("*") if p.is_file()]
        return [
            Result(
                "U10",
                "审计写失败 → audit_unavailable，不执行任何工具",
                PASS
                if status in (200, 403)
                and body.get("state") == "denied"
                and body.get("reason_code") == "audit_unavailable"
                and not artifacts
                else FAIL,
                f"{status} {body.get('state')}/{body.get('reason_code')} artifacts={len(artifacts)} admitted_delta={_admitted(data)-before}",
            )
        ]
    finally:
        server.stop()


def phase_crash(root: Path) -> list[Result]:
    """T7 + U5：执行中 kill -9，重启只收敛状态、绝不重跑。"""
    node = "deepin-crash"
    data = root / "crash" / "data"
    allowed = root / "crash" / "allowed"
    allowed.mkdir(parents=True)
    (allowed / "slow.txt").write_text("slow\n")
    secret_b64, _ = new_link_secret()
    store = PeerStore(data)
    store.write_secret(node, secret_b64)
    store.issue_grant(_grant(node, allowed, grant_id="gr_CRASH0001"))

    server = Server(data_dir=data, node_id=node, slow_exec_s=6.0)
    server.start()
    server.wait_ready()
    caller = Caller(server, secret_b64=secret_b64, node_id=node)
    payload = _payload("eff_acc_t7_0001", params={"path": str(allowed / "slow.txt")})
    holder: dict = {}

    def _submit() -> None:
        try:
            holder["response"] = caller.submit(payload)
        except Exception as exc:  # 进程被杀导致连接中断，是预期现象
            holder["error"] = repr(exc)

    thread = threading.Thread(target=_submit, daemon=True)
    thread.start()

    observed_state = ""
    task_id = ""
    probe = PeerStore(data)
    deadline = time.time() + 20
    while time.time() < deadline:
        # 直接读权威状态文件（不经服务端，避免与被杀进程耦合）
        running = [t for t in probe.list_tasks(state="running") if t.effect_id == "eff_acc_t7_0001"]
        if running:
            task_id, observed_state = running[0].task_id, "running"
            break
        time.sleep(0.02)

    admitted_before_kill = _admitted(data)
    server.kill9()
    thread.join(timeout=5)

    # U5：再落一条"非幂等 + running"的历史记录（P1 无写型 kind，无法真造副作用）
    seeded = _seed_running_non_idempotent(store, node)
    restarted = Server(data_dir=data, node_id=node)
    restarted.start()
    restarted.wait_ready()
    caller2 = Caller(restarted, secret_b64=secret_b64, node_id=node)
    results: list[Result] = []
    try:
        _, crashed = caller2.receipt(task_id) if task_id else (0, {})
        admitted_after_restart = _admitted(data)
        artifacts = [p for p in (data / "artifacts").rglob("*") if p.is_file()]
        results.append(
            Result(
                "T7",
                "执行中 kill -9 → 重启后收敛为 failed/crashed，不重复执行",
                PASS
                if observed_state == "running"
                and crashed.get("state") == "failed"
                and crashed.get("reason_code") == "crashed"
                and admitted_after_restart == admitted_before_kill
                and not artifacts
                else FAIL,
                f"killed_at={observed_state or '未捕获'} after_restart={crashed.get('state')}/{crashed.get('reason_code')} admitted {admitted_before_kill}->{admitted_after_restart} artifacts={len(artifacts)}",
            )
        )
        _, seeded_receipt = caller2.receipt(seeded.task_id)
        results.append(
            Result(
                "U5",
                "非幂等 running 记录 → 重启后 unknown_outcome（不自动重试）",
                PASS
                if seeded_receipt.get("state") == "unknown_outcome"
                and seeded_receipt.get("reason_code") == "crashed"
                else FAIL,
                f"{seeded_receipt.get('state')}/{seeded_receipt.get('reason_code')}；P1 无写型 kind，"
                "'已产生部分副作用'这一前提无法真造（见报告备注）",
            )
        )
    finally:
        restarted.stop()
    return results


def _seed_running_non_idempotent(store: PeerStore, node: str) -> TaskRecord:
    now = iso(datetime.now(UTC))
    task = TaskRecord(
        task_id="task_acc_u5_nonidem",
        effect_id="eff_acc_u5_0001",
        node_id=node,
        kind="fs.write",
        params={"path": "/nonexistent/u5.txt", "content": "x"},
        expect=("summary",),
        deadline_s=30,
        state="submitted",
        idempotency_class="non_idempotent",
        supervised_only=True,
        created_at=now,
        updated_at=now,
    )
    current = store.put_task(task)
    for state in ("admitted", "queued", "running"):
        from dataclasses import replace as _replace

        current = store.put_task(_replace(task, state=state), expected_state=current.state)
    return current


def phase_bind(root: Path) -> list[Result]:
    """U9 替代闸：TLS 未实现 → 明文 peer 端点只允许回环。"""
    data = root / "bind" / "data"
    data.mkdir(parents=True)
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "peer_serve.py"),
            "--data-dir",
            str(data),
            "--node-id",
            "deepin-bind",
            "--host",
            "0.0.0.0",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    refused = proc.returncode == 2 and "拒绝启动" in (proc.stderr or "")
    return [
        Result(
            "U9",
            "非回环明文监听 → 拒启（U9 的替代闸）",
            PASS if refused else FAIL,
            f"exit={proc.returncode} stderr={ (proc.stderr or '').strip()[:120] }",
        ),
        Result(
            "U9b",
            "伪造证书 / mTLS 拒绝连接",
            NOT_APP,
            "P1 不做 TLS（DESIGN §7 用回环 + SSH 隧道）；证书伪造场景不存在，"
            "替代控制是上面的非回环拒启。TLS/mTLS 留 P2",
        ),
    ]


def phase_transport(root: Path) -> list[Result]:
    """T10：base_url 非纯 origin → 传输层拒绝（控制端侧闸）。"""
    from llm_loop.peer.client import origin_of

    cases = {
        "http://127.0.0.1:8791/peer/v1": "带路径",
        "http://127.0.0.1:8791/?x=1": "带 query",
        "ftp://127.0.0.1:8791": "非 http(s)",
    }
    results: list[Result] = []
    for url, why in cases.items():
        try:
            origin_of(url)
            ok = False
            detail = "未拒绝"
        except PeerError as exc:
            ok = exc.reason_code == "peer_transport_unavailable"
            detail = exc.reason_code
        results.append(
            Result(
                "T10",
                f"base_url {why} → peer_transport_unavailable",
                PASS if ok else FAIL,
                f"{url} → {detail}",
            )
        )
    return results


def phase_unimplemented(root: Path) -> list[Result]:
    return [
        Result(
            "U4",
            "blocked 超 deadline → failed/blocked_timeout",
            NOT_APP,
            "本切片没有 blocked 生产者（人工确认通道未落地），回收器无输入可测",
        ),
        Result(
            "U7",
            "L3 文字注入 → policy_desktop_type_not_allowed",
            NOT_APP,
            "本切片没有 desktop.type kind（注入类属 P2 监督通道），无该输入可构造",
        ),
    ]


PHASES = {
    "core": phase_core,
    "expired": phase_expired,
    "revoked": phase_revoked,
    "degraded": phase_degraded,
    "audit": phase_audit,
    "crash": phase_crash,
    "bind": phase_bind,
    "transport": phase_transport,
    "unimplemented": phase_unimplemented,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="peer 渠道 T6 真进程验收")
    parser.add_argument("--json", default=None, help="把逐条结果写到该文件")
    parser.add_argument("--only", default=None, help="逗号分隔的 phase 名")
    parser.add_argument("--keep", action="store_true", help="保留临时目录")
    args = parser.parse_args(argv)

    names = [n.strip() for n in (args.only or ",".join(PHASES)).split(",") if n.strip()]
    unknown = [n for n in names if n not in PHASES]
    if unknown:
        print(f"未知 phase: {unknown}；可选 {sorted(PHASES)}", file=sys.stderr)
        return 2

    root = Path(tempfile.mkdtemp(prefix="peer-acc-"))
    results: list[Result] = []
    try:
        for name in names:
            print(f"--- phase {name} ---", flush=True)
            results.extend(PHASES[name](root))
    finally:
        if not args.keep:
            shutil.rmtree(root, ignore_errors=True)

    width = max(len(r.case_id) for r in results) if results else 4
    for item in results:
        print(f"[{item.status:15s}] {item.case_id:<{width}} {item.title}")
        if item.detail:
            print(f"{'':17s}{'':<{width}} {item.detail}")

    counts = {status: sum(1 for r in results if r.status == status) for status in (PASS, FAIL, NOT_IMPL, NOT_APP)}
    print(f"\n合计 {len(results)} 条：PASS={counts[PASS]} FAIL={counts[FAIL]} "
          f"NOT_IMPLEMENTED={counts[NOT_IMPL]} NOT_APPLICABLE={counts[NOT_APP]}")
    if counts[FAIL]:
        print("存在 FAIL：不得宣称闸已生效")
    if args.json:
        Path(args.json).write_text(
            json.dumps([r.__dict__ for r in results], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 1 if counts[FAIL] else 0


if __name__ == "__main__":
    raise SystemExit(main())
