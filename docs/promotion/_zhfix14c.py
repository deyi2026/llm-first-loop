import asyncio, json, base64, os, urllib.request, websockets
CDP="http://127.0.0.1:9229"
def page(sub):
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    for t in d:
        if t.get("type")=="page" and sub in t.get("url",""): return t
STATE=r"""(()=>{const ed=document.querySelector('.public-DraftEditor-content');
 const bl=[...ed.querySelectorAll('[data-block=true]')]; const im=[...ed.querySelectorAll('img')];
 const idxs=[]; bl.forEach(function(d,n){ if(d.querySelector('img')) idxs.push(n); });
 return JSON.stringify({blocks:bl.length, imgs:im.length, figs:bl.filter(function(d){return d.tagName==='FIGURE';}).length,
  pos:idxs.map(function(n){var p=bl[n].previousElementSibling,q=bl[n].nextElementSibling;
   return n+' before:'+(p?(p.innerText||'').replace(/\s+/g,' ').slice(-12):'-')+' after:'+(q?(q.innerText||'').replace(/\s+/g,' ').slice(0,12):'-');})});})()"""
FIGRECT=r"""(()=>{const ed=document.querySelector('.public-DraftEditor-content');
 const figs=[...ed.querySelectorAll('figure,[data-block=true]')].filter(function(d){return d.tagName==='FIGURE'&&d.querySelector('img');});
 const f=figs[0]; if(!f) return 'NO_FIG';
 f.scrollIntoView({block:'center'});
 const r=f.getBoundingClientRect();
 return JSON.stringify({x:Math.round(r.left+r.width/2),y:Math.round(r.top+6),n:figs.length});})()"""
EMPTYFIG=r"""(()=>{const ed=document.querySelector('.public-DraftEditor-content');const A=%s;
 const bl=[...ed.querySelectorAll('[data-block=true]')];
 const hi=bl.findIndex(function(d){return d.tagName==='H2'&&(d.innerText||'').trim().startsWith(A);});
 if(hi<1) return 'NO_H2';
 const cand=bl[hi-1];
 const hasText=(cand.innerText||'').trim().length>0;
 if(hasText) return 'PREV_NOT_EMPTY:'+((cand.innerText||'').trim().slice(0,12));
 if(cand.querySelector('img')) return 'PREV_HAS_IMG';
 cand.scrollIntoView({block:'center'});
 const r=cand.getBoundingClientRect();
 return JSON.stringify({x:Math.round(r.left+8),y:Math.round(r.top+Math.min(r.height/2,6)),h:Math.round(r.height)});})()"""
FPASTE=r"""(()=>{const bin=atob(%s); const arr=new Uint8Array(bin.length);
 for(let i=0;i<bin.length;i++) arr[i]=bin.charCodeAt(i);
 const tgt=document.activeElement||document.querySelector('.public-DraftEditor-content');
 const dt=new DataTransfer(); dt.items.add(new File([arr],%s,{type:'image/png'}));
 tgt.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}));
 return 'DISPATCH';})()"""
async def main():
    pg=page("zhuanlan.zhihu.com")
    async with websockets.connect(pg["webSocketDebuggerUrl"],max_size=400*1024*1024) as ws:
        i=[0]
        async def s(m,p=None):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":m,"params":p or {}}))
            while True:
                r=json.loads(await asyncio.wait_for(ws.recv(),90))
                if r.get("id")==i[0]: return r.get("result",{})
        async def ev(e):
            r=await s("Runtime.evaluate",{"expression":e,"returnByValue":True,"awaitPromise":True})
            if "exceptionDetails" in r: return "ERR:"+json.dumps(r["exceptionDetails"],ensure_ascii=False)[:200]
            return r.get("result",{}).get("value")
        async def key(k,vk,mod=0):
            b={"key":k,"code":k,"windowsVirtualKeyCode":vk,"nativeVirtualKeyCode":vk,"modifiers":mod}
            await s("Input.dispatchKeyEvent",dict(b,type="keyDown")); await asyncio.sleep(0.08)
            await s("Input.dispatchKeyEvent",dict(b,type="keyUp"))
        async def click(x,y):
            b={"x":x,"y":y,"button":"left","clickCount":1}
            await s("Input.dispatchMouseEvent",dict(b,type="mouseMoved",buttons=0)); await asyncio.sleep(0.2)
            await s("Input.dispatchMouseEvent",dict(b,type="mousePressed",buttons=1)); await asyncio.sleep(0.12)
            await s("Input.dispatchMouseEvent",dict(b,type="mouseReleased",buttons=0)); await asyncio.sleep(0.9)
        await s("Page.bringToFront",{}); await asyncio.sleep(0.4)
        print("START:", await ev(STATE))
        for k in range(4):
            fr=await ev(FIGRECT)
            print("FIGRECT", fr)
            if not fr.startswith("{"): break
            z=json.loads(fr); await click(z["x"],z["y"]); await asyncio.sleep(1.0)
            await key("Backspace",8); await asyncio.sleep(2.0)
            st=await ev(STATE); print("  after del:", st)
            if json.loads(st)["imgs"]==0: break
        print("AFTER_DEL:", await ev(STATE))
        for anchor,img in [("四、它敢让自己改自己","img/fig41-power-split.png"),
                            ("五、诚实的边界：92.1% 后面的那个括弧","img/fig42-evolution-locks.png")]:
            e=await ev(EMPTYFIG % json.dumps(anchor,ensure_ascii=False)); print("EMPTYFIG", anchor[:8], e)
            if e.startswith("{"):
                z=json.loads(e); await click(z["x"],z["y"]); await asyncio.sleep(0.8)
                b64=base64.b64encode(open(img,"rb").read()).decode()
                print("  PASTE:", await ev(FPASTE % (json.dumps(b64), json.dumps(os.path.basename(img)))))
                await asyncio.sleep(12)
        print("FINAL:", await ev(STATE))
asyncio.run(main())
