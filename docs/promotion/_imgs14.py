# -*- coding: utf-8 -*-
import asyncio, json, os, urllib.request, websockets
CDP = "http://127.0.0.1:9229"
HERE = os.path.dirname(os.path.abspath("."))
def pages():
    d = json.load(urllib.request.urlopen(CDP + "/json"))
    return [t for t in d if t.get("type") == "page" and "profile_v4/graphic/publish" in t.get("url","")]
async def main():
    t = pages()[0]
    async with websockets.connect(t["webSocketDebuggerUrl"], max_size=200*1024*1024) as ws:
        i=[0]
        async def cmd(method, params=None):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":method,"params":params or {}}))
            while True:
                m=json.loads(await ws.recv())
                if m.get("id")==i[0]:
                    if "error" in m: raise RuntimeError(method+" "+str(m["error"]))
                    return m.get("result",{})
        async def ev(e):
            r = await cmd("Runtime.evaluate", {"expression":e,"returnByValue":True,"awaitPromise":True})
            if "exceptionDetails" in r: return "ERR:"+str(r["exceptionDetails"].get("text"))
            return r.get("result",{}).get("value")
        print("IMGS_BEFORE:", await ev("document.querySelectorAll('.ProseMirror img').length"))
        print("CLICK:", await ev("(()=>{const b=[...document.querySelectorAll('.syl-toolbar-button')].find(x=>x.closest('.syl-toolbar-tool').className.includes('image')); if(b){b.click(); return 'CLICKED';} return 'NOT_FOUND';})()"))
        await asyncio.sleep(3)
        print("INPUT:", await ev("(()=>{const f=document.querySelector('input[type=file]'); return f?('FOUND accept='+(f.accept||'')):'MISSING';})()"))
        doc = await cmd("DOM.getDocument")
        q = await cmd("DOM.querySelector", {"nodeId": doc["root"]["nodeId"], "selector": "input[type=file]"})
        nid = q.get("nodeId"); print("NODE:", nid)
        if not nid: return
        for p in ["img/fig39-heartbeat-protocol.png", "img/fig40-heartbeat-cost.png"]:
            ap = os.path.abspath(os.path.join(HERE, p))
            r = await cmd("DOM.setFileInputFiles", {"nodeId": nid, "files": [ap]})
            print("SET:", os.path.basename(ap), r.get("error") or "ok")
            await asyncio.sleep(7)
            print("  imgs_now:", await ev("document.querySelectorAll('.ProseMirror img').length"))
asyncio.run(main())
