# -*- coding: utf-8 -*-
import asyncio, json, urllib.request, websockets
CDP = "http://127.0.0.1:9229"
async def main():
    ws_b = json.load(urllib.request.urlopen(CDP + "/json/version"))["webSocketDebuggerUrl"]
    async with websockets.connect(ws_b, max_size=200*1024*1024) as ws:
        await ws.send(json.dumps({"id":1,"method":"Target.createTarget","params":{"url":"https://mp.toutiao.com/profile_v4/graphic/publish?from=toutiao_pc"}}))
        r=json.loads(await asyncio.wait_for(ws.recv(),30))
        tid=r["result"]["targetId"]
        print("NEW_TAB:",tid)
        await asyncio.sleep(12)
        d=json.load(urllib.request.urlopen(CDP+"/json"))
        for t in d:
            if t.get("type")=="page" and "toutiao" in t.get("url",""):
                print("PAGE:",t["url"][:110])
        json.dump({"tid":tid}, open("_tt_tid.json","w"))
asyncio.run(main())
