# -*- coding: utf-8 -*-
import asyncio, json, urllib.request, websockets
CDP = "http://127.0.0.1:9229"
def pages():
    d = json.load(urllib.request.urlopen(CDP + "/json"))
    return [t for t in d if t.get("type") == "page" and "profile_v4/graphic/publish" in t.get("url","")]
async def main():
    t = pages()[0]
    async with websockets.connect(t["webSocketDebuggerUrl"], max_size=200*1024*1024) as ws:
        i=[0]
        async def ev(e):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True,"awaitPromise":True}}))
            while True:
                m=json.loads(await ws.recv())
                if m.get("id")==i[0]: return m.get("result",{}).get("result",{}).get("value")
        print("PM_IMGS:", await ev("document.querySelectorAll('.ProseMirror img').length"))
        print("ALL_IMGS:", await ev("document.querySelectorAll('img').length"))
        print("IMG_SRCS:", await ev("JSON.stringify([...document.querySelectorAll('img')].map(x=>x.src.slice(0,90)).slice(0,10))"))
        print("MODAL:", await ev("(()=>{const ms=document.querySelectorAll('.byte-dialog, [class*=dialog], [class*=modal], [class*=upload]'); return ms.length+' / '+[...ms].map(m=>(m.className+'').slice(0,50)).slice(0,6).join(' | ');})()"))
        print("PM_HTML_TAIL:", (await ev("document.querySelector('.ProseMirror').innerHTML.slice(-600)")))
        print("BODY_TAIL:", (await ev("document.body.innerText.slice(-400)")))
asyncio.run(main())
