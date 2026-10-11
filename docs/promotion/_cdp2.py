import json, asyncio, websockets, urllib.request
CDP = "http://127.0.0.1:9229"

def browser_ws():
    return json.load(urllib.request.urlopen(CDP + "/json/version"))["webSocketDebuggerUrl"]

def pages():
    return [t for t in json.load(urllib.request.urlopen(CDP + "/json")) if t.get("type") == "page"]

class Tab:
    """Keeps one CDP target open across steps; id is remembered by URL substring."""
    def __init__(self, url, wait=5):
        self.url = url
        asyncio.run(self._open(wait))
    async def _send(self, ws, method, params, sid=None):
        self._n += 1
        msg = {"id": self._n, "method": method, "params": params}
        if sid: msg["sessionId"] = sid
        await ws.send(json.dumps(msg))
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 40))
            if m.get("id") == self._n: return m
    async def _open(self, wait):
        async with websockets.connect(browser_ws(), max_size=200*1024*1024) as ws:
            self._n = 0
            r = await self._send(ws, "Target.createTarget", {"url": self.url})
            self.tid = r["result"]["targetId"]
            a = await self._send(ws, "Target.attachToTarget", {"targetId": self.tid, "flatten": True})
            self.sid = a["result"]["sessionId"]
            await asyncio.sleep(wait)
    def _run(self, coro_fn):
        async def main():
            async with websockets.connect(browser_ws(), max_size=200*1024*1024) as ws:
                return await coro_fn(ws)
        return asyncio.run(main())
    def ev(self, js):
        async def f(ws):
            self._n = 0
            return await self._send(ws, "Runtime.evaluate",
                {"expression": js, "returnByValue": True, "awaitPromise": True}, self.sid)
        r = self._run(f)
        res = r.get("result", {})
        if "exceptionDetails" in res:
            return "EXC:" + json.dumps(res["exceptionDetails"], ensure_ascii=False)[:400]
        return res.get("result", {}).get("value")
    def click(self, js_find):
        pos = self.ev("(()=>{const el=(%s); if(!el) return null; const r=el.getBoundingClientRect();"
                      " return JSON.stringify({x:r.left+r.width/2,y:r.top+r.height/2,w:r.width,h:r.height});})()" % js_find)
        if not pos: return "NOT_FOUND"
        p = json.loads(pos)
        if p["w"] == 0 or p["h"] == 0: return "ZERO:" + json.dumps(p)
        async def f(ws):
            self._n = 0
            for t in ("mouseMoved", "mousePressed", "mouseReleased"):
                await self._send(ws, "Input.dispatchMouseEvent",
                    {"type": t, "x": p["x"], "y": p["y"], "button": "left",
                     "clickCount": 1 if t != "mouseMoved" else 0,
                     "buttons": 1 if t == "mousePressed" else 0}, self.sid)
            await asyncio.sleep(0.6)
            return "CLICKED:" + json.dumps(p)
        return self._run(f)
    def keys(self, js):
        """Insert text through the real input pipeline (CDP Input.insertText)."""
        async def f(ws):
            self._n = 0
            r = await self._send(ws, "Input.insertText", {"text": js}, self.sid)
            await asyncio.sleep(0.5)
            return r.get("result", {})
        return self._run(f)
    def counter(self):
        return self.ev(r"""(()=>{const ed=document.querySelector('.public-DraftEditor-content')||document.querySelector('[contenteditable]');
          const t=(ed&&ed.innerText)||'';
          return JSON.stringify({len:t.replace(/\s/g,'').length, lines:t.split('\n').filter(x=>x.trim()).length,
            imgs:document.querySelectorAll('.public-DraftEditor-content img').length,
            counter:(document.body.innerText.match(/字数[：: ]*\d+/)||[null])[0],
            btns:[...document.querySelectorAll('button')].map(b=>(b.innerText||'').trim()).filter(Boolean).slice(0,25)});})()""")
    def close(self):
        async def f(ws):
            self._n = 0
            return await self._send(ws, "Target.closeTarget", {"targetId": self.tid})
        return self._run(f)


def attach(tid):
    """Rebind a Tab-like handle to an already-open target id."""
    obj = Tab.__new__(Tab)
    obj.tid = tid
    obj.url = ""
    async def main():
        async with websockets.connect(browser_ws(), max_size=200*1024*1024) as ws:
            obj._n = 0
            a = await obj._send(ws, "Target.attachToTarget", {"targetId": tid, "flatten": True})
            obj.sid = a["result"]["sessionId"]
            return obj.sid
    asyncio.run(main())
    return obj
