import asyncio, base64, json, urllib.request, websockets
CDP="http://127.0.0.1:9229"
def zt():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    return [t for t in d if t.get("type")=="page" and "/edit" in t.get("url","")]
async def main():
    t=zt()[0]
    async with websockets.connect(t["webSocketDebuggerUrl"],max_size=200*1024*1024) as ws:
        i=[0]
        async def cmd(m,p=None):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":m,"params":p or {}}))
            while True:
                r=json.loads(await ws.recv())
                if r.get("id")==i[0]: return r.get("result",{})
        r=await cmd("Page.captureScreenshot",{"format":"png"})
        open("_zhshot.png","wb").write(base64.b64decode(r["data"]))
        print("saved _zhshot.png")
asyncio.run(main())
