#!/usr/bin/env python3
"""R0 cognilocal 基线跑：6 fixture 任务经 8903 API，漂移率/完成率判定.
用法: python3 scripts/run_fixture_baseline.py &  （长任务，日志 fixtures-baseline.log）
"""

import json
import re
import time
import urllib.request

BASE = "http://127.0.0.1:8903/api/v1"
MODEL = "local/qwen/qwen3.8-27b"  # cognilocal(8901)服务已停；local 直连 LM Studio(:1234)，27B 同级保持基线语义
DRIFT_PAT = re.compile(r"(我能做|我是.{0,12}模型|作为.{0,10}(助手|AI)|能力清单|我能帮助)")


def chat(message: str, session_id=None, timeout=1800):  # 27B 本地 agentic 单轮可跑 10-30 分钟
    body = {"message": message, "model": MODEL}
    if session_id:
        body["session_id"] = session_id
    else:
        body["new_session"] = (
            True  # routes.py:179-180 契约：new_session 优先 engine.session.create()
        )
    req = urllib.request.Request(
        BASE + "/chat/stream",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    done, cur_sid, acc = None, session_id, []
    deadline = time.time() + timeout
    with urllib.request.urlopen(req, timeout=60) as resp:  # socket 级单次 read 上限
        buf = b""
        stop = False
        while not stop:
            chunk = resp.read(1)
            if not chunk:
                break  # EOF：流正常关闭
            buf += chunk
            while b"\n\n" in buf:
                block, buf = buf.split(b"\n\n", 1)
                for line in block.decode("utf-8", "replace").splitlines():
                    if line.startswith("data: "):
                        try:
                            evt = json.loads(line[6:])
                        except Exception:
                            continue
                        t = evt.get("type")
                        if t == "answer_delta":
                            acc.append(evt.get("data", {}).get("data", ""))
                        elif t == "done":
                            done = evt.get("data") or {}
                            stop = True  # 关键修复：收到 done 立即退出，不依赖 EOF（防 keep-alive 挂死）
                        elif t == "error":
                            done = {"error": evt.get("data")}
                            stop = True
                        if isinstance(done, dict) and done.get("session_id"):
                            cur_sid = done["session_id"]
                if time.time() > deadline:
                    done = done or {"timeout": True}
                    stop = True
        if done is None and acc:  # done 缺失兜底：用已收 answer_delta 拼接
            done = {"final_answer": "".join(acc), "partial": True}
    return done or {}, cur_sid


def main():
    with open("docs/injection-governance/fixtures/fixture-tasks.json") as fh:
        fixture = json.load(fh)
    results = []
    for t in fixture["tasks"]:
        tid, sid, rounds = t["id"], None, []
        print(f"[{tid}] {t['desc']} start", flush=True)
        for i, msg in enumerate(t["messages"], 1):
            t0 = time.time()
            try:
                data, sid = chat(msg, sid)
            except Exception as exc:
                rounds.append({"round": i, "error": str(exc)[:200]})
                print(f"[{tid}] r{i} ERROR {exc}", flush=True)
                continue
            ans = data.get("final_answer") or data.get("answer") or ""
            drift = bool(DRIFT_PAT.search(ans)) if ans else None
            rounds.append(
                {
                    "round": i,
                    "answer_head": ans[:150],
                    "drift": drift,
                    "model_used": data.get("model_used", ""),
                    "secs": round(time.time() - t0, 1),
                }
            )
            print(
                f"[{tid}] r{i} drift={drift} secs={round(time.time() - t0, 1)} head={ans[:60]!r}",
                flush=True,
            )
            time.sleep(2)
        total = len([r for r in rounds if "error" not in r])
        drifts = len([r for r in rounds if r.get("drift")])
        results.append(
            {
                "id": tid,
                "type": t["type"],
                "session_id": sid,
                "rounds_total": total,
                "drift_rounds": drifts,
                "drift_rate": round(drifts / total, 3) if total else None,
                "rounds": rounds,
            }
        )
    with open("docs/injection-governance/fixtures/baseline-results.json", "w") as fh:
        json.dump(
            {"model": MODEL, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "results": results},
            fh,
            ensure_ascii=False,
            indent=1,
        )
    ok = [r for r in results if r["drift_rate"] is not None]
    print("\n==== 汇总 ====", flush=True)
    for r in results:
        print(f"{r['id']} {r['type']:<15} 漂移率={r['drift_rate']}", flush=True)
    if ok:
        print(f"平均漂移率 = {sum(r['drift_rate'] for r in ok) / len(ok):.3f}", flush=True)


if __name__ == "__main__":
    main()
