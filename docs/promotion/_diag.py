import asyncio, json, urllib.request, websockets
CDP="http://127.0.0.1:9229"
d=json.load(urllib.request.urlopen(CDP+"/json"))
pg=[t for t in d if t.get("type")=="page"]
for t in pg: print("TAB:", t["url"][:95])
zt=[t for t in pg if "zhuanlan" in t.get("url","")]
if not zt: raise SystemExit("NO ZHIHU TAB")
async def main():
    t=zt[0]
    async with websockets.connect(t["webSocketDebuggerUrl"],max_size=200*1024*1024) as ws:
        i=[0]
        async def raw(e):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True}}))
            while True:
                m=json.loads(await ws.recv())
                if m.get("id")==i[0]: return json.dumps(m)[:400]
        print("RAW1:", await raw("location.href"))
        print("RAW2:", await raw("document.querySelectorAll('[contenteditable]').length"))
asyncio.run(main())
