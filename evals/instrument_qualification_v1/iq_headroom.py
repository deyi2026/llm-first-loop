"""Standalone headroom gate — IQ-V1-PREREG.md §6. Reusable for ANY future frozen pool.
Zero provider. Exit 0 = pass, 1 = fail.
Usage:
  python iq_headroom.py --result IQ-RESULT.json          # reads certified counts
  python iq_headroom.py --hplus 13 --hminus 7 [--need 6] # raw counts
Gate: H_plus >= 2 * net_flip_need (default need=6 -> >=12) AND H_minus >= 6.
"""
import argparse, json, pathlib, sys

ap = argparse.ArgumentParser()
ap.add_argument("--result", type=str)
ap.add_argument("--hplus", type=int)
ap.add_argument("--hminus", type=int)
ap.add_argument("--need", type=int, default=6, help="net flips required by the next pool's spec")
a = ap.parse_args()

if a.result:
    r = json.loads(pathlib.Path(a.result).read_text(encoding="utf-8"))
    hplus = r["gates"]["Q3_headroom"]["H_plus"]
    hminus = r["gates"]["Q3_headroom"]["H_minus"]
elif a.hplus is not None and a.hminus is not None:
    hplus, hminus = a.hplus, a.hminus
else:
    ap.error("need --result or both --hplus/--hminus")

gate_p, gate_m = 2 * a.need, 6
ok = hplus >= gate_p and hminus >= gate_m
print(f"H_plus={hplus} (gate >= {gate_p} = 2*need{a.need})  H_minus={hminus} (gate >= {gate_m})  ->  {'PASS' if ok else 'FAIL'}")
sys.exit(0 if ok else 1)
