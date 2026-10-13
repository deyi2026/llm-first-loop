# -*- coding: utf-8 -*-
"""重试上传：列出 upload-image-panel 内所有 file input，逐个尝试。"""
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
        print("PANEL_INPUTS:", await ev("""(()=>{const p=document.querySelector('.upload-image-panel'); if(!p) return 'NO_PANEL';
          const fs=p.querySelectorAll('input[type=file]');
          return fs.length+' -> '+[...fs].map(f=>(f.accept||'')+'|'+(f.multiple?'multi':'single')).join(' ; ');})()"""))
        print("PANEL_VISIBLE:", await ev("""(()=>{const p=document.querySelector('.upload-image-panel'); if(!p) return 'NO';
          return (p.offsetParent!==null)+' disp='+getComputedStyle(p).display;})()"""))
        print("BTN_LOCAL:", await ev("JSON.stringify([...document.querySelectorAll('.upload-image-panel button, .upload-image-panel [class*=btn]')].map(b=>(b.innerText||'').trim()).slice(0,15))"))
asyncio.run(main())
