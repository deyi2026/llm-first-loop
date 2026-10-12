# -*- coding: utf-8 -*-
import asyncio, json, urllib.request, websockets
CDP = "http://127.0.0.1:9229"

def targets():
    d = json.load(urllib.request.urlopen(CDP + "/json"))
    return [t for t in d if t.get("type") == "page"]

async def connect(url_sub="toutiao"):
    ts = [t for t in targets() if url_sub in t.get("url", "")]
    if not ts:
        raise RuntimeError("no page matching %r; have: %s" % (url_sub, [t.get("url","")[:60] for t in targets()]))
    ws = await websockets.connect(ts[0]["webSocketDebuggerUrl"], max_size=200*1024*1024)
    return ws, ts[0]

def make_eval(ws):
    i = [0]
    async def ev(e, await_promise=True):
        i[0] += 1
        await ws.send(json.dumps({"id": i[0], "method": "Runtime.evaluate",
                                  "params": {"expression": e, "returnByValue": True,
                                             "awaitPromise": await_promise}}))
        while True:
            m = json.loads(await ws.recv())
            if m.get("id") == i[0]:
                r = m.get("result", {})
                if "exceptionDetails" in r:
                    return "ERR:" + str(r["exceptionDetails"].get("text")) + " " + str(r["exceptionDetails"].get("exception", {}).get("description", ""))[:400]
                return r.get("result", {}).get("value")
    return ev

async def run(exprs, url_sub="toutiao"):
    ws, t = await connect(url_sub)
    ev = make_eval(ws)
    out = []
    for e in exprs:
        out.append(await ev(e))
    await ws.close()
    return t, out

def main():
    import sys, asyncio
    exprs = [l for l in open(sys.argv[1], encoding="utf-8").read().split("\n@@@\n") if l.strip()]
    t, out = asyncio.run(run(exprs))
    print("PAGE:", t.get("url", "")[:100])
    for e, o in zip(exprs, out):
        print("  ->", str(o)[:1400])

if __name__ == "__main__":
    main()
