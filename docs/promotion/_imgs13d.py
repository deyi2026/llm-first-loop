# -*- coding: utf-8 -*-
"""D13 第二张图：真实点击第四章标题定位光标 -> 工具栏图片按钮 -> setFileInputFiles(fig40) -> 确定。"""
import asyncio, json, os, urllib.request, websockets
CDP="http://127.0.0.1:9229"; HERE=os.path.dirname(os.path.abspath("."))
def pages():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    return [t for t in d if t.get("type")=="page" and "profile_v4/graphic/publish" in t.get("url","")]
async def main():
    pg=pages()
    if not pg: print("NO_PAGE"); return
    async with websockets.connect(pg[0]["webSocketDebuggerUrl"], max_size=200*1024*1024) as ws:
        i=[0]
        async def cmd(m,p=None):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":m,"params":p or {}}))
            while True:
                msg=json.loads(await ws.recv())
                if msg.get("id")==i[0]:
                    if "error" in msg: return {"__err":msg["error"]}
                    return msg.get("result",{})
        async def ev(e):
            r=await cmd("Runtime.evaluate",{"expression":e,"returnByValue":True,"awaitPromise":True})
            if "__err" in r: return "ERR:"+str(r["__err"])
            if "exceptionDetails" in r: return "ERR:"+str(r["exceptionDetails"].get("text"))
            return r.get("result",{}).get("value")
        # 1) 第四章标题：滚到视口并点击（点击行尾以把光标放到标题段落末尾）
        pos=await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const h=[...pm.children].find(n=>/^四、/.test((n.innerText||'').trim()));
          if(!h) return 'NO_H4'; h.scrollIntoView({block:'center'});
          const r=h.getBoundingClientRect();
          return JSON.stringify({x:Math.round(r.left+20), y:Math.round(r.top+r.height/2)});})()""")
        print("H4_POS:", pos)
        if not pos.startswith("{"): return
        c=json.loads(pos)
        for t in ("mousePressed","mouseReleased"):
            await cmd("Input.dispatchMouseEvent",{"type":t,"x":c["x"],"y":c["y"],"button":"left","clickCount":1})
        await asyncio.sleep(1)
        print("SELINFO:", await ev("""(()=>{const s=window.getSelection();
          return JSON.stringify({anchor:(s.anchorNode&&s.anchorNode.textContent||'').slice(0,20), off:s.anchorOffset});})()"""))
        # 2) 工具栏图片按钮
        idx=await ev("""(()=>{const b=document.querySelector('.syl-toolbar-tool.image .syl-toolbar-button'); return b?'YES':'NO';})()""")
        print("BTN_IDX:", idx)
        if idx!="YES":
            print("NO_IMAGE_BTN"); return
        await ev("document.querySelector('.syl-toolbar-tool.image .syl-toolbar-button').click()")
        await asyncio.sleep(3)
        doc=await cmd("DOM.getDocument"); q=await cmd("DOM.querySelector",{"nodeId":doc["root"]["nodeId"],"selector":"input[type=file]"})
        nid=q.get("nodeId"); print("NODE:", nid)
        if not nid: return
        ap=os.path.abspath(os.path.join(HERE,"img/fig40-heartbeat-cost.png"))
        print("SET:", await cmd("DOM.setFileInputFiles",{"nodeId":nid,"files":[ap]}))
        await asyncio.sleep(8)
        print("CONFIRM:", await ev("""(()=>{for(const b of document.querySelectorAll('button')){
          if(b.textContent.trim()==='确定'){b.click(); return 'CLICKED';}} return 'NO_BTN';})()"""))
        await asyncio.sleep(6)
        print("FINAL:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const im=[...pm.querySelectorAll('img')];
          const wc=document.body.innerText.match(/共\\s*(\\d+)\\s*字/);
          const blocks=[...pm.children];
          const idxs=blocks.map((n,k)=>(n.querySelector&&n.querySelector('img')&&!n.querySelector('templ')?k:-1)).filter(k=>k>=0);
          return JSON.stringify({imgs:im.length, dims:im.map(x=>x.naturalWidth+'x'+x.naturalHeight),
            words:wc?wc[1]:null, imgBlocks:idxs,
            before: idxs.length? (blocks[idxs[0]].previousElementSibling||{innerText:''}).innerText.slice(0,30):null});})()"""))
asyncio.run(main())
