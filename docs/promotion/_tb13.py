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
        print("TOOLBAR_HTML:", (await ev("(()=>{const b=document.querySelector('.syl-toolbar'); return b?b.outerHTML.slice(0,1500):'NONE';})()")))
        print()
        print("SVG_USES:", await ev("JSON.stringify([...document.querySelectorAll('.syl-toolbar use')].map(u=>(u.getAttribute('xlink:href')||u.getAttribute('href')||'')).slice(0,30))"))
asyncio.run(main())
