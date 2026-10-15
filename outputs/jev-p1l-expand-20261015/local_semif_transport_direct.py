#!/usr/bin/env python3
"""§11.4 direct 模式传输：子类化 §11.2 SemIfLocalTransport，仅改 --mode 与 resolved_model ID。

- 判决数学/prompt 构造与 shared 同路径（direct.py::encode_prompt + 最后位 logits softmax）；
- 每行（每题）独立全前向，无 shared 前缀校验（§11.4 根因规避）；
- 不修改 §11.2 冻结件本文件以外的任何 vendor/transport 代码。
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import time

from llm_loop.knowledge.jev.transport import JevTransportError
from local_semif_transport import (
    SEMIF_MODEL,
    SEMIF_REVISION,
    VENDOR,
    VENV_PY,
    _PROB_STATUS,
)

DIRECT_JUDGE_ID = "semif-phase1+Qwen3.5-4B@851bf6e+mlx-direct"


class SemIfLocalDirectTransport:
    """一次 send = 一次本地评分进程（一批题，CLI 对每行独立全前向 direct 评分）。"""

    def __init__(self, audit_dir: pathlib.Path | None = None) -> None:
        if not VENV_PY.exists():
            raise RuntimeError(f"SemIf venv missing: {VENV_PY}")
        self.audit_dir = audit_dir or (pathlib.Path(__file__).resolve().parent / "semif_audit_direct")
        self.calls: list[dict] = []

    def send(self, request: dict, *, deadline_s: float) -> dict:
        started = time.monotonic()
        state = request.get("state") or {}
        task_snapshot = state.get("task_snapshot")
        if not isinstance(task_snapshot, dict) or not task_snapshot:
            raise JevTransportError("transport", "state.task_snapshot missing or not an object")
        questions = request.get("questions") or {}
        if not questions:
            raise JevTransportError("transport", "request has no questions")

        rows = []
        for name, spec in questions.items():
            criteria = spec.get("criteria") or {}
            options = [
                {"id": oid, "description": str(criteria.get(oid, ""))}
                for oid in ("yes", "no", "unknown")
            ]
            if any(not o["description"] for o in options):
                raise JevTransportError("transport", f"question {name}: criteria missing an option description")
            rows.append({
                "id": name,
                "state": task_snapshot,
                "question": str(spec.get("instructions", "")),
                "options": options,
            })

        self.audit_dir.mkdir(parents=True, exist_ok=True)
        seq = len(self.calls) + 1
        stamp = time.strftime("%Y%m%dT%H%M%S")
        in_path = self.audit_dir / f"semif_in_{stamp}_{seq}.jsonl"
        out_path = self.audit_dir / f"semif_out_{stamp}_{seq}.jsonl"
        in_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

        cmd = [
            str(VENV_PY), "-m", "semif_phase1.cli",
            "--backend", "mlx", "--mode", "direct",
            "--model", SEMIF_MODEL, "--revision", SEMIF_REVISION,
            "--input", str(in_path), "--output", str(out_path),
        ]
        try:
            proc = subprocess.run(
                cmd, cwd=str(VENDOR), capture_output=True, text=True,
                timeout=float(deadline_s),
            )
        except subprocess.TimeoutExpired as exc:
            raise JevTransportError("timeout", f"semif-score exceeded {deadline_s}s") from exc
        if proc.returncode != 0 or not out_path.exists():
            raise JevTransportError("transport", f"semif-score exit={proc.returncode}: {proc.stderr.strip()[-400:]}")

        by_id: dict[str, dict] = {}
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                by_id[rec["id"]] = rec

        answers = {}
        for name in questions:
            rec = by_id.get(name)
            if rec is None:
                raise JevTransportError("transport", f"semif output missing question {name}")
            opt_ids = rec.get("option_ids")
            probs_list = rec.get("probabilities")
            if (
                not isinstance(opt_ids, list) or set(opt_ids) != {"yes", "no", "unknown"}
                or not isinstance(probs_list, list) or len(probs_list) != len(opt_ids)
            ):
                raise JevTransportError("transport", f"question {name}: unexpected probabilities shape")
            probs = {oid: float(p) for oid, p in zip(opt_ids, probs_list)}
            top = max(probs, key=probs.get)
            answers[name] = {"answer": top, "probabilities": probs, "confidence": probs[top]}

        self.calls.append({
            "elapsed_s": time.monotonic() - started,
            "input": str(in_path), "output": str(out_path),
            "returncode": proc.returncode,
        })
        return {
            "model": DIRECT_JUDGE_ID,
            "answers": answers,
            "semif_probability_status": _PROB_STATUS,
        }
