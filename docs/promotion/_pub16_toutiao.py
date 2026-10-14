# -*- coding: utf-8 -*-
"""D16 Toutiao (prefix-cache, text-only): ProseMirror paste + title + AI declare + publish + status."""
import asyncio, json, re, sys, urllib.parse, urllib.request
from pathlib import Path
import websockets
from md2html import convert

HERE = Path(__file__).resolve().parent
CDP = "http://127.0.0.1:9229"
URL = "https://mp.toutiao.com/profile_v4/graphic/publish"
TITLE = "AI 每次回答都重读整个对话——为什么你的账单没爆"
MD = HERE / "20261013-prefix-cache-kepu.md"
KEYS = ["前缀缓存（prefix caching）", "缓存命中 0.006 美元", "5 分钟", "绝不跨组织", "核实日期 2026 年 10 月 13 日"]
PHASE = sys.argv[1] if len(sys.argv) > 1 else "inspect"
assert PHASE in ("inspect", "prepare", "declare", "publish", "status")

def target():
    arr = json.load(urllib.request.urlopen(CDP + "/json", timeout=8))
    found = [t for t in arr if t.get("type") == "page" and "profile_v4/graphic/publish" in t.get("url", "")]
    if found: return found[-1]
    if PHASE == "inspect": return None
    req = urllib.request.Request(CDP + "/json/new?" + urllib.parse.quote(URL, safe=""), method="PUT")
    return json.load(urllib.request.urlopen(req, timeout=8))

def body_html():
    a = MD.read_text()
    assert a.splitlines()[0] == "# " + TITLE, a.splitlines()[0]
    body = a.split("\n", 1)[1]
    h = convert(body)
    h = re.sub(r"<h1>(.*?)</h1>", r"<h2>\1</h2>", h)
    for k in KEYS: assert k in h, k
    return h, re.sub(r"<[^>]+>", "\n", h)

async def run():
    t = target()
    if not t: print("NO_TT_TAB"); return
    print("TT_TAB", t["url"])
    async with websockets.connect(t["webSocketDebuggerUrl"], max_size=200 * 1024 * 1024) as ws:
        counter = 0
        async def cmd(method, params=None):
            nonlocal counter
            counter += 1
            await ws.send(json.dumps({"id": counter, "method": method, "params": params or {}}, ensure_ascii=False))
            while True:
                m = json.loads(await asyncio.wait_for(ws.recv(), 110))
                if m.get("id") == counter:
                    if "error" in m: raise RuntimeError(method + ": " + str(m["error"]))
                    return m.get("result", {})
        async def ev(js):
            r = await cmd("Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": True})
            if "exceptionDetails" in r: raise RuntimeError(str(r["exceptionDetails"])[:400])
            return r.get("result", {}).get("value")
        async def state():
            j = await ev("""(()=>{const ed=document.querySelector('.ProseMirror'),
               ti=document.querySelector('textarea[placeholder*="标题"],input[placeholder*="标题"]');
               if(!ed)return JSON.stringify({url:location.href,editor:false});
               const cbs=[...document.querySelectorAll('label.byte-checkbox')].map(l=>({
                 t:(l.innerText||'').replace(/\\s+/g,'').trim(),c:!!l.querySelector('input')?.checked}));
               return JSON.stringify({url:location.href,editor:true,
                title:(ti?ti.value:''), textLen:ed.innerText.replace(/\\s/g,'').length,
                imgs:ed.querySelectorAll('img').length,
                boldParas:[...ed.querySelectorAll('p')].filter(p=>p.querySelector('strong,b')&&p.innerText.replace(/\\s/g,'').length<25).length,
                checkboxes:cbs, tail:ed.innerText.slice(-100)});})()""")
            print("STATE", j, flush=True)
            return json.loads(j)

        if PHASE == "inspect":
            await state(); return
        s = None
        for _ in range(12):
            s = await state()
            if s.get("editor"): break
            await asyncio.sleep(2.5)
        if not s.get("editor"): print("NO_EDITOR_OR_LOGIN"); return
        if PHASE == "prepare":
            if s["title"] and s["title"] != TITLE: print("FOREIGN_DRAFT_STOP", s["title"]); return
            if s["title"] == TITLE and s["textLen"] > 100: print("EXISTING_D16_REUSE"); return
            h, plain = body_html()
            if s["textLen"] > 50: print("EDITOR_NOT_BLANK_STOP"); return
            print("PASTE", await ev("""(()=>{const ed=document.querySelector('.ProseMirror');
                ed.focus();const dt=new DataTransfer();
                dt.setData('text/html',%s);dt.setData('text/plain',%s);
                ed.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}));
                return 'PASTED';})()""" % (json.dumps(h, ensure_ascii=False), json.dumps(plain, ensure_ascii=False))))
            await asyncio.sleep(5)
            print("TITLE", await ev("""(()=>{const t=document.querySelector('textarea[placeholder*="标题"],input[placeholder*="标题"]');
                if(!t)return 'NO_TITLE';const set=Object.getOwnPropertyDescriptor(
                  t.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype,'value').set;
                set.call(t,%s);t.dispatchEvent(new Event('input',{bubbles:true}));return t.value;})()""" %
                json.dumps(TITLE, ensure_ascii=False)))
            await asyncio.sleep(2)
            await state(); return
        if PHASE == "declare":
            s = await state()
            if s["title"] != TITLE or s["textLen"] < 1000: print("DECLARE_GATE_STOP"); return
            print("SET_AI", await ev("""(()=>{const labels=[...document.querySelectorAll('label.byte-checkbox')];
              const lab=labels.find(l=>(l.innerText||'').replace(/\\s+/g,'').includes('引用AI'));
              if(!lab)return 'NO_LABEL';const inp=lab.querySelector('input[type=checkbox]');
              if(!inp)return 'NO_INPUT';if(!inp.checked)inp.click();
              return JSON.stringify({checked:inp.checked});})()"""))
            await asyncio.sleep(2)
            await state(); return
        if PHASE == "publish":
            s = await state()
            if s["title"] != TITLE or s["textLen"] < 1200: print("PUBLISH_GATE_STOP"); return
            print("OPEN_DLG", await ev("""(()=>{const b=[...document.querySelectorAll('button')]
              .find(x=>x.textContent.trim()==='预览并发布');if(!b||b.disabled)return 'NO_BTN';
              b.click();return 'CLICKED';})()"""))
            await asyncio.sleep(5)
            print("DLG", await ev("""(()=>{const dlgs=[...document.querySelectorAll('[class*=modal],[class*=dialog],[class*=drawer]')]
              .filter(d=>d.offsetParent);
              return JSON.stringify(dlgs.slice(0,3).map(d=>(d.innerText||'').replace(/\\s+/g,' ').slice(0,400)));})()"""))
            print("DLG_BTNS", await ev("""JSON.stringify([...document.querySelectorAll('button')]
              .filter(b=>b.offsetParent).map(b=>({txt:(b.innerText||'').replace(/\\s+/g,' ').trim().slice(0,16),dis:b.disabled})).filter(x=>x.txt))"""))
            print("CONFIRM", await ev("""(()=>{const b=[...document.querySelectorAll('button')]
              .find(x=>(x.textContent.trim()==='确认发布'||x.textContent.trim()==='发布'));
              if(!b||b.disabled)return 'NO_CONFIRM';b.click();return 'CLICKED';})()"""))
            for i in range(6):
                await asyncio.sleep(4)
                u = await ev("location.href")
                print("POST_URL", u)
                if "graphic/publish" not in u: break
            print("POST_BODY", str(await ev("document.body.innerText"))[-400:])
        if PHASE == "status":
            # bind to toutiao articles management list, find this article
            arr = json.load(urllib.request.urlopen(CDP + "/json", timeout=8))
            lst = [x for x in arr if x.get("type") == "page" and "profile_v4/graphic/articles" in x.get("url", "")]
            if not lst: print("NO_LIST_TAB"); return
            async with websockets.connect(lst[-1]["webSocketDebuggerUrl"], max_size=50 * 1024 * 1024) as ws2:
                async def ev2(js):
                    await ws2.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": js, "returnByValue": True, "awaitPromise": True}}))
                    while True:
                        m = json.loads(await ws2.recv())
                        if m.get("id") == 1: return m.get("result", {}).get("value")
                await ev2("""(()=>{location.reload();return 'RELOADING';})()""")
                await asyncio.sleep(6)
                print("LIST", await ev2("""(()=>{const t=%s;const hit=[...document.querySelectorAll('*')]
                  .filter(x=>x.children.length===0&&(x.innerText||'').includes(t)).slice(0,6)
                  .map(x=>{const row=x.closest('tr,[class*=item],[class*=article]');
                    return row?(row.innerText||'').replace(/\\s+/g,' ').slice(0,150):null}).filter(Boolean);
                  return JSON.stringify(hit);})()""" % json.dumps(TITLE, ensure_ascii=False)))

asyncio.run(run())
