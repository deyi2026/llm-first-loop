# -*- coding: utf-8 -*-
import asyncio, json, urllib.request, websockets
CDP = "http://127.0.0.1:9229"
def targets():
    d = json.load(urllib.request.urlopen(CDP + "/json"))
    return [t for t in d if t.get("type") == "page"]
async def main():
    ts = targets()
    for t in ts:
        u = t.get("url","")
        if "toutiao" in u or "zhihu" in u:
            print("TAB:", u[:100])
    tt = [t for t in ts if "toutiao" in t.get("url","")]
    if not tt:
        print("NO_TOUTIAO_TAB"); return
    ws = await websockets.connect(tt[0]["webSocketDebuggerUrl"], max_size=200*1024*1024)
    i=[0]
    async def ev(e):
        i[0]+=1
        await ws.send(json.dumps({"id":i[0],"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True,"awaitPromise":True}}))
        while True:
            m=json.loads(await ws.recv())
            if m.get("id")==i[0]: return m.get("result",{}).get("result",{}).get("value")
    print("URL:", await ev("location.href"))
    print("TITLE_TA:", await ev("(()=>{const t=document.querySelector('textarea[placeholder*=\"标题\"]'); return t?('found len='+t.value.length):'NONE';})()"))
    print("PM:", await ev("(()=>{const p=document.querySelector('.ProseMirror[contenteditable]'); return p?('found len='+(p.innerText||'').length):'NONE';})()"))
    print("BTNS:", await ev("JSON.stringify([...document.querySelectorAll('button')].map(b=>(b.innerText||'').trim()).filter(Boolean).slice(0,30))"))
    print("BODY:", (await ev("document.body.innerText") or "")[:300].replace("\n"," / "))
asyncio.run(main())
