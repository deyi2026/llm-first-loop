# -*- coding: utf-8 -*-
"""点『本地上传』再 setFileInputFiles。"""
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
        print("CLICK_LOCAL:", await ev("""(()=>{const b=[...document.querySelectorAll('.upload-image-panel *')].find(x=>(x.innerText||'').trim()==='本地上传'&&x.offsetParent!==null);
          if(!b) return 'NOT_FOUND'; b.click(); return 'CLICKED';})()"""))
        await asyncio.sleep(3)
        print("INPUT_NOW:", await ev("""(()=>{const fs=document.querySelectorAll('input[type=file]'); return [...fs].map(f=>(f.accept||'')).join(' ; ');})()"""))
        doc = await cmd("DOM.getDocument")
        # 取最后一个 file input（面板内）
        n = await ev("document.querySelectorAll('input[type=file]').length")
        print("N_INPUTS:", n)
        # 用 DOM.querySelectorAll 找最后一个
        qa = await cmd("DOM.querySelectorAll", {"nodeId": doc["root"]["nodeId"], "selector": "input[type=file]"})
        ids = qa.get("nodeIds",[])
        print("IDS:", ids)
        if not ids: return
        nid = ids[-1]
        for p in ["img/fig39-heartbeat-protocol.png", "img/fig40-heartbeat-cost.png"]:
            ap = os.path.abspath(os.path.join(HERE, p))
            r = await cmd("DOM.setFileInputFiles", {"nodeId": nid, "files": [ap]})
            print("SET:", os.path.basename(ap), r.get("error") or "ok")
            await asyncio.sleep(9)
            print("  imgs:", await ev("document.querySelectorAll('.ProseMirror img').length"))
            print("  uploaded_txt:", await ev("(()=>{const p=document.querySelector('.upload-image-panel'); const m=(p&&p.innerText||'').match(/已上传\\s*(\\d+)\\s*张/); return m?m[1]:'?';})()"))
asyncio.run(main())
