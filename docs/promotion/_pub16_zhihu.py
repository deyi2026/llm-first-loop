# -*- coding: utf-8 -*-
"""D16 Zhihu (prefix-cache, text-only): staged Slate paste + AI mark + publish + public verify."""
import asyncio, json, re, sys, urllib.parse, urllib.request
from pathlib import Path
import websockets
from md2html import convert

HERE = Path(__file__).resolve().parent
CDP = "http://127.0.0.1:9229"
URL = "https://zhuanlan.zhihu.com/write"
TITLE = "AI 每次回答都重读整个对话——为什么你的账单没爆"
MD = HERE / "20261013-prefix-cache-kepu.md"
H2_N = 5
KEYS = ["前缀缓存（prefix caching）", "缓存命中 0.006 美元", "5 分钟", "绝不跨组织", "核实日期 2026 年 10 月 13 日"]
PHASE = sys.argv[1] if len(sys.argv) > 1 else "inspect"
assert PHASE in ("inspect", "prepare", "mark", "publish", "verify")

def target():
    arr = json.load(urllib.request.urlopen(CDP + "/json", timeout=8))
    found = [t for t in arr if t.get("type") == "page" and "zhuanlan.zhihu.com/p/2093486494619013424/edit" in t.get("url", "")] or [t for t in arr if t.get("type") == "page" and "zhuanlan.zhihu.com/write" in t.get("url", "")]
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
    assert h.count("<h2>") == H2_N, h.count("<h2>")
    for k in KEYS: assert k in h, k
    return h, re.sub(r"<[^>]+>", "\n", h)

async def run():
    t = target()
    if not t: print("NO_ZHIHU_EDITOR"); return
    print("ZHIHU_TAB", t["url"])
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
            if "exceptionDetails" in r: raise RuntimeError(str(r["exceptionDetails"])[:500])
            return r.get("result", {}).get("value")
        async def state():
            j = await ev("""(()=>{const ed=document.querySelector('.public-DraftEditor-content'),
               ti=document.querySelector('textarea[placeholder*="标题"]');
               if(!ed)return JSON.stringify({url:location.href,editor:false});
               const im=[...ed.querySelectorAll('img')];
               const boxes=[...document.querySelectorAll('label.byte-checkbox')].map(l=>({
                 t:(l.innerText||'').trim(),c:!!l.querySelector('input')?.checked}));
               const declaration=[...document.querySelectorAll('button')].map(b=>(b.innerText||'').trim())
                 .find(x=>x==='无声明'||x==='引用AI'||x.startsWith('包含 AI 辅助创作'))||null;
               return JSON.stringify({url:location.href,editor:true,title:ti?.value||'',
                textLen:ed.innerText.replace(/\\s/g,'').length,
                headings:ed.querySelectorAll('h2').length,imgs:im.length,
                ai:boxes.filter(x=>x.t.includes('引用AI')),declaration,
                tail:ed.innerText.slice(-120)});})()""")
            print("STATE", j, flush=True)
            return json.loads(j)

        if PHASE == "inspect":
            await state(); return
        await asyncio.sleep(5 if t.get("url") == URL else 2)
        s = await state()
        if not s.get("editor"): print("NO_EDITOR_OR_LOGIN"); return
        if PHASE == "prepare":
            if s["title"] and s["title"] != TITLE:
                print("FOREIGN_DRAFT_STOP", s["title"]); return
            if s["title"] == TITLE and s["textLen"] > 100:
                print("EXISTING_D16_REUSE"); return
            h, plain = body_html()
            if s["textLen"] > 50: print("EDITOR_NOT_BLANK_STOP", s); return
            print("PASTE", await ev("""(()=>{const ed=document.querySelector('.public-DraftEditor-content');
                ed.focus();const dt=new DataTransfer();
                dt.setData('text/html',%s);dt.setData('text/plain',%s);
                ed.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}));
                return 'PASTED';})()""" % (json.dumps(h, ensure_ascii=False), json.dumps(plain, ensure_ascii=False))))
            await asyncio.sleep(6)
            print("TITLE", await ev("""(()=>{const t=document.querySelector('textarea[placeholder*="标题"]');
                if(!t)return 'NO_TITLE';const set=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set;
                set.call(t,%s);t.dispatchEvent(new Event('input',{bubbles:true}));return t.value;})()""" %
                json.dumps(TITLE, ensure_ascii=False)))
            await asyncio.sleep(2)
            await state(); return
        if PHASE == "mark":
            s = await state()
            if s["title"] != TITLE or s["textLen"] < 1000: print("MARK_GATE_STOP"); return
            already_open = await ev("document.querySelectorAll('button[role=option]').length")
            if s["declaration"] == "无声明" and not already_open:
                print("DECLARATION_OPEN", await ev("""(()=>{const b=[...document.querySelectorAll('button')]
                  .find(x=>x.textContent.trim()==='无声明');
                  if(!b)return 'NO_CREATION_DECLARATION_BUTTON';b.click();return 'OPENED';})()"""))
                await asyncio.sleep(1)
            print("AI_MARK", await ev("""(()=>{const b=[...document.querySelectorAll('button[role=option]')]
                .find(x=>(x.innerText||'').startsWith('包含 AI 辅助创作'));
                if(!b)return 'NO_AI_OPTION';b.click();return 'CLICKED_AI_OPTION';})()"""))
            await asyncio.sleep(2)
            await state(); return
        if PHASE == "publish":
            s = await state()
            if (s["title"] != TITLE or s["headings"] != H2_N or s["imgs"] != 0
                    or s["textLen"] < 1200 or not (s["declaration"] == "引用AI" or
                    (s["declaration"] or "").startswith("包含 AI 辅助创作") or any(x["c"] for x in s["ai"]))):
                print("PUBLISH_GATE_STOP", s); return
            print("SUBMIT", await ev("""(()=>{const b=[...document.querySelectorAll('button')]
              .find(x=>x.textContent.trim()==='发布');if(!b||b.disabled)return 'NO_PUBLISH';
              b.click();return 'CLICKED';})()"""))
            await asyncio.sleep(8)
            print("POST_URL", await ev("location.href"))
            print("POST_BODY", str(await ev("document.body.innerText"))[-500:])
        if PHASE == "verify":
            url = sys.argv[2] if len(sys.argv) > 2 else ""
            if "zhuanlan.zhihu.com/p/" not in url:
                print("VERIFY_NEED_URL"); return
            j = await ev("""fetch(%s,{credentials:'include'}).then(r=>r.text()).then(t=>{
              const d=new DOMParser().parseFromString(t,'text/html');
              const art=d.querySelector('article')||d.body;
              const h1=d.querySelector('h1');
              return JSON.stringify({status_doc:t.length, canonical:(d.querySelector('link[rel=canonical]')||{}).href||'',
               title:(h1&&h1.innerText||'').trim(), h2:art.querySelectorAll('h2').length,
               imgs:art.querySelectorAll('img').length,
               keys:%s.map(k=>({k:k.slice(0,12),hit:art.innerText.replace(/\\s/g,'').includes(k.replace(/\\s/g,''))})),
               err:d.body.innerText.slice(0,80)});})""" % (json.dumps(url, ensure_ascii=False), json.dumps(KEYS, ensure_ascii=False)))
            print("VERIFY", j)

asyncio.run(run())
