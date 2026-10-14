import asyncio, json, base64, urllib.request, websockets
CDP="http://127.0.0.1:9229"
def page(sub):
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    for t in d:
        if t.get("type")=="page" and sub in t.get("url",""): return t
async def main():
    pg=page("zhihu.com")
    async with websockets.connect(pg["webSocketDebuggerUrl"],max_size=400*1024*1024) as ws:
        i=[0]
        async def cmd(m,p=None):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":m,"params":p or {}}))
            while True:
                r=json.loads(await asyncio.wait_for(ws.recv(),60))
                if r.get("id")==i[0]: return r.get("result",{})
        async def ev(e):
            r=await cmd("Runtime.evaluate",{"expression":e,"returnByValue":True,"awaitPromise":True})
            if "exceptionDetails" in r: return "ERR"
            return r.get("result",{}).get("value")
        await cmd("Page.bringToFront",{})
        for _ in range(9):
            await cmd("Input.dispatchKeyEvent",{"type":"keyDown","key":"Backspace","code":"Backspace","windowsVirtualKeyCode":8})
            await cmd("Input.dispatchKeyEvent",{"type":"keyUp","key":"Backspace","code":"Backspace","windowsVirtualKeyCode":8})
        await asyncio.sleep(0.5)
        await cmd("Input.insertText",{"text":"人工智能"}); await asyncio.sleep(4.5)
        s=await cmd("Page.captureScreenshot",{"format":"png"})
        if "data" in s: open("/tmp/d14_tag2.png","wb").write(base64.b64decode(s["data"]))
        print("SHOT ok")
asyncio.run(main())
