import _cdp2, pickle, json, asyncio, websockets
tid = pickle.load(open('_tab.pkl','rb'))
async def main():
    async with websockets.connect(_cdp2.browser_ws(), max_size=200*1024*1024) as ws:
        n=[0]
        async def send(method, params, sid=None):
            n[0]+=1; msg={"id":n[0],"method":method,"params":params}
            if sid: msg["sessionId"]=sid
            await ws.send(json.dumps(msg))
            while True:
                m=json.loads(await asyncio.wait_for(ws.recv(),30))
                if m.get("id")==n[0]: return m
        a=await send("Target.attachToTarget",{"targetId":tid,"flatten":True})
        print("ATTACH:", json.dumps(a)[:400])
        sid=a["result"]["sessionId"]
        print("EVAL:", json.dumps(await send("Runtime.evaluate",{"expression":"location.href","returnByValue":True},sid))[:600])
asyncio.run(main())
