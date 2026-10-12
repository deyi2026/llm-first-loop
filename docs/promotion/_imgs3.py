# -*- coding: utf-8 -*-
"""第3期插图：CDP 点图片按钮 -> setFileInputFiles -> 点确定。依方法卡第3条+陷阱A/B。"""
import asyncio, json, os, urllib.request, websockets

CDP = "http://127.0.0.1:9229"
IMGS = ["img/fig11-three-state-layers.png", "img/fig12-debt-ratchet.png",
        "img/fig13-ideal-vs-reality.png", "img/fig14-ratchet-coverage.png",
        "img/fig15-evidence-tiering.png"]
HERE = os.path.dirname(os.path.abspath(__file__))

def targets():
    d = json.load(urllib.request.urlopen(CDP + "/json"))
    return [t for t in d if t.get("type") == "page" and "toutiao" in t.get("url", "")]

async def main():
    t = targets()[0]
    paths = [os.path.abspath(os.path.join(HERE, p)) for p in IMGS]
    for p in paths:
        assert os.path.exists(p), "MISSING " + p
    async with websockets.connect(t["webSocketDebuggerUrl"], max_size=200*1024*1024) as ws:
        i = [0]
        async def cmd(method, params=None):
            i[0] += 1
            await ws.send(json.dumps({"id": i[0], "method": method, "params": params or {}}))
            while True:
                m = json.loads(await ws.recv())
                if m.get("id") == i[0]:
                    if "error" in m: raise RuntimeError(method + " -> " + str(m["error"]))
                    return m.get("result", {})
        async def ev(expr):
            r = await cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
            return r.get("result", {}).get("value")

        # 1) 滚到正文顶部，避免在参考来源区插图
        await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          pm.scrollIntoView(); pm.focus(); return 'TOP';})()""")
        # 2) 找图片按钮：.syl-toolbar-button 里 svg use 的图标名含 pic/image
        idx = await ev("""(()=>{const bs=[...document.querySelectorAll('.syl-toolbar-button')];
          return 11;})()""")
        print("IMG_BTN_INDEX:", idx)
        if idx is None or idx < 0:
            raise SystemExit("IMG BUTTON NOT FOUND")
        await ev("document.querySelectorAll('.syl-toolbar-button')[%d].click()" % idx)
        await asyncio.sleep(2)
        # 3) 动态 file input
        got = await ev("""(()=>{const f=document.querySelector('input[type=file]');
          return f? 'FOUND':'MISSING';})()""")
        print("FILE_INPUT:", got)
        if got != "FOUND":
            print("ALL FILE INPUTS:", await ev("JSON.stringify([...document.querySelectorAll('input[type=file]')].map(f=>f.className))"))
            raise SystemExit(1)
        doc = await cmd("DOM.getDocument")
        node = await cmd("DOM.querySelector", {"nodeId": doc["root"]["nodeId"],
                                               "selector": "input[type=file]"})
        await cmd("DOM.setFileInputFiles", {"files": paths, "nodeId": node["nodeId"]})
        await asyncio.sleep(4)
        # 4) 点确定
        conf = await ev("""(()=>{const bs=[...document.querySelectorAll('button')];
          for(const b of bs){ if(b.textContent.trim()==='确定'){ b.click(); return 'CLICKED'; } }
          return JSON.stringify(bs.map(b=>b.textContent.trim()).filter(Boolean).slice(0,25));})()""")
        print("CONFIRM:", conf)
        await asyncio.sleep(5)
        st = await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const wc=document.body.innerText.match(/共\\s*(\\d+)\\s*字/);
          return JSON.stringify({words: wc?wc[1]:null, imgs: pm?pm.querySelectorAll('img').length:-1,
            emptyH1: pm?[...pm.querySelectorAll('h1')].filter(h=>h.textContent.trim()==='').length:-1});})()""")
        print("STATE:", st)

asyncio.run(main())
