# -*- coding: utf-8 -*-
"""重贴正文 -> 段末 Enter 造独立块 -> 在独立块内 paste File 插图（不 split 段落、不动 H2）"""
import asyncio, json, re, base64, os, urllib.request, websockets
CDP="http://127.0.0.1:9229"
HTML_F="20261013-lfl-daily-13.html"
def page():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    for t in d:
        if t.get("type")=="page" and "zhuanlan.zhihu.com" in t.get("url",""): return t
    return None
def tune(h):
    h=h.replace("<strong>","<b>").replace("</strong>","</b>")
    def up(m):
        t=m.group(1)
        return "<h2>%s</h2>"%t if re.match(r'^[一二三四五六七八九十]+、',t) else "<p><b>%s</b></p>"%t
    h=re.sub(r'<p><b>([^<]{2,60})</b></p>', up, h)
    return h, re.sub(r'<[^>]+>','\n',h)
CLEAR=r"""(()=>{const ed=document.querySelector('.public-DraftEditor-content');ed.focus();
 const r=document.createRange();r.selectNodeContents(ed);const s=window.getSelection();
 s.removeAllRanges();s.addRange(r);return 'CLEARED';})()"""
PASTE="""(()=>{const ed=document.querySelector('.public-DraftEditor-content');ed.focus();
 const dt=new DataTransfer();dt.setData('text/html',%s);dt.setData('text/plain',%s);
 ed.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}));return 'DISPATCHED';})()"""
PARAEND=r"""(()=>{const ed=document.querySelector('.public-DraftEditor-content');const A=%s;
 const bl=[...ed.querySelectorAll('[data-block=true]')];
 const hi=bl.findIndex(d=>d.tagName==='H2'&&(d.innerText||'').trim().startsWith(A));
 if(hi<1) return 'NO_H2';
 const prev=bl[hi-1]; prev.scrollIntoView({block:'center'});
 const w=document.createTreeWalker(prev,NodeFilter.SHOW_TEXT);let last=null,n;
 while(w.nextNode()){ if(w.currentNode.textContent && w.currentNode.textContent.length) last=w.currentNode; }
 if(!last) return 'NO_TEXT';
 const rg=document.createRange(); rg.selectNodeContents(last);
 const rects=rg.getClientRects(); const rr=rects.length?rects[rects.length-1]:rg.getBoundingClientRect();
 return JSON.stringify({x:Math.round(rr.right-1),y:Math.round(rr.top+Math.min(rr.height/2,4)),hi:hi,
   lastTxt:last.textContent.slice(-10), prevLen:prev.innerText.replace(/\s/g,'').length,
   lines:rects.length});})()"""
EMPTY=r"""(()=>{const ed=document.querySelector('.public-DraftEditor-content');const A=%s;
 const bl=[...ed.querySelectorAll('[data-block=true]')];
 const hi=bl.findIndex(d=>d.tagName==='H2'&&(d.innerText||'').trim().startsWith(A));
 if(hi<1) return 'NO_H2';
 const cand=bl[hi-1];
 if(!cand||cand.tagName==='FIGURE'||(cand.innerText||'').trim().length>0) return 'NOT_EMPTY:'+(cand?(cand.innerText||'').trim().slice(0,12):'null');
 cand.scrollIntoView({block:'center'});
 const r=cand.getBoundingClientRect();
 return JSON.stringify({x:Math.round(r.left+5),y:Math.round(r.top+r.height/2),h:Math.round(r.height),tag:cand.tagName});})()"""
FPASTE="""(()=>{const bin=atob(%s);const arr=new Uint8Array(bin.length);
 for(let i=0;i<bin.length;i++) arr[i]=bin.charCodeAt(i);
 const tgt=document.activeElement||document.querySelector('.public-DraftEditor-content');
 const dt=new DataTransfer(); dt.items.add(new File([arr],%s,{type:'image/png'}));
 tgt.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}));
 return 'DISPATCH';})()"""
DUMP=r"""(()=>{const ed=document.querySelector('.public-DraftEditor-content');
 const bl=[...ed.querySelectorAll('[data-block=true]')]; const ims=[...ed.querySelectorAll('img')];
 return JSON.stringify({h2n:ed.querySelectorAll('h2').length,total:bl.length,
   edLen:ed.innerText.replace(/\s/g,'').length, imgs:ims.length,
   loaded:ims.filter(x=>x.naturalWidth>0).length, dims:ims.map(x=>x.naturalWidth+'x'+x.naturalHeight),
   counter:(document.body.innerText.match(/字数[：:]\s*\d+/)||['none'])[0],
   rows:bl.map((d,n)=>({n:n,tag:d.tagName,img:!!d.querySelector('img'),t:(d.innerText||'').replace(/\s+/g,' ').trim().slice(0,12)}))});})()"""
async def main():
    pg=page()
    if not pg: print('NO_PAGE'); return
    log={}
    async with websockets.connect(pg['webSocketDebuggerUrl'],max_size=400*1024*1024) as ws:
        i=[0]
        async def s(m,p):
            i[0]+=1
            await ws.send(json.dumps({'id':i[0],'method':m,'params':p}))
            while True:
                r=json.loads(await asyncio.wait_for(ws.recv(),90))
                if r.get('id')==i[0]: return r.get('result',{})
        async def ev(e):
            r=await s('Runtime.evaluate',{'expression':e,'returnByValue':True,'awaitPromise':True})
            if 'exceptionDetails' in r: return 'ERR:'+json.dumps(r['exceptionDetails'],ensure_ascii=False)[:300]
            return r.get('result',{}).get('value')
        async def key(k,code,vk):
            b={'key':k,'code':code,'windowsVirtualKeyCode':vk,'nativeVirtualKeyCode':vk,'modifiers':0}
            await s('Input.dispatchKeyEvent',dict(b,type='keyDown')); await asyncio.sleep(0.08)
            await s('Input.dispatchKeyEvent',dict(b,type='keyUp'))
        async def click(x,y):
            b={'x':x,'y':y,'button':'left','clickCount':1}
            await s('Input.dispatchMouseEvent',dict(b,type='mouseMoved',buttons=0)); await asyncio.sleep(0.25)
            await s('Input.dispatchMouseEvent',dict(b,type='mousePressed',buttons=1)); await asyncio.sleep(0.15)
            await s('Input.dispatchMouseEvent',dict(b,type='mouseReleased',buttons=0)); await asyncio.sleep(1.0)
        await s('Page.bringToFront',{}); await asyncio.sleep(0.6)
        await ev(CLEAR); await asyncio.sleep(0.5); await key('Backspace','Backspace',8); await asyncio.sleep(3)
        h,plain=tune(open(HTML_F,encoding='utf-8').read())
        log['paste']=await ev(PASTE % (json.dumps(h,ensure_ascii=False), json.dumps(plain,ensure_ascii=False)))
        await asyncio.sleep(10)
        for name,anchor in [("fig39-heartbeat-protocol.png","三、比指令更硬的两条边界"),
                            ("fig40-heartbeat-cost.png","四、什么时候值得用心跳")]:
            k=name[4:6]
            p=await ev(PARAEND % json.dumps(anchor,ensure_ascii=False)); log[k+'_paraend']=p
            if p!='NO_H2':
                q=json.loads(p); await click(q['x'],q['y']); await asyncio.sleep(0.8)
                log[k+'_sel']=await ev("(()=>{const s=window.getSelection();return JSON.stringify({off:s.anchorOffset,txt:s.anchorNode?s.anchorNode.textContent.slice(-10):null});})()")
                await key('Enter','Enter',13); await asyncio.sleep(1.5)
            e=await ev(EMPTY % json.dumps(anchor,ensure_ascii=False)); log[k+'_empty']=e
            if e.startswith('{'):
                z=json.loads(e); await click(z['x'],z['y']); await asyncio.sleep(0.8)
                b64=base64.b64encode(open(os.path.join('img',name),'rb').read()).decode()
                log[k+'_paste']=await ev(FPASTE % (json.dumps(b64), json.dumps(name)))
                await asyncio.sleep(10)
                log[k+'_verify']=json.loads(await ev(DUMP))
            else:
                log[k+'_split_miss']=True
        log['final']=json.loads(await ev(DUMP))
    print(json.dumps({k:(v if not isinstance(v,str) else v) for k,v in log.items()},ensure_ascii=False,indent=1))
asyncio.run(main())
