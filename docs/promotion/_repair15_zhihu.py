# -*- coding: utf-8 -*-
"""Repair exactly one dropped published figure in D15, then update existing Zhihu post.

The source review has already passed; this is a bounded publishing-integrity repair.
Does not create a new post or touch other work.
"""
import asyncio
import base64
import json
import urllib.request
from pathlib import Path
import websockets

HERE=Path(__file__).resolve().parent
CDP="http://127.0.0.1:9229"
EDIT="https://zhuanlan.zhihu.com/p/2093460921402275186/edit"
TITLE="问一句，后台跑了几次？Agent 的隐形账本"
CAP="图 47｜三种回执状态，决定哪些数据可以相信"
IMAGE=HERE/"img/fig47-receipt-evidence-states.png"
assert IMAGE.is_file()

async def main():
    pages=json.load(urllib.request.urlopen(CDP+"/json",timeout=10))
    t=next(x for x in pages if x.get("type")=="page" and x.get("url")==EDIT)
    async with websockets.connect(t["webSocketDebuggerUrl"],max_size=60_000_000) as ws:
        i=0
        async def cmd(method,params=None):
            nonlocal i
            i+=1
            await ws.send(json.dumps({"id":i,"method":method,"params":params or {}},
                                     ensure_ascii=False))
            while True:
                m=json.loads(await asyncio.wait_for(ws.recv(),70))
                if m.get("id")==i:
                    if "error" in m: raise RuntimeError(str(m["error"]))
                    return m.get("result",{})
        async def ev(js):
            r=await cmd("Runtime.evaluate",{"expression":js,"returnByValue":True,
                                            "awaitPromise":True})
            if "exceptionDetails" in r:raise RuntimeError(str(r["exceptionDetails"])[:450])
            return r.get("result",{}).get("value")
        async def key(k,vk):
            p={"key":k,"code":k,"windowsVirtualKeyCode":vk,"nativeVirtualKeyCode":vk}
            await cmd("Input.dispatchKeyEvent",dict(p,type="keyDown"))
            await cmd("Input.dispatchKeyEvent",dict(p,type="keyUp"))
        async def click(x,y):
            p={"x":x,"y":y,"button":"left","clickCount":1}
            await cmd("Input.dispatchMouseEvent",dict(p,type="mouseMoved",buttons=0))
            await cmd("Input.dispatchMouseEvent",dict(p,type="mousePressed",buttons=1))
            await cmd("Input.dispatchMouseEvent",dict(p,type="mouseReleased",buttons=0))
        STATE=r"""(()=>{const ed=document.querySelector('.public-DraftEditor-content'),
            b=[...ed.querySelectorAll('[data-block=true]')],n=b.findIndex(x=>(x.innerText||'').trim().startsWith('图 47｜'));
            const ti=document.querySelector('textarea[placeholder*="标题"]');
            const imgs=[...ed.querySelectorAll('img')];
            const declared=[...document.querySelectorAll('button')].map(x=>(x.innerText||'').trim())
              .find(x=>x.startsWith('包含 AI 辅助创作')||x==='无声明')||'UNKNOWN';
            return JSON.stringify({title:ti?.value||'',imgCount:imgs.length,
              loaded:imgs.filter(x=>x.naturalWidth===1200&&x.naturalHeight===740).length,
              caption:n, nextTag:b[n+1]?.tagName, nextText:(b[n+1]?.innerText||'').slice(0,30),
              imgBlocks:b.map((x,k)=>x.querySelector('img')?k:-1).filter(k=>k>=0),
              declared,button:[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='更新')?.disabled});})()"""
        async def status():
            s=json.loads(await ev(STATE))
            print("STATE",s,flush=True)
            return s
        s=await status()
        if s["title"]!=TITLE or s["caption"]<0:
            print("STOP_UNEXPECTED_POST");return
        if s["loaded"]==6 and s["nextTag"]=="FIGURE":
            print("FIG47_ALREADY_PRESENT")
        else:
            if s["loaded"]!=5 or s["nextTag"]=="FIGURE":
                print("STOP_UNEXPECTED_FIGURE_COUNTS");return
            pos=await ev("""(()=>{const b=[...document.querySelectorAll('.public-DraftEditor-content [data-block=true]')];
              const x=b.find(d=>(d.innerText||'').trim().startsWith(%s));
              x.scrollIntoView({block:'center'});
              const r=document.createRange();r.selectNodeContents(x);const z=r.getClientRects();
              const t=z.length?z[z.length-1]:r.getBoundingClientRect();
              return JSON.stringify({x:Math.round(t.right-2),y:Math.round(t.top+t.height/2)});})()""" %
              json.dumps(CAP,ensure_ascii=False))
            print("INSERT_POINT",pos)
            p=json.loads(pos)
            await click(p["x"],p["y"])
            await key("End",35)
            caret=await ev("""(()=>{const s=window.getSelection();
              return JSON.stringify({text:(s.anchorNode?.textContent||'').slice(0,80),
                off:s.anchorOffset,len:(s.anchorNode?.textContent||'').length});})()""")
            print("CARET",caret)
            if CAP not in json.loads(caret)["text"]:print("STOP_CARET");return
            await key("Enter",13)
            await asyncio.sleep(.7)
            empty=await ev("""(()=>{const b=[...document.querySelectorAll('.public-DraftEditor-content [data-block=true]')];
              const k=b.findIndex(x=>(x.innerText||'').trim().startsWith(%s)),x=b[k+1];
              if(!x||x.querySelector('img')||(x.innerText||'').trim())return 'NO_EMPTY_AFTER_CAP';
              x.scrollIntoView({block:'center'});const r=x.getBoundingClientRect();
              return JSON.stringify({x:Math.round(r.left+13),y:Math.round(r.top+Math.min(r.height/2,8))});})()""" %
              json.dumps(CAP,ensure_ascii=False))
            print("EMPTY",empty)
            if not empty.startswith("{"):return
            p=json.loads(empty)
            await click(p["x"],p["y"])
            raw=base64.b64encode(IMAGE.read_bytes()).decode()
            print("IMAGE_PASTE",await ev("""(()=>{const bin=atob(%s),arr=new Uint8Array(bin.length);
              for(let j=0;j<bin.length;j++)arr[j]=bin.charCodeAt(j);
              const dt=new DataTransfer();dt.items.add(new File([arr],%s,{type:'image/png'}));
              (document.activeElement||document.querySelector('.public-DraftEditor-content'))
                .dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}));
              return 'SENT';})()"""%
              (json.dumps(raw),json.dumps(IMAGE.name))))
            good=False
            for z in range(12):
                await asyncio.sleep(2)
                s=await status()
                if s["loaded"]==6 and s["nextTag"]=="FIGURE":good=True;break
            if not good:print("STOP_PASTE_NOT_SETTLED");return
        # Platform editing UI reverts the declaration selection on reopening,
        # so explicitly select it again for this update.
        s=await status()
        if s["declared"]=="无声明":
            print("AI_MENU",await ev("""(()=>{let b=[...document.querySelectorAll('button')]
              .find(x=>x.textContent.trim()==='无声明');if(!b)return 'NO_MENU';b.click();return 'OPENED';})()"""))
            await asyncio.sleep(1)
            print("AI_SELECT",await ev("""(()=>{let b=[...document.querySelectorAll('button[role=option]')]
              .find(x=>x.textContent.trim().startsWith('包含 AI 辅助创作'));
              if(!b)return 'NO_AI_OPTION';b.click();return 'SET';})()"""))
        s=await status()
        if s["loaded"]!=6 or s["nextTag"]!="FIGURE" or not s["declared"].startswith("包含 AI 辅助创作"):
            print("STOP_UPDATE_GATE");return
        await asyncio.sleep(8)
        print("UPDATE",await ev("""(()=>{let b=[...document.querySelectorAll('button')]
          .find(x=>x.textContent.trim()==='更新');if(!b||b.disabled)return 'NO_UPDATE';
          b.click();return 'UPDATE_CLICKED';})()"""))
        await asyncio.sleep(7)
        print("URL_AFTER_UPDATE",await ev("location.href"))
        print("TAIL_AFTER_UPDATE",(await ev("document.body.innerText"))[-270:])

asyncio.run(main())
