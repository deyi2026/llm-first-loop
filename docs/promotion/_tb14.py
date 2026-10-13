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
        # 打印 toolbar 按钮容器类名序列
        print("TOOLS:", await ev("JSON.stringify([...document.querySelectorAll('.syl-toolbar-tool')].map(x=>x.className.replace('syl-toolbar-tool','').trim()))"))
        # 每个按钮的 aria-label / title / parent class
        print("BTN_META:", await ev("""JSON.stringify([...document.querySelectorAll('.syl-toolbar-button')].map(b=>{
            const par=b.closest('.syl-toolbar-tool'); return par?par.className.replace('syl-toolbar-tool','').trim():'?';}))"""))
asyncio.run(main())
