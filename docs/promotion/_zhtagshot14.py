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
        await cmd("Page.bringToFront",{}); await asyncio.sleep(1)
        s=await cmd("Page.captureScreenshot",{"format":"png"})
        if "data" in s:
            open("/tmp/d14_tag.png","wb").write(base64.b64decode(s["data"])); print("SHOT ok")
asyncio.run(main())
