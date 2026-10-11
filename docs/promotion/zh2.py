# -*- coding: utf-8 -*-
"""知乎编辑器助手：page-level CDP（已验证可收输入事件）。"""
import json, asyncio, websockets, urllib.request
CDP = "http://127.0.0.1:9229"

def pages():
    return [t for t in json.load(urllib.request.urlopen(CDP + "/json")) if t.get("type") == "page"]

def pick(sub, idx=0):
    ts = [t for t in pages() if sub in t.get("url", "")]
    if not ts:
        raise SystemExit("NO_TAB:" + sub)
    return ts[idx]

def _one(ws_url, fn, wait=0.0):
    async def m():
        async with websockets.connect(ws_url, max_size=200*1024*1024) as ws:
            n = [0]
            async def s(method, params):
                n[0] += 1
                await ws.send(json.dumps({"id": n[0], "method": method, "params": params}))
                while True:
                    r = json.loads(await asyncio.wait_for(ws.recv(), 40))
                    if r.get("id") == n[0]: return r
            out = await fn(s)
            if wait: await asyncio.sleep(wait)
            return out
    return asyncio.run(m())

def ev(tab, js):
    r = _one(tab["webSocketDebuggerUrl"], lambda s: s("Runtime.evaluate",
        {"expression": js, "returnByValue": True, "awaitPromise": True}))
    res = r.get("result", {})
    if "exceptionDetails" in res:
        return "EXC:" + json.dumps(res["exceptionDetails"], ensure_ascii=False)[:400]
    return res.get("result", {}).get("value")

def activate(tab):
    _one(tab["webSocketDebuggerUrl"], lambda s: s("Page.bringToFront", {}), wait=0.8)
    return "FRONT"

def click(tab, js_find, wait=0.8):
    pos = ev(tab, "(()=>{const el=(%s); if(!el) return null; const r=el.getBoundingClientRect();"
            " return JSON.stringify({x:r.left+r.width/2,y:r.top+r.height/2,w:r.width,h:r.height});})()" % js_find)
    if not pos: return "NOT_FOUND"
    p = json.loads(pos)
    if p["w"] == 0 or p["h"] == 0: return "ZERO:" + json.dumps(p)
    async def f(s):
        base = {"x": p["x"], "y": p["y"], "button": "left", "clickCount": 1}
        await s("Input.dispatchMouseEvent", dict(base, type="mouseMoved", buttons=0))
        await asyncio.sleep(0.12)
        await s("Input.dispatchMouseEvent", dict(base, type="mousePressed", buttons=1))
        await asyncio.sleep(0.12)
        await s("Input.dispatchMouseEvent", dict(base, type="mouseReleased", buttons=0))
    _one(tab["webSocketDebuggerUrl"], f, wait=wait)
    return "CLICKED:" + json.dumps(p)

def typ(tab, text, wait=0.5):
    r = _one(tab["webSocketDebuggerUrl"],
             lambda s: s("Input.insertText", {"text": text}), wait=wait)
    return r.get("result", {})

def key(tab, k, mods=0, wait=0.5):
    KEYS = {"a": ("a", "KeyA", 65, "a"), "A": ("a", "KeyA", 65, None),
            "V": ("v", "KeyV", 86, "v"),
            "Backspace": ("Backspace", "Backspace", 8, None)}
    kk, code, vk, text = KEYS[k]
    async def f(s):
        c = {"modifiers": mods, "key": kk, "code": code, "windowsVirtualKeyCode": vk}
        await s("Input.dispatchKeyEvent", dict(c, type="keyDown"))
        if text: await s("Input.dispatchKeyEvent", dict(c, type="char", text=text))
        await s("Input.dispatchKeyEvent", dict(c, type="keyUp"))
    _one(tab["webSocketDebuggerUrl"], f, wait=wait)
    return "KEY:" + k

def shot(tab, path):
    import base64
    r = _one(tab["webSocketDebuggerUrl"], lambda s: s("Page.captureScreenshot", {"format": "png"}))
    d = r.get("result", {}).get("data")
    if not d: return "NO_DATA"
    open(path, "wb").write(base64.b64decode(d))
    return path

COUNTER_JS = r"""(()=>{const ed=document.querySelector('.public-DraftEditor-content');
 const t=(ed&&ed.innerText)||'';
 return JSON.stringify({len:t.replace(/\s/g,'').length, lines:t.split('\n').filter(x=>x.trim()).length,
  imgs:document.querySelectorAll('.public-DraftEditor-content img').length,
  counter:(document.body.innerText.match(/字数[：: ]*\d+/)||[null])[0],
  head:t.replace(/\s+/g,' ').slice(0,80)});})()"""

def counter(tab):
    v = ev(tab, COUNTER_JS)
    return json.loads(v) if v and v.startswith("{") else v


def set_file(tab, selector, files):
    async def f(s):
        d = await s("DOM.getDocument", {"depth": 0})
        root = d["result"]["root"]["nodeId"]
        q = await s("DOM.querySelector", {"nodeId": root, "selector": selector})
        nid = q["result"]["nodeId"]
        if not nid:
            return "NODE_NOT_FOUND"
        return await s("DOM.setFileInputFiles", {"nodeId": nid, "files": files})
    r = _one(tab["webSocketDebuggerUrl"], f, wait=2.5)
    return json.dumps(r.get("result", {}), ensure_ascii=False)[:300]


def set_file2(tab, js_find, files):
    async def f(s):
        ev = await s("Runtime.evaluate", {"expression": "(%s)" % js_find, "returnByValue": False})
        oid = ev.get("result", {}).get("result", {}).get("objectId")
        if not oid:
            return "NO_OBJECT:" + json.dumps(ev)[:200]
        r = await s("DOM.setFileInputFiles", {"objectId": oid, "files": files})
        chk = await s("Runtime.evaluate", {"expression": "(%s).files.length" % js_find, "returnByValue": True})
        return {"set": r.get("result"), "filesLen": chk.get("result", {}).get("result", {}).get("value")}
    r = _one(tab["webSocketDebuggerUrl"], f, wait=3.0)
    return json.dumps(r, ensure_ascii=False)[:400]


def type_keys(tab, text, per_char_wait=0.0, wait=0.6):
    """Type char-by-char through the real key pipeline (each char as a 'char' key event).
    Unlike Input.insertText (a paste), this fires the editor's own input rules."""
    async def f(s):
        for chx in text:
            await s("Input.dispatchKeyEvent", {"type": "char", "text": chx, "key": chx, "modifiers": 0})
    _one(tab["webSocketDebuggerUrl"], f, wait=wait)
    return "TYPED:" + str(len(text))


def type_md(tab, text, wait=0.8):
    """Type char-by-char (markdown rules fire); newline -> real Enter key event."""
    async def f(s):
        for i, seg in enumerate(text.split("\n")):
            if i:
                for t in ("keyDown", "keyUp"):
                    await s("Input.dispatchKeyEvent", {"type": t, "key": "Enter", "code": "Enter",
                                                       "windowsVirtualKeyCode": 13, "modifiers": 0})
            for chx in seg:
                await s("Input.dispatchKeyEvent", {"type": "char", "text": chx, "key": chx, "modifiers": 0})
    _one(tab["webSocketDebuggerUrl"], f, wait=wait)
    return "TYPED:%d" % len(text)


def grant_clipboard(tab):
    async def f(s):
        return await s("Browser.grantPermissions", {
            "origin": "https://zhuanlan.zhihu.com",
            "permissions": ["clipboardReadWrite", "clipboardSanitizedWrite"]})
    return json.dumps(_one(tab["webSocketDebuggerUrl"], f, wait=0.5))[:200]


def cmd_key(tab, key, code, vk, commands, wait=1.5):
    """Key event carrying an editor command (selectAll / paste / copy / cut)."""
    async def f(s):
        c = {"modifiers": 4, "key": key, "code": code, "windowsVirtualKeyCode": vk,
             "commands": commands, "nativeVirtualKeyCode": vk}
        await s("Input.dispatchKeyEvent", dict(c, type="rawKeyDown"))
        await s("Input.dispatchKeyEvent", dict(c, type="keyUp"))
    _one(tab["webSocketDebuggerUrl"], f, wait=wait)
    return "CMD:" + ",".join(commands)


def upload_image(tab, files, sel="[...document.querySelectorAll('input[type=file]')].filter(x=>x.accept.includes('image')).pop()", wait=6.0):
    """setFileInputFiles + change dispatch inside ONE cdp session (files do not survive a reconnect)."""
    async def f(s):
        ev = await s("Runtime.evaluate", {"expression": "(%s)" % sel, "returnByValue": False})
        oid = ev.get("result", {}).get("result", {}).get("objectId")
        if not oid:
            return {"err": "no_input", "raw": ev}
        st = await s("DOM.setFileInputFiles", {"objectId": oid, "files": files})
        n = await s("Runtime.callFunctionOn", {"objectId": oid, "functionDeclaration":
            "function(){var n=this.files.length;"
            "this.dispatchEvent(new Event('input',{bubbles:true}));"
            "this.dispatchEvent(new Event('change',{bubbles:true}));"
            "return n;}", "returnByValue": True})
        return {"set": st.get("result"), "filesLen": n.get("result", {}).get("result", {}).get("value")}
    return json.dumps(_one(tab["webSocketDebuggerUrl"], f, wait=wait), ensure_ascii=False)[:300]


def vk(tab, key, code, vkc, mods=0, wait=0.5):
    async def f(s):
        c = {"modifiers": mods, "key": key, "code": code, "windowsVirtualKeyCode": vkc}
        await s("Input.dispatchKeyEvent", dict(c, type="rawKeyDown"))
        await s("Input.dispatchKeyEvent", dict(c, type="keyUp"))
    _one(tab["webSocketDebuggerUrl"], f, wait=wait)
    return "VK:" + key
