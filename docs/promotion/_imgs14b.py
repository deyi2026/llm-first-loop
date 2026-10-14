# -*- coding: utf-8 -*-
"""D14 两图插入：在指定段落末尾定位光标 -> 工具栏图片按钮 -> setFileInputFiles -> 确定。"""
import asyncio, json, os, re, urllib.request, websockets
CDP="http://127.0.0.1:9229"; HERE=os.path.dirname(os.path.abspath("."))
def pages():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    return [t for t in d if t.get("type")=="page" and "profile_v4/graphic/publish" in t.get("url","")]
async def main():
    pg=pages()
    if not pg: print("NO_PAGE"); return
    t=pg[0]; print("PAGE:", t["url"][:90])
    async with websockets.connect(t["webSocketDebuggerUrl"],max_size=200*1024*1024) as ws:
        i=[0]
        async def cmd(method,params=None):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":method,"params":params or {}}))
            while True:
                m=json.loads(await ws.recv())
                if m.get("id")==i[0]:
                    if "error" in m: raise RuntimeError(method+" "+str(m["error"]))
                    return m.get("result",{})
        async def ev(e):
            r=await cmd("Runtime.evaluate",{"expression":e,"returnByValue":True,"awaitPromise":True})
            if "exceptionDetails" in r: return "ERR:"+str(r["exceptionDetails"].get("text"))
            return r.get("result",{}).get("value")
        async def key(k,code,vk):
            for ty in ("keyDown","keyUp"):
                await cmd("Input.dispatchKeyEvent",{"type":ty,"key":k,"code":code,"windowsVirtualKeyCode":vk,"nativeVirtualKeyCode":vk})
        async def insert_after(pat,img):
            pos=await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
              const hit=[...pm.querySelectorAll('p,li')].find(n=>new RegExp(%s).test((n.innerText||'').trim()));
              if(!hit) return 'NO_PARA'; hit.scrollIntoView({block:'center'});
              const r=hit.getBoundingClientRect();
              return JSON.stringify({x:Math.round(r.left+30), y:Math.round(r.top+r.height/2), txt:hit.innerText.slice(0,24)});})()""" % json.dumps(pat))
            print("ANCHOR:", pos)
            if not pos.startswith("{"): return False
            c=json.loads(pos)
            for ty in ("mousePressed","mouseReleased"):
                await cmd("Input.dispatchMouseEvent",{"type":ty,"x":c["x"],"y":c["y"],"button":"left","clickCount":1})
            await asyncio.sleep(1); await key("End","End",35); await asyncio.sleep(1)
            print("SEL:", await ev("""(()=>{const s=window.getSelection(); const n=s.anchorNode;
              return JSON.stringify({off:s.anchorOffset, para:(n&&n.textContent||'').slice(-24)});})()"""))
            print("BTN:", await ev("""(()=>{const b=document.querySelector('.syl-toolbar-tool.image .syl-toolbar-button');
              if(!b) return 'NO'; b.click(); return 'CLICKED';})()"""))
            await asyncio.sleep(3)
            doc=await cmd("DOM.getDocument"); q=await cmd("DOM.querySelector",{"nodeId":doc["root"]["nodeId"],"selector":"input[type=file]"})
            nid=q.get("nodeId")
            if not nid: print("NO_FILE_INPUT"); return False
            ap=os.path.abspath(os.path.join(HERE,img))
            print("SET:", os.path.basename(ap), await cmd("DOM.setFileInputFiles",{"nodeId":nid,"files":[ap]}))
            await asyncio.sleep(8)
            print("CONFIRM:", await ev("""(()=>{for(const b of document.querySelectorAll('button')){
              if(b.textContent.trim()==='确定'){b.click(); return 'CLICKED';}} return 'NO_BTN';})()"""))
            await asyncio.sleep(6); return True
        print("IMGS_BEFORE:", await ev("document.querySelectorAll('.ProseMirror img').length"))
        await insert_after(r"^人工审批流与审计", "img/fig41-power-split.png")
        await insert_after(r"^第 3 条是关键", "img/fig42-evolution-locks.png")
        print("FINAL:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const blocks=[...pm.children];
          const idxs=blocks.map((n,k)=>((n.querySelector&&n.querySelector('img')&&!n.querySelector('template'))?k:-1)).filter(k=>k>=0);
          const im=[...pm.querySelectorAll('img')];
          const wc=document.body.innerText.match(/共\\s*(\\d+)\\s*字/);
          return JSON.stringify({imgs:im.length, dims:im.map(x=>x.naturalWidth+'x'+x.naturalHeight),
            words:wc?wc[1]:null, blocks:idxs.length,
            neighbors:idxs.map(k=>({before:(blocks[k].previousElementSibling&&blocks[k].previousElementSibling.innerText||'').slice(0,22),
              after:(blocks[k].nextElementSibling&&blocks[k].nextElementSibling.innerText||'').slice(0,22)}))});})()"""))
asyncio.run(main())
