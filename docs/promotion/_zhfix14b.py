import asyncio, json, base64, os, urllib.request, websockets
CDP="http://127.0.0.1:9229"
def page(sub):
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    for t in d:
        if t.get("type")=="page" and sub in t.get("url",""): return t
STATE=r"""(()=>{const ed=document.querySelector('.public-DraftEditor-content');
 if(!ed) return 'NO_ED';
 const bl=[...ed.querySelectorAll('[data-block=true]')];
 const im=[...ed.querySelectorAll('img')];
 const idxs=[]; bl.forEach((d,n)=>{ if(d.querySelector('img')) idxs.push(n); });
 return JSON.stringify({blocks:bl.length, imgs:im.length, loaded:im.filter(x=>x.naturalWidth>0).length,
  dims:im.map(x=>x.naturalWidth+'x'+x.naturalHeight),
  pos:idxs.map(function(n){ var p=bl[n].previousElementSibling, q=bl[n].nextElementSibling;
    return n+' | before:'+(p?(p.innerText||'').replace(/\s+/g,' ').slice(-14):'-')+' | after:'+(q?(q.innerText||'').replace(/\s+/g,' ').slice(0,14):'-'); }),
  tail:bl.slice(-2).map(function(d){return d.tagName+':'+(d.innerText||'').replace(/\s+/g,' ').slice(0,14);})});})()"""
PARAEND=r"""(()=>{const ed=document.querySelector('.public-DraftEditor-content');const A=%s;
 const bl=[...ed.querySelectorAll('[data-block=true]')];
 const hi=bl.findIndex(function(d){return d.tagName==='H2'&&(d.innerText||'').trim().startsWith(A);});
 if(hi<1) return 'NO_H2';
 const prev=bl[hi-1]; prev.scrollIntoView({block:'center'});
 const w=document.createTreeWalker(prev,NodeFilter.SHOW_TEXT); let last=null;
 while(w.nextNode()){ if(w.currentNode.textContent&&w.currentNode.textContent.length) last=w.currentNode; }
 if(!last) return 'NO_TEXT';
 const rg=document.createRange(); rg.selectNodeContents(last);
 const rects=rg.getClientRects(); const rr=rects.length?rects[rects.length-1]:rg.getBoundingClientRect();
 return JSON.stringify({x:Math.round(rr.right-1),y:Math.round(rr.top+Math.min(rr.height/2,4)),hi:hi,lastTxt:last.textContent.slice(-10)});})()"""
EMPTY=r"""(()=>{const ed=document.querySelector('.public-DraftEditor-content');const A=%s;
 const bl=[...ed.querySelectorAll('[data-block=true]')];
 const hi=bl.findIndex(function(d){return d.tagName==='H2'&&(d.innerText||'').trim().startsWith(A);});
 if(hi<1) return 'NO_H2';
 const cand=bl[hi-1];
 if(!cand||cand.tagName==='FIGURE'||(cand.innerText||'').trim().length>0) return 'NOT_EMPTY:'+((cand&&cand.innerText||'').trim().slice(0,12));
 cand.scrollIntoView({block:'center'});
 const r=cand.getBoundingClientRect();
 return JSON.stringify({x:Math.round(r.left+6),y:Math.round(r.top+r.height/2)});})()"""
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
            await s("Input.dispatchMouseEvent",dict(b,type="mouseReleased",buttons=0)); await asyncio.sleep(0.8)
        await s("Page.bringToFront",{}); await asyncio.sleep(0.4)
        await ev("(()=>{document.querySelector('.public-DraftEditor-content').focus();return 1;})()")
        print("BEFORE:", await ev(STATE))
        for n in range(12):
            raw=await ev(STATE)
            if json.loads(raw)["imgs"]==0: print("UNDO_DONE steps=",n); break
            await key("z",6,4); await asyncio.sleep(1.6)
        print("AFTER_UNDO:", await ev(STATE))
        for anchor,img in [("四、它敢让自己改自己","img/fig41-power-split.png"),
                            ("五、诚实的边界：92.1% 后面的那个括弧","img/fig42-evolution-locks.png")]:
            p=await ev(PARAEND % json.dumps(anchor,ensure_ascii=False)); print("PARAEND", anchor[:8], p)
            if p.startswith("{"):
                q=json.loads(p); await click(q["x"],q["y"]); await asyncio.sleep(0.8)
                print("  SEL:", await ev("(()=>{const s=window.getSelection();return JSON.stringify({off:s.anchorOffset,txt:s.anchorNode?s.anchorNode.textContent.slice(-10):null});})()"))
                await key("Enter",13); await asyncio.sleep(1.5)
            e=await ev(EMPTY % json.dumps(anchor,ensure_ascii=False)); print("  EMPTY:", e)
            if e.startswith("{"):
                z=json.loads(e); await click(z["x"],z["y"]); await asyncio.sleep(0.8)
                b64=base64.b64encode(open(img,"rb").read()).decode()
                print("  PASTE:", await ev(FPASTE % (json.dumps(b64), json.dumps(os.path.basename(img)))))
                await asyncio.sleep(12)
        print("FINAL:", await ev(STATE))
asyncio.run(main())
