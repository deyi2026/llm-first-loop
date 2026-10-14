# -*- coding: utf-8 -*-
"""LFL第10期 v3：刷新+标题+paste+校验 -> drop 方案插图（绕开上传面板）单图试验。"""
import asyncio, json, base64, urllib.request, websockets

CDP = "http://127.0.0.1:9229"
BASE = "~/Project/llm-first-loop-mirror/outputs/lfl-article"
BODY_HTML = open(BASE + "/toutiao-body.html", encoding="utf-8").read()
TITLE = 'AI 说"改好了"却没改？这个开源项目，专治智能体撒谎'
BANNER = BASE + "/assets/img0_banner.png"
PM_SEL = "document.querySelector('.syl-editor .ProseMirror')"

def mp_pages():
    d = json.load(urllib.request.urlopen(CDP + "/json"))
    return [t for t in d if t.get("type") == "page" and "mp.toutiao.com" in t.get("url", "")]

async def main():
    t = [x for x in mp_pages() if "publish" in x.get("url","")] or mp_pages()
    t = t[0]
    async with websockets.connect(t["webSocketDebuggerUrl"], max_size=500*1024*1024) as ws:
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

        # 1) 刷新
        print("NAV:", await cmd("Page.navigate", {"url": "https://mp.toutiao.com/profile_v4/graphic/publish"}))
        await sleep(8)
        ok = False
        for _ in range(40):
            if await ev(f"!!{PM_SEL}") == True: ok=True; break
            await sleep(1)
        print("PM_READY:", ok)
        if not ok: return

        # 2) 标题 + paste
        print("TITLE:", await ev("""(()=>{const ta=document.querySelector('textarea[placeholder*="标题"]');
          if(!ta) return 'NO_TA';
          const s=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;
          s.call(ta, %s); ta.dispatchEvent(new Event('input',{bubbles:true}));
          return 'SET';})()""" % json.dumps(TITLE)))
        html = json.dumps(BODY_HTML)
        plain = json.dumps(BODY_HTML.replace("<"," ").replace(">"," ")[:6000])
        print("PASTE:", await ev(f"""(()=>{{const pm={PM_SEL};
          const dt=new DataTransfer(); dt.setData('text/html',{html}); dt.setData('text/plain',{plain});
          pm.focus(); const sel=window.getSelection(); const r=document.createRange();
          r.selectNodeContents(pm); sel.removeAllRanges(); sel.addRange(r);
          pm.dispatchEvent(new ClipboardEvent('paste',{{clipboardData:dt,bubbles:true,cancelable:true}}));
          return 'DISPATCHED';}})()"""))
        await sleep(5)
        st0 = await ev(f"""(()=>{{const pm={PM_SEL}; const wc=document.body.innerText.match(/共\\s*(\\d+)\\s*字/);
          return JSON.stringify({{blocks:pm.children.length, imgs:pm.querySelectorAll('img').length, words:wc?wc[1]:null}});}})()""")
        print("AFTER_PASTE:", st0)
        s0 = json.loads(st0)
        if not s0.get("words") or int(s0["words"]) < 1200:
            print("ABORT: paste 未达阈值"); return

        # 3) drop 单图试验
        b64 = base64.b64encode(open(BANNER, "rb").read()).decode()
        js = """(()=>{const pm=%s;
          const hit=[...pm.querySelectorAll('p')].find(n=>(n.innerText||'').trim().startsWith('它叫 '));
          if(!hit) return 'NO_ANCHOR';
          hit.scrollIntoView({block:'center'});
          const r=hit.getBoundingClientRect();
          return JSON.stringify({x:Math.round(r.left+30), y:Math.round(r.top+r.height/2)});})()""" % PM_SEL
        pos = await ev(js)
        print("ANCHOR:", pos)
        if not str(pos).startswith("{"): return
        c = json.loads(pos)
        for ty in ("mousePressed","mouseReleased"):
            await cmd("Input.dispatchMouseEvent", {"type":ty,"x":c["x"],"y":c["y"],"button":"left","clickCount":1})
        await sleep(1)
        await cmd("Input.dispatchKeyEvent", {"type":"keyDown","key":"End","code":"End","windowsVirtualKeyCode":35,"nativeVirtualKeyCode":35})
        await cmd("Input.dispatchKeyEvent", {"type":"keyUp","key":"End","code":"End","windowsVirtualKeyCode":35,"nativeVirtualKeyCode":35})
        await sleep(1)
        r = await ev("""(async (b64) => {
          const pm = document.querySelector('.syl-editor .ProseMirror');
          const bin = atob(b64);
          const buf = new Uint8Array(bin.length);
          for (let i=0;i<bin.length;i++) buf[i]=bin.charCodeAt(i);
          const file = new File([buf], 'lfl-banner.png', {type:'image/png'});
          const dt = new DataTransfer();
          dt.items.add(file);
          pm.focus();
          const dtev = new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true});
          pm.dispatchEvent(dtev);
          return 'DROPPED';})()""" + "(" + json.dumps(b64) + ")")
        print("DROP:", r)
        # 轮询 imgs
        for k in range(45):
            await sleep(2)
            w = await ev(f"""(()=>{{const pm={PM_SEL}; const wc=document.body.innerText.match(/共\\s*(\\d+)\\s*字/);
              return JSON.stringify({{imgs:pm.querySelectorAll('img').length, words:wc?wc[1]:null, blocks:pm.children.length}});}})()""")
            if k % 5 == 0: print(f"POLL{k}:", w)
            s = json.loads(w)
            if s.get("imgs", 0) >= 1:
                print("DROP_OK:", w)
                break
        else:
            print("DROP_TIMEOUT")
        shot = await cmd("Page.captureScreenshot", {"format": "png"})
        open(BASE + "/toutiao-v3-drop.png", "wb").write(base64.b64decode(shot["data"]))
        print("SCREENSHOT saved")

asyncio.run(main())
