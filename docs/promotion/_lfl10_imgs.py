# -*- coding: utf-8 -*-
"""LFL第10期：paste正文 + 8图（照抄D14实证节奏：set->sleep10->第一个'确定'->sleep6）+ AI声明 + 终态校验。"""
import asyncio, json, base64, urllib.request, websockets

CDP = "http://127.0.0.1:9229"
BASE = "~/Project/llm-first-loop-mirror/outputs/lfl-article"
BODY_HTML = open(BASE + "/toutiao-body.html", encoding="utf-8").read()
IMGS = [
    (r"^它叫 ", BASE + "/assets/img0_banner.png"),
    (r"^官方给它的定位就一句话", BASE + "/assets/img1_positioning.png"),
    (r"^在 LFL 里，每条消息进来", BASE + "/assets/img2_core_loop.png"),
    (r"^程序层：安全硬边界", BASE + "/assets/img3_three_layers.png"),
    (r"^传统 Agent 出错", BASE + "/assets/img4_honesty.png"),
    (r"^昨天的事今天忘", BASE + "/assets/img6_memory.png"),
    (r"^LFL 会基于自评发起演进建议", BASE + "/assets/img5_evolution.png"),
    (r"^浏览器接管", BASE + "/assets/img7_capabilities.png"),
]
MAIN_PM = """[...document.querySelectorAll('.ProseMirror')].find(pm=>!pm.closest('[class*="modal"],[class*="Modal"],[class*="Dialog"],[class*="dialog"],[class*="drawer"],[class*="Drawer"]'))"""

def mp_pages():
    d = json.load(urllib.request.urlopen(CDP + "/json"))
    return [t for t in d if t.get("type") == "page" and "publish" in t.get("url", "")]

async def main():
    t = mp_pages()[0]
    async with websockets.connect(t["webSocketDebuggerUrl"], max_size=200*1024*1024) as ws:
        i=[0]
        async def cmd(method, params=None):
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
        async def sleep(s): await asyncio.sleep(s)
        async def esc():
            await cmd("Input.dispatchKeyEvent", {"type":"keyDown","key":"Escape","code":"Escape","windowsVirtualKeyCode":27,"nativeVirtualKeyCode":27})
            await cmd("Input.dispatchKeyEvent", {"type":"keyUp","key":"Escape","code":"Escape","windowsVirtualKeyCode":27,"nativeVirtualKeyCode":27})
        async def words():
            return await ev(f"(()=>{{const pm={MAIN_PM}; const wc=document.body.innerText.match(/共\\s*(\\d+)\\s*字/); return JSON.stringify({{imgs:pm.querySelectorAll('img').length, words:wc?wc[1]:null}});}})()")

        # 1) 等编辑器 + paste
        for _ in range(20):
            if await ev(f"!!{MAIN_PM}") == True: break
            await sleep(1)
        print("PM:", await ev(f"{MAIN_PM}? 'OK':'NO'"))
        html = json.dumps(BODY_HTML)
        plain = json.dumps(BODY_HTML.replace("<"," ").replace(">"," ")[:6000])
        print("PASTE:", await ev(f"""(()=>{{const pm={MAIN_PM};
          const dt=new DataTransfer(); dt.setData('text/html',{html}); dt.setData('text/plain',{plain});
          pm.focus(); const sel=window.getSelection(); const r=document.createRange();
          r.selectNodeContents(pm); sel.removeAllRanges(); sel.addRange(r);
          pm.dispatchEvent(new ClipboardEvent('paste',{{clipboardData:dt,bubbles:true,cancelable:true}}));
          return 'DISPATCHED';}})()"""))
        await sleep(5)
        st0 = json.loads(await ev(f"""(()=>{{const pm={MAIN_PM}; const wc=document.body.innerText.match(/共\\s*(\\d+)\\s*字/);
          return JSON.stringify({{blocks:pm.children.length, imgs:pm.querySelectorAll('img').length, words:wc?wc[1]:null}});}})()"""))
        print("AFTER_PASTE:", json.dumps(st0))
        if not st0.get("words") or int(st0["words"]) < 2000:
            print("ABORT: 正文未贴入"); return

        # 2) 逐张插图（D14 实证节奏）
        async def insert_after(pat, path, idx):
            js = """(()=>{const pm=%s;
              const hit=[...pm.querySelectorAll('p,li,h2')].find(n=>new RegExp(%s).test((n.innerText||'').trim()));
              if(!hit) return 'NO_ANCHOR';
              hit.scrollIntoView({block:'center'});
              const r=hit.getBoundingClientRect();
              return JSON.stringify({x:Math.round(r.left+30), y:Math.round(r.top+r.height/2), txt:hit.innerText.slice(0,18)});})()""" % (MAIN_PM, json.dumps(pat))
            pos = await ev(js)
            print(f"[图{idx}] ANCHOR:", pos)
            if not str(pos).startswith("{"): return False
            c = json.loads(pos)
            for ty in ("mousePressed","mouseReleased"):
                await cmd("Input.dispatchMouseEvent", {"type":ty,"x":c["x"],"y":c["y"],"button":"left","clickCount":1})
            await sleep(1)
            await cmd("Input.dispatchKeyEvent", {"type":"keyDown","key":"End","code":"End","windowsVirtualKeyCode":35,"nativeVirtualKeyCode":35})
            await cmd("Input.dispatchKeyEvent", {"type":"keyUp","key":"End","code":"End","windowsVirtualKeyCode":35,"nativeVirtualKeyCode":35})
            await sleep(1)
            print(f"[图{idx}] BTN:", await ev("""(()=>{const b=document.querySelector('.syl-toolbar-tool.image .syl-toolbar-button');
              if(!b) return 'NO'; b.click(); return 'CLICKED';})()"""))
            await sleep(3)
            doc = await cmd("DOM.getDocument")
            q = await cmd("DOM.querySelector", {"nodeId": doc["root"]["nodeId"], "selector": "input[type=file]"})
            if not q.get("nodeId"):
                print(f"[图{idx}] NO_FILE_INPUT"); await esc(); return False
            await cmd("DOM.setFileInputFiles", {"nodeId": q["nodeId"], "files": [path]})
            await sleep(10)
            print(f"[图{idx}] CONFIRM:", await ev("""(()=>{for(const b of document.querySelectorAll('button')){
              if(b.textContent.trim()==='确定'){b.click(); return 'CLICKED';}} return 'NO_BTN';})()"""))
            await sleep(6)
            await esc()
            await sleep(1)
            w = await words()
            print(f"[图{idx}] STATE: {w}")
            try:
                return json.loads(w).get("imgs", 0)
            except Exception:
                return -1

        for idx, (pat, path) in enumerate(IMGS):
            n = await insert_after(pat, path, idx)
            if n == "NO_ANCHOR" or n == False:
                print(f"[图{idx}] MISS, 继续")

        # 3) AI 声明
        await sleep(2)
        print("AI_CLICK:", await ev("""(()=>{const ls=[...document.querySelectorAll('label.byte-checkbox')];
          const hit=ls.find(l=>/引用AI|内容由\\s*AI|AI生成/.test(l.innerText));
          if(!hit) return 'NO_LABEL';
          const inp=hit.querySelector('input[type=checkbox]');
          if(inp.checked) return 'ALREADY'; inp.click(); return 'CLICKED '+hit.innerText.trim().slice(0,10);})()"""))
        await sleep(1)

        # 4) 终态校验
        fin = await ev(f"""(()=>{{const pm={MAIN_PM};
          const im=[...pm.querySelectorAll('img')];
          const blocks=[...pm.children];
          const wc=document.body.innerText.match(/共\\s*(\\d+)\\s*字/);
          const ta=document.querySelector('textarea[placeholder*="标题"]');
          const at=blocks.map((n,k)=>((n.querySelector&&n.querySelector('img')&&!n.querySelector('template'))?k:-1)).filter(k=>k>=0);
          return JSON.stringify({{title:ta?ta.value.length:-1, imgs:im.length,
            dims:im.map(x=>x.naturalWidth+'x'+x.naturalHeight), words:wc?wc[1]:null, blocks:blocks.length,
            neighbors:at.map(k=>({before:(blocks[k].previousElementSibling&&blocks[k].previousElementSibling.innerText||'').slice(0,16),
              after:(blocks[k].nextElementSibling&&blocks[k].nextElementSibling.innerText||'').slice(0,16)}))}});}})()""")
        print("FINAL:", fin)
        shot = await cmd("Page.captureScreenshot", {"format": "png"})
        open(BASE + "/toutiao-preview2.png", "wb").write(base64.b64decode(shot["data"]))
        print("SCREENSHOT saved")

asyncio.run(main())
