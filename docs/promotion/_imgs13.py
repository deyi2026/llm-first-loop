# -*- coding: utf-8 -*-
"""D13 配图：点工具栏图片按钮 -> setFileInputFiles -> 点确定。依 _imgs3.py 方法。"""
import asyncio, json, os, urllib.request, websockets
CDP = "http://127.0.0.1:9229"
HERE = os.path.dirname(os.path.abspath("."))

def pages():
    d = json.load(urllib.request.urlopen(CDP + "/json"))
    return [t for t in d if t.get("type") == "page" and "profile_v4/graphic/publish" in t.get("url","")]

async def main():
    pg = pages()
    if not pg: print("NO_PUBLISH_PAGE"); return
    t = pg[0]
    async with websockets.connect(t["webSocketDebuggerUrl"], max_size=200*1024*1024) as ws:
        i=[0]
        async def cmd(method, params=None):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":method,"params":params or {}}))
            while True:
                m=json.loads(await ws.recv())
                if m.get("id")==i[0]:
                    if "error" in m: raise RuntimeError(method+" -> "+str(m["error"]))
                    return m.get("result",{})
        async def ev(e):
            r = await cmd("Runtime.evaluate", {"expression":e,"returnByValue":True,"awaitPromise":True})
            if "exceptionDetails" in r: return "ERR:"+str(r["exceptionDetails"].get("text"))
            return r.get("result",{}).get("value")

        # 找图片按钮：工具栏里 svg use 引用含 pic/image 的按钮
        print("TOOLBAR:", await ev("""(()=>{const bs=[...document.querySelectorAll('.syl-toolbar-button')];
          return JSON.stringify(bs.map((b,k)=>({k, tip:(b.getAttribute('data-tooltip')||b.title||'').slice(0,20)})));})()"""))
        idx = await ev("""(()=>{const bs=[...document.querySelectorAll('.syl-toolbar-button')];
          for(let k=0;k<bs.length;k++){
            const t=(bs[k].getAttribute('data-tooltip')||bs[k].title||'');
            if(/图|图片|image|pic/i.test(t)) return k;
          }
          return -1;})()""")
        print("IMG_BTN_IDX:", idx)
        if idx is None or idx < 0:
            print("BUTTON_NOT_FOUND"); return
        print("CLICK:", await ev("document.querySelectorAll('.syl-toolbar-button')[%d].click()" % idx))
        await asyncio.sleep(3)
        print("FILE_INPUT:", await ev("(()=>{const f=document.querySelector('input[type=file]'); return f?'FOUND':'MISSING';})()"))
        doc = await cmd("DOM.getDocument")
        q = await cmd("DOM.querySelector", {"nodeId": doc["root"]["nodeId"], "selector": "input[type=file]"})
        nid = q.get("nodeId")
        print("NODE:", nid)
        if not nid: return
        for p in ["img/fig39-heartbeat-protocol.png", "img/fig40-heartbeat-cost.png"]:
            ap = os.path.abspath(os.path.join(HERE, p))
            r = await cmd("DOM.setFileInputFiles", {"nodeId": nid, "files": [ap]})
            print("SET:", os.path.basename(ap), r.get("error") or "ok")
            await asyncio.sleep(6)
            print("  imgs_now:", await ev("document.querySelectorAll('.ProseMirror img').length"))
        conf = await ev("""(()=>{const bs=[...document.querySelectorAll('button')];
          for(const b of bs){ if(b.textContent.trim()==='确定'){ b.click(); return 'CLICKED'; } }
          return 'NO_CONFIRM_BTN';})()""")
        print("CONFIRM:", conf)
        await asyncio.sleep(5)
        print("STATE:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const wc=document.body.innerText.match(/共\\s*(\\d+)\\s*字/);
          return JSON.stringify({words: wc?wc[1]:null, imgs: pm?pm.querySelectorAll('img').length:-1});})()"""))
asyncio.run(main())
