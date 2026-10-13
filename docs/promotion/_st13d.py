# -*- coding: utf-8 -*-
import asyncio, json, urllib.request, websockets
CDP = "http://127.0.0.1:9229"
def pages():
    d = json.load(urllib.request.urlopen(CDP + "/json"))
    return [t for t in d if t.get("type")=="page" and "profile_v4/graphic/publish" in t.get("url","")]
async def main():
    pg = pages()
    if not pg:
        print("NO_PAGE"); return
    t = pg[0]
    async with websockets.connect(t["webSocketDebuggerUrl"], max_size=200*1024*1024) as ws:
        i=[0]
        async def ev(e):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True,"awaitPromise":True}}))
            while True:
                m=json.loads(await ws.recv())
                if m.get("id")==i[0]:
                    r=m.get("result",{})
                    if "exceptionDetails" in r: return "ERR:"+str(r["exceptionDetails"].get("text"))
                    return r.get("result",{}).get("value")
        print("TITLE_INPUT:", await ev("""(()=>{const ta=document.querySelector('textarea[placeholder*="标题"]'); return ta? ta.value.length+'|'+ta.value.slice(0,60):'NONE';})()"""))
        print("EDITOR_LEN:", await ev("""(()=>{const d=document.querySelector('.ProseMirror'); return d? d.innerText.length : 'NONE';})()"""))
        print("EDITOR_HEAD:", await ev("""(()=>{const d=document.querySelector('.ProseMirror'); return d? d.innerText.slice(0,120).replace(/\\n/g,' / ') : 'NONE';})()"""))
        print("IMGS:", await ev("""(()=>{const d=document.querySelector('.ProseMirror'); if(!d) return 'NONE';
          const im=[...d.querySelectorAll('img')]; return im.length+' -> '+im.map(i=>(i.src||'').slice(0,90)).join(' ;; ');})()"""))
        print("PANEL:", await ev("""(()=>{const p=document.querySelector('.upload-image-panel'); if(!p) return 'NO_PANEL';
          const fs=p.querySelectorAll('input[type=file]');
          return fs.length+' files; vis='+(p.offsetParent!==null);})()"""))
        print("BTNS:", await ev("""JSON.stringify([...document.querySelectorAll('button')].map(b=>(b.innerText||'').trim()).filter(Boolean).slice(0,25))"""))
asyncio.run(main())
