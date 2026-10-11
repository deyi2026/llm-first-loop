"""Isolated *deterministic* Reviewer in a true Linux Python container.

Only literal acceptance checks are performed. No LFL Provider, tools, shell,
network, dynamic code, files or model inference are loaded. A bounded PASS
never becomes permission to commit, publish, execute or take over a Task.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sys

SCHEMA = "lfl.dual_assurance.p18_review_request/v1"
ACCEPTANCE_SCHEMA = "lfl.dual_assurance.p18_acceptance/v1"
RECEIPT_SCHEMA = "lfl.dual_assurance.p18_review_receipt/v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX32 = re.compile(r"^[0-9a-f]{32}$")
CHECK_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
MAX_INPUT = 16384
MAX_CANDIDATE = 4096
MAX_EVIDENCE = 8192
MAX_CHECKS = 6
REQ_KEYS = {
    "schema", "nonce", "candidate_b64", "candidate_sha256",
    "evidence_b64", "evidence_sha256", "acceptance",
    "acceptance_sha256",
}
CHECK_KEYS = {"id", "type", "value"}
TYPES = {"CONTAINS_LITERAL", "EXCLUDES_LITERAL", "SEMANTIC_REVIEW_REQUIRED"}


def canonical(data: object) -> bytes:
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")


def decode_b64(value: str, *, limit: int) -> bytes:
    if not isinstance(value, str) or len(value) > 4 * ((limit + 2) // 3):
        raise ValueError("invalid bounded base64")
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ValueError("invalid base64") from exc
    if not 0 < len(raw) <= limit:
        raise ValueError("decoded size rejected")
    return raw


def review(frame: object) -> dict:
    if not isinstance(frame, dict) or set(frame) != REQ_KEYS:
        raise ValueError("exact request keys required")
    if frame["schema"] != SCHEMA or not isinstance(frame["nonce"], str) or not HEX32.fullmatch(frame["nonce"]):
        raise ValueError("schema or nonce mismatch")
    candidate = decode_b64(frame["candidate_b64"], limit=MAX_CANDIDATE)
    evidence = decode_b64(frame["evidence_b64"], limit=MAX_EVIDENCE)
    if (
        not isinstance(frame["candidate_sha256"], str)
        or not HEX64.fullmatch(frame["candidate_sha256"])
        or hashlib.sha256(candidate).hexdigest() != frame["candidate_sha256"]
        or not isinstance(frame["evidence_sha256"], str)
        or not HEX64.fullmatch(frame["evidence_sha256"])
        or hashlib.sha256(evidence).hexdigest() != frame["evidence_sha256"]
    ):
        raise ValueError("frozen input digest mismatch")
    acceptance = frame["acceptance"]
    if (
        not isinstance(acceptance, dict)
        or set(acceptance) != {"schema", "checks"}
        or acceptance["schema"] != ACCEPTANCE_SCHEMA
        or not isinstance(acceptance["checks"], list)
        or not 0 < len(acceptance["checks"]) <= MAX_CHECKS
        or not isinstance(frame["acceptance_sha256"], str)
        or not HEX64.fullmatch(frame["acceptance_sha256"])
        or hashlib.sha256(canonical(acceptance)).hexdigest() != frame["acceptance_sha256"]
    ):
        raise ValueError("acceptance identity invalid")
    seen = set()
    checks = []
    candidate_text = candidate.decode("utf-8", errors="strict")
    for item in acceptance["checks"]:
        if not isinstance(item, dict) or set(item) != CHECK_KEYS:
            raise ValueError("invalid check shape")
        check_id, kind, value = item["id"], item["type"], item["value"]
        if (
            not isinstance(check_id, str) or not CHECK_ID.fullmatch(check_id)
            or check_id in seen or kind not in TYPES
            or not isinstance(value, str) or len(value.encode("utf-8")) > 200
        ):
            raise ValueError("unsupported or duplicate acceptance check")
        if kind != "SEMANTIC_REVIEW_REQUIRED" and not value:
            raise ValueError("literal assertion must not be empty")
        seen.add(check_id)
        if kind == "SEMANTIC_REVIEW_REQUIRED":
            verdict = "UNKNOWN"
        elif kind == "CONTAINS_LITERAL":
            verdict = "PASS" if value in candidate_text else "FAIL"
        else:
            verdict = "PASS" if value not in candidate_text else "FAIL"
        checks.append({"id": check_id, "verdict": verdict})
    statuses = {x["verdict"] for x in checks}
    overall = "FAIL" if "FAIL" in statuses else (
        "UNCERTAIN" if "UNKNOWN" in statuses else "PASS_BOUNDED"
    )
    return {
        "schema": RECEIPT_SCHEMA,
        "nonce": frame["nonce"],
        "candidate_sha256": frame["candidate_sha256"],
        "acceptance_sha256": frame["acceptance_sha256"],
        "evidence_sha256": frame["evidence_sha256"],
        "verdict": overall,
        "checks": checks,
        "production_release_qualified": False,
    }


def main() -> int:
    source = sys.stdin.buffer.read(MAX_INPUT + 1)
    if not 0 < len(source) <= MAX_INPUT:
        print("INVALID_FRAME", file=sys.stderr)
        return 41
    try:
        payload = json.loads(source)
        result = review(payload)
    except (ValueError, KeyError, TypeError, UnicodeError):
        print("INVALID_FRAME", file=sys.stderr)
        return 42
    # Exact JSON record only: never print the user candidate or evidence bytes.
    out = canonical(result)
    if len(out) > 2048:
        print("OVERSIZED_RECEIPT", file=sys.stderr)
        return 43
    sys.stdout.buffer.write(out + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
