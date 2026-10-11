"""P1.12 closed functional evidence, run by the Host, never by model assertion.

This fixture is intentionally task-specific: merge_closed_intervals, seed
20261011, 11 boundary cases plus 300 random cases. Only an offline, locally
cached, digest-pinned Python image may execute untrusted candidate source.
No production Reviewer/Provider or release permission is granted here.
"""

from __future__ import annotations

import ast
import hashlib
import json
import random
import re
import secrets
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROTOCOL = "lfl.dual_agent.functional_evidence/v1"
SUITE = "merge_closed_intervals_v1"
BASE_IMAGE = (
    "python@sha256:2d9aefe2fef018a7eb2c13064c89c71929800fd2e5dccdbf52ea5da5bb8d929a"
)
_IMAGE = re.compile(r"^python@sha256:[0-9a-f]{64}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_DOCKER = "/opt/homebrew/bin/docker"
_MAX_SOURCE = 4096
_CASE_COUNT = 311
_ALLOWED_CALLS = frozenset({
    "sorted", "len", "range", "enumerate", "min", "max", "zip",
    "list", "tuple", "abs", "sum",
})
_FORBIDDEN = (
    ast.Import, ast.ImportFrom, ast.ClassDef, ast.AsyncFunctionDef,
    ast.Await, ast.Yield, ast.YieldFrom, ast.Global, ast.Nonlocal,
    ast.Try, ast.TryStar, ast.With, ast.AsyncWith, ast.While,
    ast.Raise, ast.Delete, ast.NamedExpr,
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(obj: Any) -> bytes:
    return json.dumps(
        obj, sort_keys=True, ensure_ascii=True, separators=(",", ":"),
    ).encode("ascii")


def frozen_merge_acceptance() -> dict[str, Any]:
    """Exact Host-owned P1.8 checklist from the recorded GLM-5.3 canary."""
    return {
        "schema": "lfl.dual_assurance.p18_acceptance/v1",
        "checks": [
            {"id": "has_merge_function", "type": "CONTAINS_LITERAL",
             "value": "def merge_closed_intervals("},
            {"id": "returns_new_list", "type": "CONTAINS_LITERAL",
             "value": "return merged"},
            {"id": "no_os_shell", "type": "EXCLUDES_LITERAL",
             "value": "os.system("},
        ],
    }


def frozen_merge_acceptance_sha256() -> str:
    return _sha(_canonical(frozen_merge_acceptance()))


def suite_cases() -> list[list[list[int]]]:
    cases = [
        [], [[1, 3], [3, 5], [8, 9]], [[5, 5], [1, 2], [2, 3]],
        [[2, 2], [2, 2]], [[1, 10], [3, 4], [7, 8]],
        [[5, 9], [1, 3]], [[-5, -1], [-1, 0], [1, 2]],
        [[0, 0]], [[-4, -4], [-2, -2], [-4, -3]],
        [[-1, 0], [-2, -2]], [[1, 1], [1, 1], [1, 1]],
    ]
    rng = random.Random(20261011)
    for _ in range(300):
        vals = []
        for _ in range(rng.randrange(0, 20)):
            a = rng.randrange(-50, 51)
            vals.append([a, a + rng.randrange(0, 25)])
        cases.append(vals)
    assert len(cases) == _CASE_COUNT
    return cases


def _oracle(vals: list[list[int]]) -> list[list[int]]:
    ordered = sorted([list(pair) for pair in vals])
    if not ordered:
        return []
    out = [ordered[0]]
    for a, b in ordered[1:]:
        if a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _validate_candidate(source: str) -> bool:
    if not 0 < len(source.encode("utf-8")) <= _MAX_SOURCE:
        return False
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        return False
    func = tree.body[0]
    args = func.args
    if (
        func.name != "merge_closed_intervals" or func.decorator_list
        or len(args.args) != 1 or args.args[0].arg != "intervals"
        or args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg
        or args.defaults or args.kw_defaults
    ):
        return False
    for node in ast.walk(tree):
        if isinstance(node, _FORBIDDEN):
            return False
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            return False
        if isinstance(node, ast.Attribute) and node.attr != "append":
            return False
        if isinstance(node, ast.Call) and not (
            isinstance(node.func, ast.Name) and node.func.id in _ALLOWED_CALLS
            or isinstance(node.func, ast.Attribute) and node.func.attr == "append"
        ):
            return False
        if isinstance(node, ast.FunctionDef) and node is not func:
            return False
    return True


# Candidate and oracle must never share the Python process's globals.
# Docker is the security boundary; the AST restriction is defense-in-depth.
_CHILD = r"""
import ast, builtins, json, sys
p=json.loads(sys.stdin.read())
allowed={name:getattr(builtins,name) for name in
 ("sorted","len","range","enumerate","min","max","zip","list","tuple","abs","sum")}
scope={"__builtins__":allowed}
exec(compile(ast.parse(p["source"]),"<candidate>","exec"),scope)
fun=scope["merge_closed_intervals"]
rows=[]
for values in p["cases"]:
 try:
  res=fun(values)
  rows.append({"result":res,"after":values,"input_alias":res is values,
               "inner_alias":any(x is y for x in res for y in values)
                  if isinstance(res,list) else False})
 except Exception as e:
  rows.append({"error":type(e).__name__,"after":values})
sys.stdout.write(json.dumps(rows,separators=(",",":")))
"""


@dataclass(frozen=True)
class FunctionalEvidence:
    verdict: str
    reason: str
    candidate_sha256: str
    suite_sha256: str | None = None
    passed: int = 0
    cases: int = _CASE_COUNT
    guest_receipt_sha256: str | None = None
    may_publish: bool = False
    may_dispatch_production_effect: bool = False


def _unknown(candidate_sha: str, reason: str) -> FunctionalEvidence:
    return FunctionalEvidence("UNKNOWN", reason, candidate_sha)


def _guest(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"verdict": "UNKNOWN", "reason": "INVALID_REQUEST"}
    source = payload.get("source")
    expected = payload.get("expected_sha256")
    if (
        payload.get("suite") != SUITE
        or not isinstance(source, str)
        or not isinstance(expected, str)
        or not _SHA.fullmatch(expected)
    ):
        return {"verdict": "UNKNOWN", "reason": "INVALID_REQUEST"}
    actual = _sha(source.encode("utf-8"))
    if actual != expected or not _validate_candidate(source):
        return {"verdict": "UNKNOWN", "reason": "SOURCE_SHA_OR_POLICY_INVALID"}
    cases = suite_cases()
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-B", "-c", _CHILD],
            input=json.dumps({"source": source, "cases": cases}),
            text=True, capture_output=True, timeout=10, check=False,
            env={"PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"verdict": "UNKNOWN", "reason": "CHILD_UNSETTLED"}
    if proc.returncode != 0 or len(proc.stdout) > 400_000:
        return {"verdict": "UNKNOWN", "reason": "CHILD_FAILED_OR_OVERSIZE"}
    try:
        rows = json.loads(proc.stdout)
        if not isinstance(rows, list) or len(rows) != _CASE_COUNT:
            raise ValueError("row count")
        passed = 0
        for original, row in zip(cases, rows, strict=True):
            if not isinstance(row, dict):
                raise ValueError("row type")
            result = row.get("result")
            if (
                type(result) is list
                and all(type(x) is list for x in result)
                and result == _oracle(original)
                and row.get("after") == original
                and row.get("input_alias") is False
                and row.get("inner_alias") is False
            ):
                passed += 1
    except (ValueError, TypeError, KeyError):
        return {"verdict": "UNKNOWN", "reason": "CHILD_RECEIPT_INVALID"}
    return {
        "protocol": PROTOCOL, "suite": SUITE,
        "candidate_sha256": actual, "suite_sha256": _sha(_canonical(cases)),
        "verdict": "PASS_FUNCTIONAL" if passed == _CASE_COUNT else "FAIL_FUNCTIONAL",
        "reason": "ALL_ASSERTIONS_PASS" if passed == _CASE_COUNT else "ORACLE_DISAGREES",
        "passed": passed, "cases": _CASE_COUNT,
        "may_publish": False, "may_dispatch_production_effect": False,
    }


def run_host_functional_review(
    candidate: bytes, *, expected_sha256: str, suite: str,
    image_ref: str = BASE_IMAGE, docker_binary: str = _DOCKER,
) -> FunctionalEvidence:
    """Host alone runs the pinned guest and independently checks its receipt.

    No externally supplied verdict/receipt parameter is accepted; only the
    frozen candidate, exact Task SHA, Host-selected suite and exact OCI ref.
    """
    actual = _sha(candidate)
    if not _SHA.fullmatch(expected_sha256) or actual != expected_sha256:
        return _unknown(actual, "CANDIDATE_SHA_MISMATCH")
    if suite != SUITE:
        return _unknown(actual, "FUNCTIONAL_SUITE_NOT_FROZEN")
    if not _IMAGE.fullmatch(image_ref):
        return _unknown(actual, "OCI_IMAGE_DIGEST_REQUIRED")
    try:
        source = candidate.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return _unknown(actual, "SOURCE_NOT_UTF8")
    if not _validate_candidate(source):
        return _unknown(actual, "SOURCE_SYNTAX_OR_POLICY_INVALID")
    env = {
        "HOME": "/nonexistent", "PATH": "/usr/bin:/bin",
        "DOCKER_CONFIG": "/nonexistent", "LC_ALL": "C",
    }
    def docker(*args: str, timeout: float = 12.0, data: bytes | None = None):
        return subprocess.run(
            [docker_binary, "--host", "unix:///var/run/docker.sock", *args],
            input=data, capture_output=True, check=False,
            env=env, timeout=timeout,
        )
    try:
        pin = docker("image", "inspect", image_ref,
                     "--format", "{{json .RepoDigests}}")
        if pin.returncode or image_ref not in json.loads(pin.stdout):
            return _unknown(actual, "PINNED_OCI_IMAGE_MISSING")
    except (OSError, ValueError, subprocess.TimeoutExpired, TypeError):
        return _unknown(actual, "DOCKER_IMAGE_INSPECT_UNAVAILABLE")
    nonce = secrets.token_hex(12)
    name = "lfl-assurance-p112-functional-" + nonce
    wire = _canonical({
        "source": source, "expected_sha256": expected_sha256, "suite": suite,
    })
    content = Path(__file__).read_bytes()
    result: dict[str, Any] | None = None
    cleanup_ok = False
    try:
        # Container has no mounts or network, and no ability to access Docker.
        proc = docker(
            "run", "--rm", "--pull=never", "--name", name,
            "--network=none", "--ipc=none", "--read-only",
            "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--user=65534:65534", "--pids-limit=32",
            "--memory=128m", "--cpus=1", "--interactive",
            "--entrypoint=python3", image_ref, "-I", "-B", "-c",
            content.decode("utf-8"), "--guest",
            timeout=24.0, data=wire,
        )
        if proc.returncode == 0 and 0 < len(proc.stdout) <= 8192:
            obj = json.loads(proc.stdout)
            if type(obj) is dict:
                result = obj
    except (OSError, ValueError, UnicodeError, subprocess.TimeoutExpired):
        result = None
    finally:
        # The exact randomized fixture container must not survive a timed
        # out docker client; no broad cleanup by prefix is ever performed.
        try:
            docker("rm", "--force", name, timeout=8)
            probe = docker("inspect", name, timeout=5)
            cleanup_ok = probe.returncode != 0
        except (OSError, subprocess.TimeoutExpired):
            cleanup_ok = False
    if not cleanup_ok:
        return _unknown(actual, "GUEST_CLEANUP_UNCONFIRMED")
    expected_suite = _sha(_canonical(suite_cases()))
    if result is None or set(result) != {
        "protocol", "suite", "candidate_sha256", "suite_sha256",
        "verdict", "reason", "passed", "cases",
        "may_publish", "may_dispatch_production_effect",
    }:
        return _unknown(actual, "GUEST_RECEIPT_MISSING")
    passed = result.get("passed")
    verdict = result.get("verdict")
    expected_reason = "ORACLE_DISAGREES"
    if passed == _CASE_COUNT:
        expected_reason = "ALL_ASSERTIONS_PASS"
    if not (
        result.get("protocol") == PROTOCOL
        and result.get("suite") == SUITE
        and result.get("candidate_sha256") == actual
        and result.get("suite_sha256") == expected_suite
        and type(passed) is int and 0 <= passed <= _CASE_COUNT
        and result.get("cases") == _CASE_COUNT
        and verdict in {"PASS_FUNCTIONAL", "FAIL_FUNCTIONAL"}
        and (verdict == "PASS_FUNCTIONAL") == (passed == _CASE_COUNT)
        and result.get("reason") == expected_reason
        and result.get("may_publish") is False
        and result.get("may_dispatch_production_effect") is False
    ):
        return _unknown(actual, "GUEST_RECEIPT_INVALID")
    return FunctionalEvidence(
        verdict=verdict, reason=result["reason"],
        candidate_sha256=actual, suite_sha256=expected_suite,
        passed=passed, guest_receipt_sha256=_sha(_canonical(result)),
    )


def main() -> None:
    if sys.argv[1:] != ["--guest"]:
        raise SystemExit(2)
    try:
        request = json.loads(sys.stdin.buffer.read(12_000))
        receipt = _guest(request)
    except (OSError, ValueError, TypeError):
        receipt = {"verdict": "UNKNOWN", "reason": "INVALID_GUEST_INPUT"}
    sys.stdout.write(_canonical(receipt).decode("ascii") + "\n")


if __name__ == "__main__":
    main()
