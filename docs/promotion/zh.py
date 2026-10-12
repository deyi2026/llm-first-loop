# -*- coding: utf-8 -*-
"""知乎编辑器 CDP 助手：真实输入事件 + 计数器不变量。"""
import json, asyncio, websockets, urllib.request, os
CDP = "http://127.0.0.1:9229"
HERE = os.path.dirname(os.path.abspath(__file__))

def _bws():
    return json.load(urllib.request.urlopen(CDP + "/json/version"))["webSocketDebuggerUrl"]

def _pages():
    return [t for t in json.load(urllib.request.urlopen(CDP + "/json")) if t.get("type") == "page"]

def new_tab(url, wait=6):
    async def m():
        async with websockets.connect(_bws(), max_size=200*1024*1024) as ws:
            n = [0]
            async def s(method, params, sid=None):
                n[0] += 1
                msg = {"id": n[0], "method": method, "params": params}
                if sid: msg["sessionId"] = sid
                await ws.send(json.dumps(msg))
                while True:
                    r = json.loads(await asyncio.wait_for(ws.recv(), 40))
                    if r.get("id") == n[0]: return r
            t = (await s("Target.createTarget", {"url": url}))["result"]["targetId"]
            a = (await s("Target.attachToTarget", {"targetId": t, "flatten": True}))["result"]["sessionId"]
            await asyncio.sleep(wait)
            return t, a
    return asyncio.run(m())


COUNTER_JS = r"""(()=>{const ed=document.querySelector('.public-DraftEditor-content')||document.querySelector('[contenteditable]');
 const t=(ed&&ed.innerText)||'';
 return JSON.stringify({len:t.replace(/\s/g,'').length, lines:t.split('\n').filter(x=>x.trim()).length,
  imgs:document.querySelectorAll('.public-DraftEditor-content img').length,
  counter:(document.body.innerText.match(/字数[：: ]*\d+/)||[null])[0],
  head:t.replace(/\s+/g,' ').slice(0,90), tail:t.replace(/\s+/g,' ').slice(-90)});})()"""


def _unused(fn):
    """Attach to target, run fn(send), always detach. CDP flat sessions do not
    survive the WebSocket that created them, so attach per call."""
    tid = fn.__dict__.get("_tid")

def call(target_id, fn, wait=0.0):
    async def m():
        async with websockets.connect(_bws(), max_size=200*1024*1024) as ws:
            n = [0]
            async def s(method, params, sid=None):
                n[0] += 1
                msg = {"id": n[0], "method": method, "params": params}
                if sid: msg["sessionId"] = sid
                await ws.send(json.dumps(msg))
                while True:
                    r = json.loads(await asyncio.wait_for(ws.recv(), 40))
                    if r.get("id") == n[0]: return r
            a = (await s("Target.attachToTarget", {"targetId": target_id, "flatten": True}))["result"]["sessionId"]
            try:
                out = await fn(s, a)
            finally:
                await s("Target.detachFromTarget", {"sessionId": a})
            if wait: await asyncio.sleep(wait)
            return out
    return asyncio.run(m())

def ev(target_id, js):
    r = call(target_id, lambda s, a: s("Runtime.evaluate",
        {"expression": js, "returnByValue": True, "awaitPromise": True}, a))
    res = r.get("result", {})
    if "exceptionDetails" in res:
        return "EXC:" + json.dumps(res["exceptionDetails"], ensure_ascii=False)[:400]
    return res.get("result", {}).get("value")

def center(target_id, js_find):
    pos = ev(target_id, "(()=>{const el=(%s); if(!el) return null; const r=el.getBoundingClientRect();"
            " return JSON.stringify({x:r.left+r.width/2,y:r.top+r.height/2,w:r.width,h:r.height});})()" % js_find)
    return json.loads(pos) if pos else None

def click(target_id, js_find, wait=0.8):
    p = center(target_id, js_find)
    if not p: return "NOT_FOUND"
    if p["w"] == 0 or p["h"] == 0: return "ZERO:" + json.dumps(p)
    async def f(s, a):
        for t in ("mouseMoved", "mousePressed", "mouseReleased"):
            await s("Input.dispatchMouseEvent", dict({"type": t, "x": p["x"], "y": p["y"], "button": "left",
                "clickCount": 1 if t != "mouseMoved" else 0,
                "buttons": 1 if t == "mousePressed" else 0}, ), )
    # dispatchMouseEvent must carry the sessionId too
    async def g(s, a):
        base = {"x": p["x"], "y": p["y"], "button": "left", "clickCount": 1}
        await s("Input.dispatchMouseEvent", dict(base, type="mouseMoved", buttons=0))
        await asyncio.sleep(0.12)
        await s("Input.dispatchMouseEvent", dict(base, type="mousePressed", buttons=1))
        await asyncio.sleep(0.12)
        await s("Input.dispatchMouseEvent", dict(base, type="mouseReleased", buttons=0))
    call(target_id, g, wait=wait)
    return "CLICKED:" + json.dumps(p)

def typ(target_id, text, wait=0.4):
    r = call(target_id, lambda s, a: s("Input.insertText", {"text": text}), wait=wait)
    return r.get("result", {})

def key(target_id, k, mods=0, wait=0.5):
    KEYS = {"a": ("a", "KeyA", 65, "a"),
            "A": ("a", "KeyA", 65, None),
            "Backspace": ("Backspace", "Backspace", 8, None),
            "Enter": ("Enter", "Enter", 13, None)}
    kk, code, vk, text = KEYS[k]
    async def f(s, a):
        common = {"modifiers": mods, "key": kk, "code": code, "windowsVirtualKeyCode": vk}
        await s("Input.dispatchKeyEvent", dict(common, type="keyDown"))
        if text: await s("Input.dispatchKeyEvent", dict(common, type="char", text=text))
        await s("Input.dispatchKeyEvent", dict(common, type="keyUp"))
    call(target_id, f, wait=wait)
    return "KEY:" + k

def counter(target_id):
    v = ev(target_id, COUNTER_JS)
    return json.loads(v) if v and v.startswith("{") else v

def close_tab(target_id):
    async def m():
        async with websockets.connect(_bws(), max_size=200*1024*1024) as ws:
            await ws.send(json.dumps({"id": 1, "method": "Target.closeTarget", "params": {"targetId": target_id}}))
            await asyncio.sleep(0.5)
    asyncio.run(m())

def open_tab(url, wait=8):
    async def m():
        async with websockets.connect(_bws(), max_size=200*1024*1024) as ws:
            await ws.send(json.dumps({"id": 1, "method": "Target.createTarget", "params": {"url": url}}))
            r = json.loads(await asyncio.wait_for(ws.recv(), 40))
            await asyncio.sleep(wait)
            return r["result"]["targetId"]
    return asyncio.run(m())


def shot(target_id, path):
    import base64
    r = call(target_id, lambda s, a: s("Page.captureScreenshot", {"format": "png"}, a))
    d = r.get("result", {}).get("data")
    if not d:
        return "NO_DATA:" + json.dumps(r)[:200]
    open(path, "wb").write(base64.b64decode(d))
    return path


def activate(target_id):
    async def m():
        async with websockets.connect(_bws(), max_size=200*1024*1024) as ws:
            await ws.send(json.dumps({"id": 1, "method": "Target.activateTarget", "params": {"targetId": target_id}}))
            await asyncio.sleep(0.8)
    asyncio.run(m())
    return "ACTIVATED"
