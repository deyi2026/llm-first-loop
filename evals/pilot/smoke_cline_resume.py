#!/usr/bin/env python3
"""Cline --id resume smoke qualification（t12 复测前的独立闸门）。

直接 import run_pilot 的 _cline_cmd/_cline_parse，保证 smoke 验证的调用路径
与正式矩阵完全一致（而非另拼一条命令）。

机械判据：
  A（新会话）: rc=0, finishReason!=error, 解析出 conv_* taskid, smoke_a.txt 落盘
  B（--id 恢复）: rc=0, finishReason!=error, smoke_b.txt 落盘
  continuity: B 的 JSON 流报告的 taskid == A 的 taskid（同一 conv_ 会话被续接）
输出：/tmp/agentpilot_smoke_cline/ws1/_smoke_result.json + 全量日志落盘
"""
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_pilot import _cline_cmd, _cline_parse  # noqa: E402

WS = Path("/tmp/agentpilot_smoke_cline/ws1")
WS.mkdir(parents=True, exist_ok=True)


def run(prompt: str, sid: str, tag: str) -> dict:
    cmd = _cline_cmd(prompt, WS, 120, sid)
    t0 = time.time()
    r = subprocess.run(cmd, cwd=WS, capture_output=True, text=True, timeout=180)
    info = _cline_parse(r.stdout)
    (WS / f"_smoke_{tag}.jsonl").write_text(r.stdout)  # 全量 JSON 流落盘备查
    return {"rc": r.returncode, "dur": round(time.time() - t0, 1),
            "taskid": info["taskid"], "meta": info["meta"], "stderr_tail": r.stderr[-300:]}


def main() -> int:
    res = {}
    pA = ("在当前目录创建文件 smoke_a.txt，内容恰好一行：phase1。"
          "完成后只回复 DONE_A，不要做其他事。")
    res["A"] = run(pA, "", "A")
    okA = (res["A"]["rc"] == 0 and res["A"]["taskid"].startswith("conv_")
           and res["A"]["meta"].get("finish") != "error" and (WS / "smoke_a.txt").exists())
    print("A:", json.dumps(res["A"], ensure_ascii=False), "okA=", okA, flush=True)
    if not res["A"]["taskid"]:
        print(json.dumps({"smoke": "FAIL", "stage": "A", "reason": "no conv_ id parsed",
                          "res": res}, ensure_ascii=False, indent=1))
        return 1
    pB = ("这是我们同一会话的延续。请在当前目录创建文件 smoke_b.txt，"
          "内容恰好一行：phase2_resumed。完成后只回复 DONE_B。")
    res["B"] = run(pB, res["A"]["taskid"], "B")
    okB = (res["B"]["rc"] == 0 and res["B"]["meta"].get("finish") != "error"
           and (WS / "smoke_b.txt").exists())
    same_id = res["B"]["taskid"] == res["A"]["taskid"]
    if okA and okB and same_id:
        verdict = "PASS"
    elif okA and okB:
        verdict = "PARTIAL-new-taskid"  # 文件完成但 conv id 变了：需查 history 判定续接真伪
    else:
        verdict = "FAIL"
    out = {"smoke": verdict, "okA": okA, "okB": okB, "same_conv_id": same_id, "res": res}
    (WS / "_smoke_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
