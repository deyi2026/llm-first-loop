#!/usr/bin/env python3
"""P1b-L 本地开源 judge 传输（包外实现；DESIGN §11.2 预注册，冻结于任何本地真实评分之前）。

- judge = SemIf（vendored，MIT，接口模式复现，非 Jev 本体）+ 钉住
  Qwen/Qwen3.5-4B@851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a + MLX 后端 bf16 不量化，
  shared 模式（一次 state prefill + 独立题后缀；shared 要求全批同 state，批1/批2 均满足）。
- 零外发：仅本机 subprocess 调 vendored venv；无凭据、无费用。
- 映射契约：question=instructions；options=yes/no/unknown(description=criteria.*)；
  answer=argmax；probabilities=dict(zip(option_ids, softmax_list))；
  confidence:=p_selected（SemIf 无 Jev confidence，此为 adapter 定义的分布确定性摘要）；
  SemIf probability_status（uncalibrated）原样透传；usage 不映射（无计量→unknown 不计 0），
  SemIf 原始输出（含 input_tokens/prompt_sha256）落盘 semif_audit/ 供审计。
- 单次尝试、无重试；超时/非零退出按 JevTransportError 上报（shadow 层归 transport_failed）。
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import time

from llm_loop.knowledge.jev.transport import JevTransportError

OUT_DIR = pathlib.Path(__file__).resolve().parent
VENDOR = OUT_DIR / "vendor" / "SemIf"
VENV_PY = VENDOR / ".venv" / "bin" / "python"
SEMIF_MODEL = "Qwen/Qwen3.5-4B"
SEMIF_REVISION = "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
LOCAL_JUDGE_ID = "semif-phase1+Qwen3.5-4B@851bf6e+mlx"
_PROB_STATUS = "conditional option score; uncalibrated as decision confidence"


class SemIfLocalTransport:
    """一次 send = 一次本地评分进程（一批题共享 state，一次 prefill）。"""

    def __init__(self, audit_dir: pathlib.Path | None = None) -> None:
        if not VENV_PY.exists():
            raise RuntimeError(f"SemIf venv missing: {VENV_PY}")
        self.audit_dir = audit_dir or (OUT_DIR / "semif_audit")
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
            "--backend", "mlx", "--mode", "shared",
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
            probs = {oid: float(p) for oid, p in zip(opt_ids, probs_list, strict=True)}
            top = max(probs, key=probs.get)
            # EVO-20261015（R1 根因修复同步）：官方逐题值字段名 choice
            answers[name] = {"choice": top, "probabilities": probs, "confidence": probs[top]}

        self.calls.append({
            "elapsed_s": time.monotonic() - started,
            "input": str(in_path), "output": str(out_path),
            "returncode": proc.returncode,
        })
        return {
            "model": LOCAL_JUDGE_ID,
            "answers": answers,
            "semif_probability_status": _PROB_STATUS,
        }
