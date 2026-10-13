# -*- coding: utf-8 -*-
import asyncio, json, urllib.request, websockets
CDP = "http://127.0.0.1:9229"
async def main():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    pg=[t for t in d if t.get("type")=="page" and "profile_v4/graphic/publish" in t.get("url","")]
    if not pg: print("NO_PUBLISH_PAGE"); return
    t=pg[0]
    print("PAGE:",t["url"][:110])
    async with websockets.connect(t["webSocketDebuggerUrl"], max_size=200*1024*1024) as ws:
        i=[0]
        async def ev(e):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True,"awaitPromise":True}}))
            while True:
                m=json.loads(await ws.recv())
                if m.get("id")==i[0]: return m.get("result",{}).get("result",{}).get("value")
        print("TITLE_TA:", await ev("(()=>{const t=document.querySelector('textarea[placeholder*=\"标题\"]'); return t?('found'):'NONE';})()"))
        print("PM:", await ev("(()=>{const p=document.querySelector('.ProseMirror[contenteditable]'); return p?('found len='+(p.innerText||'').length):'NONE';})()"))
        print("BTNS:", await ev("JSON.stringify([...document.querySelectorAll('button')].map(b=>(b.innerText||'').trim()).filter(Boolean).slice(0,30))"))
        print("BODY:", (await ev("document.body.innerText") or "")[:400].replace("\n"," / "))
asyncio.run(main())
