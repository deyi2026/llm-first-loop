# -*- coding: utf-8 -*-
"""D15 Zhihu: staged Slate paste, six real file uploads and exact prepublish gate."""
import asyncio
import base64
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
import websockets
from md2html import convert

HERE = Path(__file__).resolve().parent
CDP = "http://127.0.0.1:9229"
URL = "https://zhuanlan.zhihu.com/write"
EDIT_URL = "https://zhuanlan.zhihu.com/p/2093460921402275186/edit"
TITLE = "问一句，后台跑了几次？Agent 的隐形账本"
IMAGES = [
    (43,"fig43-one-prompt-many-calls.png"),
    (44,"fig44-logical-vs-physical.png"),
    (45,"fig45-cache-not-free.png"),
    (46,"fig46-four-denominators.png"),
    (47,"fig47-receipt-evidence-states.png"),
    (48,"fig48-six-questions.png"),
]
PHASE = sys.argv[1] if len(sys.argv)>1 else "inspect"
assert PHASE in ("inspect", "prepare", "insert43", "insert_rest", "mark", "publish")

def target():
    arr = json.load(urllib.request.urlopen(CDP+"/json",timeout=8))
    found = [t for t in arr if t.get("type")=="page" and
             ("zhuanlan.zhihu.com/write" in t.get("url","") or t.get("url","")==EDIT_URL)]
    if found: return found[-1]
    if PHASE == "inspect": return None
    req = urllib.request.Request(CDP+"/json/new?"+urllib.parse.quote(URL,safe=""),method="PUT")
    return json.load(urllib.request.urlopen(req,timeout=8))

def body_html():
    a=(HERE/"20261013-lfl-daily-15.md").read_text()
    assert a.splitlines()[0]=="# "+TITLE
    body=a.split("\n",1)[1]
    body=re.sub(r"(?m)^!\[[^\n]*\]\(img/[^)]*\.png\)[ \t]*\n?", "", body)
    h=convert(body)
    h=re.sub(r"<h1>(.*?)</h1>",r"<h2>\1</h2>",h)
    assert h.count("<h2>")==7
    assert all(f"图 {n}｜" in h for n,_ in IMAGES)
    return h, re.sub(r"<[^>]+>","\n",h)

async def run():
    t=target()
    if not t: print("NO_ZHIHU_EDITOR");return
    print("ZHIHU_TAB",t["url"])
    async with websockets.connect(t["webSocketDebuggerUrl"],max_size=200*1024*1024) as ws:
        counter=0
        async def cmd(method,params=None):
            nonlocal counter
            counter+=1
            await ws.send(json.dumps({"id":counter,"method":method,"params":params or {}},
                                     ensure_ascii=False))
            while True:
                m=json.loads(await asyncio.wait_for(ws.recv(),110))
                if m.get("id")==counter:
                    if "error" in m: raise RuntimeError(method+": "+str(m["error"]))
                    return m.get("result",{})
        async def ev(js):
            r=await cmd("Runtime.evaluate",{"expression":js,"returnByValue":True,
                                            "awaitPromise":True})
            if "exceptionDetails" in r:raise RuntimeError(str(r["exceptionDetails"])[:500])
            return r.get("result",{}).get("value")
        async def key(k,vk,code=None):
            d={"key":k,"code":code or k,"windowsVirtualKeyCode":vk,
               "nativeVirtualKeyCode":vk}
            await cmd("Input.dispatchKeyEvent",dict(d,type="keyDown"))
            await cmd("Input.dispatchKeyEvent",dict(d,type="keyUp"))
        async def click(x,y):
            d={"x":x,"y":y,"button":"left","clickCount":1}
            await cmd("Input.dispatchMouseEvent",dict(d,type="mouseMoved",buttons=0))
            await cmd("Input.dispatchMouseEvent",dict(d,type="mousePressed",buttons=1))
            await cmd("Input.dispatchMouseEvent",dict(d,type="mouseReleased",buttons=0))
        async def state():
            j=await ev("""(()=>{const ed=document.querySelector('.public-DraftEditor-content'),
               ti=document.querySelector('textarea[placeholder*="标题"]');
               if(!ed)return JSON.stringify({url:location.href,editor:false});
               const bl=[...ed.querySelectorAll('[data-block=true]')], im=[...ed.querySelectorAll('img')];
               const boxes=[...document.querySelectorAll('label.byte-checkbox')].map(l=>({
                 t:(l.innerText||'').trim(),c:!!l.querySelector('input')?.checked}));
               const declaration=[...document.querySelectorAll('button')].map(b=>(b.innerText||'').trim())
                 .find(x=>x==='无声明'||x==='引用AI'||x.startsWith('包含 AI 辅助创作'))||null;
               return JSON.stringify({url:location.href,editor:true,title:ti?.value||'',
                textLen:ed.innerText.replace(/\\s/g,'').length,
                headings:ed.querySelectorAll('h2').length,imgs:im.length,
                loaded:im.filter(i=>i.naturalWidth>100&&i.naturalHeight>100).length,
                sizes:im.map(i=>i.naturalWidth+'x'+i.naturalHeight),
                blocks:bl.length,
                anchors:[43,44,45,46,47,48].map(n=>bl.findIndex(x=>(x.innerText||'').includes('图 '+n+'｜'))),
                imageBlocks:bl.map((x,n)=>x.querySelector('img')?n:-1).filter(x=>x>=0),
                ai:boxes.filter(x=>x.t.includes('引用AI')),declaration,
                tail:ed.innerText.slice(-120)});})()""")
            print("STATE",j,flush=True)
            return json.loads(j)

        if PHASE=="inspect":
            await state();return
        await asyncio.sleep(5 if t.get("url")==URL else 2)
        s=await state()
        if not s.get("editor"): print("NO_EDITOR_OR_LOGIN");return
        if PHASE=="prepare":
            if s["title"] and s["title"]!=TITLE:
                print("FOREIGN_DRAFT_STOP",s["title"]);return
            if s["title"]==TITLE and s["textLen"]>100:
                print("EXISTING_D15_REUSE");return
            h,plain=body_html()
            if s["textLen"]>50:print("EDITOR_NOT_BLANK_STOP",s);return
            print("PASTE",await ev("""(()=>{const ed=document.querySelector('.public-DraftEditor-content');
                ed.focus();const dt=new DataTransfer();
                dt.setData('text/html',%s);dt.setData('text/plain',%s);
                ed.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}));
                return 'PASTED';})()""" % (json.dumps(h,ensure_ascii=False),json.dumps(plain,ensure_ascii=False))))
            await asyncio.sleep(6)
            print("TITLE",await ev("""(()=>{const t=document.querySelector('textarea[placeholder*="标题"]');
                if(!t)return 'NO_TITLE';const set=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set;
                set.call(t,%s);t.dispatchEvent(new Event('input',{bubbles:true}));return t.value;})()""" %
                json.dumps(TITLE,ensure_ascii=False)))
            await asyncio.sleep(2)
            await state();return

        async def insert(fig,name):
            state0=await state()
            if state0["title"]!=TITLE:print("WRONG_TITLE_STOP");return False
            if state0["loaded"]!=fig-43:
                print("EXISTING_IMAGE_COUNT_UNEXPECTED",fig,state0["loaded"]);return False
            cap="图 "+str(fig)+"｜"
            pt=await ev("""(()=>{const ed=document.querySelector('.public-DraftEditor-content');
              const cap=[...ed.querySelectorAll('[data-block=true]')].find(x=>(x.innerText||'').includes(%s));
              if(!cap)return 'NO_CAP';cap.scrollIntoView({block:'center'});
              const r=cap.getBoundingClientRect();const rg=document.createRange();
              rg.selectNodeContents(cap);rg.collapse(false);
              const rect=rg.getBoundingClientRect();
              const x=rect.width>0?rect.right-3:r.left+Math.min(r.width-20,210);
              const y=rect.height>0?rect.top+rect.height/2:r.top+r.height/2;
              return JSON.stringify({x:Math.round(x),y:Math.round(y),rect:{w:r.width,h:r.height},txt:cap.innerText.slice(0,60)});
              })()"""%json.dumps(cap,ensure_ascii=False))
            print("CAP_COORD",fig,pt,flush=True)
            if not pt.startswith("{"):return False
            pos=json.loads(pt)
            await click(pos["x"],pos["y"])
            await key("End",35)
            inspect=await ev("""(()=>{const s=window.getSelection(),n=s.anchorNode;
                return JSON.stringify({text:(n?.textContent||'').slice(-70),off:s.anchorOffset,len:(n?.textContent||'').length});})()""")
            print("CARET",inspect)
            if cap not in json.loads(inspect)["text"]:
                print("CARET_NOT_AT_CAP_STOP");return False
            await key("Enter",13)
            await asyncio.sleep(0.8)
            empty=await ev("""(()=>{const ed=document.querySelector('.public-DraftEditor-content'),
                bl=[...ed.querySelectorAll('[data-block=true]')],
                k=bl.findIndex(n=>(n.innerText||'').includes(%s));
                if(k<0)return 'NO_CAP';const b=bl[k+1];
                if(!b)return 'NO_NEXT';if((b.innerText||'').trim().length>0)return 'NEXT_NOT_EMPTY:'+b.innerText.slice(0,24);
                if(b.querySelector('img'))return 'NEXT_HAS_IMAGE';
                b.scrollIntoView({block:'center'});const r=b.getBoundingClientRect();
                return JSON.stringify({x:Math.round(r.left+12),y:Math.round(r.top+Math.min(r.height/2,8)),k,tag:b.tagName});
                })()"""%json.dumps(cap,ensure_ascii=False))
            print("EMPTY_AFTER_CAP",fig,empty)
            if not empty.startswith("{"):return False
            z=json.loads(empty); await click(z["x"],z["y"])
            raw=base64.b64encode((HERE/"img"/name).read_bytes()).decode()
            print("PASTE_IMAGE",fig,await ev("""(()=>{const b=atob(%s),arr=new Uint8Array(b.length);
                 for(let i=0;i<b.length;i++)arr[i]=b.charCodeAt(i);
                 const dt=new DataTransfer();dt.items.add(new File([arr],%s,{type:'image/png'}));
                 const ed=document.querySelector('.public-DraftEditor-content');
                 const tgt=document.activeElement||ed;
                 tgt.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}));
                 return 'DISPATCHED';})()""" % (json.dumps(raw),json.dumps(name))))
            for i in range(10):
                await asyncio.sleep(2)
                ss=await state()
                if ss["loaded"]==fig-42:
                    return True
                if ss["loaded"]>fig-42:break
            print("PASTE_IMAGE_NOT_CONFIRMED_STOP",fig);return False

        if PHASE in ("insert43","insert_rest"):
            if PHASE=="insert43":
                await insert(*IMAGES[0])
            else:
                for fig,name in IMAGES[1:]:
                    if not await insert(fig,name):break
            return
        if PHASE=="mark":
            s=await state()
            if s["title"]!=TITLE or s["loaded"]!=6:print("MARK_GATE_STOP");return
            already_open = await ev("document.querySelectorAll('button[role=option]').length")
            if s["declaration"]=="无声明" and not already_open:
                print("DECLARATION_OPEN",await ev("""(()=>{const b=[...document.querySelectorAll('button')]
                  .find(x=>x.textContent.trim()==='无声明');
                  if(!b)return 'NO_CREATION_DECLARATION_BUTTON';b.click();return 'OPENED';})()"""))
                await asyncio.sleep(1)
                print("DECLARATION_OPTIONS",await ev("""(()=>JSON.stringify({
                 options:[...document.querySelectorAll('label')].map(x=>(x.innerText||'').trim()).filter(Boolean).slice(-15),
                 inputs:[...document.querySelectorAll('input[type=checkbox]')].map(x=>({v:x.value,checked:x.checked})),
                 text:document.body.innerText.slice(-450)}))()"""))
            print("AI_MARK",await ev("""(()=>{const b=[...document.querySelectorAll('button[role=option]')]
                .find(x=>(x.innerText||'').startsWith('包含 AI 辅助创作'));
                if(!b)return 'NO_AI_OPTION';b.click();return 'CLICKED_AI_OPTION';})()"""))
            await state();return
        if PHASE=="publish":
            s=await state()
            if (s["title"]!=TITLE or s["loaded"]!=6 or s["headings"]!=7
                or s["textLen"]<1200 or not (s["declaration"]=="引用AI" or
                   (s["declaration"] or "").startswith("包含 AI 辅助创作") or any(x["c"] for x in s["ai"]))):
                print("PUBLISH_GATE_STOP",s);return
            print("SUBMIT",await ev("""(()=>{const b=[...document.querySelectorAll('button')]
              .find(x=>x.textContent.trim()==='发布');if(!b||b.disabled)return 'NO_PUBLISH';
              b.click();return 'CLICKED';})()"""))
            await asyncio.sleep(6)
            print("POST_URL",await ev("location.href"))
            print("POST_BODY",str(await ev("document.body.innerText"))[-500:])

asyncio.run(run())
