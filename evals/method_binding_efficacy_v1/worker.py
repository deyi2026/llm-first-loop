#!/usr/bin/env python3
"""One headless LFL run: one arm x one case (or smoke probe). Env is fully controlled by orchestrator."""
import argparse, hashlib, json, sys, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
for p in (str(HERE), str(REPO), str(REPO / "src")): sys.path.insert(0, p)
from protocol import MODEL, BINDING_MARKER, PROMPT_TEMPLATE, SMOKE_PROMPT, sha256_json

def _tc_entry(tc):
    name = getattr(tc, "name", None) or (tc.get("name") if isinstance(tc, dict) else None) or "?"
    raw = getattr(tc, "arguments", None)
    if raw is None and isinstance(tc, dict): raw = tc.get("arguments")
    args = {}
    if isinstance(raw, str):
        try: args = json.loads(raw) or {}
        except Exception: args = {"_raw": str(raw)[:80]}
    elif isinstance(raw, dict): args = raw
    keep = {k: args.get(k) for k in ("action", "use_decision", "method_ref") if k in args}
    return {"name": str(name), **keep}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=["C0", "C1"])
    ap.add_argument("--case-id"); ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--surface-only", action="store_true")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    started = time.monotonic()
    row = {"arm": args.arm, "case_id": args.case_id or "smoke",
           "kind": "smoke" if args.smoke else ("surface_only" if args.surface_only else "formal"),
           "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    try:
        from llm_loop.config import load_env_file, load_settings
        from llm_loop.factory import build_engine
        from llm_loop.introspection import registry_experience as reg
        from llm_loop.core.trace_leak.ingress_token import issue_ingress
        load_env_file(); settings = load_settings()
        desc = next(r for r in reg.tool_defs() if r["name"] == "save_experience")["description"]
        binding = BINDING_MARKER in desc
        assert binding == (args.arm == "C1"), f"BINDING GATE MISMATCH arm={args.arm} binding={binding}"
        assert settings.llm_model == MODEL, f"MODEL DRIFT {settings.llm_model}"
        assert Path(settings.data_dir).resolve() == (HERE / "run_data").resolve(), f"DATA_DIR DRIFT {settings.data_dir}"
        engine = build_engine(settings)
        surface = {r["name"]: sha256_json(r) for r in engine.registry.schemas(lazy=True)}
        row.update({"binding_asserted": binding, "model_registered": settings.llm_model,
                    "surface_tool_count": len(surface), "surface_sha256": sha256_json(surface)})
        if args.surface_only:
            row["status"] = "SURFACE_ONLY"; row["surface"] = surface
        else:
            prompt = SMOKE_PROMPT
            if not args.smoke:
                pool = json.loads((HERE / "pool.json").read_text())
                case = pool["cases"][args.case_id]
                row["kind"], row["expected"] = case["kind"], case["expected"]
                prompt = PROMPT_TEMPLATE.format(trigger=case["trigger"], card=case["card"])
            sid = engine.session.create()
            result = engine.run(sid, prompt, ingress=issue_ingress("cli"))
            tcs = [_tc_entry(tc) for tc in (result.tool_calls or [])]
            row.update({"status": "RUN_OK",
                        "session_sha256": hashlib.sha256(sid.encode()).hexdigest()[:16],
                        "wall_s": round(time.monotonic() - started, 3),
                        "rounds": result.rounds, "tool_calls": tcs, "tool_call_count": len(tcs),
                        "tokens_in": result.tokens_in, "tokens_out": result.tokens_out,
                        "cache_hit_tokens": result.tokens_cache_hit, "truncated": bool(result.truncated),
                        "model_used": result.model_used, "fallback_used": bool(result.fallback_receipt),
                        "final_answer": result.final_answer or "",
                        "final_answer_sha256": hashlib.sha256((result.final_answer or "").encode()).hexdigest()[:16],
                        "record_use_applied": any(t["name"] == "method_manage" and t.get("use_decision") == "applied" for t in tcs)})
    except Exception as exc:
        row.update({"status": "WORKER_ERROR", "error_type": type(exc).__name__,
                    "error": str(exc)[:300], "wall_s": round(time.monotonic() - started, 3)})
    finally:
        try: engine.close()
        except Exception: pass
    with open(args.out, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(row["status"], row["arm"], row["case_id"], row.get("wall_s", "?"), "s")

if __name__ == "__main__": main()
