import asyncio, json, urllib.request, websockets
CDP="http://127.0.0.1:9229"
def tg():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    return [t for t in d if t.get("type")=="page" and "profile_v4/graphic/publish" in t.get("url","")]
async def main():
    t=tg()[0]
    async with websockets.connect(t["webSocketDebuggerUrl"],max_size=200*1024*1024) as ws:
        i=[0]
        async def ev(e):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True,"awaitPromise":True}}))
            while True:
                m=json.loads(await ws.recv())
                if m.get("id")==i[0]:
                    if "exceptionDetails" in m.get("result",{}): return "ERR:"+str(m["result"]["exceptionDetails"].get("text"))
                    return m.get("result",{}).get("result",{}).get("value")
        print("STATE:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const dlgs=[...document.querySelectorAll('[role=dialog],.syl-dialog,.byte-modal__content')].map(d=>d.innerText.slice(0,40));
          return JSON.stringify({imgs:pm?pm.querySelectorAll('img').length:-1,
            allImgs:document.querySelectorAll('img').length,
            fileInputs:document.querySelectorAll('input[type=file]').length,
            dialogs:dlgs, bodyHas:document.body.innerText.slice(0,60)});})()"""))
asyncio.run(main())
