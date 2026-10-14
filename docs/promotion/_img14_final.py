import asyncio, json, os, urllib.request, websockets
CDP="http://127.0.0.1:9229"
def tg():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    return [t for t in d if t.get("type")=="page" and "profile_v4/graphic/publish" in t.get("url","")]
async def main():
    t=tg()[0]
    async with websockets.connect(t["webSocketDebuggerUrl"],max_size=200*1024*1024) as ws:
        i=[0]
        async def cmd(method,params=None):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":method,"params":params or {}}))
            while True:
                m=json.loads(await ws.recv())
                if m.get("id")==i[0]:
                    if "error" in m: return {"ERR":m["error"]}
                    return m.get("result",{})
        async def ev(e):
            r=await cmd("Runtime.evaluate",{"expression":e,"returnByValue":True,"awaitPromise":True})
            if "ERR" in r: return "CDPERR:"+str(r["ERR"])
            if "exceptionDetails" in r: return "ERR:"+str(r["exceptionDetails"].get("text"))
            return r.get("result",{}).get("value")
        async def close_dlg():
            r=await ev("""(()=>{for(const b of document.querySelectorAll('button')){if(b.textContent.trim()==='取消'){b.click(); return 'CANCELLED';}}
              return 'NONE';})()""")
            if r!='NONE': await asyncio.sleep(2)
            return r
        async def set_sel(pat):
            return await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
              const hit=[...pm.querySelectorAll('p,li')].find(n=>new RegExp(%s).test((n.innerText||'').trim()));
              if(!hit) return 'NO_PARA';
              hit.scrollIntoView({block:'center'});
              const r=document.createRange(); r.selectNodeContents(hit); r.collapse(false);
              const s=window.getSelection(); s.removeAllRanges(); s.addRange(r);
              return JSON.stringify({at:(hit.innerText||'').slice(-18), sel:(s.anchorNode.textContent||'').slice(-18), off:s.anchorOffset});})()"""
              % json.dumps(pat))
        async def insert(pat,img):
            print("---", img)
            print("CLOSED:", await close_dlg())
            print("SEL:", await set_sel(pat))
            print("OPEN:", await ev("""(()=>{const b=document.querySelector('.syl-toolbar-tool.image .syl-toolbar-button');
              if(!b) return 'NO_BTN'; b.click(); return 'CLICKED';})()"""))
            await asyncio.sleep(3)
            doc=await cmd("DOM.getDocument")
            q=await cmd("DOM.querySelector",{"nodeId":doc["root"]["nodeId"],"selector":".btn-upload-handle input[type=file]"})
            nid=q.get("nodeId")
            if not nid: print("NO_FILE_INPUT"); return
            print("SET:", await cmd("DOM.setFileInputFiles",{"nodeId":nid,"files":[os.path.abspath(img)]}))
            ok=False
            for w in range(4,26,3):
                await asyncio.sleep(3)
                st=await ev("""(()=>{const t=document.body.innerText; const m=t.match(/已上传\\s*(\\d+)\\s*张/);
                  const f=(t.match(/上传失败/g)||[]).length;
                  const c=[...document.querySelectorAll('button')].filter(b=>b.textContent.trim()==='确定').map(b=>b.disabled?'D':'E');
                  return JSON.stringify({up:m?m[1]:null, fail:f, ok:c});})()""")
                print(f"  T+{w}:", st)
                if st and '"fail":0' in st and '"E"' in st and '"up":"1"' in st: ok=True; break
            if not ok: print("UPLOAD_NOT_READY"); return
            print("CONFIRM:", await ev("""(()=>{for(const b of document.querySelectorAll('button')){if(b.textContent.trim()==='确定'){b.click(); return 'CLICKED';}} return 'NO';})()"""))
            await asyncio.sleep(6)
            print("AFTER:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
              const blocks=[...pm.children]; const idxs=blocks.map((n,k)=>((n.querySelector&&n.querySelector('img'))?k:-1)).filter(k=>k>=0);
              const im=[...pm.querySelectorAll('img')];
              const wc=document.body.innerText.match(/共\\s*(\\d+)\\s*字/);
              return JSON.stringify({imgs:im.length, dims:im.map(x=>x.naturalWidth+'x'+x.naturalHeight), words:wc?wc[1]:null,
                neighbors:idxs.map(k=>({before:(blocks[k].previousElementSibling&&blocks[k].previousElementSibling.innerText||'').slice(-20),
                  after:(blocks[k].nextElementSibling&&blocks[k].nextElementSibling.innerText||'').slice(0,20)}))});})()"""))
        print("IMGS_START:", await ev("""document.querySelectorAll('.ProseMirror img').length"""))
        await insert(r"^人工审批流与审计", "img/fig41-power-split.png")
        await insert(r"^第 3 条是关键", "img/fig42-evolution-locks.png")
        await close_dlg()
asyncio.run(main())
